# IE Subprotocol Specification

**Version:** 1.0  
**Status:** Draft  
**Copyright 2026 Cisco Systems, Inc. and its affiliates**  
**SPDX-License-Identifier: Apache-2.0**

---

## 1. Overview

The **IE (Interaction Engine) subprotocol** governs structured multi-agent dialogue within SSTP sessions. It defines the message types, assertion chain, agent identity model, belief state semantics, and contingency decision logic that together guarantee verifiable, intent-aligned peer communication.

### Scope

- Per-utterance identity, integrity, and chain linkage via `UtteranceAssertion`
- A declaration handshake that roots each agent's assertion chain at session start
- Semantic belief state management: seeding, incremental update, drift detection
- Ambiguity detection and repair decision logic
- Wire message envelopes for all IE event types

### Non-Goals

- Transport framing (handled by SSTP L9)
- Persistent storage of belief history (caller responsibility)
- Cross-session state continuity

---

## 2. Message Types

| `event_type`               | Direction         | Description                                                              |
|----------------------------|-------------------|--------------------------------------------------------------------------|
| `declaration`              | broadcast         | Sent once per agent at session start; roots the assertion chain          |
| `utterance`                | peer-to-peer      | A standard content-bearing turn in the dialogue                          |
| `clarification_request`    | peer-to-peer      | Issued when ambiguity score > 0.6; belief update is held pending reply   |
| `clarification_response`   | peer-to-peer      | Resolves a previously issued clarification request                       |
| `repair`                   | peer-to-peer      | Triggered when invariants are violated or drift exceeds thresholds       |

---

## 3. Declaration Handshake

Before peer dialogue begins, every participating agent **must** broadcast a signed `IEDeclaration` as the root of its assertion chain.

**Procedure:**

1. Agent constructs an `IEDeclaration` with `sequence_number = 1`, `prev_utterance_hash = ""`, and `event_type = "declaration"`.
2. Agent signs the declaration using its `signing_key` (see §5).
3. Declaration is broadcast to all peers before any `utterance` messages are sent.
4. Receiving agents verify the declaration's signature. On failure: raise `AssertionVerificationError`; session is aborted.
5. All subsequent assertions from this agent must chain from this declaration.

---

## 4. Agent Identity

```
AgentIdentity {
    agent_id:    str       # Unique agent identifier within the session
    role:        str       # Semantic role (e.g., "orchestrator", "fmc", "sfdc")
    session_id:  str       # UUID identifying this dialogue session
    signing_key: bytes     # HMAC-SHA256 key, derived via HMAC(session_secret, agent_id)
}
```

The `signing_key` is derived per-agent per-session using HMAC:

```
signing_key = HMAC-SHA256(session_secret, agent_id.encode())
```

The `session_secret` is established out-of-band before session start and never transmitted.

---

## 5. UtteranceAssertion Structure

Every IE turn is wrapped in an `UtteranceAssertion`:

```
UtteranceAssertion {
    utterance_id:         str    # UUID
    agent_id:             str    # Originating agent
    session_id:           str    # Session UUID
    task_goal:            str    # The declared task goal for this session
    content:              str    # The utterance text
    content_hash:         str    # SHA-256(content), hex-encoded
    timestamp_ms:         int    # Unix epoch milliseconds at creation
    sequence_number:      int    # Monotonically increasing per agent; starts at 1
    prev_utterance_hash:  str    # SHA-256(prev_assertion.content); "" for the first assertion
    parent_ids:           list   # utterance_ids this assertion responds to (may be empty)
    signature:            str    # HMAC-SHA256(signing_key, canonical_payload), hex-encoded
    event_type:           str    # One of the types in §2; default "utterance"
}
```

---

## 6. Signing

The assertion signature is computed over the **canonical JSON payload** of the following fields, serialised with `sort_keys=True` and no extra whitespace:

```json
{
  "utterance_id":        "<uuid>",
  "agent_id":            "<agent_id>",
  "session_id":          "<session_id>",
  "content_hash":        "<sha256 hex>",
  "timestamp_ms":        <int>,
  "sequence_number":     <int>,
  "prev_utterance_hash": "<sha256 hex or empty string>"
}
```

Signing algorithm:

```
signature = HMAC-SHA256(signing_key, canonical_json.encode('utf-8')).hexdigest()
```

`content` and `task_goal` are intentionally excluded from the signed payload to allow redaction.  Their integrity is covered by `content_hash`.

---

## 7. Verification

Receivers **must** verify every incoming assertion in order:

1. **Content hash**: Recompute `SHA-256(assertion.content)` and compare to `assertion.content_hash`.
2. **Signature**: Recompute `HMAC-SHA256(signing_key, canonical_payload)` and compare to `assertion.signature` using a constant-time comparison.
3. **Chain integrity**: If a previous assertion from this agent exists, verify `assertion.prev_utterance_hash == SHA-256(prev_assertion.content)`.
4. **Sequence gap**: Verify `assertion.sequence_number > prev_assertion.sequence_number`.

### On Verification Failure

If any check fails, raise `AssertionVerificationError(utterance_id, agent_id, reason)`.  
**No repair is attempted.** The session must be aborted.

`reason` values: `content_hash_mismatch`, `signature_invalid`, `chain_broken`, `sequence_gap`.

---

## 8. Belief State

The IE subprotocol maintains a **semantic belief dict** per agent — not a float vector.

```python
belief = {
    "role":                str,    # Agent role as declared
    "objective":           str,    # Current inferred task objective
    "context_summary":     str,    # Running natural-language summary of observed context
    "inferred_constraints": list,  # Constraints extracted from utterances
    "confidence":          float,  # [0.0, 1.0] current belief confidence
}
```

### 8.1 Belief Seeding

```
seed_belief(agent_id, role_description, session_context) → belief dict
```

- Calls LLM task `tom_belief_seed` with `agent_id`, `role_description`, `task_goal`, `session_context`.
- Stores the result as `_beliefs[agent_id]`.
- **Freezes** the result as `_anchors[agent_id]` — the anchor is never mutated after seeding.
- Initialises `_ema_alignments[agent_id] = 1.0` and `_change_logs[agent_id] = []`.

### 8.2 Belief Update

```
update_belief(agent_id, utterance, task_goal) → belief dict
```

- Calls LLM task `tom_belief_update` with current belief and new utterance.
- Updates `objective`, `context_summary`, `inferred_constraints`, `confidence` in place.
- Appends utterance to `_utterance_history[agent_id]` (capped at 10 entries).
- Appends `change_summary` to `_change_logs[agent_id]` (capped at 10 entries).
- Calls `assess_task_alignment` to obtain an alignment score, then updates EMA.

### 8.3 EMA Alignment

Exponential Moving Average alignment tracks belief trajectory stability:

```
ema[t] = α × alignment_score[t] + (1 − α) × ema[t−1]
```

Where `α = 0.3` and `ema[0] = 1.0`.

---

## 9. Drift Detection

```
drift_signals(agent_id) → {
    "agent_id":      str,
    "ema_alignment": float,   # Current EMA alignment value
    "anchor_gap":    float,   # |current_confidence − anchor_confidence|
    "change_log":    list,    # Last ≤ 10 change summaries
    "confidence":    float,   # Current belief confidence
}
```

**anchor_gap** measures confidence drift from the seeded anchor:

```
anchor_gap = |_beliefs[agent_id]["confidence"] − _anchors[agent_id]["confidence"]|
```

---

## 10. Ambiguity Detection

```
detect_ambiguity(utterance, task_goal, agent_id=None) → {
    "ambiguous":                bool,
    "ambiguity_score":          float,  # [0.0, 1.0]
    "ambiguous_spans":          list,   # Substrings identified as ambiguous
    "plausible_interpretations": list,  # Possible readings
}
```

Calls LLM task `detect_ambiguity` with the utterance, task goal, and current agent belief (if `agent_id` is supplied).

When `ambiguous == True` and `ambiguity_score > 0.6`:
- Belief update for this utterance is **held**.
- The engine returns a `request_clarification` contingency.
- An `IEClarificationRequest` should be emitted with `ambiguous_spans` and `plausible_interpretations`.

---

## 11. Repair Decision Tree

Contingency selection is evaluated in strict priority order:

| Priority | Condition                                    | Contingency              |
|----------|----------------------------------------------|--------------------------|
| 1        | `invariants_violated` is non-empty           | `repair_hard_stop`       |
| 2        | `ambiguity_score > 0.6`                      | `request_clarification`  |
| 3        | `anchor_gap > 0.3` OR `ema_alignment < 0.45` | `repair_anchor`          |
| 4        | `alignment_score < 0.55` OR `disagreement > 0.35` | `repair_alignment`  |
| 5        | `urgency > 0.72`                             | `expedite_decision`      |
| default  | (none of the above)                          | `normal_alignment`       |

### Contingency Semantics

- **`repair_hard_stop`**: An invariant has been violated. Session must be paused; emit an `IERepair` with `repair_strategy = "hard_stop"`.
- **`request_clarification`**: Ambiguity is too high to proceed. Emit `IEClarificationRequest`; hold belief update until `IEClarificationResponse` received.
- **`repair_anchor`**: Confidence drift from anchor is large or EMA has decayed. Re-anchor agent to its original objective.
- **`repair_alignment`**: Alignment or disagreement score indicates misalignment. Restate alignment constraints.
- **`expedite_decision`**: Urgency is high; constrain response to fast-path terms only.
- **`normal_alignment`**: Proceed with standard aligned turn.

---

## 12. Error Types

| Exception                   | When raised                                                        |
|-----------------------------|--------------------------------------------------------------------|
| `AssertionVerificationError` | Content hash, signature, chain, or sequence check fails          |

Constructor signature:
```python
AssertionVerificationError(utterance_id: str, agent_id: str, reason: str)
```

---

## 13. Implementation Notes

- `hmac.new` is used in the reference implementation (Python standard library `hmac` module).
- All SHA-256 digests are hex-encoded strings (64 hex characters).
- `sequence_number` starts at 1 for each agent; 0 is reserved to indicate "no previous assertion."
- The `anchor` is set exactly once, at `seed_belief` time, and is never updated.
- LLM tasks (`tom_belief_seed`, `tom_belief_update`, `tom_task_alignment`, `tom_peer_attribution`, `detect_ambiguity`) are defined in the LLM client task registry.

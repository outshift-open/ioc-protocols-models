# IE Subprotocol Specification

**Version:** 2.0
**Status:** Normative
**Copyright 2026 Cisco Systems, Inc. and its affiliates**
**SPDX-License-Identifier: Apache-2.0**

---

## 1. Overview

The **IE (Interaction Engine) subprotocol** is the pairwise inter-agent grounding protocol. Its sole purpose is to ensure that when agent A says Y to agent B, B has correctly understood and integrated Y before the session proceeds.

IE is not a transport layer, a security layer, or a message-sequencing layer. IE is a **semantic fidelity layer**: it verifies that each exchange produces genuine grounded understanding between agent pairs, and records that understanding as `CommonGround`.

IE runs beneath SNP. All SNP operations (propose, consider, evaluate, counter_proposal, accept, reject) are carried over IE sessions. IE does not interpret SNP payloads — SNP semantics live in the payload; IE governs the grounding quality of the exchange that carries them.

### Scope

- Defining canonical event types and their mapping to L9 `kind`
- Specifying the grounding verification invariant
- Defining `CommonGround` as the output of verified grounding
- Defining speech acts and task phases as epistemic annotations
- Specifying how IE reads and writes `BeliefState`
- Specifying Theory of Mind (ToM) integration at pre- and post-utterance
- Specifying the repair decision tree using the current `contingency_mode` values

### Non-Goals

- Transport framing (SSTP L9)
- Domain-specific payload schema
- Multi-party convergence (SNP)
- Cross-session semantic memory (SemanticMemory store)

### Reference

Epistemic data structures (`BeliefState`, `CommonGround`, `PeerInteractionRecord`, etc.) are defined in `EPISTEMIC_DATA_STRUCTURES.md`. The L9 header and kind vocabulary are defined in `SSTP_FORMAL_MODEL.md`.

---

## 2. Event Types

IE uses the following event types. Each maps to an L9 `kind` per `SSTP_FORMAL_MODEL.md §3.4`.

| `event_type`               | L9 `kind`    | Description |
|----------------------------|--------------|-------------|
| `peer_turn`                | `exchange`   | Normal in-session utterance; primary grounding vehicle |
| `repair_required`          | `contingency`| Opens a grounding repair branch; main session held |
| `repair_applied`           | `commit`     | Closes a repair branch; main session resumes; `CommonGround` is recorded |
| `epistemic_clarification`  | `contingency`| Opens a clarification branch for epistemic disagreement or belief conflict |
| `decision_emitted`         | `exchange`   | Trace-only; local epistemic state update; not routed to peers |
| `episode_persisted`        | `commit`     | Memory write; closes episodic scope |
| `conversation_terminated`  | `commit`     | Session terminated (unrecoverable or clean) |
| `prior_query`              | `exchange`   | Read from semantic memory |
| `prior_injection`          | `exchange`   | Inject prior into an agent's `BeliefState` from semantic memory |
| `rule_update`              | `commit`     | Write a `TeamGroundedTruth` to semantic memory; stabilizes epistemic state |
| `outcome_reported`         | `exchange`   | Informational outcome report; does not close session |

All agent-to-agent interactions are `peer_turn` events.  Task delegation uses `speech_act=task_handoff` at `epistemic_state=grounding`; results use `speech_act=belief_assertion` at `epistemic_state=taskwork`; failures use `speech_act=help_request` at `epistemic_state=grounding`.  There is no privileged coordinator role and no separate RPC event type.

The `epistemic` block in the L9 header MUST be present on all `peer_turn`, `repair_required`, `repair_applied`, and `epistemic_clarification` messages.

---

## 3. Grounding Verification

### 3.1 The Core IE Invariant

> When A asserts Y to B, B's response is epistemically sufficient only if it is **contingent on the specific content of Y**. A response that could have been produced without Y is not grounds for updating common ground.

Formal definition:

```text
GroundingVerified(A_message_id, B_response_id) =
    B_response.addresses_evidence contains A_message_id
    AND B_response.confidence_score reflects engagement with A's specific reasoning
    AND B_response.epistemic.speech_act ≠ deliberation_pass
```

`contingency_verified` in `CommonGround` is the boolean outcome of this check.

### 3.2 Grounding Failure

If `GroundingVerified = False`, IE MUST emit `repair_required` with:

```text
repair_reason = "grounding_failure"
parent_ids    = [A_message_id, B_response_id]
```

This is a **semantic repair** event, not a delivery retry. The session is held pending repair. The failed exchange does NOT update `BeliefState`.

### 3.3 Grounding Success

If `GroundingVerified = True` for a `peer_turn` pair (A→B), IE records `CommonGround`:

```text
CommonGround {
  holder_id:            A.agent_id,
  confirmer_id:         B.agent_id,
  concept_id:           topic of the assertion,
  use_case:             session use_case,
  episode_id:           episode_id,
  grounding_confidence: A's confidence that B correctly integrated the belief,
  holder_confidence:    A's public_confidence at grounding time,
  confirmer_confidence: B's public_confidence after grounding,
  contingency_verified: True,
  speech_acts:          [A's speech_act, B's speech_act],
  grounding_message_ids:[A_message_id, B_response_id],
  formed_at_ms:         now,
}
```

`CommonGround.contingency_verified` MUST be `True`. A `CommonGround` with `contingency_verified = False` MUST NOT be created.

---

## 4. Speech Acts and Epistemic States

Every L9 header on a peer-dialogue message MUST carry an `EpistemicBlock`:

```text
EpistemicBlock := {
  speech_act:      SpeechAct,
  epistemic_state: EpistemicState,
  belief_status:   BeliefStatus,
}
```

### 4.1 Speech Acts

| `speech_act`          | Meaning |
|-----------------------|---------|
| `belief_assertion`    | Asserting a position with supporting reasoning |
| `alignment_challenge` | Challenging another agent's position with counter-evidence |
| `help_request`        | Requesting clarification or information |
| `task_handoff`        | Delegating work to another agent |
| `deliberation_pass`   | Expressing a position shift driven by social pressure, not grounded argument |

When the IE layer detects `speech_act = deliberation_pass`, it records `BeliefRevision.cause = social_compliance` in `AgentBeliefStore`. This updates `social_compliance_ratio` but MUST NOT update the posterior and MUST NOT trigger a `CommonGround` record.

### 4.2 Epistemic States

| `epistemic_state` | Epistemic weight | Description |
|---|---|---|
| `taskwork`      | High | Agent forming independent prior; no peer contact yet |
| `grounding`     | High | Pairwise IE exchange; positions being verified or repaired |
| `team_process`  | Medium | SNP convergence round; team negotiating shared position |

`grounding` exchanges are the primary vehicle for `CommonGround` records. `taskwork` establishes the independent prior that GAR measures convergence against. `team_process` marks SNP convergence turns; forced accepts (`deliberation_pass`) within `team_process` increment SCR.

### 4.3 Belief Status

| `belief_status` | Meaning |
|---|---|
| `asserted`   | Sender holds this belief with normal confidence |
| `deferred`   | Sender withholds judgment; awaiting more information |
| `challenged` | Sender's belief has been challenged by a peer |
| `revised`    | Sender has updated their belief based on new evidence |
| `retracted`  | Sender withdraws a prior assertion |
| `unresolved` | Challenge or repair cycle could not be closed |

Default for all IE events: `asserted`. Repair events default to `challenged`. Epistemic clarification events default to `deferred`.

---

## 5. Belief State Integration

IE reads and writes `BeliefState` (defined in `EPISTEMIC_DATA_STRUCTURES.md §6`).

### 5.1 On `peer_turn` — grounding verified

1. Determine the concept being asserted (from payload or epistemic annotation)
2. Record `BeliefRevision` with `cause = grounded_argument`
3. Call `AgentBeliefStore.record_revision(B.agent_id, concept_id, use_case, episode_id, revision, new_status="asserted")`
4. Append `(argument_concept_id, Δ)` to `BeliefState.likelihoods`
5. Update `BeliefState.posterior`
6. Record `CommonGround` (§3.3)

### 5.2 On `peer_turn` — grounding not verified

1. Hold the belief update
2. Emit `repair_required`
3. Do NOT update `BeliefState`; do NOT record `CommonGround`

### 5.3 On `repair_applied`

1. If repair succeeded: apply the held belief update with `cause = repair_resolution`
2. Record `CommonGround` with `contingency_verified = True`
3. Resume parent session

### 5.4 On `prior_injection`

1. Extract prior value and prior_weight from payload
2. Call `AgentBeliefStore.set_prior(agent_id, concept_id, use_case, prior, prior_weight)`
3. Record `BeliefRevision` with `cause = semantic_memory`, `message_id = None`
4. `BeliefState.prior` is set once at episode open; it is NOT updated by subsequent `prior_injection` calls in the same episode

### 5.5 On `deliberation_pass`

1. Record `BeliefRevision` with `cause = social_compliance`
2. Update `BeliefState.public_confidence` but NOT `BeliefState.posterior`
3. Do NOT record `CommonGround`
4. Increment `social_compliance_ratio`

---

## 6. Theory of Mind Integration

IE uses the ToM layer at two points per peer_turn exchange.

### 6.1 Pre-utterance — 1st-order ToM

Before A sends an assertion to B:

1. Read `AgentBeliefStore.current_belief(B.agent_id, concept_id, use_case)`
2. If B's `posterior` is already close to A's intended position, a `belief_assertion` may not move B — consider whether to assert or take a different approach
3. If B has `status = committed`, A must use `alignment_challenge` rather than `belief_assertion`

### 6.2 Pre-utterance — 2nd-order ToM

Before A sends an assertion of a specific `argument_type` to B:

1. Consult `PeerInteractionStore.get_peer_record(A.agent_id, B.agent_id, use_case)`
2. If A's planned `argument_type` is in `PeerInteractionRecord.argument_types_ignored`, reformulate the argument or probe first
3. Check `evidence_weights` for the target `concept_id` — weight A's framing toward concepts B historically values highly
4. Record a `PredictionRecord` with `predicted_confidence` before sending — this MUST be genuine pre-utterance

### 6.3 Post-response — update loop

After receiving B's response:

1. Record `ArgumentOutcome`:
   - `contingent`: was B's response contingent on A's specific reasoning?
   - `moved`: did B's `public_confidence` shift beyond noise threshold?
   - `move_cause`: `grounded_argument` | `social_compliance` | `no_move`
2. Fill in `PredictionRecord.actual_confidence` and compute `prediction_error`
3. Call `PeerInteractionStore.record_argument_outcome(A.agent_id, B.agent_id, use_case, outcome)`
4. Call `PeerInteractionStore.record_prediction(A.agent_id, B.agent_id, use_case, pred)`
5. Update `argument_types_that_move` / `argument_types_ignored` accordingly

---

## 7. Repair Decision Tree

Contingency selection is evaluated in strict priority order. The `contingency_mode` values used here are those implemented in the reference runtime.

| Priority | Condition | `contingency_mode` | L9 `kind` |
|----------|-----------|-------------------|-----------|
| 1 | `GroundingVerified = False` | `repair_required` | `contingency` |
| 2 | `ambiguity_score > 0.6` | `request_clarification` | `contingency` |
| 3 | `anchor_gap > 0.3` or `ema_alignment < 0.45` | `repair_anchor` | `contingency` |
| 4 | `alignment_score < 0.55` or `disagreement > 0.35` | `repair_alignment` | `contingency` |
| 5 | `urgency > 0.72` | `expedite_decision` | `contingency` |
| default | (none of the above) | `normal_alignment` | — (no contingency) |

### Contingency Semantics

- **`repair_required`**: Grounding failed — B's response was not contingent on A's reasoning. Semantic repair, not delivery retry. Session is held. After successful `repair_applied`, `CommonGround` is recorded.
- **`request_clarification`**: Ambiguity too high to proceed. Emit `epistemic_clarification` (`kind = contingency`); hold belief update until clarification response received.
- **`repair_anchor`**: Confidence has drifted significantly from the agent's taskwork prior. Re-anchor the agent to its independent prior before proceeding.
- **`repair_alignment`**: Alignment score or disagreement indicates positions are misaligned without grounded reasoning. Restate alignment constraints.
- **`expedite_decision`**: Urgency exceeds threshold; constrain response to fast-path terms.
- **`normal_alignment`**: Proceed with standard aligned turn; no contingency branch.

All contingency modes other than `normal_alignment` emit with `kind = contingency`. Resolution emits with `kind = commit`.

---

## 8. Episode Close

At episode close (on `episode_persisted` or `conversation_terminated`):

1. For each agent pair `(A, B)` that exchanged during the episode:
   a. Collect all `ArgumentOutcome` and `PredictionRecord` accumulated in the episodic buffer
   b. Call `PeerInteractionStore.promote_outcomes_for_pair(A.agent_id, B.agent_id, use_case, episode_id, outcomes, predictions)`
2. `CommonGround` records are already written turn-by-turn; no promotion needed
3. `BeliefState` is cross-episode; no promotion needed

---

## 9. Invariants

1. **Grounding contingency invariant**: `CommonGround.contingency_verified` MUST be `True`. A `CommonGround` with `contingency_verified = False` MUST NOT be recorded.

2. **Prediction pre-utterance invariant**: `PredictionRecord.predicted_confidence` MUST be recorded before B's message is received. Post-hoc predictions are invalid.

3. **Social compliance exclusion invariant**: `BeliefRevision` records with `cause = social_compliance` MUST NOT contribute to `BeliefState.posterior` or `likelihoods`. They contribute only to `social_compliance_ratio`.

4. **Prior immutability invariant**: `BeliefState.prior` is set once per episode via `prior_injection` or `set_prior`. Subsequent `record_revision` calls update `posterior` via `likelihoods` but MUST NOT overwrite `prior`.

5. **Deliberation pass invariant**: A `peer_turn` with `speech_act = deliberation_pass` MUST NOT produce a `CommonGround` record. The IE layer records `BeliefRevision.cause = social_compliance` — no self-declared wire field is required.

6. **Repair before belief update invariant**: If `GroundingVerified = False` for a `peer_turn`, the corresponding `BeliefRevision` MUST NOT be applied until a `repair_applied` event resolves the branch.

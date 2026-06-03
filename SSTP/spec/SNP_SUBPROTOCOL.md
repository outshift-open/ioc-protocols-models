# Semantic Negotiation Protocol Profile (SNP)

Status: Active specification, normative.

Comment: This profile is the authoritative definition of the SNP operation vocabulary and its binding to the SSTP envelope.  It does not replace the base SSTP protocol.

Scope: A negotiation profile that runs on top of the Interaction Engine envelope and SSTP v0 header model.

Non-goals:
- This profile does not replace SSTP core rules.
- This profile does not add new SSTP base kinds.
- This profile does not define domain-specific business payloads.

## 1. SNP Vocabulary

### 1.1 Negotiation Operations

```text
NegotiationOperation :=
  propose
  | consider_proposal
  | evaluate_proposal
  | review_proposal
  | counter_proposal
  | accept
  | reject
  | negotiate
```

### 1.2 Negotiation Status

```text
NegotiationStatus := pending | reviewed | incorporated | resolved
```

### 1.3 SSTP Kind Mapping

SNP uses the 5-value session-flow vocabulary defined in `SSTP_FORMAL_MODEL.md §3.4`:

```text
SSTPKind := intent | exchange | contingency | commit | knowledge
```

SNP operation → L9 `kind` mapping:

| SNP operation | `event_type` | L9 `kind` |
|---|---|---|
| `propose` (session-opening) | `peer_turn` | `intent` |
| `consider_proposal`, `evaluate_proposal`, `review_proposal`, `negotiate` | `peer_turn` | `exchange` |
| `counter_proposal` | `peer_turn` | `contingency` |
| Individual `accept` / `reject` | `decision_emitted` | `commit` |
| Group convergence announcement | `convergence_emitted` | `commit` |

Notes:
- Payload-level `operation` carries SNP semantics. SSTP `kind` carries session-layer role.
- `counter_proposal` opens a contingency branch at L9; the proposal payload carries the SNP semantics. Resolved by a subsequent `commit`.
- `convergence_emitted` is multicast to all participants; it is the group-closing `commit` that closes the outer session.

## 2. Data Structures

```text
String, Int, Bool, JsonValue, TimestampSec := Int where TimestampSec >= 0
Option[T] := T | null
Seq[T] := ordered finite sequence of T
Map[K, V] := finite mapping from K to V
```

### 2.1 Origin and Policy (SSTP-Compatible)

```text
Origin := {
  actor_id: String,
  tenant_id: String,
  attestation: Option[String],
}

PolicyLabels := {
  sensitivity: "public" | "internal" | "restricted" | "confidential",
  propagation: "forward" | "restricted" | "no_forward",
  retention_policy: Option[String],
}
```

### 2.2 Semantic Proposal Record

```text
SemanticProposal := {
  proposal_id: String,
  sender: String,
  receiver: String,
  payload: Map[String, JsonValue],
  payload_hash: String,
  origin: Origin,
  policy_labels: PolicyLabels,
  timestamp_sec: TimestampSec,
}
```

`payload_hash` is SHA-256 over canonical JSON payload (`sort_keys=true`).

### 2.3 Negotiation Message

```text
NegotiationMessage := {
  negotiation_id: String,
  proposal_id: String,
  sender: String,
  receiver: String,
  operation: NegotiationOperation,
  content: String,
  timestamp_sec: TimestampSec,
  status: NegotiationStatus,
}
```

### 2.4 NegotiationRound

A structured record of one multi-party negotiation round. Replaces the flat `NegotiationStore` for rounds that require Bayesian provenance tracking.

```text
NegotiationRound := {
  round_id:              String,
  proposal_id:           String,
  participants:          Seq[String],               -- agent_ids
  messages:              Seq[NegotiationMessage],   -- ordered
  individual_positions:  Map[String, Float],        -- agent_id → current posterior
  status:                open | resolved | failed,
}
```

### 2.5 ConvergenceResult

The output of a completed SNP round. Payload of `convergence_emitted`. Written to SemanticMemory as a `TeamGroundedTruth`.

```text
ConvergenceResult := {
  negotiation_id:          String,
  concept_id:              UriString,
  use_case:                String,
  participant_ids:         Seq[String],
  individual_priors:       Map[String, Float],     -- agent_id → prior at round open
  individual_posteriors:   Map[String, Float],     -- agent_id → posterior at round close
  consensus_posterior:     Float,                  -- MPC: mean position confidence at commit
  genuine_agreement_ratio: Float,                  -- GAR: fraction consistent with taskwork priors
  social_compliance_ratio: Float,                  -- SCR: fraction of revisions with cause = social_compliance
  common_ground_ids:       Seq[String],            -- CommonGround episode_ids that fed this
  outcome:                 accept | reject | deferred,
  formed_at_ms:            TimestampMs,
}
```

The `ConvergenceResult.prior_weight` for SemanticMemory is `(1.0 - SCR) × GAR` (from `EPISTEMIC_DATA_STRUCTURES.md §8.1`).

### 2.6 Stores

```text
ProposalStore    := Map[String, SemanticProposal]            -- proposal_id → SemanticProposal
NegotiationStore := Map[String, Seq[NegotiationMessage]]     -- proposal_id → ordered messages
NegotiationIndex := Map[String, NegotiationMessage]          -- negotiation_id → NegotiationMessage
RoundStore       := Map[String, NegotiationRound]            -- round_id → NegotiationRound
```

## 3. Binding to Interaction Engine + SSTP

This profile is carried inside the canonical event envelope with `l9_header`.

### 3.1 Event-Type Mapping

```text
MapOperationToEventType(op):
  propose              -> peer_turn
  consider_proposal    -> peer_turn
  evaluate_proposal    -> peer_turn
  review_proposal      -> peer_turn
  counter_proposal     -> peer_turn
  negotiate            -> peer_turn
  accept               -> decision_emitted
  reject               -> decision_emitted
```

Implications from SSTP base model:
- `peer_turn` yields `kind = exchange` (or `intent` for session-opening `propose`).
- `decision_emitted` yields `kind = commit` (individual terminal signal).
- `convergence_emitted` yields `kind = commit` (group closure commit; multicast).
- All SNP messages carry `cognition_profile_id = "semantic_alignment"` and `cognition_protocol = "SNP"` in `semantic_context`.

#### 3.1.1 convergence_emitted Event Type

```text
convergence_emitted: emitted by coordinator after majority or unanimous determination;
  kind              = commit
  commit_resolution = "converged"
  delivery          = multicast to all participant_ids
  parent_ids        = [last decision_emitted message_id]
  payload           = ConvergenceResult (§2.5)
```

This is a new SNP event type. It carries `ConvergenceResult` as payload and is the record written to SemanticMemory via `rule_update`.

### 3.2 Payload Shape for Negotiation Events

```text
NegotiationPayload := {
  profile: "semantic_negotiation",
  operation: NegotiationOperation,
  proposal_id: String,
  negotiation_id: Option[String],
  content: String,
  status: NegotiationStatus,
  payload_hash: Option[String],
  proposal_payload: Option[Map[String, JsonValue]],
}
```

Required rules:
1. `profile` MUST equal `semantic_negotiation`.
2. `operation` MUST be a value from `NegotiationOperation`.
3. `proposal_id` MUST be present for every negotiation event.
4. `proposal_payload` and `payload_hash` MUST be present for `operation = propose`.
5. `operation in {accept, reject}` SHOULD use `status = resolved`.

### 3.3 Causality Rules

1. The first `propose` message for a proposal has empty `parent_ids` unless it is a derived revision.
2. Every subsequent negotiation event SHOULD include at least one parent message id that references either:
   - the initial proposal header id, or
   - the most recent negotiation header id in the same proposal thread.
3. `accept` or `reject` SHOULD reference the latest negotiation step in `parent_ids`.

## 4. Negotiation Procedures

### 4.1 CreateProposal

```text
procedure CreateProposal(sender, receiver, proposal_payload, origin, policy, profile)
1. proposal_id := UUID4()
2. payload_hash := SHA256(CanonicalJson(proposal_payload))
3. store SemanticProposal in ProposalStore[proposal_id]
4. initialize NegotiationStore[proposal_id] := []
5. emit envelope using operation=propose and event_type=peer_turn
6. return proposal_id
```

### 4.2 SendNegotiation

```text
procedure SendNegotiation(proposal_id, sender, receiver, operation, content, parent_ids, profile)
1. require proposal_id exists or create empty negotiation thread for forward compatibility
2. negotiation_id := UUID4()
3. msg := NegotiationMessage(..., status="pending")
4. append msg to NegotiationStore[proposal_id]
5. NegotiationIndex[negotiation_id] := msg
6. event_type := MapOperationToEventType(operation)
7. emit envelope with NegotiationPayload and given parent_ids
8. return negotiation_id
```

### 4.3 ReviewNegotiation

```text
procedure ReviewNegotiation(negotiation_id)
1. if negotiation_id not in NegotiationIndex: return false
2. set NegotiationIndex[negotiation_id].status := reviewed
3. return true
```

### 4.4 ResolveNegotiation

```text
procedure ResolveNegotiation(negotiation_id)
1. if negotiation_id not in NegotiationIndex: return false
2. set NegotiationIndex[negotiation_id].status := resolved
3. return true
```

### 4.5 GetPendingNegotiations

```text
procedure GetPendingNegotiations(receiver)
1. return all NegotiationMessage where message.receiver = receiver and message.status = pending
```

### 4.6 VerifyProposalIntegrity

```text
procedure VerifyProposalIntegrity(proposal_id)
1. if proposal_id not in ProposalStore: return false
2. stored_hash := ProposalStore[proposal_id].payload_hash
3. recomputed := SHA256(CanonicalJson(ProposalStore[proposal_id].payload))
4. return (stored_hash = recomputed)
```

### 4.7 DetermineConvergence

Called by the coordinator after collecting individual `decision_emitted` messages.

```text
procedure DetermineConvergence(negotiation_id, positions, priors, scr, threshold, profile)
-- positions : Map[agent_id, Float]  -- current posteriors
-- priors    : Map[agent_id, Float]  -- taskwork priors at round open
-- scr       : Float                 -- fraction of revisions with cause = social_compliance
-- threshold : Float                 -- majority or unanimity threshold (e.g. 0.5 or 1.0)

1. mpc := mean(positions.values())
2. gar := fraction of agents where (positions[a] - 0.5) × (priors[a] - 0.5) >= 0
   -- i.e. initial and final beliefs are on the same side of 0.5: convergence did not reverse direction
3. if count(positions.values() >= threshold) / len(positions) >= threshold:
   a. outcome := accept
4. else if count(positions.values() < (1.0 - threshold)) / len(positions) >= threshold:
   a. outcome := reject
5. else if max_rounds_exceeded:
   a. outcome := deferred
6. build ConvergenceResult {
     consensus_posterior     = mpc,
     genuine_agreement_ratio = gar,
     social_compliance_ratio = scr,
     outcome                 = outcome,
     ...
   }
7. emit convergence_emitted to all participant_ids (multicast, kind = commit, commit_resolution = "converged")
8. write ConvergenceResult to SemanticMemory via rule_update with:
   prior_weight = (1.0 - scr) × gar
9. return ConvergenceResult
```

---

## 5. Theory of Mind Integration

Before a proposing agent sends a PROPOSE or COUNTER_PROPOSAL, it SHOULD consult the ToM layer to maximise the grounding quality of the proposal.

### 5.1 Pre-proposal — 1st-order ToM

1. For each peer `p` in `participant_ids`:
   - Read `AgentBeliefStore.current_belief(p.agent_id, concept_id, use_case)`
   - If `BeliefState.posterior` is already at or beyond the proposal's target value, the argument may not move `p` — consider whether to reformulate

### 5.2 Pre-proposal — 2nd-order ToM

1. For each peer `p`:
   - Consult `PeerInteractionStore.get_peer_record(self.agent_id, p.agent_id, use_case)`
   - If the planned argument type is in `PeerInteractionRecord.argument_types_ignored` for `p`, reformulate to an argument type in `argument_types_that_move`
   - Check `evidence_weights` for the target `concept_id` — weight the proposal framing toward concepts `p` historically values highly
2. Construct the proposal payload to lead with evidence types that have historically moved the specific audience

### 5.3 Post-decision update

After receiving each peer's `decision_emitted` response:
1. Record `ArgumentOutcome` and `PredictionRecord` for each peer (see `IE_SUBPROTOCOL.md §6.3`)
2. Update `PeerInteractionRecord` — the social skill map (`argument_types_that_move`, `argument_types_ignored`) improves over episodes

---

## 6. Conformance Requirements

1. Implementations MUST preserve SSTP header invariants from the base formal model.
2. Negotiation semantics MUST be represented using payload-level `operation` values.
3. Implementations SHOULD maintain deterministic causality via `parent_ids` chains.
4. Implementations SHOULD use `decision_emitted` for individual terminal acceptance/rejection outcomes.
5. Proposal integrity checks SHOULD be performed before final convergence.
6. After individual `decision_emitted` messages are collected, a coordinator MUST emit `convergence_emitted` to all `participant_ids` (multicast, `kind = commit`, `commit_resolution = "converged"`).
7. `ConvergenceResult` MUST carry `genuine_agreement_ratio` and `social_compliance_ratio`. `prior_weight` written to SemanticMemory MUST equal `(1.0 - SCR) × GAR`.

## 7. SNP Payload Extension for Social Compliance

When `speech_act = deliberation_pass` (a forced accept), the SNP layer adds `deferred_to`
in `NegotiationPayload.proposal_payload` to identify the agent whose position is being
deferred to:

```text
NegotiationPayload.proposal_payload (when deliberation_pass):
  deferred_to: Option[String],  -- agent_id this accept defers to (typically the Coordinator)
```

`deferred_to` MUST only be present when `speech_act = deliberation_pass`.  It is set by
`build_snp_payload(deferred_to=...)` in `sstp/snp/l9.py` and populated automatically by
`StarNegotiation._emit_member_accept()` when `infer_snp_epistemic()` returns `DELIBERATION_PASS`.

Note: `deferred_to` is NOT in the L9 header epistemic block.  The L9 header carries only
base epistemic fields (speech_act, epistemic_state, belief_status, concept_id, uncertainty).
The `make_snp_epistemic_extension()` function in `vocabulary.py` is available for callers
that need to stamp `deferred_to` directly onto the epistemic dict (e.g. for audit purposes),
but the normative location is `proposal_payload.deferred_to`.

## 8. Interoperability Note

A system that does not implement SNP-specific operations can still process events as standard SSTP messages:
- It can rely on `event_type`, `kind`, and `policy_labels`.
- It may treat unknown `operation` payload values as opaque negotiation metadata.

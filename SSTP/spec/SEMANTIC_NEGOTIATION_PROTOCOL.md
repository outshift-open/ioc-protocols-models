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

The SSTP base kind vocabulary used by SNP:

```text
SSTPKind :=
  intent | delegation | knowledge | query | proposal | negotiation | commit
```

Note:
- `proposal` and `negotiation` are represented as payload-level operations.
- SSTP header `kind` is always derived from canonical `event_type` by base SSTP rules.

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

### 2.4 Stores

```text
ProposalStore := Map[String, SemanticProposal]              # proposal_id -> SemanticProposal
NegotiationStore := Map[String, Seq[NegotiationMessage]]    # proposal_id -> ordered negotiation messages
NegotiationIndex := Map[String, NegotiationMessage]         # negotiation_id -> NegotiationMessage
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
- `peer_turn` yields `kind = delegation`.
- `decision_emitted` yields `kind = commit`.
- All SNP messages carry `cognition_profile_id = "semantic_alignment"` and `cognition_protocol = "SNP"` in `semantic_context`.

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

## 5. Conformance Requirements

1. Implementations MUST preserve SSTP header invariants from the base formal model.
2. Negotiation semantics MUST be represented using payload-level `operation` values.
3. Implementations SHOULD maintain deterministic causality via `parent_ids` chains.
4. Implementations SHOULD use `decision_emitted` for terminal acceptance/rejection outcomes.
5. Proposal integrity checks SHOULD be performed before final commit/decision.

## 6. Interoperability Note

A system that does not implement SNP-specific operations can still process events as standard SSTP messages:
- It can rely on `event_type`, `kind`, and `policy_labels`.
- It may treat unknown `operation` payload values as opaque negotiation metadata.

# SSTP v0 Formal Model

Status: Derived from the implemented profile in protocol/l9.py and the generic runtime usage pattern exercised by hospital3.

Scope: This document specifies the currently implemented SSTP v0 profile: the L9 header, the generic JSON transport envelope that carries it, and the message procedures that the runtime already uses.

Non-goals:
- No domain-specific payload schema is specified here.
- No application-specific alias tables, tenant tables, or policy tables are normative here.
- No business logic for healthcare, travel, sales, or any other workload is part of SSTP itself.

## 1. Model Boundary

SSTP v0 is the semantic framing layer carried inside a JSON message. The protocol governs:

1. Event-type normalization.
2. Event-to-kind classification.
3. Deterministic header construction.
4. Causal linkage through parent_ids.
5. Request, response, error, repair, and shutdown message patterns.

SSTP v0 does not govern:

1. The internal schema of payload beyond being serializable.
2. The transport implementation, other than assuming ordered message delivery per channel.
3. Domain-specific payload fields such as task goals, clinical facts, or business decisions.

In hospital3, SSTP is instantiated in two places:

1. Peer-dialogue records between agents.
2. Orchestrator-to-worker IPC envelopes over a pipe transport.

Those are example instantiations, not protocol-specific business semantics.

## 2. Notation

The model uses the following abstract types.

```text
String, Bool, Int, Float, JsonValue
TimestampMs := Int where TimestampMs >= 0
Iso8601Utc := String
UuidString := String
UriString := String

Option[T] := T | null
Seq[T] := ordered finite sequence of T
Map[K, V] := finite mapping from K to V
```

## 3. Protocol Vocabulary

### 3.1 Fixed Constants

```text
ProtocolName := "SSTP"
ProtocolVersion := "0"
```

### 3.2 Canonical Event Types

```text
EventType :=
  turn_ingested
  | peer_turn
  | repair_required
  | repair_applied
  | decision_emitted
  | episode_persisted
  | conversation_terminated
```

### 3.3 Event Aliases

```text
Alias("message") = peer_turn
Alias("peer_repair") = repair_applied
Alias("repair_applied") = repair_applied
Alias("conversation_terminated") = conversation_terminated
Alias(x) = x for all other x
```

### 3.4 Semantic Kinds

Five session-flow kinds. Each describes the role of a message in the session lifecycle, not its sub-protocol semantics.

```text
Kind := intent | exchange | contingency | commit | knowledge
```

| Kind | Session role |
|---|---|
| `intent` | Session-initiating message; triggers service selection and session establishment |
| `exchange` | Normal in-session turn; sub-protocol carries semantics |
| `contingency` | Opens a branching sub-session (repair, clarification, epistemic challenge) |
| `commit` | Closes a contingency branch or the outer session; multicast for group closure |
| `knowledge` | Propagates stable shared knowledge to semantic memory; non-session-closing |

The classification relation:

```text
KindOf(turn_ingested)           = exchange
KindOf(peer_turn)               = exchange
KindOf(repair_required)         = contingency
KindOf(repair_applied)          = commit
KindOf(epistemic_clarification) = contingency
KindOf(decision_emitted)        = commit           -- terminal SNP decision; closes contingency branch
KindOf(episode_persisted)       = commit
KindOf(conversation_terminated) = commit
KindOf(rule_update)             = knowledge        -- team-level grounded truth written to SemanticMemory
KindOf(prior_query)             = exchange
KindOf(prior_injection)         = exchange
KindOf(outcome_reported)        = exchange
KindOf(convergence_emitted)     = commit           -- group closure commit; multicast
KindOf(x)                       = exchange for any unrecognized canonical x
```

### 3.5 Schema Trust Levels

```text
SchemaTrustLevel := draft | certified
```

`commit` is the only certified kind — it carries terminal, state-stabilizing decisions that cross session or memory boundaries.

```text
TrustLevelOf(commit)         = certified
TrustLevelOf(any other kind) = draft
```

### 3.6 Schema Version Rule

```text
SchemaVersionOf(commit)         = "1.0"
SchemaVersionOf(any other kind) = "0.1"
```

## 4. Deployment Profile

To keep the protocol free of application-specific functions, the following deployment-specific functions are abstract parameters rather than normative tables.

```text
CanonicalizeUseCase : String -> String
TenantOf : String -> String
PolicyOf : String -> PolicyLabels
SchemaTopicOf : EventType -> (area: String, topic: String)
```

Required properties:

1. CanonicalizeUseCase MUST be deterministic.
2. CanonicalizeUseCase MUST be idempotent.
3. TenantOf MUST be total over canonical use cases accepted by the deployment.
4. PolicyOf MUST be total over canonical use cases accepted by the deployment.
5. SchemaTopicOf MUST be total over canonical event types.

The currently implemented event-to-schema-topic mapping is protocol-level, not application-level:

```text
SchemaTopicOf(turn_ingested) = ("intake", "turn")
SchemaTopicOf(peer_turn) = ("coordination", "peer_message")
SchemaTopicOf(repair_required) = ("coordination", "repair_request")
SchemaTopicOf(repair_applied) = ("coordination", "repair_message")
SchemaTopicOf(decision_emitted) = ("coordination", "decision")
SchemaTopicOf(episode_persisted) = ("memory", "episode_delta")
SchemaTopicOf(conversation_terminated) = ("coordination", "termination_notice")
```

## 5. Core Data Structures

### 5.1 Header Components

```text
PayloadRef := {
  type: String,
  ref: UriString,
}

Origin := {
  actor_id: String,
  tenant_id: String,
  attestation: String,
}

SemanticContext := {
  schema_id: UriString,
  schema_version: String,
  encoding: String,
  schema_trust_level: SchemaTrustLevel,
  schema_inline: Option[Map[String, JsonValue]],
}

PolicyLabels := {
  sensitivity: String,
  propagation: String,
  retention_policy: String,
}

Provenance := {
  sources: Seq[String],
  transforms: Seq[String],
}
```

### 5.2 SSTP Header

```text
EpistemicBlock := {
  speech_act:        String,   -- belief_assertion | alignment_challenge | help_request | task_handoff | deliberation_pass
  task_phase:        String,   -- taskwork | transition | action | interpersonal
}

SSTPHeader := {
  protocol:         "SSTP",
  version:          "0",
  kind:             Kind,
  message_id:       UuidString,
  dt_created:       Iso8601Utc,
  origin:           Origin,
  semantic_context: SemanticContext,
  policy_labels:    PolicyLabels,
  provenance:       Provenance,
  episode_id:         String,
  conversation_id:    Option[String],
  parent_ids:         Seq[UuidString],
  turn_depth:         Option[Int],
  confidence_score:   Option[Float],
  risk_score:         Option[Float],
  ttl_seconds:        Int,
  merge_strategy:     String,
  commit_resolution:  Option["converged" | "aborted"],
  payload_refs:       Seq[PayloadRef],
  epistemic:          Option[EpistemicBlock],
  state_sequence:     Option[Map[String, JsonValue]],
}
```

Field constraints:

1. protocol MUST equal "SSTP".
2. version MUST equal "0".
3. payload_refs MUST be non-empty.
4. parent_ids MAY be empty.
5. confidence_score and risk_score MAY be null.
6. epistemic SHOULD be present on all peer-dialogue messages; MAY be null on runtime IPC messages.
7. turn_depth MUST be present and greater than zero on `contingency` messages; MAY be null otherwise.
8. A `contingency` message MUST carry a child `episode_id` scoped to its parent exchange.
9. `commit_resolution` MUST be present when `kind = commit`; MUST be null otherwise.
10. `conversation_id` identifies the group of two or more agents engaged in this conversation.  Every message exchanged within the same agent group carries the same `conversation_id`, regardless of episode boundaries.  Set once at session open; threaded forward across all episodes for the same agent group.

### 5.3 Generic Runtime Envelope

The runtime message that carries SSTP in hospital3 is generic enough to specify as a protocol-facing envelope without including application payload semantics.

```text
Transport := {
  kind: String,
  channel: String,
}

ErrorRecord := {
  type: String,
  message: String,
  traceback: Option[String],
}

Envelope := {
  transport: Transport,
  event_type: EventType,
  request_id: String,
  sender: String,
  receiver: String,
  action: String,
  sequence_number: Int,
  status: Option[String],
  worker_pid: Option[Int],
  timestamp_ms: TimestampMs,
  payload: JsonValue,
  error: Option[ErrorRecord],
  l9_header: SSTPHeader,
}
```

Payload is intentionally opaque at the SSTP layer.

## 6. Derived Functions

### 6.1 CanonicalEventType

```text
CanonicalEventType(raw_event_type: String) -> EventType
  = Alias(lowercase(trim(raw_event_type)))
```

### 6.2 SchemaIdOf

For canonical use case `u`, canonical event type `e`, semantic kind `k`, and trust level `t`:

```text
let (area, topic) = SchemaTopicOf(e)
let version = SchemaVersionOf(k)

if t = certified then
  SchemaIdOf(u, e, k, t) = "urn:ioc:" + u + ":" + area + ":" + topic + ":v" + version
else
  SchemaIdOf(u, e, k, t) = "urn:ioc:draft:" + u + ":" + area + ":" + topic + ":v" + version
```

### 6.3 Iso8601FromTimestampMs

```text
Iso8601FromTimestampMs(t) = ISO-8601 UTC rendering of max(0, t)
```

### 6.4 MessageIdSeed

If omitted fields are null, the seed uses literal fallback strings:

```text
sender_fallback = sender if sender is non-empty else "unknown"
receiver_fallback = receiver if receiver is not null and non-empty else "none"
sequence_fallback = decimal(sequence_number) if sequence_number is not null else "none"
depth_fallback = decimal(turn_depth) if turn_depth is not null else "none"
time_fallback = decimal(max(0, timestamp_ms))

MessageIdSeed = JoinWithPipe([
  canonical_use_case,
  canonical_event_type,
  sender_fallback,
  receiver_fallback,
  sequence_fallback,
  depth_fallback,
  utterance,
  time_fallback,
])
```

### 6.5 Deterministic MessageId Rule

```text
if explicit_message_id is supplied then
  message_id = explicit_message_id
else
  message_id = UUID5(NAMESPACE_URL, MessageIdSeed)
```

### 6.6 TTL Rule

```text
TTLOf(peer_turn) = 86400
TTLOf(repair_required) = 86400
TTLOf(repair_applied) = 86400
TTLOf(any other event) = 604800
```

### 6.7 Default Logical Clock

```text
DefaultLogicalClock(sequence_number) =
  "lamport:" + decimal(sequence_number) if sequence_number is not null
  null otherwise
```

## 7. Normative Procedures

### 7.1 BuildHeader

```text
procedure BuildHeader(
  use_case,
  event_type,
  sender,
  receiver,
  timestamp_ms,
  turn_depth = null,
  utterance = "",
  parent_ids = [],
  confidence_score = null,
  risk_score = null,
  episode_id = null,
  conversation_id = null,
  merge_strategy = "merge",
  provenance_sources = [],
  provenance_transforms = [],
  payload_refs = null,
  schema_inline = null,
  schema_trust_level = null,
  message_id = null,
  kind_override = null,
  commit_resolution = null,
  profile,
) returns SSTPHeader

1. u := profile.CanonicalizeUseCase(use_case)
2. e := CanonicalEventType(event_type)
3. k := kind_override if supplied else KindOf(e)
4. t := schema_trust_level if supplied else TrustLevelOf(k)
5. mid := message_id if supplied else UUID5(NAMESPACE_URL, MessageIdSeed(...))
6. parents := ordered list of non-empty string values from parent_ids
7. sources := ordered list of non-empty string values from provenance_sources
8. transforms := ordered list of non-empty string values from provenance_transforms
9. refs := payload_refs if supplied else [{type: "inline", ref: "urn:ioc:payload:" + mid}]
10. ttl := TTLOf(e)
11. tenant := profile.TenantOf(u)
12. policy := profile.PolicyOf(u)
13. schema_id := SchemaIdOf(u, e, k, t)
14. cr := commit_resolution if k = commit else null
15. return the SSTPHeader value populated with these derived fields
```

Default episode scope rule used by the implementation:

```text
if episode_id is omitted then
  episode_id := "urn:ioc:" + u + ":state:shared_dialogue"
```

### 7.2 BuildEnvelope

```text
procedure BuildEnvelope(
  transport,
  event_type,
  sender,
  receiver,
  action,
  sequence_number,
  payload,
  request_id,
  parent_ids = [],
  status = null,
  error = null,
  worker_pid = null,
  header_episode_id = null,
  header_conversation_id = null,
  header_kind_override = null,
  header_commit_resolution = null,
  header_provenance_sources = [],
  header_provenance_transforms = [],
  profile,
) returns Envelope

1. timestamp_ms := current wall-clock time in milliseconds
2. utterance := action if status is null else action + ":" + status
3. header := BuildHeader(...)
4. return Envelope {
     transport,
     event_type,
     request_id,
     sender,
     receiver,
     action,
     sequence_number,
     status,
     worker_pid,
     timestamp_ms,
     payload,
     error,
     l9_header = header,
   }
```

### 7.3 SerializeAndSend

```text
procedure SerializeAndSend(connection, envelope)
1. encoded := UTF-8 bytes of JSON(envelope)
2. write encoded to connection
```

### 7.4 ReceiveAndDecode

```text
procedure ReceiveAndDecode(connection) returns Envelope
1. encoded := read bytes from connection
2. return JSON-decode(encoded)
```

### 7.5 Peer Turn / Repair / Termination Lifecycle

This is the generic message pattern already present in the implementation.

```text
procedure EmitPeerTurn(...)
1. emit Envelope with event_type = peer_turn
2. if the turn is within policy bounds, stop
3. if the turn violates policy bounds:
   a. emit Envelope with event_type = repair_required and parent_ids = [peer_turn.message_id]
   b. if repair is available:
      i. emit Envelope with event_type = repair_applied and parent_ids = [repair_required.message_id]
   c. else if termination policy fires:
      i. emit Envelope with event_type = conversation_terminated and parent_ids = [peer_turn.message_id]
```

The protocol does not constrain how "out of bounds", "repair available", or "termination policy" is decided. Those are application policies outside SSTP.

### 7.6 InitiateSession

The first message in a session MUST carry `kind = intent`. It triggers service selection and session establishment.

```text
procedure InitiateSession(use_case, sender, receiver, intent_payload, profile)
1. episode_id := new session identifier, e.g. "urn:ioc:{use_case}:session:{UUID4()}"
2. conversation_id := identifier for this agent group, e.g. "urn:ioc:{use_case}:group:{UUID4()}"
3. emit BuildEnvelope(event_type = "peer_turn", header_kind_override = "intent",
     header_episode_id = episode_id, header_conversation_id = conversation_id, parent_ids = [],
     payload = intent_payload)
4. service routing resolves the receiving endpoint from the intent payload
5. session state is established at both sender and receiver
6. subsequent messages in this session use the same episode_id with kind = exchange
```

### 7.9 ContingencyBranch

A `contingency` message opens a branching sub-session. The parent session is held while the branch executes. A subsequent `commit` closes the branch and resumes the parent.

```text
procedure OpenContingencyBranch(parent_message_id, parent_episode_id, parent_turn_depth, branch_payload, profile)
1. child_episode_id := parent_episode_id + ":branch:" + UUID4()
2. child_turn_depth := parent_turn_depth + 1
3. emit BuildEnvelope(event_type = "repair_required", header_kind_override = "contingency",
     header_episode_id = child_episode_id,
     turn_depth = child_turn_depth,
     parent_ids = [parent_message_id],
     payload = branch_payload)
4. parent session is held pending branch resolution

procedure CloseContingencyBranch(branch_message_id, parent_episode_id, resolution_payload, profile)
1. emit BuildEnvelope(event_type = "repair_applied", header_kind_override = "commit",
     header_episode_id = parent_episode_id,
     header_commit_resolution = "converged",
     turn_depth = null,
     parent_ids = [branch_message_id],
     payload = resolution_payload)
2. parent session resumes from the point it was held
```

### 7.10 ConvergeSession

A group closure `commit` closes the outer session. It MUST be multicast to all participant_ids. All epistemic states stabilize at this point.

```text
procedure ConvergeSession(session_id, participant_ids, convergence_payload, profile)
1. emit BuildEnvelope(event_type = "convergence_emitted", header_kind_override = "commit",
     header_episode_id = session_id,
     header_commit_resolution = "converged",
     parent_ids = [last_exchange_message_id],
     payload = convergence_payload)
   for each p in participant_ids (multicast delivery)
2. each recipient updates epistemic state per the ConvergenceResult in the payload
3. session is closed; no further exchange messages are valid on this episode_id
```

## 8. State Machines

### 8.1 Message Causality State Machine

```text
Drafted -> Framed -> Sent -> Received -> Applied -> Archived
                         \-> Failed
                         \-> TimedOut
```

Interpretation:

1. Drafted: caller has semantic intent but no header yet.
2. Framed: SSTP header and envelope are built.
3. Sent: serialized message is written to transport.
4. Received: peer decodes message.
5. Applied: peer has processed the message.
6. Archived: message becomes part of trace or persisted episode state.
7. Failed: peer returns an error event.
8. TimedOut: sender never observes a reply in the permitted interval.

### 8.2 Repair Subprotocol State Machine

```text
Stable
  -> PeerTurnEmitted
  -> RepairRequired
  -> Repaired

Stable
  -> PeerTurnEmitted
  -> RepairRequired
  -> Terminated
```

### 8.3 Request / Response State Machine

```text
Idle
  -> RequestSent
  -> ResponseReceived

Idle
  -> RequestSent
  -> ErrorReceived

Idle
  -> RequestSent
  -> TimedOut

Idle
  -> ShutdownSent
  -> ShutdownAcknowledged
```

## 9. Safety and Consistency Invariants

1. Header protocol/version invariant:
   Every SSTP header MUST carry protocol = "SSTP" and version = "0".

2. Kind classification invariant:
   header.kind MUST equal KindOf(CanonicalEventType(envelope.event_type)).

3. Schema version invariant:
   header.semantic_context.schema_version MUST equal SchemaVersionOf(header.kind).

4. Trust-level invariant:
   If the caller did not explicitly override trust level, header.semantic_context.schema_trust_level MUST equal TrustLevelOf(header.kind).

5. Deterministic identity invariant:
   If explicit message_id is omitted, identical canonical inputs MUST produce identical message_id values.

6. Parent linkage invariant:
   If a message is causally derived from an earlier message, the earlier message_id SHOULD appear in parent_ids.

7. Request-response correlation invariant:
   A successful or failed reply SHOULD preserve request_id and SHOULD place the request message_id in parent_ids when available.

8. TTL invariant:
   ttl_seconds MUST equal TTLOf(canonical event type).

9. Payload reference invariant:
   If payload_refs is omitted, the header MUST contain exactly one inline payload reference of the form urn:ioc:payload:{message_id}.

10. Protocol boundary invariant:
    Domain payload fields and deployment policy tables are external to SSTP semantics and MUST NOT alter the rules above except through the explicit deployment profile functions.

11. Session initiation invariant:
    The first message in any session MUST carry `kind = intent`. Service routing resolves only on this message. Subsequent messages in the session MUST NOT carry `kind = intent`.

12. Contingency nesting invariant:
    A `contingency` message MUST carry `turn_depth > 0` and a child `state_object_id` distinct from the parent session's `state_object_id`. A `commit` that closes a branch MUST reference the `contingency` message in `parent_ids`.

13. Convergence delivery invariant:
    A `convergence` message MUST be delivered to all `participant_ids` listed in the session or convergence payload. No further `exchange` messages are valid on the same `state_object_id` after a `convergence` is delivered.

## 10. Example Instantiations From Hospital3

These examples are informative only.

### 10.1 Peer Dialogue Example

Hospital3 uses a shared-dialogue state object for peer-to-peer turns.

```text
event_type      = peer_turn
sender          = actor_A
receiver        = actor_B
state_object_id = urn:ioc:{use_case}:state:shared_dialogue
kind            = exchange
ttl_seconds     = 86400
```

If that peer turn is judged out of bounds, hospital3 emits:

```text
peer_turn -> repair_required -> repair_applied
```

with parent_ids chaining each step to the prior step.

### 10.2 Worker IPC Example

Hospital3 uses a process-local transport envelope carrying SSTP:

```text
transport.kind              = multiprocessing_pipe
event_type                  = peer_turn
state_object_id             = urn:ioc:{use_case}:state:agent_pipe:{receiver}
provenance.sources          = ["process:{pid}"]
provenance.transforms       = ["multiprocessing_pipe"]
```

The worker reply references the request header through parent_ids.

## 11. What Is Normative vs Configurable

Normative in this document:

1. SSTP header structure.
2. Event normalization and kind classification.
3. Schema version and default trust-level rules.
4. Deterministic message-id construction.
5. Envelope structure used by the current runtime profile.
6. Generic request, response, repair, and shutdown procedures.

Configurable by deployment:

1. Use-case canonicalization.
2. Tenant mapping.
3. Sensitivity, propagation, and retention policies.
4. Concrete transport implementation.
5. Payload schema.
6. Application policy deciding when repair or termination is triggered.

This separation is what keeps the specification free of application-specific functions while still matching the implemented protocol.

## 12. Adaptation Profile: Semantic Negotiation Over SSTP

Source basis: `/Users/pbosch/src/GitHub/ioc-cfn-protocols-experiments/protocols/simple_protocol_v3.py`.

Comment: This adaptation imports the external semantic-negotiation operations into the local protocol stack by binding them to SSTP envelopes, header rules, and causal linkage.

This section defines a use-case adaptation profile that runs on top of the base SSTP model without changing SSTP core invariants. The full copied/adapted profile specification is in `protocol/SEMANTIC_NEGOTIATION_PROTOCOL.md`.

### 12.1 Profile Intent

The semantic-negotiation profile adds explicit operation semantics for collaborative proposal refinement:

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

This operation vocabulary is encoded in payload, while SSTP header `kind` remains derived from canonical `event_type`.

### 12.2 Adaptation Data Structures

```text
SemanticProposal := {
  proposal_id: String,
  sender: String,
  receiver: String,
  payload: Map[String, JsonValue],
  payload_hash: String,
  origin: Origin,
  policy_labels: PolicyLabels,
  timestamp_sec: Int,
}

NegotiationMessage := {
  negotiation_id: String,
  proposal_id: String,
  sender: String,
  receiver: String,
  operation: NegotiationOperation,
  content: String,
  timestamp_sec: Int,
  status: pending | reviewed | incorporated | resolved,
}

NegotiationPayload := {
  profile: "semantic_negotiation",
  operation: NegotiationOperation,
  proposal_id: String,
  negotiation_id: Option[String],
  content: String,
  status: String,
  payload_hash: Option[String],
  proposal_payload: Option[Map[String, JsonValue]],
}
```

### 12.3 Mapping to SSTP Event Types and Kinds

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

By base SSTP rules:

```text
KindOf(peer_turn)        = exchange
KindOf(decision_emitted) = commit
```

Therefore terminal agreement outcomes are represented as `decision_emitted` events with `kind = commit`, while iterative discussion steps remain `peer_turn` with `kind = exchange`.

### 12.4 Adaptation Procedures

```text
procedure CreateProposal(sender, receiver, proposal_payload, profile)
1. proposal_id := UUID4()
2. payload_hash := SHA256(CanonicalJson(proposal_payload))
3. initialize proposal and negotiation stores for proposal_id
4. emit BuildEnvelope(event_type = peer_turn, payload.operation = propose, payload.payload_hash = payload_hash)
5. return proposal_id
```

```text
procedure SendNegotiation(proposal_id, sender, receiver, operation, content, parent_ids, profile)
1. negotiation_id := UUID4()
2. event_type := MapOperationToEventType(operation)
3. emit BuildEnvelope(event_type = event_type, payload.operation = operation, payload.negotiation_id = negotiation_id, parent_ids = parent_ids)
4. append message to negotiation history for proposal_id
5. return negotiation_id
```

```text
procedure ReviewNegotiation(negotiation_id)
1. mark negotiation status as reviewed if it exists
```

```text
procedure ResolveNegotiation(negotiation_id)
1. mark negotiation status as resolved if it exists
2. if this resolution is accept or reject, ensure the corresponding event was emitted as decision_emitted
```

```text
procedure VerifyProposalIntegrity(proposal_id)
1. recompute SHA256(CanonicalJson(proposal_payload))
2. compare with stored payload_hash
3. return true iff equal
```

### 12.5 Adaptation Invariants

1. Base SSTP invariants in Section 9 remain mandatory.
2. `payload.profile` MUST equal `semantic_negotiation` for this adaptation.
3. `payload.operation` MUST be one of the profile operations above.
4. `accept` and `reject` SHOULD map to `decision_emitted` and thus `kind = commit`.
5. Every non-initial negotiation step SHOULD include a causal parent in `parent_ids`.
6. Proposal finalization SHOULD be gated by successful payload integrity verification.
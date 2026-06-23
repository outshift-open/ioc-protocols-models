# Contingency Interaction Protocol (CIP)

CIP is the sub-protocol of SSTP that ensures pairwise grounding between agents. It verifies that each message in an exchange genuinely engages the prior turn's argument, detects failures, and drives repair cycles. CIP is the SSTP rename of what was previously called the Interaction Engine (IE).

CIP runs on every exchange message alongside SIEP. A SIEP counter-proposal, for example, must also pass CIP's contingency check — without it, SIEP could converge on a position that was never actually argued for.

## Purpose

Three things must hold for a pairwise exchange to produce genuine common ground:

1. Each agent declares an independent prior belief before any peer contact. Without this, there is no baseline to measure whether exchange actually moved anyone.
2. Each response must demonstrably engage the concepts from the prior turn. A response that does not engage is a parallel assertion, not a reply.
3. When grounding fails, the protocol must detect it and drive a repair cycle so the exchange either recovers or terminates cleanly rather than propagating nonsense.

CIP enforces all three.

## Concepts and beliefs

CIP tracks belief at the level of individual concepts identified by URI. An agent can be expert on `concept:drug_interaction` and have no knowledge of `concept:appointment_timing` — CIP's belief model captures this per-concept granularity.

**Concept URIs** follow the convention `urn:concept:<use_case>:<category>:<specific>`. The category URI is always present; the specific URI is added when the agent has identified a concrete instance (e.g. a named drug pair).

**Prior** `π(a,c,ε)` — agent `a`'s belief in concept `c` at episode open. Declared once via the initial prior message. Immutable for the episode. Used as the GAR anchor.

**Posterior** `ρ(a,c,ε)` — agent `a`'s current belief after all peer-influenced revisions in episode `ε`.

**Revision cause** — why belief moved. One of:

| Value | Meaning |
|---|---|
| `grounded_argument` | Peer's argument was contingent and engaged this agent's evidence. Counts toward GAR. |
| `social_compliance` | Agent yielded to social pressure without genuine conviction. Counts toward SCR. |
| `semantic_memory` | Prior set from SemanticMemory at episode open. Not a peer revision. |
| `new_evidence` | External evidence not part of the peer exchange. |
| `repair_resolution` | Belief updated after a repair cycle resolved a grounding failure. |

## CIP payload fields

The CIP payload is carried as `payload[type=ie]` on any L9 message.

| Field | Values | Description |
|---|---|---|
| `utterance.evidence` | `list[URI]` | Concept URIs the sender asserts evidence for. |
| `utterance.addresses_evidence` | `list[URI]` | Concept URIs from the prior turn being engaged. Empty on the opening turn. |
| `utterance.turn_depth` | `int` | Depth within a repair branch. 0 = top-level or initial prior. |
| `grounding.contingency_verified` | `bool \| null` | Whether the receiver confirmed this turn engages the prior. Filled by receiver. |
| `grounding.contingency_score` | `float \| null` | Grounding confidence `[0,1]`. Filled by receiver. |
| `grounding.repair_reason` | `"initial_prior" \| "grounding_failure" \| "scope_mismatch" \| "ungroundable_novelty" \| null` | Why repair is needed. `initial_prior` signals the opening turn — not a failure; grounding starts here. |
| `grounding.challenges` | `list[URI]` | Concept URIs the receiver disputes. |
| `belief.prior` | `float [0,1]` | GAR anchor — belief at episode open; immutable per episode. |
| `belief.posterior` | `float [0,1]` | Current belief after all revisions this episode. |
| `belief.revision_cause` | `string \| null` | See revision cause table above. |

## Contingency check

The contingency check determines whether message M_B genuinely responds to message M_A:

```
contingency_score = |M_B.cip.utterance.addresses_evidence ∩ M_A.cip.utterance.evidence| / normalization
contingency holds iff contingency_score ≥ θ_c   (θ_c = 0.40)
```

If contingency holds, the receiver sets `contingency_verified=true` and `contingency_score`. If it fails, the receiver emits a `contingency` message (repair request) against the offending turn.

## Evidence field usage examples

**`utterance.evidence`** — what this agent is asserting:

| Value | When |
|---|---|
| `["concept:drug_interaction"]` | Category-only — prior not yet resolved to a specific instance. |
| `["concept:drug_interaction", "urn:concept:healthcare:drug_interaction:warfarin+ibuprofen"]` | Category + specific pair known from domain assessment. |
| `[]` | Repair turns re-anchoring without new conceptual content. |

**`utterance.addresses_evidence`** — what the prior turn said that this turn engages:

| Value | When |
|---|---|
| `["concept:drug_interaction", "concept:coverage_decision"]` | Engaging multiple prior-turn concepts. |
| `["concept:drug_interaction", "urn:concept:healthcare:drug_interaction:warfarin+ibuprofen"]` | Engaging a specific sub-concept from the prior turn. |
| `[]` | Opening turn — no prior turn to address. |

## Prior/posterior examples

| Setting | Meaning |
|---|---|
| `prior=0.5, posterior=0.5` | Flat prior — no prior knowledge on this concept. |
| `prior=0.93, posterior=0.64` | Strong prior moved by a genuinely engaging counter-argument. |
| `prior=0.5, posterior=0.5, revision_cause=social_compliance` | Belief nominally unchanged but agent yielded under pressure. SCR increment. |

## Protocol flows

### Initial prior declaration

Must be emitted once per agent per concept before any grounding exchange on that concept in the episode.

```
aᵢ →_ε bus :
  kind=exchange, subprotocol=CIP
  epistemic.state=taskwork, epistemic.message_act=assertion
  topic=c
  epistemic.uncertainty = 1 − π(aᵢ,c,ε)
  payload[cip].belief.prior     = π(aᵢ,c,ε)
  payload[cip].belief.posterior = π(aᵢ,c,ε)   -- prior = posterior at declaration
  payload[cip].belief.revision_cause = semantic_memory
  payload[cip].utterance.addresses_evidence = []
```

**Invariant T1:** `prior_declaration(aᵢ,c,ε)` must be emitted before the first CIP exchange on `c` in `ε` where `aᵢ` appears as sender or receiver.
**Invariant T2:** `payload[cip].belief.prior` is immutable in `ε` once declared.

### Normal grounding exchange

```
Step 1 — A asserts:
A →_ε B :
  kind=exchange, subprotocol=CIP
  epistemic.state=grounding, epistemic.message_act=assertion
  topic=c
  payload[cip].utterance.evidence = E_A
  payload[cip].utterance.addresses_evidence = E_B   -- ∅ on first turn

Step 2 — B verifies and responds:
  contingency_score = |E_A ∩ prior_turn.evidence| / normalization
  if contingency_score ≥ θ_c:
    B →_ε A :
      kind=exchange, subprotocol=CIP
      epistemic.state=grounding
      payload[cip].grounding.contingency_verified = true
      payload[cip].grounding.contingency_score = contingency_score
      payload[cip].utterance.addresses_evidence = E_A
      payload[cip].belief.posterior = ρ(B,c,ε)
      payload[cip].belief.revision_cause ∈ { grounded_argument, social_compliance, … }
      message.parents = [M_A.message.id]
```

**Invariant G1:** If M_B responds to M_A, then `M_B.message.parents ⊇ { M_A.message.id }`.
**Invariant G2:** If `M_B.cip.grounding.contingency_verified = true`, then `M_B.epistemic.belief_status ∈ { asserted, revised }`.

### Repair cycle

When contingency fails, the listener (not the speaker) opens a repair branch via `kind=contingency`. The listener owns the branch from open to close.

```
Step 1 — A sends bad turn:
  A →_ε B : M_bad
    kind=exchange, subprotocol=CIP, epistemic.state=grounding
    contingency_score(M_bad, prior) < θ_c

Step 2 — B detects failure and requests repair:
  B →_ε A : M_req          ← LISTENER is sender
    kind=contingency, subprotocol=CIP
    epistemic.state=grounding, epistemic.belief_status=challenged
    message.parents = [M_bad.message.id]
    payload[utterance] = "repair_required:reason=<r>:target=<M_bad.id>"

Step 3 — A re-attempts:
  A →_ε B : M_rep
    kind=exchange, subprotocol=CIP, epistemic.state=grounding
    message.parents = [M_req.message.id]
    payload[cip].utterance.addresses_evidence ∩ M_bad.cip.utterance.evidence ≠ ∅

Step 4 — B verifies and closes:
  B →_ε A : M_close         ← LISTENER closes what it opened
    kind=commit, subkind=resolved, subprotocol=CIP
    epistemic.state=grounding
    message.parents = [M_rep.message.id]
```

Causal chain: `M_bad ← M_req ← M_rep ← M_close`

**Invariant R1:** `sender(M_req) = receiver(M_bad)` — the listener detects and reports.
**Invariant R2:** `sender(M_close) = sender(M_req)` — the listener who opened the branch closes it.
**Invariant R3:** Repair depth is bounded. If repair fails after `d_max` cycles the exchange terminates with `belief_status=unresolved`.

## CIP payload schema (formal)

```
CIPPayload := {
  utterance := {
    evidence:           [URI]          -- concepts the sender argues from
    addresses_evidence: [URI]          -- concepts from prior turn engaged; ∅ on first turn
    turn_depth:         N              -- 0 = top-level; >0 = inside repair branch
    -- note: utterance text, rationale, thought_summary carried in payload[type=utterance]
  }
  grounding := {
    contingency_verified: Bool ∪ { nil }   -- filled by receiver
    contingency_score:    [0,1] ∪ { nil }  -- filled by receiver
    repair_reason:        "initial_prior" | "grounding_failure" | "scope_mismatch"
                          | "ungroundable_novelty" | nil
    challenges:           [URI]
  }
  belief := {
    prior:          [0,1]    -- π(a,c,ε); immutable after initial_prior
    posterior:      [0,1]    -- ρ(a,c,ε); current belief
    revision_cause: String | nil
  }
}
```

## Composition with SIEP

CIP and SIEP compose on the same message. A single exchange may carry both `payload[cip]` and `payload[siep]`:

- `payload[siep].proposal_payload.addresses_evidence` feeds the CIP contingency check on SIEP counter-proposals.
- `payload[cip].grounding.contingency_verified` is the result of that check.
- A counter-proposal that fails CIP contingency is flagged but not blocked — CIP produces the signal, SIEP decides whether to accept or re-propose.

## Well-formedness conditions

| Condition |
|---|
| Every `M.kind = contingency` has a descendant `M'` where `M'.kind = commit ∧ M'.subkind = resolved ∧ M'.message.parents ⊇ { M_rep.id }` — every repair branch is closed. |
| `M.message.parents ⊆ { id : M' ∈ ε ∧ M'.message.id ∈ M.message.parents }` — all parents exist in the same episode. |
| The parent graph is acyclic. |
| For all `(a,c,ε)`: `prior_declaration(a,c,ε)` precedes (causal order) the first grounding exchange on `(a,c,ε)`. |

## API methods (AgentBus)

The following `AgentBus` methods emit CIP messages. All return an L9 header dict; use `result["message"]["id"]` as `parent_id` for the responding turn.

### `emit_initial_prior`

Declares an agent's independent belief before any peer exchange. Must be called once per concept per agent before any `emit_grounding_turn` on that concept.

```python
bus.emit_initial_prior(
    sender="diagnostics",
    receiver="orchestrator",
    concept_id="concept:drug_interaction",
    prior=0.93,
    posterior=0.93,
    evidence=["concept:drug_interaction"],
)
```

### `emit_grounding_turn`

Asserts a position in a pairwise CIP grounding exchange. The caller passes domain values; the method constructs the full CIP payload.

```python
# Opening turn
h1 = bus.emit_grounding_turn(
    speaker="diagnostics",
    listener="pharmacy",
    utterance="drug interaction risk is high — anticoagulant with ibuprofen",
    concept_id="concept:drug_interaction",
    prior=0.93, posterior=0.93,
    evidence=["concept:drug_interaction", "concept:anticoagulant_use"],
)

# Response — must address prior evidence
h2 = bus.emit_grounding_turn(
    speaker="pharmacy", listener="diagnostics",
    utterance="confirmed, interaction risk elevated",
    concept_id="concept:drug_interaction",
    prior=0.50, posterior=0.85,
    revision_cause="grounded_argument",
    evidence=["concept:drug_interaction"],
    addresses_evidence=["concept:drug_interaction", "concept:anticoagulant_use"],
    parent_id=h1["message"]["id"],
)
```

### `emit_semantic_repair`

The listener emits this when it detects a grounding failure. Opens a repair branch (`kind=contingency`).

```python
repair_req = bus.emit_semantic_repair(
    sender="pharmacy",           # listener — detected the failure
    receiver="diagnostics",      # speaker — must repair
    target_message_id=bad_turn["message"]["id"],
    repair_reason=RepairReason.GROUNDING_FAILURE,
)
```

### `receive_peer_turn`

Processes an incoming CIP grounding message. Runs the contingency check; auto-emits `repair_required` if the check fails. Returns `None` if grounded, or the repair-request header if not.

```python
repair = bus.receive_peer_turn(
    envelope=header,
    replica=my_replica,
    belief_store=my_belief_store,
    common_ground_store=my_cg_store,
)
if repair is not None:
    # repair_required was emitted automatically; wait for sender's repair attempt
    pass
```

# L9 Formal Protocol Definitions

This document contains the formal notation, message schema, payload schemas, protocol flows,
and well-formedness conditions for L9 version 0.0.5. All field names match the current
implementation in `SSTP/l9_base.py`, `SSTP/subprotocol/cip/src/l9.py`, and
`SSTP/subprotocol/siep/src/l9.py`.

---

## Notation

```
A →_ε B : M      agent A sends message M to agent B within episode ε
[A]              the set of agents A₁…Aₙ
M.field          field access on message M (nested: M.context.epistemic.state)
∀i               for all i in the applicable set
∃                there exists
⊆                subset
∩                intersection
←                parented by (message.parents)
⊥                empty / null
θ_c              contingency threshold = 0.40
θ_a              accept threshold (configurable per negotiation; default 0.10)
```

---

## Definitions

**Episode ε** — a bounded coordination context identified by a URN. All messages within one
coordination cycle share `message.episode = ε`. An episode has exactly one `kind=intent` root
and at most one `kind=commit` leaf. An episode without a commit is void.

**Concept c** — a URI identifying a specific piece of knowledge under discussion.
Index key for belief tracking, ToM prediction, and GAR anchor computation.
Convention: `urn:concept:<use_case>:<category>` (category) or
`urn:concept:<use_case>:<category>:<specific>` (sub-concept, tokens alphabetically ordered).

**Prior π(a,c,ε)** — agent a's belief in concept c at episode open. Declared in a
`kind=exchange, context.epistemic.state=taskwork` message before any peer exchange.
Immutable once declared in ε.

**Posterior ρ(a,c,ε)** — agent a's current belief in concept c after all revisions in episode ε.
Starts equal to π(a,c,ε); updated by grounded peer exchange, repair resolution, or
(contributing to SCR) social compliance.

**Contingency** — message M_B is contingent on M_A iff:
```
M_B.payload[type=cip].utterance.addresses_evidence ∩ M_A.payload[type=cip].utterance.evidence ≠ ∅
```
Quantified as:
```
contingency_score(M_B, M_A) = |addresses_evidence(M_B) ∩ evidence(M_A)| / |evidence(M_A)|
```
A turn is grounded iff `contingency_score ≥ θ_c`.

**GAR (Genuine Agreement Ratio)** — fraction of agents whose posterior moved in the same
direction as the consensus relative to their prior:
```
GAR(c,ε) = |{ aᵢ : (ρ(aᵢ,c,ε) − π(aᵢ,c,ε)) × (MPC(c,ε) − 0.5) ≥ 0 }| / |[A]|
```

**SCR (Social Compliance Ratio)** — fraction of belief revisions caused by social compliance
rather than grounded argument, aggregated over the team:
```
SCR_team(c,ε) = |{ (a,rev) : rev.revision_cause = social_compliance, a ∈ [A] }|
              / |{ (a,rev) : a ∈ [A] }|
```

**MPC (Multi-Party Consensus)** — mean posterior across all participating agents at convergence:
```
MPC(c,ε) = mean({ ρ(aᵢ,c,ε) : aᵢ ∈ [A] })
```

**Provenance weight** of a converged rule written to TeamEpistemicMemory:
```
W(c,ε) = (1 − SCR_team(c,ε)) × GAR(c,ε)
```
A rule with W=1.0 was unanimously and genuinely agreed. A rule with W→0 was produced largely
by social compliance and should be trusted less in future episodes.

---

## Message Schema

Every L9 message M carries the following fields (v0.0.5 wire format):

```
M := {
  protocol    = "SSTP"
  version     = "0.0.5"
  kind        ∈ { intent, exchange, contingency, commit, knowledge }
  subkind     ∈ { converged, rejected, resolved, ready, ⊥ }
  subprotocol ∈ { "CIP", "SIEP" }

  participants := {
    actors : [Actor+]           -- at least one; exactly one with participant_type="sender"
    groups : object | ⊥
  }

  Actor := {
    id               : string
    role             : string
    participant_type ∈ { "sender", "recipient", "observer" }
    attestation      : string | ⊥
  }

  message := {
    id      : UUID              -- random UUID; unique per message
    parents : [UUID*]           -- causal predecessors
    episode : URN               -- shared by all messages in ε
  }

  context := {
    topic    : URI | ⊥          -- concept under discussion; ⊥ on session-lifecycle messages
    epistemic : {
      message_act    ∈ { assertion, challenge, compliance, ⊥ }
      state          ∈ { taskwork, grounding, team_process, ⊥ }
      belief_status  ∈ { asserted, deferred, challenged, revised, retracted, unresolved, ⊥ }
      uncertainty    ∈ [0,1]    -- 1 − posterior; 0.0 on process messages
    }
    semantic : {
      schema_id    : URN | ⊥
      ontology_ref : URI | ⊥
    }
  }

  policy := {
    sensitivity      ∈ { public, internal, restricted, confidential, ⊥ }
    propagation      ∈ { forward, restricted, no_forward, ⊥ }
    retention_policy : URN | ⊥
  }

  attributes := {
    msg_sources    : [string*]
    msg_transforms : [string*]
    msg_created    : ISO 8601 UTC
    msg_expiry     : ISO 8601 UTC | ⊥
  }

  payload : [PayloadPart*]
}

PayloadPart := {
  type     ∈ { utterance, cip, siep, cip-repair, team_process, knowledge, team_prior, query, snp-convergence, … }
  location ∈ { inline, external }
  content  : string | dict | ⊥
  ref      : URN | ⊥
}
```

---

## CIP Payload Schema

`payload[type=cip].content` — carried on all CIP grounding exchange messages.

```
CIPPayload := {
  utterance := {
    evidence           : [URI]   -- concepts the sender argues from
    addresses_evidence : [URI]   -- concepts from prior turn being engaged; ∅ on first turn
    ring_round         : ℕ       -- pass through agent ring (0 = first pass / not in ring)
    repair_depth       : ℕ       -- recursion depth in repair branch (0 = not in repair)
  }
  grounding := {
    contingency_verified : Bool | ⊥   -- filled by receiver after contingency check
    contingency_score    : [0,1] | ⊥  -- filled by receiver
    repair_reason        : string | ⊥  -- "grounding_failure" | "scope_mismatch" | "ungroundable_novelty"
    challenges           : [URI]        -- concept URIs the receiver disputes
  }
  belief := {
    prior          : [0,1]   -- π(a,c,ε); immutable after first declaration in ε
    posterior      : [0,1]   -- ρ(a,c,ε); current belief
    revision_cause : string | ⊥
                   -- "grounded_argument" | "social_compliance" | "semantic_memory"
                   -- | "new_evidence" | "repair_resolution"
  }
}
```

---

## SIEP Payload Schema

`payload[type=siep].content` — carried on SIEP panel negotiation messages.

```
SIEPPayload := {
  profile      : "semantic_negotiation"
  operation    ∈ { propose, counter_proposal, accept, reject, negotiate,
                   consider_proposal, evaluate_proposal, review_proposal }
  proposal_id  : UUID
  content      : string          -- position label on the concept axis
  status       ∈ { pending, reviewed, incorporated, resolved }
  negotiation_id : UUID | ⊥

  proposal_payload := {
    posterior           : [0,1]
    supporting_evidence : [URI]
    against_evidence    : [URI]
    addresses_evidence  : [URI]   -- CIP contingency input for counter-proposals
    reasoning_summary   : string
    deferred_to         : AgentID | ⊥   -- ⊥ = genuine accept; set = social compliance
  }
}
```

Convergence metrics are carried separately in `payload[type=snp-convergence]` on
`commit:converged` messages:

```
SNPConvergencePayload := {
  mpc             : [0,1]      -- mean posterior at convergence
  gar             : [0,1]      -- genuine agreement ratio
  scr             : [0,1]      -- social compliance ratio
  participant_ids : [AgentID+] -- agents included in the convergence calculation
}
```

---

## Protocol Flows

### Session Lifecycle

**Open (team process or taskwork episode)**
```
Coordinator →_ε [A] :
  kind=intent, subprotocol=CIP, context.epistemic.state=team_process
  participants.actors = [sender] + [recipient × |[A]|]
  message.parents = []
  message.episode = ε
  context.topic = ⊥
```

**Close — converged**
```
Coordinator →_ε [A] :
  kind=commit, subkind=converged, subprotocol=CIP, context.epistemic.state=team_process
  participants.actors = [sender] + [recipient × |[A]|]
  message.episode = ε
```

**Close — rejected**
```
Coordinator →_ε [A] :
  kind=commit, subkind=rejected, subprotocol=CIP, context.epistemic.state=team_process
  message.episode = ε
```

Pre-condition OPEN: no prior `kind=intent` in ε.
Post-condition CLOSE: every `kind=contingency` in ε has a descendant `kind=commit,
subkind=resolved` — all repair branches are closed before the outer episode commits.

---

### Taskwork — Independent Prior Declaration

For each agent aᵢ and concept c before any peer grounding exchange in episode ε:

```
aᵢ →_ε coordinator :
  kind=exchange, subprotocol=CIP
  context.epistemic.state=taskwork
  context.epistemic.message_act=assertion
  context.topic = c
  context.epistemic.uncertainty = 1 − π(aᵢ,c,ε)
  payload[type=cip].belief.prior          = π(aᵢ,c,ε)
  payload[type=cip].belief.posterior      = π(aᵢ,c,ε)   -- prior = posterior at declaration
  payload[type=cip].belief.revision_cause = semantic_memory
  payload[type=cip].utterance.addresses_evidence = []
```

**Invariant T1:** `prior_declaration(aᵢ,c,ε)` must precede (in causal order) the first CIP
grounding exchange on c in ε where aᵢ appears as sender or receiver.

**Invariant T2:** `payload[type=cip].belief.prior` is immutable in ε once declared.

---

### CIP Grounding Exchange — Normal

For agents A, B and concept c in episode ε:

```
Step 1 — A asserts:
  A →_ε B : M_A
    kind=exchange, subprotocol=CIP
    context.epistemic.state=grounding
    context.epistemic.message_act=assertion
    context.topic = c
    payload[type=cip].utterance.evidence          = E_A   -- E_A ⊆ concept URIs
    payload[type=cip].utterance.addresses_evidence = E_B   -- ∅ on first turn; prior B→A evidence

Step 2 — B computes contingency and responds:
  contingency_score = |E_A ∩ evidence(prior_turn)| / |evidence(prior_turn)|

  if contingency_score ≥ θ_c:
    B →_ε A : M_B
      kind=exchange, subprotocol=CIP
      context.epistemic.state=grounding
      payload[type=cip].grounding.contingency_verified = true
      payload[type=cip].grounding.contingency_score    = contingency_score
      payload[type=cip].utterance.addresses_evidence   = E_A   -- B engages A's evidence
      payload[type=cip].belief.posterior               = ρ(B,c,ε)
      payload[type=cip].belief.revision_cause          ∈ { grounded_argument, social_compliance, … }
      message.parents = [M_A.message.id]

  if contingency_score < θ_c:  → see Repair Cycle below
```

**Invariant G1:** If M_B responds to M_A, then `M_B.message.parents ⊇ { M_A.message.id }`.

**Invariant G2:** If `M_B.payload[type=cip].grounding.contingency_verified = true`, then
`M_B.context.epistemic.belief_status ∈ { asserted, revised }`.

---

### CIP Repair Cycle

```
Step 1 — A sends turn with contingency_score(M_bad, prior_turn) < θ_c:
  A →_ε B : M_bad
    kind=exchange, subprotocol=CIP, context.epistemic.state=grounding

Step 2 — B detects failure and requests repair (LISTENER is sender):
  B →_ε A : M_req
    kind=contingency, subprotocol=CIP
    context.epistemic.state=grounding
    context.epistemic.belief_status=challenged
    message.parents = [M_bad.message.id]
    payload[type=utterance].content = "repair_required:reason=<r>:target=<M_bad.message.id>"

Step 3 — A re-attempts:
  A →_ε B : M_rep
    kind=exchange, subprotocol=CIP, context.epistemic.state=grounding
    message.parents = [M_req.message.id]
    payload[type=cip].utterance.addresses_evidence ∩ M_bad.payload[type=cip].utterance.evidence ≠ ∅

Step 4 — B verifies and closes (LISTENER closes what it opened):
  B →_ε A : M_close
    kind=commit, subkind=resolved, subprotocol=CIP
    context.epistemic.state=grounding
    message.parents = [M_rep.message.id]
```

Causal chain: `M_bad ← M_req ← M_rep ← M_close`

**Invariant R1:** `sender(M_req) = receiver(M_bad)` — the listener detects and reports, not the speaker.

**Invariant R2:** `sender(M_close) = sender(M_req)` — the listener who opened the repair branch closes it.

**Invariant R3:** Repair depth is bounded. If repair fails after `repair_depth_max` cycles,
the exchange terminates with `context.epistemic.belief_status=unresolved`.

---

### SIEP Panel Negotiation

Panel episode `ε_p` — child episode, typically `ε:panel:<uuid>`. Controller c,
specialists [s₁…sₙ], concept x, accept threshold θ_a.

**Open**
```
c →_εₚ [s₁…sₙ] :
  kind=intent, subprotocol=SIEP, context.epistemic.state=team_process
  participants.actors = [sender=c] + [recipient=sᵢ ∀i]
  context.topic = x
```

**Propose–Respond (star topology)**

For each sᵢ:
```
c →_εₚ sᵢ : M_prop_i
  kind=exchange, subprotocol=SIEP
  context.epistemic.state=taskwork (round 0) | team_process (round ≥ 1)
  context.epistemic.message_act=assertion
  payload[type=siep].operation=propose
  payload[type=siep].proposal_payload.posterior           = ρ(c,x,ε)
  payload[type=siep].proposal_payload.supporting_evidence = E_c

sᵢ →_εₚ c : M_resp_i
  kind=exchange, subprotocol=SIEP
  message.parents = [M_prop_i.message.id]

  CASE genuine accept  ( |ρ(sᵢ,x,ε) − ρ(c,x,ε)| ≤ θ_a ):
    payload[type=siep].operation=accept
    payload[type=siep].proposal_payload.deferred_to = ⊥
    context.epistemic.message_act=assertion                      ← GAR+1

  CASE deliberation pass  ( ρ(c,x,ε) dominates, sᵢ yields ):
    payload[type=siep].operation=accept
    payload[type=siep].proposal_payload.deferred_to = c          ← SCR+1
    context.epistemic.message_act=compliance

  CASE counter-proposal  ( |ρ(sᵢ,x,ε) − ρ(c,x,ε)| > θ_a ):
    payload[type=siep].operation=counter_proposal
    payload[type=siep].proposal_payload.addresses_evidence ⊆ E_c  ← CIP contingency input
    context.epistemic.message_act=challenge
```

**Convergence**
```
c →_εₚ [s₁…sₙ] :
  kind=commit, subkind=converged, subprotocol=SIEP
  context.epistemic.state=team_process
  participants.actors = [sender=c] + [recipient=sᵢ ∀i]
  payload[type=snp-convergence].mpc = MPC(x,εₚ)
  payload[type=snp-convergence].gar = GAR(x,εₚ)
  payload[type=snp-convergence].scr = SCR_team(x,εₚ)
  payload[type=snp-convergence].participant_ids = [sᵢ ∀i]
```

**Knowledge output**
```
c →_εₚ [s₁…sₙ] + team-epistemic-memory :
  kind=knowledge, subprotocol=SIEP
  context.epistemic.state=taskwork
  context.topic = urn:concept:<use_case>:<winning_position>
  payload[type=utterance].content =
    "rule_update:<position>:posterior=<MPC>:gar=<GAR>:scr=<SCR>:provenance_weight=<W>"
  payload[type=knowledge].content = {
    posterior, gar, scr, provenance_weight: W(x,εₚ), revision_cause: "converged_episode"
  }
  message.parents = [commit:converged.message.id]
```

**Invariant P1:** A `counter_proposal` must set
`addresses_evidence ⊆ supporting_evidence` of the prior `propose` — the counter-argument
must engage the original argument's evidence.

**Invariant P2:** `deferred_to ≠ ⊥ → message_act = compliance`.
`deferred_to = ⊥ → message_act ∈ { assertion, challenge }`.

**Invariant P3:** A `kind=knowledge` message is emitted iff `commit:converged` was reached.
Never emitted after `commit:rejected`.

---

### CIP + SIEP Composition

CIP and SIEP compose on the same message. A SIEP counter-proposal may carry both
`payload[type=siep]` and `payload[type=cip]`:

- `payload[type=siep].proposal_payload.addresses_evidence` feeds the CIP contingency check
- `payload[type=cip].grounding.contingency_verified` is the result of that check
- A counter-proposal that fails CIP contingency (contingency_score < θ_c) is flagged
  but not blocked — CIP produces the grounding signal; SIEP decides whether to accept
  or re-propose

---

## Well-Formedness Conditions

| # | Condition |
|---|---|
| W1 | Every `kind=contingency` message has a descendant `kind=commit, subkind=resolved` whose `message.parents ⊇ { M_rep.message.id }` — every opened repair branch is closed before the outer episode commits. |
| W2 | `M.message.parents ⊆ { id : M' ∈ ε ∧ M'.message.id ∈ M.message.parents }` — all parent IDs exist within the same episode. |
| W3 | The parent graph is acyclic — no message is its own ancestor. |
| W4 | For all (a,c,ε): `prior_declaration(a,c,ε)` precedes (causal order) the first `kind=exchange, subprotocol=CIP, context.epistemic.state=grounding` for (a,c,ε). |
| W5 | Every episode ε has exactly one `kind=intent` root and at most one `kind=commit` leaf. |
| W6 | `kind=knowledge` messages have `message.parents` containing exactly one `kind=commit, subkind=converged` message ID. |
| W7 | Exactly one actor in `participants.actors` has `participant_type="sender"` per message. |
| W8 | `subkind=resolved` is used only on `kind=commit` messages that close a `kind=contingency` branch. `subkind=converged` and `subkind=rejected` are used only on `kind=commit` messages that close a full episode or SIEP panel. |

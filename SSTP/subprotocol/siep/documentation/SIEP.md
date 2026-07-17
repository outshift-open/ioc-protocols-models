# Semantic Information Exchange Protocol (SIEP)

SIEP is the sub-protocol of SSTP that turns a collection of independent agent beliefs into a single team decision. It is the SSTP rename of what was previously called the Semantic Negotiation Protocol (SNP).

SIEP cannot produce trustworthy convergence on its own. It relies on CIP asserting common grounding between agents turn by turn. Without CIP, SIEP could converge on a position that was never actually argued for — just the loudest or most persistent agent winning.

## Purpose

Without a structured convergence protocol, a team of agents would either vote (majority wins regardless of reasoning quality) or defer to a single authority (one agent decides, others follow). Both are problematic — voting ignores the strength of the evidence behind each position, and pure authority ignores expertise the other agents hold.

SIEP gives every agent a voice proportional to the confidence of its reasoning. It forces counter-proposals to engage the prior agent's evidence (via CIP), so the convergence is built on argument rather than assertion. It records how convergence happened — whether agents were genuinely persuaded or merely complied — so the quality of the outcome is measurable and can be trusted proportionally in future episodes.

## Convergence quality metrics

Three metrics capture the quality of a SIEP convergence outcome.

### SCR — Social Compliance Ratio

SCR measures, per agent, what fraction of its belief revisions happened because of social pressure rather than genuine persuasion. An agent revises under social compliance when it changes its stated position without engaging the other agent's evidence. A high SCR means agreement is unreliable — the agent said yes but was not convinced.

```
SCR(a,c,ε) = |{ revisions where revision_cause = social_compliance }| / |{ total revisions }|
```

### GAR — Genuine Agreement Ratio

GAR measures what fraction of the team's agents ended up on the winning side for the right reason — their posterior moved in the same direction as the consensus, consistent with their initial prior trajectory. A high GAR means the team genuinely converged. A low GAR means most agents were dragged to the outcome rather than reasoned into it.

```
GAR = |{ aᵢ : (ρ(aᵢ,c,ε) − π(aᵢ,c,ε)) × (MPC − 0.5) ≥ 0 }| / |[A]|
```

### MPC — Multi-Party Consensus

MPC is the mean confidence of the team at the point of convergence. It answers: how strongly does the team collectively believe in the position it agreed on? MPC is about belief strength, not about how convergence happened (that is GAR and SCR).

```
MPC = mean({ ρ(aᵢ,c,ε) : aᵢ ∈ [A] })
```

### Provenance weight

The provenance weight of a converged rule records the combined quality of its GAR and SCR:

```
W = (1 − SCR_team) × GAR
```

A team decision backed by high GAR and low SCR is written to TeamEpistemicMemory with high provenance weight and will be trusted strongly in future episodes. Low GAR or high SCR produces a low provenance weight and the rule will be challenged again sooner.

## SIEP payload fields

The SIEP payload is carried as `payload[type=snp]` on any L9 message.

| Field | Values | Description |
|---|---|---|
| `profile` | `"semantic_negotiation"` | Always `"semantic_negotiation"`. |
| `operation` | `"propose" \| "counter_proposal" \| "accept" \| "reject" \| "negotiate" \| "consider_proposal" \| "evaluate_proposal" \| "review_proposal"` | The SIEP operation for this turn. |
| `proposal_id` | URN or UUID | Links all turns in this proposal thread. |
| `content` | string | The position label being proposed on the concept axis. |
| `status` | `"pending" \| "reviewed" \| "incorporated" \| "resolved"` | Lifecycle state of this proposal. |
| `negotiation_id` | URN or UUID or null | Negotiation session this turn belongs to. |
| `proposal_payload.posterior` | `float [0,1]` | Bayesian confidence in this position. |
| `proposal_payload.supporting_evidence` | `list[URI]` | Concepts supporting this position. |
| `proposal_payload.against_evidence` | `list[URI]` | Concepts arguing against this position. |
| `proposal_payload.addresses_evidence` | `list[URI]` | Concepts from the prior propose being engaged — CIP contingency input. |
| `proposal_payload.reasoning_summary` | string | LLM-generated explanation of the Bayesian chain. |
| `proposal_payload.deferred_to` | agent ID or null | Identity of the actor being deferred to. `null` = genuine accept. Non-null = social compliance; SCR increments. |

## Operation values

| Value | Used for | Relevant when |
|---|---|---|
| `propose` | Controller opens the negotiation with its leading position. | First turn in any panel negotiation round. |
| `counter_proposal` | Specialist disagrees and proposes an alternative with evidence. | Specialist's posterior is too far from controller's to accept. |
| `accept` | Participant or controller agrees with the proposed position. | Posterior gap within `accept_threshold`, or deliberation pass. |
| `reject` | Agent rejects a proposal outright. | Position is fundamentally incompatible. Rare — typically triggers a new round. |
| `negotiate` | Ring topology: each member proposes to the next. | Insurance-style ring panels. |
| `consider_proposal / evaluate_proposal / review_proposal` | Intermediate review steps. | Multi-round review workflows. |

## `deferred_to` semantics

| Value | Meaning |
|---|---|
| `"diagnostics-controller"` | Specialist is yielding. Marks this accept as social compliance. SCR increments. |
| `null` | Genuine accept — no deference. GAR counts this. |

**Invariant P2:** `deferred_to ≠ null → message_act = compliance`. `deferred_to = null → message_act ∈ { assertion, challenge }`.

## Posterior examples

| Value | When |
|---|---|
| `0.9935` | Near-unanimous — all specialists converge. |
| `0.7443` | Moderate-high — one specialist had lower confidence. |
| `0.8528` | Moderate — ambiguous presentation, split between positions. |

## SIEP payload schema (formal)

```
SIEPPayload := {
  profile:     "semantic_negotiation"
  operation:   ∈ { propose, counter_proposal, accept, reject, negotiate, … }
  proposal_id: UUID
  content:     String          -- position label on the concept axis
  status:      ∈ { pending, reviewed, incorporated, resolved }
  proposal_payload := {
    posterior:            [0,1]
    supporting_evidence:  [URI]
    against_evidence:     [URI]
    addresses_evidence:   [URI]   -- CIP contingency input for counter-proposals
    reasoning_summary:    String
    deferred_to:          AgentID ∪ { ⊥ }
  }
}
```

## Protocol flows

### Panel episode open

Panel episode `ε_p ⊂ ε` (child of outer session). Controller `c`, specialists `[s₁…sₙ]`, concept `x`.

```
c →_εₚ bus :
  kind=intent, subprotocol=SIEP, epistemic.state=team_process
```

### Propose–Respond (star topology)

```
For each sᵢ:

c →_εₚ sᵢ : M_prop_i
  kind=exchange, subprotocol=SIEP
  epistemic.state=taskwork (round 0) | team_process (later rounds)
  epistemic.message_act=assertion
  payload[siep].operation=propose
  payload[siep].proposal_payload.posterior = ρ(c,x,ε)
  payload[siep].proposal_payload.supporting_evidence = E_c

sᵢ →_εₚ c : M_resp_i
  kind=exchange, subprotocol=SIEP
  message.parents = [M_prop_i.message.id]

  CASE genuine accept (|ρ(sᵢ,x,ε) − ρ(c,x,ε)| ≤ θ_accept):
    payload[siep].operation=accept
    payload[siep].proposal_payload.deferred_to = ⊥
    epistemic.message_act=assertion           ← GAR+1

  CASE deliberation pass (ρ(c,x,ε) dominates):
    payload[siep].operation=accept
    payload[siep].proposal_payload.deferred_to = c
    epistemic.message_act=compliance          ← SCR+1

  CASE counter-proposal (|ρ(sᵢ,x,ε) − ρ(c,x,ε)| > θ_accept):
    payload[siep].operation=counter_proposal
    payload[siep].proposal_payload.addresses_evidence ⊆ E_c   ← CIP contingency input
    epistemic.message_act=challenge
```

**Invariant P1:** `counter_proposal` must set `addresses_evidence ⊆ supporting_evidence` of the prior propose — the counter-argument must engage the original argument.

### Convergence commit

```
c →_εₚ bus :
  kind=commit, subkind=converged, subprotocol=SIEP
  epistemic.state=team_process
  consensus_posterior = MPC
  genuine_agreement_ratio = GAR
  social_compliance_ratio = SCR_team
```

### Knowledge output (after converged commit)

```
c →_εₚ bus :
  kind=knowledge, subprotocol=SIEP, epistemic.state=taskwork
  topic = urn:concept:<use_case>:<position>
  payload[utterance] = "rule_update:<position>:posterior=<MPC>:gar=<GAR>:scr=<SCR>:provenance_weight=<W>"
  message.parents = [commit:converged.message.id]
```

**Invariant P3:** The knowledge message is emitted if and only if `commit:converged` was reached.

## Theory of Mind integration

ToM runs alongside SIEP negotiation. Before a participant sends a proposal, ToM predicts how the peer agent is likely to respond given its known belief patterns and prior episode history. After each response, ToM updates its model of the peer agent. Over episodes, ToM makes SIEP progressively more efficient — the controller stops wasting rounds on specialists it can predict will defer.

ToM derives SCR and GAR signals from the CIP trace: if an agent's posterior is moving but its supporting evidence is empty or weak, ToM flags social compliance. These predictions and observations are stored per-agent per-concept in the AgentBeliefStore and PeerInteractionStore.

## TeamEpistemicMemory integration

After `commit:converged`, the episode initiator emits one `knowledge` message per converged concept, routed to the `team-epistemic-memory` agent. The provenance weight `W = (1 − SCR) × GAR` is written alongside the posterior so future episodes can blend the team prior accordingly.

Before opening a new episode, the initiator performs a lookup episode to retrieve the team prior for the concept being discussed. If no prior entry exists, the concept starts at `prior=0.5` (maximum uncertainty).

**Prior blend formula at episode open:**

```python
w_team  = team.episode_count * team.provenance_weight   if team  else 0.0
w_agent = agent.episode_count * agent.specialty_match   if agent else 0.0
total   = w_team + w_agent
prior   = (w_agent * agent.confidence + w_team * team.confidence) / total if total > 0 else 0.5
```

## Well-formedness conditions

| Condition |
|---|
| `counter_proposal.addresses_evidence ⊆ prior_propose.supporting_evidence` — counter-argument must engage original argument. |
| `deferred_to ≠ null → message_act = compliance`. |
| Knowledge message emitted iff `commit:converged` reached. |
| All `contingency` messages opened during a SIEP episode have a corresponding `commit:resolved` descendant. |

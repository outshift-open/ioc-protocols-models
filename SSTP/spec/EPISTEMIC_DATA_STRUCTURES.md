# Epistemic Data Structures

**Version:** 1.0
**Status:** Normative
**Copyright 2026 Cisco Systems, Inc. and its affiliates**
**SPDX-License-Identifier: Apache-2.0**

---

## 1. Purpose and Scope

This document defines the data structures that carry epistemic state across the L9 protocol stack. Epistemic state is the structured representation of what agents believe, how confidently they believe it, how those beliefs were formed, and how well each agent understands its peers' belief-formation process.

These structures serve three functions:

1. **Grounding audit trail** — every belief change is traceable to a specific speech act and episode
2. **Bayesian inference substrate** — prior, likelihood contributions, and posterior are explicit fields, not derived post-hoc
3. **Theory of Mind (ToM) input** — per-agent-pair interaction history feeds both 1st-order and 2nd-order ToM

### Scope

- All stores are **cross-episode** — they persist beyond individual episodic transactions
- All structures are **application-agnostic** — `concept_id` and `argument_type` are domain-specific strings; the epistemic structure is universal
- `payload` in episode messages is **opaque** to the epistemic layer — only application-layer agents read it
- Revision history is **append-only** — never pruned; full causal trace of every belief change

### Non-Goals

- Episodic transaction scoping (governed by `episode_id` in the SSTP header)
- Transport framing or message routing
- Domain-specific payload schema

---

## 2. Notation

```text
String, Bool, Int, Float, JsonValue
TimestampMs := Int where TimestampMs >= 0
UriString   := String   -- concept namespace: "urn:concept:{domain}:{name}"
UuidString  := String
Option[T]   := T | null
Seq[T]      := ordered finite sequence of T
Map[K, V]   := finite mapping from K to V
```

---

## 3. Vocabulary

### 3.1 Speech Acts

```text
SpeechAct :=
    belief_assertion       -- asserting a position with supporting reasoning
  | alignment_challenge    -- challenging another agent's position with counter-evidence
  | help_request           -- requesting clarification or information
  | task_handoff           -- delegating work to another agent
  | deliberation_pass      -- expressing a position without grounded argument (social compliance signal)
```

### 3.2 Task Phases

```text
TaskPhase :=
    taskwork       -- individual prior formation; no peer contact
  | transition     -- committing independent priors to the shared space
  | action         -- IE-grounded exchanges; positions update for traceable reasons
  | interpersonal  -- surfaced when grounding fails or conflict persists; epistemically weakest
```

### 3.3 Belief Revision Causes

```text
RevisionCause :=
    grounded_argument   -- position changed due to a contingency-verified peer argument
  | social_compliance   -- position changed under social pressure without grounded argument
  | new_evidence        -- new external evidence; not from a peer argument
  | semantic_memory     -- prior injected from cross-episode memory at episode open
  | repair_resolution   -- position updated after a grounding repair cycle completed
```

### 3.4 Belief Status

```text
BeliefStatus := held | asserted | committed | retracted
```

---

## 4. EpistemicBlock

The `EpistemicBlock` is stamped on every L9 message header. It annotates the epistemic intent of the utterance.

```text
EpistemicBlock := {
  speech_act:          SpeechAct,
  task_phase:          TaskPhase,
}
```

The IE layer detects `speech_act = deliberation_pass` and records `BeliefRevision.cause = social_compliance` in `AgentBeliefStore` — no self-declared wire field is required. This revision updates the rolling `social_compliance_ratio` for the concept but does NOT update the posterior.

---

## 5. BeliefRevision

One atomic change to an agent's belief in a concept. Append-only; never deleted.

```text
BeliefRevision := {
  revision_id:            UuidString,
  timestamp_ms:           TimestampMs,
  episode_id:             String,           -- episode_id of episode that triggered this revision
  message_id:             Option[UuidString], -- L9 message_id that caused revision; null for semantic_memory injections
  confidence_before:      Float,            -- [0.0, 1.0]
  confidence_after:       Float,            -- [0.0, 1.0]
  cause:                  RevisionCause,
  caused_by_agent:        Option[String],   -- peer agent whose utterance triggered revision; null for self-initiated
  argument_concept_ids:   Seq[UriString],   -- concepts in the argument; promoted to PeerInteractionStore at episode close
  argument_summary:       Option[String],   -- natural-language capture for human audit only
}
```

---

## 6. BeliefState

An agent's current and historical belief in a single concept, with explicit Bayesian decomposition.

```text
BeliefState := {
  agent_id:                 String,
  concept_id:               UriString,

  -- Bayesian decomposition (explicit; not derived post-hoc)
  prior:                    Float,                   -- from SemanticMemory at episode open; default 0.5 (uniform)
  prior_weight:             Float,                   -- provenance quality: 1.0 - SCR_of_prior_producing_episode
  likelihoods:              Seq[(UriString, Float)], -- (argument_concept_id, Δ) per grounded argument received
  posterior:                Float,                   -- current private confidence = f(prior, likelihoods)

  -- Observation layer (what peers see)
  public_confidence:        Float,   -- last asserted value; peers observe this, not posterior
  status:                   BeliefStatus,
  use_case:                 String,  -- domain scope; prevents cross-domain belief merges

  -- History
  first_formed_episode:     String,
  last_revised_episode:     String,
  revision_history:         Seq[BeliefRevision],   -- append-only

  -- Rolling quality metrics
  social_compliance_ratio:  Float,  -- fraction of revisions with cause = social_compliance
  revision_count:           Int,
  confidence_variance:      Float,  -- variance of confidence_after across revisions; high = frequently contested
}
```

### 6.1 Posterior Rule

The posterior is a function of the prior and all grounded-argument likelihoods received within the current episode:

```text
posterior ≈ prior + Σ(Δ_i for each grounded_argument likelihood_i)
```

Likelihoods from `social_compliance` revisions are excluded from this sum — they contribute to `social_compliance_ratio` but not to the posterior calculation. The prior_weight discounts the starting prior when it was derived from a high-SCR episode.

### 6.2 Private vs Public

`posterior` is the agent's private belief. `public_confidence` is what the agent has asserted in an L9 message. They may diverge: an agent may hold a private position while publicly asserting a different one under social pressure. The gap between them is an epistemic red flag.

---

## 7. CommonGround

The output of a successful IE pairwise grounding exchange. Created when agent B's response to agent A's assertion is verified contingent on A's specific reasoning.

```text
CommonGround := {
  holder_id:               String,        -- A: who asserted
  confirmer_id:            String,        -- B: who grounded
  concept_id:              UriString,
  use_case:                String,
  episode_id:              String,        -- episode_id of containing episode
  grounding_confidence:    Float,         -- A's confidence that B correctly integrated the belief
  holder_confidence:       Float,         -- A's public_confidence at grounding time
  confirmer_confidence:    Float,         -- B's public_confidence after grounding
  contingency_verified:    Bool,          -- True iff B's response engaged A's specific reasoning
  speech_acts:             Seq[String],   -- ordered sequence of speech acts that established this ground
  grounding_message_ids:   Seq[UuidString], -- the turn pair(s) that verified it
  formed_at_ms:            TimestampMs,
}
```

`CommonGround` is created at `repair_applied` (grounding repair resolved) or when a `peer_turn` exchange is verified contingent without requiring repair. A `CommonGround` with `contingency_verified = false` MUST NOT be created — the exchange that failed to ground produces a `repair_required` event instead.

---

## 8. TeamGroundedTruth

The output of a completed SNP multi-party convergence round. This is what gets written to SemanticMemory as a new rule, with SCR and GAR as its provenance weights.

```text
TeamGroundedTruth := {
  concept_id:               UriString,
  use_case:                 String,
  episode_id:               String,           -- episode_id of episode in which convergence occurred
  participant_ids:          Seq[String],

  -- Bayesian provenance
  individual_priors:        Map[String, Float],    -- agent_id → prior at episode open
  individual_posteriors:    Map[String, Float],    -- agent_id → posterior at convergence
  consensus_posterior:      Float,                 -- MPC: mean position confidence at commit
  genuine_agreement_ratio:  Float,                 -- GAR: fraction of agents whose posterior is consistent with their taskwork prior
  social_compliance_ratio:  Float,                 -- SCR: fraction of revisions across all agents with cause = social_compliance

  -- Grounding provenance
  common_ground_ids:        Seq[String],           -- CommonGround episode_ids that fed this convergence

  -- Outcome
  outcome:                  accept | reject | deferred,
  formed_at_ms:             TimestampMs,
}
```

### 8.1 Provenance Weight Rule

When a `TeamGroundedTruth` is written to SemanticMemory, its `prior_weight` for future episodes is:

```text
prior_weight = (1.0 - social_compliance_ratio) × genuine_agreement_ratio
```

A consensus produced by genuine argument (low SCR, high GAR) has weight approaching 1.0. A consensus produced by social pressure (high SCR, low GAR) has weight approaching 0.0 and should be weighted accordingly when it primes future individual priors.

---

## 9. ArgumentOutcome

Records the result of one argument A made to B, from A's perspective. Promoted from the episodic transcript to `PeerInteractionStore` at episode close.

```text
ArgumentOutcome := {
  episode_id:                String,
  message_id:                UuidString,
  task_phase:                TaskPhase,           -- INTERPERSONAL moves are epistemically weaker
  argument_concept_id:       UriString,
  argument_type:             String,              -- rhetorical/evidential classifier: "onset_timing", "causal_mechanism", etc.
  subject_confidence_before: Float,               -- B's public_confidence before A's argument
  subject_confidence_after:  Float,               -- B's public_confidence after responding
  contingent:                Bool,                -- True iff B's response engaged A's specific reasoning
  moved:                     Bool,                -- True iff confidence delta exceeded noise threshold
  move_cause:                RevisionCause,       -- grounded_argument | social_compliance | no_move
}
```

---

## 10. PredictionRecord

A's prediction of B's response, recorded **before** B speaks. The self-improving component of 2nd-order ToM.

```text
PredictionRecord := {
  episode_id:           String,
  concept_id:           UriString,
  predicted_confidence: Float,   -- A's prediction before B spoke (genuine pre-utterance prediction)
  actual_confidence:    Float,   -- B's actual public_confidence when message arrived
  prediction_error:     Float,   -- |predicted - actual|
  prediction_basis:     argument_history | prior_distribution | 2nd_order_tom,
}
```

Predictions MUST be recorded before B's message is received. Post-hoc predictions do not constitute 2nd-order ToM.

---

## 11. PeerInteractionRecord

A's cross-episode model of B. Directional: A's model of B ≠ B's model of A. Promoted at episode close, never written turn-by-turn.

```text
PeerInteractionRecord := {
  observer_id:                    String,           -- agent A: whose model this is
  subject_id:                     String,           -- agent B: being modelled
  use_case:                       String,

  -- Argument history (1st-order ToM substrate)
  argument_outcomes:              Seq[ArgumentOutcome],   -- append-only

  -- Prediction history (2nd-order ToM loop)
  prediction_history:             Seq[PredictionRecord],  -- append-only
  predictive_accuracy:            Float,            -- rolling mean(1 - prediction_error); 0.5 = random, approaches 1.0

  -- Social skill map (2nd-order ToM output: how to communicate with B)
  argument_types_that_move:       Seq[String],      -- argument_type values where moved=True and contingent=True
  argument_types_ignored:         Seq[String],      -- argument_type values where contingent=False or moved=False
  evidence_weights:               Map[UriString, Float],  -- per concept_id: estimated weight B places on it

  -- Calibration signal
  confidence_accuracy_correlation: Float,           -- B's stated confidence vs historical accuracy (requires outcome feedback)

  -- Staleness
  episode_count:                  Int,              -- episodes contributing; low = thin model, discount predictions
  last_episode:                   String,           -- episode_id of most recent contributing episode
}
```

### 11.1 Using PeerInteractionRecord for Social Skill Adaptation

Before sending an argument to B, A SHOULD:

1. Check `argument_types_ignored` — if A's planned argument type is on this list, reformulate or probe first
2. Check `evidence_weights` for the target concept — weight A's framing toward concepts B values highly
3. Record a `PredictionRecord` with the expected B posterior before sending
4. After receiving B's response: record the `ArgumentOutcome`, update `prediction_history`, revise `predictive_accuracy`

The `argument_types_that_move` list is the actionable output: it tells A which rhetorical patterns have grounded with B historically and are worth leading with. This is communication strategy, not manipulation — A is adapting its frame to make genuine evidence legible to B.

---

## 12. The Bayesian Chain

The full belief formation loop, with explicit Bayesian scores at every step:

```text
SemanticMemory (rule with prior_weight = (1 - SCR) × GAR)
  ↓ prior injection at episode open
BeliefState.prior (weighted by prior_weight)
  ↓ IE-grounded peer_turn exchanges
BeliefRevision (cause = grounded_argument) → BeliefState.likelihoods
  ↓ contingency verification per pair
CommonGround (contingency_verified = True)
  ↓ SNP multi-party convergence
TeamGroundedTruth (consensus_posterior, GAR, SCR)
  ↓ written to SemanticMemory
SemanticMemory (new rule, prior_weight = (1 - SCR) × GAR)
```

The system produces genuine knowledge only when SCR is low and GAR is high at every step. A `TeamGroundedTruth` with high SCR MUST be stored with a low `prior_weight` so it does not strongly prime future individual priors.

---

## 13. Store Interfaces

### 13.1 AgentBeliefStore

Cross-episode. Keyed by `(agent_id, concept_id, use_case)`.

```text
current_belief(agent_id, concept_id, use_case) → Option[BeliefState]
all_beliefs(agent_id, use_case) → Seq[BeliefState]
record_revision(agent_id, concept_id, use_case, episode_id, revision, new_status, new_public_confidence) → BeliefState
set_prior(agent_id, concept_id, use_case, prior, prior_weight) → BeliefState
```

### 13.2 CommonGroundStore

Cross-episode, directional. Keyed by `(holder_id, confirmer_id, concept_id, use_case)`.

```text
record(ground: CommonGround) → void
get_for_pair(holder_id, confirmer_id, use_case) → Seq[CommonGround]
get_for_concept(concept_id, use_case) → Seq[CommonGround]
```

### 13.3 ConvergenceStore

Cross-episode. Keyed by `(concept_id, use_case, episode_id)`.

```text
record(truth: TeamGroundedTruth) → void
latest(concept_id, use_case) → Option[TeamGroundedTruth]
all_for_use_case(use_case) → Seq[TeamGroundedTruth]
```

### 13.4 PeerInteractionStore

Cross-episode, directional. Keyed by `(observer_id, subject_id, use_case)`.

```text
get_peer_record(observer_id, subject_id, use_case) → Option[PeerInteractionRecord]
record_argument_outcome(observer_id, subject_id, use_case, outcome: ArgumentOutcome) → void
record_prediction(observer_id, subject_id, use_case, pred: PredictionRecord) → void
promote_outcomes_for_pair(observer_id, subject_id, use_case, episode_id, outcomes, predictions) → void
```

---

## 14. Invariants

1. **Append-only invariant**: `revision_history`, `argument_outcomes`, and `prediction_history` are never pruned or reordered.

2. **Prior immutability invariant**: `BeliefState.prior` is set once at episode open via `set_prior`. Subsequent `record_revision` calls update `posterior` (via `likelihoods`) but never overwrite `prior`.

3. **Deliberation pass invariant**: A `peer_turn` with `speech_act = deliberation_pass` contributes `BeliefRevision.cause = social_compliance` — recorded by the IE layer, not self-declared on the wire. It MUST NOT produce a `CommonGround` record.

4. **CommonGround contingency invariant**: `CommonGround.contingency_verified` MUST be `True`. A failed grounding produces `repair_required`; only a resolved repair or a directly verified exchange produces `CommonGround`.

5. **Prediction pre-utterance invariant**: `PredictionRecord.predicted_confidence` MUST be recorded before B's actual response is known.

6. **Directional invariant**: `PeerInteractionRecord` for `(A, B)` is never used to update A's own `BeliefState` — it is A's model of B, not A's self-model.

7. **TeamGroundedTruth provenance invariant**: `prior_weight = (1.0 - SCR) × GAR`. Implementations MUST NOT assign `prior_weight = 1.0` to a `TeamGroundedTruth` with `SCR > 0` or `GAR < 1`.

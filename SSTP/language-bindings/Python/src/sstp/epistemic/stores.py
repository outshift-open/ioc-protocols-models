# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/epistemic/stores.py — Three cross-episode epistemic stores.

Layer 6 of the epistemic stack: persistent belief state for agents and
agent-pairs. These stores are cross-episode and persist across episodic transactions.

Three stores:
    AgentBeliefStore      — per-agent, per-concept beliefs with revision history
    PeerInteractionStore  — per-agent-pair, directional model built across episodes

The Episode Store (Layer 6 store 1) is the existing EpistemicStore / local_replica;
no structural change needed there.

All concept_ids and agent_ids are plain strings — domain-specific namespaces,
universal epistemic structure. The stores are application-agnostic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, List, Optional


# ── Belief State (AgentBeliefStore) ───────────────────────────────────────────


@dataclass
class BeliefRevision:
    """One atomic change to an agent's belief in a concept."""

    revision_id: str           # unique; enables point-in-time replay
    timestamp_ms: int          # when the revision occurred
    episode_id: str            # episode_id of the episode that triggered this revision
    message_id: Optional[str]  # EpisodeMessage that caused revision; None for semantic memory injections
    confidence_before: float   # confidence immediately before revision
    confidence_after: float    # confidence immediately after revision
    cause: str                 # grounded_argument | social_compliance | new_evidence |
                               #   semantic_memory | repair_resolution
    caused_by_agent: Optional[str]        # peer agent whose utterance triggered revision; None for self-initiated
    argument_concept_ids: List[str]       # concepts in the argument; fed to PeerInteractionStore at close
    argument_summary: Optional[str] = None  # natural-language capture for human audit only


@dataclass
class BeliefState:
    """An agent's current and historical belief in a single concept.

    Explicit Bayesian decomposition per EPISTEMIC_DATA_STRUCTURES.md §6:
    - prior          — from SemanticMemory at episode open (set once)
    - prior_weight   — provenance quality: 1.0 - SCR of prior-producing episode
    - likelihoods    — (argument_concept_id, Δ) per grounded argument received
    - posterior      — alias for current_confidence; private belief
    - public_confidence — last asserted; what peers observe (may differ from posterior)
    """

    agent_id: str                          # which agent holds this belief
    concept_id: str                        # concept believed; URI namespace throughout
    current_confidence: float              # private posterior — ground truth for 1st-order ToM
    public_confidence: float               # last asserted — what peers observe
    status: str                            # held | asserted | committed | retracted
    use_case: str                          # domain scope; prevents cross-domain belief merges
    first_formed_episode: str              # episode_id in which belief was first established
    last_revised_episode: str             # episode_id of most recent episode in which belief changed

    # Bayesian decomposition fields (set at episode open; updated by record_revision)
    prior: float = 0.5                     # from SemanticMemory at episode open; uniform default
    prior_weight: float = 1.0              # provenance weight (1.0 - SCR of prior-producing episode)
    prior_locked: bool = False             # True after set_prior() — prevents re-setting within same episode
    likelihoods: List[tuple] = field(default_factory=list)  # [(argument_concept_id, Δ), ...]

    revision_history: List[BeliefRevision] = field(default_factory=list)  # append-only
    social_compliance_ratio: float = 0.0  # rolling SCR: fraction of revisions with cause=social_compliance
    revision_count: int = 0               # total revisions
    confidence_variance: float = 0.0      # variance across revision_after values; high = frequently contested

    @property
    def posterior(self) -> float:
        """Private belief; alias for current_confidence."""
        return self.current_confidence


# ── Peer Interaction Store ─────────────────────────────────────────────────────


@dataclass
class ArgumentOutcome:
    """Result of one argument A made to B, from A's perspective."""

    episode_id: str                    # which episode this exchange occurred in
    message_id: str                    # EpisodeMessage containing the argument
    task_phase: str                    # INTERPERSONAL moves are epistemically weaker
    argument_concept_id: str           # primary concept the argument was about
    argument_type: str                 # rhetorical/evidential classifier: "onset_timing", etc.
    subject_confidence_before: float   # B's confidence before receiving A's argument
    subject_confidence_after: float    # B's confidence after responding
    contingent: bool                   # True if B's response engaged A's specific reasoning
    moved: bool                        # True if confidence delta exceeded noise threshold
    move_cause: str                    # grounded_argument | social_compliance | no_move


@dataclass
class PredictionRecord:
    """A's prediction of B's response — recorded before B speaks."""

    episode_id: str              # which episode this prediction was made for
    concept_id: str              # concept A was predicting B's belief about
    predicted_confidence: float  # A's prediction before B spoke (genuine, not post-hoc)
    actual_confidence: float     # B's actual asserted confidence when message arrived
    prediction_error: float      # |predicted - actual|; rolling mean of (1 - error) = predictive_accuracy
    prediction_basis: str        # argument_history | prior_distribution | 2nd_order_tom


@dataclass
class PeerInteractionRecord:
    """A's cross-episode model of B — A's model of B ≠ B's model of A."""

    observer_id: str               # agent A — whose model this is; directional
    subject_id: str                # agent B — being modelled
    use_case: str                  # domain scope
    argument_outcomes: List[ArgumentOutcome] = field(default_factory=list)    # append-only
    prediction_history: List[PredictionRecord] = field(default_factory=list)  # append-only
    predictive_accuracy: float = 0.5                # rolling mean(1 - error); 0.5 = random, approaches 1.0
    argument_types_that_move: List[str] = field(default_factory=list)  # where moved=True, contingent=True
    argument_types_ignored: List[str] = field(default_factory=list)    # where contingent=False or moved=False
    evidence_weights: Dict[str, float] = field(default_factory=dict)   # per concept_id: estimated weight B places on it
    confidence_accuracy_correlation: float = 0.0   # B's stated confidence vs historical accuracy (requires outcome feedback)
    episode_count: int = 0             # episodes contributing; low = thin model, discount predictions
    last_episode: str = ""             # episode_id of most recent contributing episode; staleness check


# ── CommonGround ─────────────────────────────────────────────────────────────


@dataclass
class CommonGround:
    """Output of a successful IE pairwise grounding exchange.

    Created when agent B's response to A's assertion is verified contingent
    on A's specific reasoning. contingency_verified MUST be True.
    See EPISTEMIC_DATA_STRUCTURES.md §7.
    """

    holder_id: str               # A — who asserted
    confirmer_id: str            # B — who grounded
    concept_id: str
    use_case: str
    episode_id: str              # episode_id of containing episode
    grounding_confidence: float  # A's confidence that B correctly integrated
    holder_confidence: float     # A's public_confidence at grounding time
    confirmer_confidence: float  # B's public_confidence after grounding
    contingency_verified: bool   # True iff B's response engaged A's specific reasoning
    speech_acts: List[str]       # ordered sequence of speech acts that established ground
    grounding_message_ids: List[str]  # the turn pair(s) that verified it
    formed_at_ms: int


# ── TeamGroundedTruth ─────────────────────────────────────────────────────────


@dataclass
class TeamGroundedTruth:
    """Output of a completed SNP multi-party convergence round.

    Written to SemanticMemory as a new rule. SCR and GAR are provenance weights:
    prior_weight = (1.0 - social_compliance_ratio) × genuine_agreement_ratio.
    See EPISTEMIC_DATA_STRUCTURES.md §8.
    """

    concept_id: str
    use_case: str
    episode_id: str
    participant_ids: List[str]
    individual_priors: Dict[str, float]      # agent_id → prior at episode open
    individual_posteriors: Dict[str, float]  # agent_id → posterior at convergence
    consensus_posterior: float               # MPC: mean position confidence at commit
    genuine_agreement_ratio: float           # GAR: fraction consistent with taskwork priors
    social_compliance_ratio: float           # SCR: fraction of revisions = social_compliance
    common_ground_ids: List[str]            # CommonGround episode_ids that fed this
    outcome: str                             # accept | reject | deferred
    formed_at_ms: int


# ── AgentBeliefStore ──────────────────────────────────────────────────────────


class AgentBeliefStore:
    """Cross-episode store of per-agent beliefs.

    Keyed by (agent_id, concept_id, use_case). Revision history is
    append-only; current_confidence and status are mutable.

    1st-order ToM: ``current_belief()`` is a direct lookup — no inference.
    """

    def __init__(self) -> None:
        # (agent_id, concept_id, use_case) → BeliefState
        self._store: Dict[tuple, BeliefState] = {}

    def _key(self, agent_id: str, concept_id: str, use_case: str) -> tuple:
        return (agent_id, concept_id, use_case)

    def current_belief(
        self, agent_id: str, concept_id: str, use_case: str = ""
    ) -> Optional[BeliefState]:
        """1st-order ToM: what does agent_id currently believe about concept_id?"""
        return self._store.get(self._key(agent_id, concept_id, use_case))

    def all_beliefs(self, agent_id: str, use_case: str = "") -> List[BeliefState]:
        """All current beliefs held by agent_id within use_case."""
        return [
            bs for (aid, _, uc), bs in self._store.items()
            if aid == agent_id and (not use_case or uc == use_case)
        ]

    def set_prior(
        self,
        agent_id: str,
        concept_id: str,
        use_case: str,
        prior: float,
        prior_weight: float,
    ) -> Optional["BeliefState"]:
        """Set the prior for an agent's belief at episode open (called once per episode).

        Does not create a new BeliefState if one doesn't exist — caller should
        call record_revision first or ensure the belief exists. Returns None if
        the belief does not exist yet.
        """
        key = self._key(agent_id, concept_id, use_case)
        if key not in self._store:
            return None
        belief = self._store[key]
        if belief.prior_locked:
            return belief  # idempotent — spec: prior set once per episode
        belief.prior = prior
        belief.prior_weight = prior_weight
        belief.prior_locked = True
        return belief

    def reset_episode(self, agent_id: str, concept_id: str, use_case: str) -> None:
        """Unlock prior at episode open so the new episode can set a fresh prior."""
        key = self._key(agent_id, concept_id, use_case)
        if key in self._store:
            self._store[key].prior_locked = False

    def record_revision(
        self,
        agent_id: str,
        concept_id: str,
        use_case: str,
        episode_id: str,
        revision: BeliefRevision,
        new_status: str = "asserted",
        new_public_confidence: Optional[float] = None,
    ) -> "BeliefState":
        """Apply a revision to an agent's belief, creating the belief if new."""
        key = self._key(agent_id, concept_id, use_case)
        if key not in self._store:
            self._store[key] = BeliefState(
                agent_id=agent_id,
                concept_id=concept_id,
                current_confidence=revision.confidence_before,
                public_confidence=revision.confidence_before,
                status="held",
                use_case=use_case,
                first_formed_episode=episode_id,
                last_revised_episode=episode_id,
            )
        belief = self._store[key]
        belief.revision_history.append(revision)

        # Update posterior (current_confidence).
        # grounded_argument revisions accumulate as likelihoods and recompute posterior
        # from prior + Σ(Δ_i) — social_compliance revisions are excluded from the sum.
        if revision.cause == "grounded_argument":
            delta = revision.confidence_after - revision.confidence_before
            for cid in (revision.argument_concept_ids or [concept_id]):
                belief.likelihoods.append((cid, round(delta, 6)))
            total_delta = sum(d for _, d in belief.likelihoods)
            # prior_weight discounts the prior toward 0.5 (uniform) when provenance is poor
            # (high SCR episode); weight=1.0 = full trust, weight=0.0 = retreat to 0.5
            effective_prior = round(0.5 + (belief.prior - 0.5) * belief.prior_weight, 6)
            belief.current_confidence = round(
                max(0.0, min(1.0, effective_prior + total_delta)), 4
            )
        else:
            belief.current_confidence = revision.confidence_after

        if new_public_confidence is not None:
            belief.public_confidence = new_public_confidence
        belief.status = new_status
        belief.last_revised_episode = episode_id
        belief.revision_count += 1

        # Update SCR
        compliance_count = sum(
            1 for r in belief.revision_history if r.cause == "social_compliance"
        )
        belief.social_compliance_ratio = compliance_count / belief.revision_count

        # Update confidence variance
        confidences = [r.confidence_after for r in belief.revision_history]
        if len(confidences) >= 2:
            m = mean(confidences)
            belief.confidence_variance = round(
                sum((c - m) ** 2 for c in confidences) / len(confidences), 6
            )
        return belief

    def _store_flat(self) -> List[Dict[str, Any]]:
        """Serialize all BeliefStates to plain dicts for persistence."""
        import dataclasses
        return [dataclasses.asdict(bs) for bs in self._store.values()]

    def _restore_flat(self, records: List[Dict[str, Any]]) -> None:
        """Restore BeliefStates from plain dicts produced by _store_flat()."""
        for r in records:
            try:
                r = dict(r)
                rev_list = [BeliefRevision(**rv) for rv in r.pop("revision_history", [])]
                r["likelihoods"] = [tuple(x) for x in r.get("likelihoods", [])]
                bs = BeliefState(**r)
                bs.revision_history = rev_list
                key = self._key(bs.agent_id, bs.concept_id, bs.use_case)
                self._store[key] = bs
            except (TypeError, KeyError):
                pass


# ── PeerInteractionStore ──────────────────────────────────────────────────────


class PeerInteractionStore:
    """Cross-episode, directional model of agent-pair interactions.

    Promoted from episodic transcript at episode close — never written turn-by-turn.
    A's model of B ≠ B's model of A.

    Keyed by (observer_id, subject_id, use_case).
    """

    def __init__(self) -> None:
        # (observer_id, subject_id, use_case) → PeerInteractionRecord
        self._store: Dict[tuple, PeerInteractionRecord] = {}

    def _key(self, observer_id: str, subject_id: str, use_case: str) -> tuple:
        return (observer_id, subject_id, use_case)

    def get_peer_record(
        self, observer_id: str, subject_id: str, use_case: str = ""
    ) -> Optional[PeerInteractionRecord]:
        return self._store.get(self._key(observer_id, subject_id, use_case))

    def _ensure(
        self, observer_id: str, subject_id: str, use_case: str
    ) -> PeerInteractionRecord:
        key = self._key(observer_id, subject_id, use_case)
        if key not in self._store:
            self._store[key] = PeerInteractionRecord(
                observer_id=observer_id,
                subject_id=subject_id,
                use_case=use_case,
            )
        return self._store[key]

    def record_argument_outcome(
        self,
        observer_id: str,
        subject_id: str,
        use_case: str,
        outcome: ArgumentOutcome,
    ) -> None:
        """Append an argument outcome to observer's model of subject."""
        record = self._ensure(observer_id, subject_id, use_case)
        record.argument_outcomes.append(outcome)

        # Update argument_types_that_move / argument_types_ignored
        if outcome.contingent and outcome.moved:
            if outcome.argument_type not in record.argument_types_that_move:
                record.argument_types_that_move.append(outcome.argument_type)
        elif not outcome.contingent or not outcome.moved:
            if outcome.argument_type not in record.argument_types_ignored:
                record.argument_types_ignored.append(outcome.argument_type)

    def record_prediction(
        self,
        observer_id: str,
        subject_id: str,
        use_case: str,
        pred: PredictionRecord,
    ) -> None:
        """Append a prediction record and update predictive_accuracy."""
        record = self._ensure(observer_id, subject_id, use_case)
        record.prediction_history.append(pred)
        errors = [p.prediction_error for p in record.prediction_history]
        record.predictive_accuracy = round(
            1.0 - (sum(errors) / len(errors)), 4
        )

    def promote_outcomes_for_pair(
        self,
        observer_id: str,
        subject_id: str,
        use_case: str,
        episode_id: str,
        argument_outcomes: List[ArgumentOutcome],
        prediction_records: List[PredictionRecord],
    ) -> None:
        """Promote outcomes for a specific (observer, subject) pair at episode close."""
        for outcome in argument_outcomes:
            self.record_argument_outcome(observer_id, subject_id, use_case, outcome)
        for pred in prediction_records:
            self.record_prediction(observer_id, subject_id, use_case, pred)

        record = self._ensure(observer_id, subject_id, use_case)
        if record.last_episode != episode_id:
            record.episode_count += 1
            record.last_episode = episode_id

        # Spec: B's stated confidence vs B's historical accuracy.
        # Uses subject's (B's) stated confidence before being argued to, correlated with
        # whether B held their position (not moved = correctly confident).
        _ao = record.argument_outcomes
        if len(_ao) >= 2:
            _xs = [o.subject_confidence_before for o in _ao]
            _ys = [0.0 if o.moved else 1.0 for o in _ao]
            _xm = sum(_xs) / len(_xs)
            _ym = sum(_ys) / len(_ys)
            _num = sum((x - _xm) * (y - _ym) for x, y in zip(_xs, _ys))
            _denom = (
                sum((x - _xm) ** 2 for x in _xs) * sum((y - _ym) ** 2 for y in _ys)
            ) ** 0.5
            record.confidence_accuracy_correlation = round(_num / _denom, 4) if _denom > 0 else 0.0

        # AF4: compute evidence_weights from outcomes where the listener actually moved
        # on a contingent argument. Tracks which concept IDs reliably move this peer.
        _ev: Dict[str, float] = {}
        for _out in argument_outcomes:
            if _out.moved and _out.contingent and _out.argument_concept_id:
                _ev[_out.argument_concept_id] = _ev.get(_out.argument_concept_id, 0.0) + 1.0
        if _ev:
            _total = sum(_ev.values())
            for _k, _v in _ev.items():
                record.evidence_weights[_k] = round(_v / _total, 4)

    def _store_flat(self) -> List[Dict[str, Any]]:
        """Serialize all PeerInteractionRecords to plain dicts for persistence."""
        import dataclasses
        return [dataclasses.asdict(rec) for rec in self._store.values()]

    def _restore_flat(self, records: List[Dict[str, Any]]) -> None:
        """Restore PeerInteractionRecords from plain dicts produced by _store_flat()."""
        for r in records:
            try:
                r = dict(r)
                ao_list = [ArgumentOutcome(**ao) for ao in r.pop("argument_outcomes", [])]
                pr_list = [PredictionRecord(**pr) for pr in r.pop("prediction_history", [])]
                rec = PeerInteractionRecord(**r)
                rec.argument_outcomes = ao_list
                rec.prediction_history = pr_list
                key = self._key(rec.observer_id, rec.subject_id, rec.use_case)
                self._store[key] = rec
            except (TypeError, KeyError):
                pass


# ── CommonGroundStore ──────────────────────────────────────────────────────────


class CommonGroundStore:
    """Cross-episode store of pairwise grounding records.

    Keyed by (holder_id, confirmer_id, concept_id, use_case).
    All entries have contingency_verified = True by invariant.
    """

    def __init__(self) -> None:
        self._store: Dict[tuple, List[CommonGround]] = {}

    def _key(self, holder_id: str, confirmer_id: str, concept_id: str, use_case: str) -> tuple:
        return (holder_id, confirmer_id, concept_id, use_case)

    def record(self, ground: CommonGround) -> None:
        """Append a CommonGround record. contingency_verified must be True."""
        if not ground.contingency_verified:
            raise ValueError(
                "CommonGround.contingency_verified must be True — "
                "failed groundings produce repair_required, not CommonGround"
            )
        key = self._key(ground.holder_id, ground.confirmer_id, ground.concept_id, ground.use_case)
        if key not in self._store:
            self._store[key] = []
        self._store[key].append(ground)

    def get_for_pair(
        self, holder_id: str, confirmer_id: str, use_case: str = ""
    ) -> List[CommonGround]:
        return [
            g for (h, c, _, uc), gs in self._store.items()
            for g in gs
            if h == holder_id and c == confirmer_id and (not use_case or uc == use_case)
        ]

    def get_for_concept(self, concept_id: str, use_case: str = "") -> List[CommonGround]:
        return [
            g for (_, _, cid, uc), gs in self._store.items()
            for g in gs
            if cid == concept_id and (not use_case or uc == use_case)
        ]

    def _store_flat(self) -> List[Dict[str, Any]]:
        """Serialize all records to a list of plain dicts for persistence."""
        import dataclasses
        result = []
        for gs in self._store.values():
            for g in gs:
                result.append(dataclasses.asdict(g))
        return result

    def _restore_flat(self, records: List[Dict[str, Any]]) -> None:
        """Restore records from a list of plain dicts produced by _store_flat()."""
        for r in records:
            try:
                ground = CommonGround(**r)
                key = self._key(ground.holder_id, ground.confirmer_id, ground.concept_id, ground.use_case)
                if key not in self._store:
                    self._store[key] = []
                self._store[key].append(ground)
            except (TypeError, KeyError):
                pass  # skip malformed records from older serialization formats


# ── ConvergenceStore ──────────────────────────────────────────────────────────


class ConvergenceStore:
    """Cross-episode store of SNP convergence results (TeamGroundedTruth).

    Keyed by (concept_id, use_case, episode_id).
    Written to SemanticMemory as new rules at episode close.
    """

    def __init__(self) -> None:
        self._store: Dict[tuple, TeamGroundedTruth] = {}

    def _key(self, concept_id: str, use_case: str, episode_id: str) -> tuple:
        return (concept_id, use_case, episode_id)

    def record(self, truth: TeamGroundedTruth) -> None:
        """Record a TeamGroundedTruth at episode close."""
        self._store[self._key(truth.concept_id, truth.use_case, truth.episode_id)] = truth

    def latest(self, concept_id: str, use_case: str = "") -> Optional[TeamGroundedTruth]:
        """Return the most recently formed TeamGroundedTruth for a concept."""
        candidates = [
            t for (cid, uc, _), t in self._store.items()
            if cid == concept_id and (not use_case or uc == use_case)
        ]
        return max(candidates, key=lambda t: t.formed_at_ms) if candidates else None

    def all_for_use_case(self, use_case: str) -> List[TeamGroundedTruth]:
        return [t for (_, uc, _), t in self._store.items() if uc == use_case]


# ── AgentEpistemicStore ───────────────────────────────────────────────────────


class AgentEpistemicStore:
    """Per-agent epistemic store owned by AgentTOM.

    Holds this agent's CommonGround records (observer-relative grounding confidence
    may differ between A and B — that difference is 2nd-order ToM signal) and the
    cross-episode peer belief models built from prediction logs.

    CommonGround records are keyed by confirmer_id (this agent is always the holder);
    peer models are keyed by peer_id.
    """

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._common_ground = CommonGroundStore()
        self._peer_models: Dict[str, Dict] = {}
        self._prediction_logs: Dict[str, List[Dict]] = {}

    def record_common_ground(self, ground: CommonGround) -> None:
        """Record a grounding outcome where this agent was involved."""
        self._common_ground.record(ground)

    def common_grounds_with(self, peer_id: str, use_case: str = "") -> List[CommonGround]:
        """Return all CommonGround records between this agent and peer_id."""
        return self._common_ground.get_for_pair(self.agent_id, peer_id, use_case)

    def save_peer_model(
        self,
        peer_id: str,
        belief: Dict,
        prediction_log_entry: Optional[Dict] = None,
    ) -> None:
        """Persist an updated peer belief model and optionally append a prediction log entry."""
        self._peer_models[peer_id] = dict(belief)
        if prediction_log_entry is not None:
            log = self._prediction_logs.setdefault(peer_id, [])
            log.append(prediction_log_entry)

    def load_peer_model(self, peer_id: str) -> Optional[Dict]:
        """Return the persisted peer belief dict, or None if no model yet."""
        m = self._peer_models.get(peer_id)
        return dict(m) if m is not None else None

    def load_prediction_log(self, peer_id: str) -> List[Dict]:
        """Return all recorded prediction log entries for peer_id."""
        return list(self._prediction_logs.get(peer_id, []))


# ── SemanticRuleStore ─────────────────────────────────────────────────────────


@dataclass
class SemanticRule:
    """A stabilised rule written from a TeamGroundedTruth convergence event.

    The payload is opaque to the store — application-defined content (e.g. a
    drug interaction dict, a risk threshold, a routing policy fragment).
    prior_for() reads confidence as the prior for the next episode.
    """

    concept_id: str             # URI identifying the rule/concept
    use_case: str
    confidence: float           # posterior confidence stabilised at convergence
    provenance_weight: float    # 1.0 - SCR of the episode that produced it
    source_episode_id: str      # TeamGroundedTruth episode that stabilised it
    payload: dict               # opaque; application-defined
    recorded_at_ms: int
    description: str = ""       # human-readable summary of what the team converged on


class SemanticRuleStore:
    """Append-only store of stabilised rules written from TeamGroundedTruth.

    Provides SemanticMemory-level read access: ``prior_for`` returns the
    confidence of the most recent rule, or 0.5 (uniform) if none is recorded.
    """

    def __init__(self) -> None:
        self._store: Dict[tuple, List[SemanticRule]] = {}

    def _key(self, concept_id: str, use_case: str) -> tuple:
        return (concept_id, use_case)

    def record(self, rule: SemanticRule) -> None:
        key = self._key(rule.concept_id, rule.use_case)
        if key not in self._store:
            self._store[key] = []
        self._store[key].append(rule)

    def latest(self, concept_id: str, use_case: str = "") -> Optional[SemanticRule]:
        candidates = self._store.get(self._key(concept_id, use_case), [])
        return candidates[-1] if candidates else None

    def all_for_use_case(self, use_case: str) -> List[SemanticRule]:
        return [
            rule
            for (_, uc), rules in self._store.items()
            if uc == use_case
            for rule in rules
        ]

    def prior_for(self, concept_id: str, use_case: str = "") -> float:
        """Returns confidence of latest rule, or 0.5 (uniform) if none recorded."""
        rule = self.latest(concept_id, use_case)
        return rule.confidence if rule is not None else 0.5

    def _store_flat(self) -> List[Dict[str, Any]]:
        """Serialize all SemanticRules to plain dicts for persistence."""
        import dataclasses
        return [dataclasses.asdict(rule) for rules in self._store.values() for rule in rules]

    def _restore_flat(self, records: List[Dict[str, Any]]) -> None:
        """Restore SemanticRules from plain dicts produced by _store_flat()."""
        for r in records:
            try:
                rule = SemanticRule(**r)
                key = self._key(rule.concept_id, rule.use_case)
                self._store.setdefault(key, []).append(rule)
            except (TypeError, KeyError):
                pass


# ── SNP Proposal and Negotiation stores ──────────────────────────────────────
# Spec SNP §2.6: ProposalStore, NegotiationStore, NegotiationIndex, RoundStore


@dataclass
class SemanticProposal:
    """A proposal emitted in a Star or Ring negotiation round."""
    proposal_id: str
    concept_id: str
    episode_id: str
    sender: str
    receiver: str
    payload: dict
    payload_hash: str
    timestamp_ms: int


class ProposalStore:
    """Spec §2.6: proposal_id → SemanticProposal. Supports payload integrity verification."""

    def __init__(self) -> None:
        self._store: Dict[str, SemanticProposal] = {}

    def record(self, proposal: SemanticProposal) -> None:
        self._store[proposal.proposal_id] = proposal

    def get(self, proposal_id: str) -> Optional[SemanticProposal]:
        return self._store.get(proposal_id)

    def verify_integrity(self, proposal_id: str) -> bool:
        import hashlib as _hl, json as _js
        p = self.get(proposal_id)
        if p is None:
            return False
        computed = _hl.sha256(
            _js.dumps(p.payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return computed == p.payload_hash


@dataclass
class NegotiationMessage:
    """Spec §2.3: a single message in a negotiation thread."""
    negotiation_id: str
    proposal_id: str
    sender: str
    receiver: str
    operation: str
    content: dict
    timestamp_sec: int
    status: str = "pending"  # pending | reviewed | resolved


@dataclass
class NegotiationRound:
    """Spec §2.4: a round of negotiation with per-participant Bayesian provenance."""
    round_id: str
    proposal_id: str
    participants: List[str]
    messages: List[NegotiationMessage] = field(default_factory=list)
    individual_positions: Dict[str, float] = field(default_factory=dict)
    status: str = "open"  # open | resolved | failed


class NegotiationStore:
    """Spec §2.6: proposal_id → ordered NegotiationMessage sequence."""

    def __init__(self) -> None:
        self._store: Dict[str, List[NegotiationMessage]] = {}

    def record(self, msg: NegotiationMessage) -> None:
        self._store.setdefault(msg.proposal_id, []).append(msg)

    def get(self, proposal_id: str) -> List[NegotiationMessage]:
        return self._store.get(proposal_id, [])


class NegotiationIndex:
    """Spec §2.6: negotiation_id → latest NegotiationMessage for fast lookup."""

    def __init__(self) -> None:
        self._index: Dict[str, NegotiationMessage] = {}

    def record(self, msg: NegotiationMessage) -> None:
        self._index[msg.negotiation_id] = msg

    def get(self, negotiation_id: str) -> Optional[NegotiationMessage]:
        return self._index.get(negotiation_id)


class RoundStore:
    """Spec §2.6: round_id → NegotiationRound with Bayesian provenance."""

    def __init__(self) -> None:
        self._store: Dict[str, NegotiationRound] = {}

    def record(self, rnd: NegotiationRound) -> None:
        self._store[rnd.round_id] = rnd

    def get(self, round_id: str) -> Optional[NegotiationRound]:
        return self._store.get(round_id)


__all__ = [
    "BeliefRevision",
    "BeliefState",
    "CommonGround",
    "TeamGroundedTruth",
    "SemanticRule",
    "SemanticRuleStore",
    "SemanticProposal",
    "ProposalStore",
    "NegotiationMessage",
    "NegotiationRound",
    "NegotiationStore",
    "NegotiationIndex",
    "RoundStore",
    "ArgumentOutcome",
    "PredictionRecord",
    "PeerInteractionRecord",
    "AgentBeliefStore",
    "AgentEpistemicStore",
    "CommonGroundStore",
    "ConvergenceStore",
    "PeerInteractionStore",
]

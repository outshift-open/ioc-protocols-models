# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/epistemic/stores.py — Three cross-episode epistemic stores.

Layer 6 of the epistemic stack: persistent belief state for agents and
agent-pairs. Soid scopes episodic transactions only; these stores are
soid-free and persist across episodes.

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
from typing import Dict, List, Optional


# ── Belief State (AgentBeliefStore) ───────────────────────────────────────────


@dataclass
class BeliefRevision:
    """One atomic change to an agent's belief in a concept."""

    revision_id: str           # unique; enables point-in-time replay
    timestamp_ms: int          # when the revision occurred
    episode_id: str            # soid of the episode that triggered this revision
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
    """An agent's current and historical belief in a single concept."""

    agent_id: str                          # which agent holds this belief
    concept_id: str                        # concept believed; URI namespace throughout
    current_confidence: float              # private — ground truth for 1st-order ToM
    public_confidence: float               # last asserted — what peers observe
    status: str                            # held | asserted | committed | retracted
    use_case: str                          # domain scope; prevents cross-domain belief merges
    first_formed_episode: str              # soid of episode in which belief was first established
    last_revised_episode: str             # soid of most recent episode in which belief changed
    revision_history: List[BeliefRevision] = field(default_factory=list)  # append-only
    social_compliance_ratio: float = 0.0  # rolling SCR: fraction of revisions with cause=social_compliance
    revision_count: int = 0               # total revisions
    confidence_variance: float = 0.0      # variance across revision_after values; high = frequently contested


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
    last_episode: str = ""             # soid of most recent contributing episode; staleness check


# ── AgentBeliefStore ──────────────────────────────────────────────────────────


class AgentBeliefStore:
    """Cross-episode, soid-free store of per-agent beliefs.

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

    def record_revision(
        self,
        agent_id: str,
        concept_id: str,
        use_case: str,
        episode_id: str,
        revision: BeliefRevision,
        new_status: str = "asserted",
        new_public_confidence: Optional[float] = None,
    ) -> BeliefState:
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
        soid: str,
        argument_outcomes: List[ArgumentOutcome],
        prediction_records: List[PredictionRecord],
    ) -> None:
        """Promote outcomes for a specific (observer, subject) pair at episode close."""
        for outcome in argument_outcomes:
            self.record_argument_outcome(observer_id, subject_id, use_case, outcome)
        for pred in prediction_records:
            self.record_prediction(observer_id, subject_id, use_case, pred)

        record = self._ensure(observer_id, subject_id, use_case)
        if record.last_episode != soid:
            record.episode_count += 1
            record.last_episode = soid


__all__ = [
    "BeliefRevision",
    "BeliefState",
    "ArgumentOutcome",
    "PredictionRecord",
    "PeerInteractionRecord",
    "AgentBeliefStore",
    "PeerInteractionStore",
]

"""
Phase 2 — GoalIntent
Define the Goal / Mission; includes a Clarifying sub-phase.
Evidence bundles feed ambiguity detection and the consensus commit.
Implementors: NegMas, Stigmetry.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from l9.shared import EvidenceBundle


class GoalIntentSubKind(str, Enum):
    AMBIGUITY       = "ambiguity"
    CONTINGENCY     = "contingency"
    NEGOTIATION     = "negotiation"
    EVIDENCE_BUNDLE = "evidence_bundle"  # packaged evidence used to clarify goals


class GoalIntentAction(str, Enum):
    DETECT_AMBIGUITY   = "detect_ambiguity"
    DETECT_CONTINGENCY = "detect_contingency"
    ATTACH_EVIDENCE    = "attach_evidence"   # attach an EvidenceBundle to the goal context
    CONSENSUS_COMMIT   = "consensus_commit"  # payload: ConsensusCommitPayload


class GoalIntentEvent(str, Enum):
    GOAL_PROPOSED        = "goal_proposed"
    AMBIGUITY_DETECTED   = "ambiguity_detected"
    CONTINGENCY_DETECTED = "contingency_detected"
    EVIDENCE_ATTACHED    = "evidence_attached"
    CONSENSUS_REACHED    = "consensus_reached"
    GOAL_COMMITTED       = "goal_committed"


class ConsensusCommitPayload(BaseModel):
    """Structured record produced by a CONSENSUS_COMMIT action."""
    goal_specified:     str                  = ""
    intent_behind_it:   str                  = ""
    problems_found:     List[str]            = Field(default_factory=list)
    solution:           str                  = ""
    supporting_bundles: List[EvidenceBundle] = Field(default_factory=list)


class NegMasState(BaseModel):
    negotiation_round: int       = 0
    offers:            List[str] = Field(default_factory=list)
    accepted:          bool      = False


class StigmetryState(BaseModel):
    pheromone_map:         Dict[str, float] = Field(default_factory=dict)
    convergence_threshold: float            = 0.95


class GoalIntentState(BaseModel):
    evidence_bundles: List[EvidenceBundle]             = Field(default_factory=list)
    commit_payload:   Optional[ConsensusCommitPayload] = None


class GoalIntentKind(BaseModel):
    phase:           int                     = 2
    name:            str                     = "GoalIntent"
    sub_kinds:       List[GoalIntentSubKind] = Field(default_factory=lambda: list(GoalIntentSubKind))
    actions:         List[GoalIntentAction]  = Field(default_factory=lambda: list(GoalIntentAction))
    events:          List[GoalIntentEvent]   = Field(default_factory=lambda: list(GoalIntentEvent))
    state:           GoalIntentState         = Field(default_factory=GoalIntentState)
    negmas_state:    NegMasState             = Field(default_factory=NegMasState)
    stigmetry_state: StigmetryState          = Field(default_factory=StigmetryState)

    def attach_evidence(self, bundle: EvidenceBundle) -> None:
        """Attach an EvidenceBundle to the goal context (ATTACH_EVIDENCE action)."""
        self.state.evidence_bundles.append(bundle)

    def consensus_commit(self, payload: ConsensusCommitPayload) -> None:
        """Record a consensus commit, including any supporting evidence."""
        self.state.commit_payload = payload

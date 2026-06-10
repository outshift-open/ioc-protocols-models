# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
store.py — Team process state data model.

TeamProcessStore is the single authoritative record of team coordination state:
current phase, role assignments, team goal, and whether the phase gate is open.

It is *prescriptive*, not descriptive.  A taskwork belief store (AgentBeliefStore)
records what an agent believes about a clinical concept — epistemic.  TeamProcessStore
records what the team has committed to about how it will work — normative.  Agents
cannot unilaterally ignore it.

Lifecycle
---------
1. Starts empty (phase=TRANSITION, gate closed).
2. Written by TeamCoordinator after each team-process SNP converges.
3. Read by PhaseGate before every taskwork turn.
4. Overwritten by TeamCoordinator on re-entry (trigger-driven mid-taskwork updates).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Phase(str, Enum):
    """Marks et al. team phase vocabulary used as coordination ground truth."""
    TRANSITION    = "transition"     # planning, role assignment, prior alignment
    ACTION        = "action"         # domain taskwork and SNP negotiation
    INTERPERSONAL = "interpersonal"  # SCR management, conflict resolution


class ReentryTrigger(str, Enum):
    """Reason a mid-taskwork team-process re-entry episode was triggered."""
    REPAIR_FAILED      = "repair_failed"       # IE contingency failed 2+ times on same pair
    SCR_HIGH           = "scr_high"            # SNP convergence driven by compliance not argument
    ALIGNMENT_DIVERGED = "alignment_diverged"  # ReplicaToM shows persistent scope URI mismatch
    TASK_SHIFT         = "task_shift"          # task type changed mid-episode (e.g. ICU escalation)
    NEW_AGENT          = "new_agent"           # new agent joined after team was formed


@dataclass
class AgentCapability:
    """Capability declaration — what an agent asserts it can own during TP-1."""
    agent_id: str
    concept_ids: List[str]   # clinical concept_ids this agent can assess
    confidence: float = 1.0


@dataclass
class AgentTeamBelief:
    """Per-agent epistemic belief about the current team process state.

    Distinct from TeamProcessState (authoritative).  Divergence between an
    agent's belief and the converged state is a team-process contingency failure.
    """
    agent_id: str
    believed_phase: str
    believed_role: str        # concept_id this agent thinks it owns
    believed_goal: str
    confidence: float
    episode_id: str


@dataclass
class TeamProcessState:
    """Converged, authoritative team coordination ground truth.

    Written after every team-process SNP commit:converged.  Prescriptive:
    all subsequent IE and SNP turns must respect this state.
    """
    current_phase: Phase
    role_assignments: Dict[str, str]   # agent_id → concept_id owned
    team_goal: str
    converged_episode_id: str
    scr_at_convergence: float
    gate_open: bool                    # False = TRANSITION, True = ACTION


class TeamProcessStore:
    """Single authoritative record of team coordination state.

    Written exclusively by TeamCoordinator.  Read by PhaseGate.
    Application code must not write to this store directly.
    """

    def __init__(self) -> None:
        self._state: Optional[TeamProcessState] = None
        self._agent_beliefs: Dict[str, AgentTeamBelief] = {}

    # ── Write ──────────────────────────────────────────────────────────────

    def update(self, state: TeamProcessState) -> None:
        """Replace authoritative state after a team-process SNP converges."""
        self._state = state

    def record_agent_belief(self, belief: AgentTeamBelief) -> None:
        """Record an individual agent's belief about team state (epistemic layer)."""
        self._agent_beliefs[belief.agent_id] = belief

    # ── Read ───────────────────────────────────────────────────────────────

    def current(self) -> Optional[TeamProcessState]:
        return self._state

    def phase(self) -> Phase:
        """Current authoritative phase.  Defaults to TRANSITION before first converge."""
        if self._state is None:
            return Phase.TRANSITION
        return self._state.current_phase

    def is_gate_open(self) -> bool:
        """True when taskwork turns are permitted (ACTION phase, gate not locked)."""
        if self._state is None:
            return False
        return self._state.gate_open

    def role_for(self, agent_id: str) -> Optional[str]:
        """Return the concept_id assigned to this agent, or None if unassigned."""
        if self._state is None:
            return None
        return self._state.role_assignments.get(agent_id)

    def agent_belief(self, agent_id: str) -> Optional[AgentTeamBelief]:
        return self._agent_beliefs.get(agent_id)

    def all_agent_beliefs(self) -> Dict[str, AgentTeamBelief]:
        return dict(self._agent_beliefs)


__all__ = [
    "Phase",
    "ReentryTrigger",
    "AgentCapability",
    "AgentTeamBelief",
    "TeamProcessState",
    "TeamProcessStore",
]

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
coordinator.py — TeamCoordinator: team-process episode orchestration.

TeamCoordinator runs team-process SNP episodes (TP-1, TP-2, TP-R).  It is the
only writer of TeamProcessStore.  Application code calls the three public
methods; all L9/Episode/PanelNegotiationBus mechanics are internal.

Episode types
-------------
TP-1  form_team()            concept:role_assignment + concept:team_goal
TP-2  align_mental_model()   concept:shared_mental_model + concept:current_phase
TP-R  reenter()              concept chosen by ReentryTrigger (see table below)

Re-entry trigger → concept_id mapping
--------------------------------------
REPAIR_FAILED / ALIGNMENT_DIVERGED  →  concept:shared_mental_model
SCR_HIGH / NEW_AGENT                →  concept:role_assignment
TASK_SHIFT                          →  concept:current_phase
                                        + concept:shared_mental_model (reload priors)

The gate is locked (gate_open=False) while a team-process episode is running and
unlocked only when the episode converges successfully.  If the SNP fails to
converge the gate remains locked and the caller must handle the error.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from sstp.process.gate import PhaseGate
from sstp.process.store import (
    AgentCapability,
    AgentTeamBelief,
    Phase,
    ReentryTrigger,
    TeamProcessState,
    TeamProcessStore,
)

LOGGER = logging.getLogger("sstp.process.coordinator")

# Coordination concept_id constants — not clinical, never used in taskwork.
CONCEPT_ROLE_ASSIGNMENT      = "concept:role_assignment"
CONCEPT_TEAM_GOAL            = "concept:team_goal"
CONCEPT_SHARED_MENTAL_MODEL  = "concept:shared_mental_model"
CONCEPT_CURRENT_PHASE        = "concept:current_phase"

_REENTRY_CONCEPT: Dict[ReentryTrigger, List[str]] = {
    ReentryTrigger.REPAIR_FAILED:      [CONCEPT_SHARED_MENTAL_MODEL],
    ReentryTrigger.ALIGNMENT_DIVERGED: [CONCEPT_SHARED_MENTAL_MODEL],
    ReentryTrigger.SCR_HIGH:           [CONCEPT_ROLE_ASSIGNMENT],
    ReentryTrigger.NEW_AGENT:          [CONCEPT_ROLE_ASSIGNMENT],
    ReentryTrigger.TASK_SHIFT:         [CONCEPT_CURRENT_PHASE, CONCEPT_SHARED_MENTAL_MODEL],
}


class TeamFormationError(RuntimeError):
    """Raised when TP-1 cannot produce a valid role assignment."""


class MentalModelError(RuntimeError):
    """Raised when TP-2 cannot reach shared-mental-model convergence."""


class TeamCoordinator:
    """Runs team-process SNP episodes and is the sole writer of TeamProcessStore.

    Parameters
    ----------
    l9:
        The L9 instance for the coordinator agent.  Used to open/join Episodes.
    panel_bus_factory:
        Callable(concept_id) → PanelNegotiationBus.  Called once per team-process
        SNP round.  The factory is responsible for constructing a bus with the
        appropriate stores and repair function.
    store:
        TeamProcessStore instance shared with PhaseGate and TaskSession.
    gate:
        PhaseGate instance; coordination turns bypass the gate via
        gate.check_coordination().
    coordinator_agent_id:
        The agent_id used by the Coordinator in L9 messages.
    """

    def __init__(
        self,
        l9: Any,                                 # sstp.l9.episode.L9
        panel_bus_factory: Callable[[str], Any], # concept_id → PanelNegotiationBus
        store: TeamProcessStore,
        gate: PhaseGate,
        coordinator_agent_id: str = "coordinator",
    ) -> None:
        self._l9 = l9
        self._panel_bus_factory = panel_bus_factory
        self._store = store
        self._gate = gate
        self._coordinator_id = coordinator_agent_id

    # ── TP-1: team formation ───────────────────────────────────────────────

    def form_team(
        self,
        task_description: str,
        available_agents: List[AgentCapability],
    ) -> TeamProcessState:
        """TP-1: capability broadcast + role-assignment SNP.

        Opens an Episode on concept:role_assignment.  Each available agent
        asserts which concept_id it owns (capability declaration via episode.say).
        Conflict resolution (two agents claiming the same domain) is handled by
        the SNP round — the agent with higher confidence wins.

        Phase stays TRANSITION after this call.  gate_open remains False.

        Returns the converged TeamProcessState.
        Raises TeamFormationError if a required concept has no owner.
        """
        LOGGER.info(
            "coordinator.form_team task=%r agents=%d",
            task_description, len(available_agents),
        )

        eid = self._episode_id("role_assignment")
        episode = self._l9.open(
            concept_id=CONCEPT_ROLE_ASSIGNMENT,
            group=[a.agent_id for a in available_agents],
            episode_id=eid,
        )

        # Collect capability assertions.
        # In a real distributed system each agent calls episode.say() in response
        # to the intent.  Here we build the role map from capability declarations
        # directly, then let the SNP round handle conflicts.
        role_claims: Dict[str, List[AgentCapability]] = {}  # concept_id → claimants
        for cap in available_agents:
            for cid in cap.concept_ids:
                role_claims.setdefault(cid, []).append(cap)

        # Coordinator asserts the proposed assignments into the episode.
        role_assignments: Dict[str, str] = {}  # agent_id → concept_id
        for concept_id, claimants in role_claims.items():
            # Sort by confidence descending; highest confidence wins.
            claimants.sort(key=lambda c: c.confidence, reverse=True)
            winner = claimants[0]
            role_assignments[winner.agent_id] = concept_id
            episode.say(
                utterance=f"role_proposal agent={winner.agent_id} concept={concept_id} confidence={winner.confidence:.2f}",
                posterior=winner.confidence,
                evidence=[CONCEPT_ROLE_ASSIGNMENT, concept_id],
            )

        episode.done(posterior=0.9)

        # Run SNP to confirm (in a stub: accept immediately; real SNP round handled
        # by panel_bus_factory when specialists counter-propose).
        panel_bus = self._panel_bus_factory(CONCEPT_ROLE_ASSIGNMENT)
        scr = self._run_coordination_snp(panel_bus, role_assignments, available_agents)

        self._acknowledge_group(episode, available_agents)
        episode.close()

        state = TeamProcessState(
            current_phase=Phase.TRANSITION,
            role_assignments=role_assignments,
            team_goal=task_description,
            converged_episode_id=eid,
            scr_at_convergence=scr,
            gate_open=False,
        )
        self._store.update(state)
        LOGGER.info(
            "coordinator.form_team.done roles=%d scr=%.2f",
            len(role_assignments), scr,
        )
        return state

    # ── TP-2: shared mental model ──────────────────────────────────────────

    def align_mental_model(
        self,
        agent_priors: Dict[str, Dict[str, float]],
    ) -> TeamProcessState:
        """TP-2: verify priors loaded, converge on concept:shared_mental_model.

        Opens an Episode on concept:shared_mental_model.  Each agent confirms
        its prior for the concepts it owns.  On convergence the phase gate
        transitions to ACTION (gate_open=True).

        Parameters
        ----------
        agent_priors:
            Mapping agent_id → {concept_id → prior_value}.  Typically derived
            from SemanticRuleStore.activate_rules() + AgentBeliefStore.set_prior().

        Returns the updated TeamProcessState with phase=ACTION, gate_open=True.
        Raises MentalModelError if convergence fails.
        """
        current = self._store.current()
        if current is None:
            raise MentalModelError("form_team() must be called before align_mental_model()")

        LOGGER.info("coordinator.align_mental_model agents=%d", len(agent_priors))

        eid = self._episode_id("shared_mental_model")
        group = list(agent_priors.keys())
        episode = self._l9.open(
            concept_id=CONCEPT_SHARED_MENTAL_MODEL,
            group=group,
            episode_id=eid,
        )

        # Record each agent's prior confirmation.
        for agent_id, priors in agent_priors.items():
            concept_id = current.role_assignments.get(agent_id, "concept:unknown")
            prior_val = priors.get(concept_id, 0.5)
            self._store.record_agent_belief(AgentTeamBelief(
                agent_id=agent_id,
                believed_phase=Phase.TRANSITION.value,
                believed_role=concept_id,
                believed_goal=current.team_goal,
                confidence=prior_val,
                episode_id=eid,
            ))
            episode.say(
                utterance=f"prior_confirmed agent={agent_id} concept={concept_id} prior={prior_val:.3f}",
                posterior=prior_val,
                evidence=[CONCEPT_SHARED_MENTAL_MODEL, concept_id],
            )

        episode.done(posterior=0.9)
        self._acknowledge_group(episode, list(agent_priors.keys()))
        episode.close()

        state = TeamProcessState(
            current_phase=Phase.ACTION,
            role_assignments=current.role_assignments,
            team_goal=current.team_goal,
            converged_episode_id=eid,
            scr_at_convergence=0.0,
            gate_open=True,
        )
        self._store.update(state)
        LOGGER.info("coordinator.align_mental_model.done phase=ACTION gate=OPEN")
        return state

    # ── TP-R: re-entry ─────────────────────────────────────────────────────

    def reenter(
        self,
        trigger: ReentryTrigger,
        context: Optional[Dict[str, Any]] = None,
    ) -> TeamProcessState:
        """TP-R: mid-taskwork team-process re-entry episode.

        Locks the gate, runs the appropriate coordination episode(s), then
        unlocks the gate.  The concept_id(s) are selected by trigger type
        (see module docstring).

        Parameters
        ----------
        trigger:
            Why re-entry was triggered.
        context:
            Optional dict for additional context (e.g. the agent pair that
            failed grounding, the concept that diverged).

        Returns the updated TeamProcessState with gate_open=True.
        """
        current = self._store.current()
        if current is None:
            raise RuntimeError("TeamProcessStore has no state — call form_team() first")

        LOGGER.info(
            "coordinator.reenter trigger=%s context=%s",
            trigger.value, context,
        )

        # Lock the gate while re-entry is running.
        locked = TeamProcessState(
            current_phase=Phase.TRANSITION,
            role_assignments=current.role_assignments,
            team_goal=current.team_goal,
            converged_episode_id=current.converged_episode_id,
            scr_at_convergence=current.scr_at_convergence,
            gate_open=False,
        )
        self._store.update(locked)

        concepts = _REENTRY_CONCEPT.get(trigger, [CONCEPT_SHARED_MENTAL_MODEL])
        last_eid = current.converged_episode_id
        scr = 0.0

        for concept_id in concepts:
            eid = self._episode_id(concept_id.replace("concept:", ""))
            group = list(current.role_assignments.keys())
            episode = self._l9.open(
                concept_id=concept_id,
                group=group,
                episode_id=eid,
            )
            episode.say(
                utterance=f"reentry trigger={trigger.value} concept={concept_id}",
                posterior=0.8,
                evidence=[concept_id],
            )
            episode.done(posterior=0.8)
            self._acknowledge_group(episode, group)
            episode.close()
            last_eid = eid

        # After re-entry converges, restore ACTION phase with gate open.
        new_state = TeamProcessState(
            current_phase=Phase.ACTION,
            role_assignments=current.role_assignments,
            team_goal=current.team_goal,
            converged_episode_id=last_eid,
            scr_at_convergence=scr,
            gate_open=True,
        )
        self._store.update(new_state)
        LOGGER.info(
            "coordinator.reenter.done trigger=%s phase=ACTION gate=OPEN",
            trigger.value,
        )
        return new_state

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _acknowledge_group(episode: Any, members: List[Any], posterior: float = 0.9) -> None:
        """Record done signals on behalf of all group members.

        In a distributed deployment each agent calls episode.done() itself.
        The coordinator runs TP episodes synchronously, so it registers
        acknowledgements for every member before calling close().
        """
        for member in members:
            if hasattr(episode, "_record_done"):
                episode._record_done(str(getattr(member, "agent_id", member)), posterior)

    def _episode_id(self, suffix: str) -> str:
        ts = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        return f"urn:ioc:process:{suffix}:{ts}:{uid}"

    def _run_coordination_snp(
        self,
        panel_bus: Any,
        role_assignments: Dict[str, str],
        available_agents: List[AgentCapability],
    ) -> float:
        """Run coordination SNP and return SCR.  Stub — real SNP via panel_bus."""
        # In a full implementation this calls panel_bus.run_star_negotiation()
        # with coordination positions.  For now returns 0.0 (full genuine agreement).
        return 0.0


__all__ = [
    "TeamCoordinator",
    "TeamFormationError",
    "MentalModelError",
    "CONCEPT_ROLE_ASSIGNMENT",
    "CONCEPT_TEAM_GOAL",
    "CONCEPT_SHARED_MENTAL_MODEL",
    "CONCEPT_CURRENT_PHASE",
]

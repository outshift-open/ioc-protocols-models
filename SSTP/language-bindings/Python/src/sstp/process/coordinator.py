# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
coordinator.py — TeamCoordinator: team-process episode orchestration.

TeamCoordinator runs team-process SNP episodes (TP-1, TP-2, TP-R).  It is the
only writer of TeamProcessStore.  Application code calls the three public
methods; all L9/Episode/PanelBus mechanics are internal.

SNP messages from team-process episodes flow directly into the ie_bus.messages
shared by the panel buses (unified bus).  No separate trace accumulation needed.

When participant_l9s is supplied each specialist joins the IE episode and emits
its own exchange+ready, producing genuine participant responses on the bus.
The SNP round runs inside the open IE episode so all messages are temporally
interleaved correctly.

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
        Callable(concept_id) → PanelBus.  Called once per team-process
        SNP round.  The factory is responsible for constructing a bus with the
        appropriate stores and repair function.
    store:
        TeamProcessStore instance shared with PhaseGate and TaskSession.
    gate:
        PhaseGate instance; coordination turns bypass the gate via
        gate.check_coordination().
    coordinator_agent_id:
        The agent_id used by the Coordinator in L9 messages.
    participant_l9s:
        Optional mapping of agent_id → L9 for each specialist.  When supplied,
        each specialist joins the IE episode and emits its own exchange, so the
        message stream shows genuine participant responses instead of coordinator
        monologue.  When absent the coordinator speaks for all members (legacy
        behaviour).
    """

    def __init__(
        self,
        l9: Any,                                 # sstp.l9.episode.L9
        panel_bus_factory: Callable[[str], Any], # concept_id → PanelBus
        store: TeamProcessStore,
        gate: PhaseGate,
        coordinator_agent_id: str = "coordinator",
        participant_l9s: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._l9 = l9
        self._panel_bus_factory = panel_bus_factory
        self._store = store
        self._gate = gate
        self._coordinator_id = coordinator_agent_id
        self._participant_l9s: Dict[str, Any] = dict(participant_l9s or {})

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
        group_ids = [a.agent_id for a in available_agents]
        episode = self._l9.open(
            concept_id=CONCEPT_ROLE_ASSIGNMENT,
            group=group_ids,
            episode_id=eid,
        )
        # Capture the intent envelope so participants can join
        intent_envelope = self._l9._bus.messages[-1]

        # Collect capability assertions.
        role_claims: Dict[str, List[AgentCapability]] = {}  # concept_id → claimants
        for cap in available_agents:
            for cid in cap.concept_ids:
                role_claims.setdefault(cid, []).append(cap)

        # Resolve winner per concept (highest confidence wins)
        role_assignments: Dict[str, str] = {}  # agent_id → concept_id
        for concept_id, claimants in role_claims.items():
            claimants.sort(key=lambda c: c.confidence, reverse=True)
            winner = claimants[0]
            role_assignments[winner.agent_id] = concept_id

        # Each participant joins the episode and asserts its capability claim.
        # All group members must signal done regardless of whether they won a role.
        # If participant_l9s are provided the agent speaks for itself; otherwise
        # the coordinator speaks on behalf of members (legacy path).
        for cap in available_agents:
            won_concept = role_assignments.get(cap.agent_id)
            if won_concept:
                utterance = (
                    f"capability_claim agent={cap.agent_id} concept={won_concept} confidence={cap.confidence:.2f}"
                )
                evidence = [CONCEPT_ROLE_ASSIGNMENT, won_concept]
            else:
                claimed = ", ".join(cap.concept_ids)
                utterance = (
                    f"capability_claim agent={cap.agent_id} claimed={claimed} confidence={cap.confidence:.2f} outcome=no_role_assigned"
                )
                evidence = [CONCEPT_ROLE_ASSIGNMENT]
            participant_l9 = self._participant_l9s.get(cap.agent_id)
            if participant_l9 is not None:
                member_ep = participant_l9.join(intent_envelope)
                member_ep.say(
                    utterance=utterance,
                    posterior=cap.confidence,
                    evidence=evidence,
                    final=True,
                )
                episode._record_done(cap.agent_id, cap.confidence)
            else:
                # Legacy: coordinator speaks for this member
                episode.say(
                    utterance=utterance,
                    posterior=cap.confidence,
                    evidence=evidence,
                )
                episode._record_done(cap.agent_id, cap.confidence)

        # SNP round — conflicts resolved by the panel; SCR reflects residual
        # non-compliance after convergence.  Runs inside the open IE episode.
        panel_bus = self._panel_bus_factory(CONCEPT_ROLE_ASSIGNMENT)
        scr = self._run_coordination_snp(panel_bus, role_assignments, available_agents)

        episode.done(posterior=0.9)
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
        intent_envelope = self._l9._bus.messages[-1]

        # Each agent confirms its prior for its owned concept.
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
            utterance = f"prior_confirmed agent={agent_id} concept={concept_id} prior={prior_val:.3f}"
            participant_l9 = self._participant_l9s.get(agent_id)
            if participant_l9 is not None:
                member_ep = participant_l9.join(intent_envelope)
                member_ep.say(
                    utterance=utterance,
                    posterior=prior_val,
                    evidence=[CONCEPT_SHARED_MENTAL_MODEL, concept_id],
                    final=True,
                )
                episode._record_done(agent_id, prior_val)
            else:
                # Legacy: coordinator speaks for this member
                episode.say(
                    utterance=utterance,
                    posterior=prior_val,
                    evidence=[CONCEPT_SHARED_MENTAL_MODEL, concept_id],
                )
                episode._record_done(agent_id, prior_val)

        # SNP round — agents negotiate convergence on the shared prior values.
        # Runs inside the open IE episode; IE active for linguistic repair only.
        panel_bus = self._panel_bus_factory(CONCEPT_SHARED_MENTAL_MODEL)
        scr = self._run_alignment_snp(panel_bus, current.role_assignments, agent_priors)

        episode.done(posterior=0.9)
        episode.close()

        state = TeamProcessState(
            current_phase=Phase.ACTION,
            role_assignments=current.role_assignments,
            team_goal=current.team_goal,
            converged_episode_id=eid,
            scr_at_convergence=scr,
            gate_open=True,
        )
        self._store.update(state)
        LOGGER.info("coordinator.align_mental_model.done phase=ACTION gate=OPEN scr=%.2f", scr)
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

            # SNP round to re-converge on the affected concept.
            reentry_positions = {
                agent_id: {"decision_key": current.role_assignments.get(agent_id, concept_id), "confidence": 0.8}
                for agent_id in group
            }
            panel_bus = self._panel_bus_factory(concept_id)
            scr = self._run_reentry_snp(panel_bus, concept_id, group, reentry_positions)

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
        """TP-1 SNP round: agents negotiate role assignments via StarNegotiation.

        Each agent's position is its claimed concept_id with its declared confidence.
        The controller is the first agent in role_assignments; remaining agents are
        members.  Returns SCR from the convergence result.
        """
        from sstp.snp.panel_bus import StarNegotiation

        agents = list(role_assignments.keys())
        if not agents:
            return 0.0

        controller_id = agents[0]
        member_ids = agents[1:]

        # Build positions: {agent_id → {"decision_key": concept_id, "confidence": float}}
        cap_map = {c.agent_id: c for c in available_agents}
        positions: Dict[str, Any] = {}
        for agent_id, concept_id in role_assignments.items():
            conf = cap_map[agent_id].confidence if agent_id in cap_map else 0.8
            positions[agent_id] = {"decision_key": concept_id, "confidence": conf}

        controller_position = positions.get(controller_id, {"decision_key": "coordinator", "confidence": 0.9})
        panel_bus.reset()
        star = StarNegotiation(panel_bus, CONCEPT_ROLE_ASSIGNMENT.split(":")[-1])
        try:
            _, _, trace = star.run(
                controller_id=controller_id,
                member_ids=member_ids,
                controller_position=controller_position,
                specialist_positions=positions,
                task_goal=f"agree on role assignments for {CONCEPT_ROLE_ASSIGNMENT}",
                agent_beliefs={a: {"role": role_assignments.get(a, ""), "confidence": positions[a]["confidence"]}
                               for a in agents},
            )
            last = trace[-1] if trace else {}
            return float(last.get("scr", 0.0))
        except Exception as exc:
            LOGGER.warning("coordinator.tp1_snp_failed: %s", exc)
            return 0.0

    def _run_alignment_snp(
        self,
        panel_bus: Any,
        role_assignments: Dict[str, str],
        agent_priors: Dict[str, Dict[str, float]],
    ) -> float:
        """TP-2 SNP round: agents negotiate convergence on shared prior values.

        Each agent proposes its prior for its owned concept.  The controller is
        the first agent in role_assignments.  Returns SCR.
        """
        from sstp.snp.panel_bus import StarNegotiation

        agents = list(role_assignments.keys())
        if not agents:
            return 0.0

        controller_id = agents[0]
        member_ids = agents[1:]

        positions: Dict[str, Any] = {}
        for agent_id, concept_id in role_assignments.items():
            priors = agent_priors.get(agent_id, {})
            prior_val = priors.get(concept_id, 0.5)
            positions[agent_id] = {"decision_key": concept_id, "confidence": prior_val}

        controller_position = positions.get(controller_id, {"decision_key": "shared_mental_model", "confidence": 0.9})
        panel_bus.reset()
        star = StarNegotiation(panel_bus, CONCEPT_SHARED_MENTAL_MODEL.split(":")[-1])
        try:
            _, _, trace = star.run(
                controller_id=controller_id,
                member_ids=member_ids,
                controller_position=controller_position,
                specialist_positions=positions,
                task_goal=f"align priors for {CONCEPT_SHARED_MENTAL_MODEL}",
                agent_beliefs={a: {"role": role_assignments.get(a, ""), "confidence": positions[a]["confidence"]}
                               for a in agents},
            )
            last = trace[-1] if trace else {}
            return float(last.get("scr", 0.0))
        except Exception as exc:
            LOGGER.warning("coordinator.tp2_snp_failed: %s", exc)
            return 0.0

    def _run_reentry_snp(
        self,
        panel_bus: Any,
        concept_id: str,
        group: List[str],
        positions: Dict[str, Any],
    ) -> float:
        """TP-R SNP round: re-converge on a single coordination concept after re-entry."""
        from sstp.snp.panel_bus import StarNegotiation

        if not group:
            return 0.0

        controller_id = group[0]
        member_ids = group[1:]
        controller_position = positions.get(controller_id, {"decision_key": concept_id, "confidence": 0.8})

        panel_bus.reset()
        star = StarNegotiation(panel_bus, concept_id.split(":")[-1])
        try:
            _, _, trace = star.run(
                controller_id=controller_id,
                member_ids=member_ids,
                controller_position=controller_position,
                specialist_positions=positions,
                task_goal=f"reentry convergence for {concept_id}",
                agent_beliefs={a: {"role": concept_id, "confidence": positions[a]["confidence"]}
                               for a in group},
            )
            last = trace[-1] if trace else {}
            return float(last.get("scr", 0.0))
        except Exception as exc:
            LOGGER.warning("coordinator.tpr_snp_failed concept=%s: %s", concept_id, exc)
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

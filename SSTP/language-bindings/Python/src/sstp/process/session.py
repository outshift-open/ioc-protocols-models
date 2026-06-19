# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
session.py — TaskSession: taskwork episode orchestration.

TaskSession is the adaptation layer for clinical (taskwork) turns.  It wraps
AgentBus.emit_peer_turn() and PanelBus negotiation rounds behind a
single surface that:

  1. Checks PhaseGate before every turn — suppresses silently if not permitted.
  2. Builds the full epistemic block including sub-concept scope URIs.
  3. Tracks IE grounding failures per agent pair and triggers TeamCoordinator
     re-entry when the repair threshold is exceeded.
  4. Checks SCR after every SNP negotiation round and triggers re-entry if
     compliance is detected.

Application agents call assess() for domain belief assertions and negotiate()
for SNP panel rounds.  They never call AgentBus.emit_peer_turn() directly.

TW-1  assess()      individual IE belief assertion turn
TW-2  negotiate()   SNP round for one clinical concept
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sstp.process.gate import PhaseGate
from sstp.process.store import ReentryTrigger, TeamProcessStore

LOGGER = logging.getLogger("sstp.process.session")


@dataclass
class ConvergenceResult:
    """Output of a completed SNP negotiation round."""
    concept_id: str
    mpc: float
    gar: float
    scr: float
    episode_id: str
    flagged: bool   # True when SCR exceeded the configured threshold


class TaskSession:
    """Taskwork adaptation layer — wraps AgentBus and PanelBus.

    Parameters
    ----------
    bus:
        The AgentBus (or subclass) for emitting IE turns.
    gate:
        PhaseGate instance shared with TeamCoordinator.
    coordinator:
        TeamCoordinator — called when repair or SCR thresholds are breached.
    store:
        TeamProcessStore — read to check role assignments.
    repair_failure_threshold:
        Number of consecutive grounding failures on the same agent pair before
        coordinator.reenter(REPAIR_FAILED) is triggered.
    scr_threshold:
        SCR value above which negotiate() flags the result and triggers
        coordinator.reenter(SCR_HIGH).
    """

    def __init__(
        self,
        bus: Any,                     # sstp.ie.agent_bus.AgentBus
        gate: PhaseGate,
        coordinator: Any,             # sstp.process.coordinator.TeamCoordinator
        store: TeamProcessStore,
        repair_failure_threshold: int = 2,
        scr_threshold: float = 0.35,
    ) -> None:
        self._bus = bus
        self._gate = gate
        self._coordinator = coordinator
        self._store = store
        self._repair_threshold = repair_failure_threshold
        self._scr_threshold = scr_threshold
        # (agent_id, concept_id) → consecutive failure count
        self._repair_failures: Dict[Tuple[str, str], int] = defaultdict(int)

    # ── TW-1: individual assessment turn ──────────────────────────────────

    def assess(
        self,
        agent_id: str,
        concept_id: str,
        posterior: float,
        utterance: str,
        *,
        scope: Optional[List[str]] = None,
        speech_act: str = "assertion",
        belief_status: str = "asserted",
        parent_id: Optional[str] = None,
        receiver: Optional[str] = None,
    ) -> Optional[str]:
        """TW-1: emit a taskwork IE belief assertion turn.

        Checks the phase gate first.  Returns None if the turn is suppressed
        (wrong phase, wrong role, gate locked).  Otherwise emits via
        bus.emit_peer_turn() and returns the message_id.

        Parameters
        ----------
        agent_id:
            The agent making the assertion.
        concept_id:
            The clinical concept being asserted (e.g. "concept:drug_interaction").
        posterior:
            The agent's current posterior belief (0.0–1.0).
        utterance:
            The natural-language claim content.
        scope:
            List of concept URIs including the category URI and, when known,
            a sub-concept URI.  E.g.::

                ["concept:drug_interaction",
                 "urn:concept:healthcare:drug_interaction:warfarin+ibuprofen"]

            Passed as context for scope tracking (not written to wire).
        speech_act:
            Overrides default "assertion".
        belief_status:
            Overrides default "asserted".
        parent_id:
            Parent message_id for threading.
        receiver:
            Target agent_id, or None for broadcast.
        """
        if not self._gate.check(agent_id, concept_id):
            return None

        effective_scope = scope if scope is not None else [concept_id]
        uncertainty = round(1.0 - posterior, 4)

        try:
            from sstp.epistemic import SpeechAct, EpistemicState, BeliefStatus, make_epistemic_block

            _speech_act = SpeechAct(speech_act) if speech_act in [m.value for m in SpeechAct] else SpeechAct.BELIEF_ASSERTION
            _belief_status = BeliefStatus(belief_status) if belief_status in [m.value for m in BeliefStatus] else BeliefStatus.ASSERTED

            epistemic = make_epistemic_block(
                speech_act=_speech_act,
                epistemic_state=EpistemicState.TASKWORK,
                belief_status=_belief_status,
                uncertainty=uncertainty,
            )
        except Exception:
            epistemic = None

        from sstp.epistemic import SpeechAct, EpistemicState
        header = self._bus.emit_peer_turn(
            sender=agent_id,
            receiver=receiver,
            utterance=utterance,
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.TASKWORK,
            parent_id=parent_id,
            topic=concept_id,
            epistemic=epistemic,
        )

        msg_id: Optional[str] = None
        if header and isinstance(header, dict):
            msg_id = header.get("message", {}).get("id")

        LOGGER.debug(
            "session.assess agent=%s concept=%s posterior=%.3f msg_id=%s",
            agent_id, concept_id, posterior, msg_id,
        )
        return msg_id

    # ── IE grounding verification ──────────────────────────────────────────

    def verify_grounding(
        self,
        agent_id: str,
        concept_id: str,
        addresses_evidence: List[str],
        prior_evidence: List[str],
    ) -> bool:
        """Check contingency: does addresses_evidence overlap prior_evidence?

        Tracks consecutive failures per (agent_id, concept_id) pair.
        Triggers coordinator.reenter(REPAIR_FAILED) when the failure threshold
        is exceeded.

        Returns True if grounding is verified, False otherwise.
        """
        overlap = set(addresses_evidence) & set(prior_evidence)
        grounded = len(overlap) > 0

        key = (agent_id, concept_id)
        if grounded:
            self._repair_failures[key] = 0
        else:
            self._repair_failures[key] += 1
            failures = self._repair_failures[key]
            LOGGER.debug(
                "session.grounding_failed agent=%s concept=%s failures=%d threshold=%d",
                agent_id, concept_id, failures, self._repair_threshold,
            )
            if failures >= self._repair_threshold:
                LOGGER.warning(
                    "session.repair_threshold_exceeded agent=%s concept=%s — triggering reenter",
                    agent_id, concept_id,
                )
                self._repair_failures[key] = 0
                self._coordinator.reenter(
                    ReentryTrigger.REPAIR_FAILED,
                    context={"agent_id": agent_id, "concept_id": concept_id},
                )

        return grounded

    # ── TW-2: SNP negotiation round ────────────────────────────────────────

    def negotiate(
        self,
        concept_id: str,
        participants: List[str],
        panel_bus: Any,               # PanelBus
        *,
        controller_id: Optional[str] = None,
        specialist_positions: Optional[Dict[str, Any]] = None,
        task_goal: str = "",
        agent_beliefs: Optional[Dict[str, Any]] = None,
    ) -> ConvergenceResult:
        """TW-2: run one SNP negotiation round for a clinical concept.

        Checks the phase gate first.  If the gate is not open (TRANSITION phase
        or locked) the method returns a zero-confidence result without running
        the round.

        After the round, checks SCR.  If SCR > scr_threshold, flags the result
        and triggers coordinator.reenter(SCR_HIGH).

        Parameters
        ----------
        concept_id:
            Clinical concept being negotiated.
        participants:
            List of agent_ids that should participate.
        panel_bus:
            PanelBus instance (already constructed by the app).
        controller_id:
            The SNP controller agent.  Defaults to first participant.
        specialist_positions:
            Initial positions per agent_id → position dict.
        task_goal:
            Human-readable task goal string passed to the SNP round.
        agent_beliefs:
            Agent belief context passed to the SNP round.
        """
        if not self._gate.check(
            controller_id or (participants[0] if participants else ""),
            concept_id,
        ):
            LOGGER.debug(
                "session.negotiate suppressed concept=%s reason=gate_closed",
                concept_id,
            )
            return ConvergenceResult(
                concept_id=concept_id,
                mpc=0.0, gar=0.0, scr=0.0,
                episode_id="",
                flagged=False,
            )

        from sstp.snp.panel_bus import StarNegotiation, IERepairExhausted

        _controller = controller_id or f"{concept_id.split(':')[-1]}-controller"
        _members = [p for p in participants if p != _controller]
        _positions: Dict[str, Any] = specialist_positions or {}
        _beliefs = agent_beliefs or {m: {"role": concept_id, "confidence": 0.6} for m in _members}

        if not _positions:
            _controller_pos = {}
        else:
            _controller_pos = StarNegotiation._leading_position(_positions)

        panel_bus.reset()
        star = StarNegotiation(panel_bus, concept_id.split(":")[-1])

        mpc = 0.5
        gar = 0.0
        scr = 0.0
        episode_id = ""

        try:
            winning_pos, resolution_label, _ = star.run(
                controller_id=_controller,
                member_ids=_members,
                controller_position=_controller_pos,
                specialist_positions=_positions,
                task_goal=task_goal or f"negotiate {concept_id}",
                agent_beliefs=_beliefs,
            )
            # Extract metrics from panel_bus if available.
            snp_trace = list(getattr(panel_bus, "snp_trace", []))
            if snp_trace:
                from sstp.snp.panel_bus import get_snp_convergence_metrics
                last = snp_trace[-1]
                metrics = get_snp_convergence_metrics(last)
                mpc = float(metrics.get("mpc", 0.5))
                gar = float(metrics.get("gar", 0.0))
                scr = float(metrics.get("scr", 0.0))
                episode_id = metrics.get("episode_id", "")

            LOGGER.info(
                "session.negotiate concept=%s resolution=%s mpc=%.3f scr=%.3f",
                concept_id, resolution_label, mpc, scr,
            )
        except IERepairExhausted as exc:
            LOGGER.warning(
                "session.negotiate.ie_repair_exhausted concept=%s depth=%d cause=%s",
                concept_id, exc.ie_depth, exc.cause,
            )
            scr = 1.0   # treat as maximum compliance (failed to negotiate genuinely)

        flagged = scr > self._scr_threshold
        if flagged:
            LOGGER.warning(
                "session.negotiate.scr_high concept=%s scr=%.3f threshold=%.3f — triggering reenter",
                concept_id, scr, self._scr_threshold,
            )
            self._coordinator.reenter(
                ReentryTrigger.SCR_HIGH,
                context={"concept_id": concept_id, "scr": scr},
            )

        return ConvergenceResult(
            concept_id=concept_id,
            mpc=mpc,
            gar=gar,
            scr=scr,
            episode_id=episode_id,
            flagged=flagged,
        )

    # ── Session lifecycle (outer frame) ───────────────────────────────────

    def open_session(
        self,
        subject: str,
        episode_id: Optional[str] = None,
        coordinator: str = "orchestrator",
    ) -> Dict[str, Any]:
        """Emit kind=intent to open the outer session frame.

        This is the only legitimate caller of bus._emit_episode_open from
        outside the subprotocol layer.  Application code must call this
        method rather than touching the bus directly.
        """
        return self._bus._emit_episode_open(
            coordinator=coordinator,
            subject=subject,
            episode_id=episode_id,
        )

    def close_session(
        self,
        subject: str,
        accepted: bool,
        episode_id: Optional[str] = None,
        coordinator: str = "orchestrator",
    ) -> Dict[str, Any]:
        """Emit kind=commit:converged or commit:rejected to close the outer session.

        This is the only legitimate caller of bus._emit_episode_close from
        outside the subprotocol layer.  Application code must call this
        method rather than touching the bus directly.
        """
        return self._bus._emit_episode_close(
            coordinator=coordinator,
            subject=subject,
            accepted=accepted,
            episode_id=episode_id,
        )


__all__ = ["TaskSession", "ConvergenceResult"]

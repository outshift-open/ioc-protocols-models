# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/l9/episode.py — Application-facing L9 Episode API.

Application writers import :class:`L9` and the relevant Episode subclass.
They never call ``MessageBus`` or any ``emit_*`` method directly.

Three episode kinds, each fully encapsulating its protocol mechanics::

    # Episode A — team process
    tp_ep = ctrl_l9.open_team_process(
        concept_id=patient_id, group=all_ids, agreement=agreement, task_goal=...
    )
    tp_ep.run()
    tp_ep.close(rationale=..., thought_summary=...)

    # Episode B — taskwork (SIEP debate; each specialist independently declares prior)
    tw_ep = ctrl_l9.open_taskwork(
        concept_id=patient_id, group=all_ids, task_goal=...
    )
    tw_ep.run(controller_position=..., specialist_positions=..., ...)
    tw_ep.close(rationale=..., thought_summary=...)

    # Episode C — SIEP panel
    task_ep = ctrl_l9.open_task(
        concept_id="concept:drug_interaction",
        group=all_ids,
        convergence_store=..., semantic_rule_store=...,
        repair_fn=...,
    )
    task_ep.run(
        controller_position=..., specialist_positions=...,
        task_goal=..., accept_threshold=0.1, max_rounds=2,
    )
    task_ep.announce(
        concept_id=task_ep.winning_position_key,
        posterior=task_ep.mpc, gar=task_ep.gar, scr=task_ep.scr,
    )

For receiving agents (generic CIP)::

    @l9.on_intent
    def handle_intent(episode: Episode) -> None:
        episode.say("My assessment is...", posterior=0.71, final=True)

Note: this module imports directly from SSTP.* source. Import paths and
call signatures are expected to change once the SSTP Python wheel is available.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from SSTP.subprotocol.siep.src.panel import NetworkHandle
from SSTP.l9.emit import (
    emit_peer_turn as _emit_peer_turn,
    emit_semantic_repair as _emit_semantic_repair,
    emit_epistemic_clarification as _emit_epistemic_clarification,
    emit_taskwork_result as _emit_taskwork_result,
    emit_repair_resolved as _emit_repair_resolved,
    emit_grounding_turn as _emit_grounding_turn,
    emit_wire_received as _emit_wire_received,
    _emit_exchange_ready,
    _emit_ready,
    _emit_episode_close,
    _emit_knowledge_announcement,
    _emit_intent,
    _lifecycle_emit,
)
from SSTP.l9.grounding import receive_peer_turn as _receive_peer_turn

_LOGGER = logging.getLogger("sstp.l9")



# ── Session plan and errors ───────────────────────────────────────────────────


@dataclass
class SessionPlan:
    """Describes how a multi-phase session will be conducted.

    Carried on the wire opening intent and available via L9Session.plan.
    """
    phases: List[str] = field(default_factory=lambda: ["team_process", "taskwork", "task"])
    subprotocol: str = "SIEP"
    contingency: str = "CIP"


class SessionAbortedError(RuntimeError):
    """Raised when a session phase fails to reach commit before close."""

    def __init__(self, phase: str, resolution_label: str) -> None:
        self.phase = phase
        self.resolution_label = resolution_label
        super().__init__(
            f"Session aborted at phase={phase!r} resolution={resolution_label!r}"
        )


class PlanAdherenceError(RuntimeError):
    """Raised by a participant that receives a message violating the agreed SessionPlan."""

    def __init__(self, agent_id: str, violation: str) -> None:
        self.agent_id = agent_id
        self.violation = violation
        super().__init__(f"plan adherence violation by {agent_id!r}: {violation}")


# ── Prior representation ──────────────────────────────────────────────────────


@dataclass
class AgentPrior:
    """Agent-local prior belief for a concept."""
    confidence: float
    episode_count: int = 0
    specialty_match: float = 1.0


@dataclass
class TeamPrior:
    """Team-level prior from TeamEpistemicMemory."""
    confidence: float
    provenance_weight: float
    episode_count: int
    source_episode: Optional[str] = None


def blend_prior(
    agent: Optional[AgentPrior],
    team: Optional[TeamPrior],
) -> float:
    """Blend agent and team priors into a single prior for episode open.

    Weight formula:
        w_team  = team.episode_count * team.provenance_weight
        w_agent = agent.episode_count * agent.specialty_match
        prior   = (w_agent * agent.confidence + w_team * team.confidence) / (w_agent + w_team)

    Falls back to 0.5 when both are absent.
    """
    w_team = (team.episode_count * team.provenance_weight) if team else 0.0
    w_agent = (agent.episode_count * agent.specialty_match) if agent else 0.0
    total = w_team + w_agent
    if total <= 0.0:
        return 0.5
    agent_conf = agent.confidence if agent else 0.5
    team_conf = team.confidence if team else 0.5
    return (w_agent * agent_conf + w_team * team_conf) / total


# ── Module-level protocol helpers ─────────────────────────────────────────────


def _safe_tom_assess(
    tom_engine: Any,
    utterance: str,
    speaker: str,
    listener: str,
    task_goal: str,
    use_case: str,
    prior_utterance: str = "",
    belief_store: Any = None,
    concept_id: str = "",
) -> Dict[str, Any]:
    """Call assess_utterance on the listener's ToM agent; return {} on failure or skip."""
    if tom_engine is None:
        return {}
    # Protocol coordination tokens carry no clinical content — skip assessment.
    if utterance.startswith(("process_proposal:", "process_accepted:", "process_challenged:")):
        return {}
    try:
        listener_tom = tom_engine.agent(listener)
        return listener_tom.assess_utterance(
            utterance=utterance,
            task_goal=task_goal,
            speaker=speaker,
            listener=listener,
            listener_prior_utterance=prior_utterance or None,
            belief_store=belief_store,
            concept_id=concept_id,
            use_case=use_case,
        )
    except Exception as exc:
        _LOGGER.warning(
            "tom.assess_utterance failed speaker=%s listener=%s err=%s", speaker, listener, exc
        )
        return {}


def _handle_contingency(
    bus: Any,
    tom_engine: Any,
    coordinator_id: str,
    agent_id: str,
    episode_id: str,
    concept_id: str,
    utterance: str,
    posterior: float,
    evidence: Optional[List[str]],
    task_goal: str,
    original_msg_id: str,
    assessment: Dict[str, Any],
    belief_store: Any = None,
) -> None:
    """Drive epistemic_clarification → taskwork_result → re-assess → repair_resolved."""
    ambiguity_score = float(assessment.get("ambiguity_score", 0.0))
    critique = str(assessment.get("critique", ""))
    clarification_request = (
        f"Clarification requested for {agent_id} assertion on {concept_id}: "
        f"ambiguity_score={ambiguity_score:.2f} critique={critique or 'grounding_failure'}"
    )

    clarif_hdr = _emit_epistemic_clarification(
        bus,
        sender=coordinator_id,
        receiver=agent_id,
        target_message_id=original_msg_id,
        reason=f"ambiguous_taskwork:score={ambiguity_score:.2f}",
        episode_id=episode_id,
    )

    _evidence = evidence or []
    clarification_text = (
        str(utterance)
        + (f" Supporting evidence: {', '.join(str(e) for e in _evidence[:3])}." if _evidence else "")
    ).strip()
    if not clarification_text:
        clarification_text = f"Reaffirming: {concept_id} posterior={posterior:.2f}"

    _emit_taskwork_result(
        bus,
        sender=agent_id,
        receiver=coordinator_id,
        utterance=clarification_text,
        concept_id=concept_id,
        posterior=posterior,
        episode_id=episode_id,
    )

    clarif_assessment = _safe_tom_assess(
        tom_engine, clarification_text, agent_id, coordinator_id,
        task_goal, bus.use_case,
        prior_utterance=clarification_request,
        belief_store=belief_store,
        concept_id=concept_id,
    )

    resolution = (
        "resolved"
        if clarif_assessment.get("aligned") or not clarif_assessment.get("grounding_failure")
        else "partial"
    )
    _emit_repair_resolved(
        bus,
        sender=coordinator_id,
        receiver=agent_id,
        utterance=f"contingency_resolved:{concept_id}:{resolution}",
        parent_id=clarif_hdr["message"]["id"],
        episode_id=episode_id,
    )
    _LOGGER.debug(
        "taskwork.contingency_resolved agent=%s concept=%s resolution=%s",
        agent_id, concept_id, resolution,
    )


# ── Episode ───────────────────────────────────────────────────────────────────


class Episode:
    """Application-facing handle for a single L9 coordination episode.

    All protocol mechanics are internal. Application agents only call:
    - :meth:`say` — substantive contribution (kind=exchange)
    - :meth:`done` — standalone done signal (kind=commit:ready)
    - :meth:`dispute` — raise a grounding problem (kind=contingency)
    - :meth:`resolve` — close a contingency branch (kind=commit:resolved)
    - :meth:`close` — initiator closes the episode (kind=commit:converged/rejected)
    - :meth:`announce` — initiator writes a knowledge announcement (kind=knowledge)

    :attr:`prior` is the blended prior set at episode open/join. It is
    immutable once set.
    """

    def __init__(
        self,
        bus: NetworkHandle,
        agent_id: str,
        concept_id: str,
        episode_id: str,
        initiator: bool = False,
        group: Optional[List[str]] = None,
        prior: float = 0.5,
    ) -> None:
        self._bus = bus
        self._agent_id = agent_id
        self._concept_id = concept_id
        self._episode_id = episode_id
        self._initiator = initiator
        self._group = list(group or [])
        self._prior = prior
        self._done_agents: Dict[str, float] = {}
        self._open_contingencies: Dict[str, str] = {}
        self._commit_message_id: Optional[str] = None
        self._mpc: Optional[float] = None
        self._gar: Optional[float] = None
        self._scr: Optional[float] = None
        self._last_message_id: Optional[str] = None

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def prior(self) -> float:
        """Blended prior at episode open. Immutable."""
        return self._prior

    @property
    def concept_id(self) -> str:
        return self._concept_id

    @property
    def episode_id(self) -> str:
        return self._episode_id

    @property
    def mpc(self) -> Optional[float]:
        """Mean position confidence — available after close()."""
        return self._mpc

    @property
    def gar(self) -> Optional[float]:
        """Genuine agreement ratio — available after close()."""
        return self._gar

    @property
    def scr(self) -> Optional[float]:
        """Social compliance ratio — available after close()."""
        return self._scr

    # ── Application API ────────────────────────────────────────────────────

    def say(
        self,
        utterance: str,
        posterior: float,
        *,
        final: bool = False,
        evidence: Optional[List[str]] = None,
        addresses_evidence: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        rationale: str = "",
        thought_summary: str = "",
    ) -> str:
        """Emit a substantive contribution.

        ``final=False`` → kind=exchange
        ``final=True``  → kind=exchange, subkind=ready (final argument + done signal)
        ``rationale`` and ``thought_summary`` land in payload[type=utterance].
        Returns the new message id.
        """
        if final:
            h = _emit_exchange_ready(
                self._bus,
                speaker=self._agent_id,
                listener=None,
                utterance=utterance,
                posterior=posterior,
                concept_id=self._concept_id,
                evidence=evidence,
                addresses_evidence=addresses_evidence,
                parent_id=parent_id or self._last_message_id,
                episode_id=self._episode_id,
                rationale=rationale,
                thought_summary=thought_summary,
            )
            self._done_agents[self._agent_id] = posterior
        else:
            h = _emit_grounding_turn(
                self._bus,
                speaker=self._agent_id,
                listener=None,
                utterance=utterance,
                concept_id=self._concept_id,
                posterior=posterior,
                evidence=evidence,
                addresses_evidence=addresses_evidence,
                parent_id=parent_id or self._last_message_id,
                episode_id=self._episode_id,
                rationale=rationale,
                thought_summary=thought_summary,
            )
        self._last_message_id = h["message"]["id"]
        return self._last_message_id

    def done(self, posterior: float) -> str:
        """Emit a standalone done signal — kind=commit:ready, no further content.

        Returns the new message id.
        """
        h = _emit_ready(
            self._bus,
            sender=self._agent_id,
            receiver=None,
            posterior=posterior,
            concept_id=self._concept_id,
            parent_id=self._last_message_id,
            episode_id=self._episode_id,
        )
        self._done_agents[self._agent_id] = posterior
        self._last_message_id = h["message"]["id"]
        return self._last_message_id

    def dispute(self, message_id: str, reason: str) -> str:
        """Raise a grounding problem — kind=contingency.

        Suspends this agent's done signal until :meth:`resolve` is called.
        Returns the contingency message id.
        """
        if self._agent_id in self._done_agents:
            del self._done_agents[self._agent_id]
        h = _emit_semantic_repair(
            self._bus,
            sender=self._agent_id,
            receiver=None,
            target_message_id=message_id,
            repair_reason=reason,
            episode_id=self._episode_id,
        )
        contingency_id = h["message"]["id"]
        self._open_contingencies[contingency_id] = message_id
        self._last_message_id = contingency_id
        return contingency_id

    def resolve(self, contingency_id: str) -> str:
        """Close a contingency branch — kind=commit:resolved.

        Must be called by the same agent that called :meth:`dispute`.
        Returns the commit message id.
        """
        if contingency_id not in self._open_contingencies:
            raise ValueError(f"No open contingency with id {contingency_id!r}")
        from SSTP.subprotocol.siep.src.epistemic.vocabulary import SpeechAct, EpistemicState
        with _lifecycle_emit(self._bus):
            h = _emit_peer_turn(
                self._bus,
                sender=self._agent_id,
                receiver=None,
                utterance=f"repair_verified:contingency={contingency_id}",
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                kind_override="commit:resolved",
                parent_id=contingency_id,
                episode_id=self._episode_id,
            )
        del self._open_contingencies[contingency_id]
        self._last_message_id = h["message"]["id"]
        return self._last_message_id

    def close(
        self,
        *,
        rationale: str = "",
        thought_summary: str = "",
        summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Initiator closes the episode.

        Emits kind=commit:converged (MPC >= 0.5) or kind=commit:rejected.
        Raises if open contingencies exist or not all group members have signalled done.
        After close(), :attr:`mpc`, :attr:`gar`, :attr:`scr` are available.
        Returns the commit message id.
        """
        if not self._initiator:
            raise RuntimeError("Only the episode initiator can call close()")
        if self._open_contingencies:
            raise RuntimeError(
                f"Cannot close episode with open contingencies: {list(self._open_contingencies)}"
            )
        missing = [a for a in self._group if a not in self._done_agents and a != self._agent_id]
        if missing:
            raise RuntimeError(
                f"Cannot close episode — waiting for done signals from: {missing}"
            )

        all_posteriors = list(self._done_agents.values())
        mpc = sum(all_posteriors) / len(all_posteriors) if all_posteriors else 0.5
        accepted = mpc >= 0.5

        self._mpc = mpc
        self._gar = 1.0
        self._scr = 0.0

        h = _emit_episode_close(
            self._bus,
            coordinator=self._agent_id,
            subject=self._concept_id,
            accepted=accepted,
            episode_id=self._episode_id,
            rationale=rationale,
            thought_summary=thought_summary,
            summary=summary,
            recipients=self._group or None,
        )
        self._commit_message_id = h["message"]["id"]
        self._last_message_id = self._commit_message_id
        return self._commit_message_id

    def announce(
        self,
        concept_id: str,
        posterior: float,
        gar: float,
        scr: float,
    ) -> str:
        """Write a knowledge announcement after close().

        Emits kind=knowledge, parents=[commit message id], routed to
        team-memory. Returns the knowledge message id.
        """
        if self._commit_message_id is None:
            raise RuntimeError("Cannot announce before close()")
        provenance_weight = (1.0 - scr) * gar
        h = _emit_knowledge_announcement(
            self._bus,
            sender=self._agent_id,
            concept_id=concept_id,
            posterior=posterior,
            gar=gar,
            scr=scr,
            provenance_weight=provenance_weight,
            commit_message_id=self._commit_message_id or "",
            revision_cause="converged_episode",
            episode_id=self._episode_id,
        )
        self._last_message_id = h["message"]["id"]
        return self._last_message_id

    # ── Group management ───────────────────────────────────────────────────

    def _record_done(self, agent_id: str, posterior: float) -> None:
        """Called externally when a done signal arrives from a group member."""
        self._done_agents[agent_id] = posterior

    # ── Internal — set by TaskEpisode after negotiation ──────────────────

    def _set_commit(self, commit_message_id: str, mpc: float, gar: float, scr: float) -> None:
        """Record commit result without emitting — used by TaskEpisode after StarNegotiation."""
        self._commit_message_id = commit_message_id
        self._mpc = mpc
        self._gar = gar
        self._scr = scr
        self._last_message_id = commit_message_id


# ── TaskEpisode (SIEP) ───────────────────────────────────────────────────────


class TaskEpisode(Episode):
    """Application-facing handle for a SIEP task episode (Episode C).

    Returned by :meth:`L9.open_task`. Extends :class:`Episode` with
    :meth:`run` which executes the full SIEP star negotiation loop
    (including CIP grounding gates, ToM predictions, Bayesian belief
    revision, GAR/SCR/MPC computation, and convergence/knowledge emit)
    inside the package boundary.

    The orchestrator's view::

        task_ep = ctrl_l9.open_task(
            concept_id="urn:concept:healthcare:drug_interaction",
            group=all_specialist_ids,
            convergence_store=..., semantic_rule_store=...,
            tom_engine=..., repair_fn=...,
        )
        task_ep.run(
            controller_position=controller_position,
            specialist_positions=all_positions,
            task_goal=task_goal,
            accept_threshold=0.1,
            max_rounds=2,
        )
        task_ep.announce(
            concept_id=task_ep.winning_position_key,
            posterior=task_ep.mpc, gar=task_ep.gar, scr=task_ep.scr,
        )

    After :meth:`run`:
    - :attr:`mpc`, :attr:`gar`, :attr:`scr` — convergence metrics
    - :attr:`winning_position` — the winning position dict
    - :attr:`winning_position_key` — ``str`` concept key from the winning position
    - :attr:`resolution_label` — ``"consensus"``, ``"majority"``, etc.
    """

    def __init__(
        self,
        bus: NetworkHandle,
        agent_id: str,
        concept_id: str,
        episode_id: str,
        group: Optional[List[str]] = None,
        prior: float = 0.5,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        tom_engine: Any = None,
        repair_fn: Any = None,
        task_name: str = "task",
        pivot_fn: Optional[Callable] = None,
    ) -> None:
        super().__init__(
            bus=bus,
            agent_id=agent_id,
            concept_id=concept_id,
            episode_id=episode_id,
            initiator=True,
            group=group,
            prior=prior,
        )
        self._convergence_store = convergence_store
        self._semantic_rule_store = semantic_rule_store
        self._tom_engine = tom_engine
        self._repair_fn = repair_fn
        self._task_name = task_name
        self._pivot_fn = pivot_fn
        self._winning_position: Any = None
        self._resolution_label: Optional[str] = None

    @property
    def winning_position(self) -> Any:
        """Winning position dict — available after run()."""
        return self._winning_position

    @property
    def winning_position_key(self) -> str:
        """Concept key string from the winning position — available after run()."""
        from SSTP.subprotocol.siep.src.negotiation import _position_key as _pk
        return _pk(self._winning_position) if self._winning_position is not None else ""

    @property
    def resolution_label(self) -> Optional[str]:
        """Resolution label — available after run()."""
        return self._resolution_label

    def run(
        self,
        controller_position: Dict[str, Any],
        specialist_positions: Dict[str, Any],
        task_goal: str = "",
        accept_threshold: float = 0.1,
        max_rounds: int = 2,
        max_extra_rounds: int = 3,
    ) -> None:
        """Execute the SIEP star negotiation and close the episode.

        On return, :attr:`mpc`, :attr:`gar`, :attr:`scr`,
        :attr:`winning_position`, :attr:`winning_position_key`,
        and :attr:`resolution_label` are all set.

        The commit:converged and SemanticRule recording are handled inside
        StarNegotiation; this method records the results on the episode so
        that announce() can be called immediately afterward.
        """
        from SSTP.subprotocol.siep.src.panel import NegotiationContext
        from SSTP.subprotocol.siep.src.negotiation import StarNegotiator

        context = NegotiationContext(
            panel_name=self._task_name,
            use_case=self._bus.use_case,
            tom_engine=self._tom_engine,
            repair_fn=self._repair_fn,
            convergence_store=self._convergence_store,
            semantic_rule_store=self._semantic_rule_store,
        )

        star = StarNegotiator(
            context,
            self._bus,
            panel_name=self._task_name,
            pivot_fn=self._pivot_fn,
        )
        winning_position, resolution_label = star.run(
            controller_id=self._agent_id,
            member_ids=list(self._group),
            controller_position=controller_position,
            specialist_positions=specialist_positions,
            task_goal=task_goal,
            accept_threshold=accept_threshold,
            max_rounds=max_rounds,
            max_extra_rounds=max_extra_rounds,
        )

        self._winning_position = winning_position
        self._resolution_label = resolution_label

        commit_id: Optional[str] = None
        for msg in reversed(self._bus.messages):
            if msg.get("kind") == "commit" and msg.get("subkind") == "converged":
                commit_id = msg.get("message", {}).get("id")
                break

        mpc, gar, scr = 0.5, 1.0, 0.0
        for msg in reversed(self._bus.messages):
            for part in msg.get("payload") or []:
                if part.get("type") == "snp-convergence":
                    content = part.get("content") or {}
                    mpc = float(content.get("mpc", 0.5))
                    gar = float(content.get("gar", 1.0))
                    scr = float(content.get("scr", 0.0))
                    break
            else:
                continue
            break

        if commit_id:
            self._set_commit(commit_id, mpc, gar, scr)
        else:
            self._mpc = mpc
            self._gar = gar
            self._scr = scr

    def close(self, **kwargs: Any) -> str:
        raise RuntimeError(
            "TaskEpisode does not support close() — the task loop calls it internally. "
            "Call run() then announce()."
        )

    def say(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("TaskEpisode does not support say() — use run() instead.")

    def done(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("TaskEpisode does not support done() — use run() instead.")


# ── TeamProcessEpisode ────────────────────────────────────────────────────────


class TeamProcessEpisode(Episode):
    """Application-facing handle for a team-process episode (Episode A).

    Returned by :meth:`L9.open_team_process`. Extends :class:`Episode` with
    :meth:`run` which executes the proposal/acceptance loop and ToM
    assessments for all group members inside the package boundary.

    The orchestrator's view::

        tp_ep = ctrl_l9.open_team_process(
            concept_id=patient_id,
            group=all_ids,
            task_goal=task_goal,
        )
        tp_ep.run()
        tp_ep.close(rationale=..., thought_summary=...)
    """

    def __init__(
        self,
        bus: NetworkHandle,
        agent_id: str,
        concept_id: str,
        episode_id: str,
        group: Optional[List[str]] = None,
        prior: float = 0.5,
        tom_engine: Any = None,
        task_goal: str = "",
        team_process: Optional[Dict[str, Any]] = None,
        pivot_fn: Optional[Callable] = None,
        commit_fn: Optional[Callable] = None,
        repair_fn: Optional[Callable] = None,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
    ) -> None:
        super().__init__(
            bus=bus,
            agent_id=agent_id,
            concept_id=concept_id,
            episode_id=episode_id,
            initiator=True,
            group=group,
            prior=prior,
        )
        self._tom_engine = tom_engine
        self._task_goal = task_goal
        self._team_process = team_process
        self._pivot_fn = pivot_fn
        self._commit_fn = commit_fn
        self._repair_fn = repair_fn
        self._convergence_store = convergence_store
        self._semantic_rule_store = semantic_rule_store

    def run(self) -> None:
        """Execute TP governance debate (NegotiationContext + StarNegotiator).

        The controller's opening position carries ``team_process_terms`` (the full
        governance dict).  All specialists start from the same position (no independent
        governance prior).  StarNegotiation drives the round loop: each specialist
        calls ``accept_or_counter_fn``; if counters exist the controller calls
        ``pivot_fn`` to revise terms.  On convergence (or timeout), ``commit_fn`` is
        called with the winning position so callers can store ``process_params``.
        """
        from SSTP.subprotocol.siep.src.panel import NegotiationContext
        from SSTP.subprotocol.siep.src.negotiation import StarNegotiator

        context = NegotiationContext(
            panel_name="team_process",
            use_case=self._bus.use_case,
            tom_engine=self._tom_engine,
            repair_fn=self._repair_fn,
            convergence_store=self._convergence_store,
            semantic_rule_store=self._semantic_rule_store,
        )

        _tp_terms = self._team_process or {}
        _tp_rationale = (
            f"Proposing governance terms for this session: "
            f"{_tp_terms.get('debate_format', 'structured negotiation protocol')}. "
            f"Contingency rule: {_tp_terms.get('contingency_rules', {}).get('deadlock_rule', 'casting_vote')}."
        )
        controller_position: Dict[str, Any] = {
            "decision_key": "team_process",
            "confidence": 0.9,
            "team_process_terms": _tp_terms,
            "rationale": _tp_rationale,
        }
        specialist_positions = {sid: dict(controller_position) for sid in self._group}

        star = StarNegotiator(
            context,
            self._bus,
            panel_name="team_process",
            pivot_fn=self._pivot_fn,
        )
        winning_position, resolution_label = star.run(
            controller_id=self._agent_id,
            member_ids=list(self._group),
            controller_position=controller_position,
            specialist_positions=specialist_positions,
            task_goal=self._task_goal,
            accept_threshold=0.05,
            max_rounds=2,
        )

        self._winning_position = winning_position
        self._resolution_label = resolution_label

        # Extract mpc/gar/scr from commit:converged payload (same pattern as TaskEpisode)
        mpc, gar, scr = 0.5, 1.0, 0.0
        for msg in reversed(self._bus.messages):
            for part in msg.get("payload") or []:
                if part.get("type") == "snp-convergence":
                    content = part.get("content") or {}
                    mpc = float(content.get("mpc", 0.5))
                    gar = float(content.get("gar", 1.0))
                    scr = float(content.get("scr", 0.0))
                    break
            else:
                continue
            break
        self._mpc, self._gar, self._scr = mpc, gar, scr

        if self._commit_fn is not None:
            self._commit_fn(winning_position, resolution_label)

        for sid in self._group:
            self._record_done(sid, 1.0)

    def close(self, **kwargs: Any) -> str:
        if self._winning_position and "summary" not in kwargs:
            kwargs["summary"] = self._winning_position
        return super().close(**kwargs)

    def say(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("TeamProcessEpisode does not support say() — use run() instead.")

    def done(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("TeamProcessEpisode does not support done() — use run() instead.")



# ── L9 ────────────────────────────────────────────────────────────────────────


class L9:
    """Entry point for application agents.

    Encapsulates MessageBus and TeamEpistemicMemory access. Application agents
    call :meth:`open_team_process`, :meth:`open_taskwork`, :meth:`open_task`,
    :meth:`open` (generic CIP), or register :meth:`on_intent` handlers.
    They never interact with the bus directly.

    ``tom_engine`` and ``task_goal`` are injected once at construction and
    forwarded to all episode subclasses automatically.
    """

    def __init__(
        self,
        bus: NetworkHandle,
        agent_id: str,
        belief_store: Any = None,
        peer_store: Any = None,
        llm_factory: Optional[Callable] = None,
        task_goal: str = "",
        peer_descriptions: Optional[Dict[str, str]] = None,
    ) -> None:
        self._bus = bus
        self._agent_id = agent_id
        self._belief_store = belief_store
        self._peer_store = peer_store
        self._task_goal = task_goal
        self._peer_descriptions: Dict[str, str] = peer_descriptions or {}
        self._intent_handler: Optional[Callable] = None
        self._debate_round_handler: Optional[Callable] = None
        if llm_factory is not None:
            from SSTP.subprotocol.siep.src.tomcore.cognition import TheoryOfMindEngine
            self._tom_engine: Any = TheoryOfMindEngine(llm_factory=llm_factory)
        else:
            self._tom_engine = None

    def _seed_tom_peers(self, group: List[str], task_goal: str) -> None:
        """Seed the controller's ToM peer models for all group members.

        Called internally by open_team_process and open_taskwork so the
        caller never needs to touch tom_engine directly.
        """
        if self._tom_engine is None or not self._peer_descriptions:
            return
        ctrl_tom = self._tom_engine.agent(self._agent_id)
        for peer_id in group:
            desc = self._peer_descriptions.get(peer_id)
            if desc is None:
                continue
            try:
                ctrl_tom.seed_peer(peer_id, desc, {"task_goal": task_goal})
            except Exception as exc:
                import logging as _log
                _log.getLogger("ioc.l9").warning(
                    "L9._seed_tom_peers agent=%s peer=%s: %s", self._agent_id, peer_id, exc
                )

    # ── Episode lifecycle ──────────────────────────────────────────────────

    def open_team_process(
        self,
        concept_id: str,
        group: List[str],
        episode_id: Optional[str] = None,
        task_goal: str = "",
        rationale: str = "",
        thought_summary: str = "",
        team_process: Optional[Dict[str, Any]] = None,
        pivot_fn: Optional[Callable] = None,
        commit_fn: Optional[Callable] = None,
        repair_fn: Optional[Callable] = None,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
    ) -> TeamProcessEpisode:
        """Open a team-process episode as initiator.

        Emits kind=intent. Returns a :class:`TeamProcessEpisode`; call
        :meth:`TeamProcessEpisode.run` to execute the SIEP governance debate,
        then :meth:`Episode.close`.

        The per-member accept/counter decision is owned by each specialist via
        their ``on_debate_round`` hook — no callback needed here.

        ``pivot_fn(ctrl_pos, counter_list, accept_list, task_goal)``
            — coordinator revises governance terms in response to counters.
        ``commit_fn(winning_position, resolution_label)``
            — called after SIEP convergence; store process_params per specialist.
        """
        self._seed_tom_peers(group, task_goal or self._task_goal)
        team_prior_obj = self._get_team_prior(concept_id, convergence_store=convergence_store)
        agent_prior_obj = self._get_agent_prior(concept_id)
        blended = blend_prior(agent_prior_obj, team_prior_obj)

        eid = episode_id or (
            f"urn:ioc:{self._bus.use_case}:tp"
            f":{concept_id.replace(':', '-')}:{int(time.time() * 1000)}"
        )

        return TeamProcessEpisode(
            bus=self._bus,
            agent_id=self._agent_id,
            concept_id=concept_id,
            episode_id=eid,
            group=group,
            prior=blended,
            tom_engine=self._tom_engine,
            task_goal=task_goal or self._task_goal,
            team_process=team_process,
            pivot_fn=pivot_fn,
            commit_fn=commit_fn,
            repair_fn=repair_fn,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
        )

    def open_taskwork(
        self,
        concept_id: str,
        group: List[str],
        episode_id: Optional[str] = None,
        task_goal: str = "",
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        repair_fn: Any = None,
        pivot_fn: Optional[Callable] = None,
    ) -> "TaskEpisode":
        """Open a taskwork SIEP episode as initiator.

        Taskwork is a SIEP debate on the task framing and individual priors.
        Each specialist independently queries team-memory for its prior in
        its _on_debate_round handler.  Returns a :class:`TaskEpisode` with a
        :tw-suffixed episode id; call :meth:`TaskEpisode.run` with the
        coordinator position and default specialist positions.
        """
        self._seed_tom_peers(group, task_goal or self._task_goal)

        eid = episode_id or (
            f"urn:ioc:{self._bus.use_case}:tw"
            f":{concept_id.replace(':', '-')}:{int(time.time() * 1000)}"
        )
        if not eid.endswith(":tw"):
            eid = f"{eid}:tw" if ":tw" not in eid else eid

        return TaskEpisode(
            bus=self._bus,
            agent_id=self._agent_id,
            concept_id=concept_id,
            episode_id=eid,
            group=group,
            prior=0.5,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
            tom_engine=self._tom_engine,
            repair_fn=repair_fn,
            task_name="taskwork",
            pivot_fn=pivot_fn,
        )

    def open(
        self,
        concept_id: str,
        group: List[str],
        episode_id: Optional[str] = None,
        team_process: Optional[Dict[str, Any]] = None,
        rationale: str = "",
        thought_summary: str = "",
    ) -> Episode:
        """Open a generic CIP coordination episode as initiator.

        1. Looks up team prior from TeamEpistemicMemory.
        2. Reads agent prior from belief_store.
        3. Blends prior.
        4. Emits kind=intent with team_prior (and optional team_process) in payload.
        5. Returns Episode with .prior set.

        ``team_process`` is forwarded as payload[type=team_process] on the intent.
        ``rationale`` and ``thought_summary`` go into payload[type=utterance].
        """
        team_prior_obj = self._get_team_prior(concept_id, convergence_store=convergence_store)
        agent_prior_obj = self._get_agent_prior(concept_id)
        blended = blend_prior(agent_prior_obj, team_prior_obj)

        eid = episode_id or (
            f"urn:ioc:{self._bus.use_case}:episode"
            f":{concept_id.replace(':', '-')}:{int(time.time() * 1000)}"
        )

        team_prior_payload: Optional[Dict[str, Any]] = None
        if team_prior_obj:
            team_prior_payload = {
                "concept_id": concept_id,
                "confidence": team_prior_obj.confidence,
                "provenance_weight": team_prior_obj.provenance_weight,
                "episode_count": team_prior_obj.episode_count,
            }

        _emit_intent(self._bus,
            sender=self._agent_id,
            receiver=None,
            subject=concept_id,
            episode_id=eid,
            team_prior=team_prior_payload,
            team_process=team_process,
            rationale=rationale,
            thought_summary=thought_summary,
            recipients=group,
        )

        return Episode(
            bus=self._bus,
            agent_id=self._agent_id,
            concept_id=concept_id,
            episode_id=eid,
            initiator=True,
            group=group,
            prior=blended,
        )

    def open_task(
        self,
        concept_id: str,
        group: List[str],
        episode_id: Optional[str] = None,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        tom_engine: Any = None,
        repair_fn: Any = None,
        task_name: str = "task",
        pivot_fn: Optional[Callable] = None,
    ) -> "TaskEpisode":
        """Open a SIEP task episode as initiator.

        Returns a :class:`TaskEpisode`. Call :meth:`TaskEpisode.run` to
        execute the negotiation, then :meth:`Episode.announce` to write the
        knowledge outcome.

        Emits kind=intent on the outer :t episode to all group members before
        the inner SIEP panel opens inside TaskEpisode.run().
        """
        team_prior_obj = self._get_team_prior(concept_id, convergence_store=convergence_store)
        agent_prior_obj = self._get_agent_prior(concept_id)
        blended = blend_prior(agent_prior_obj, team_prior_obj)

        eid = episode_id or (
            f"urn:ioc:{self._bus.use_case}:task"
            f":{concept_id.replace(':', '-')}:{int(time.time() * 1000)}:t"
        )

        return TaskEpisode(
            bus=self._bus,
            agent_id=self._agent_id,
            concept_id=concept_id,
            episode_id=eid,
            group=group,
            prior=blended,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
            tom_engine=tom_engine or self._tom_engine,
            repair_fn=repair_fn,
            task_name=task_name,
            pivot_fn=pivot_fn,
        )

    # ── Convenience wrappers: open + run + close in one call ─────────────

    def run_team_process(
        self,
        concept_id: str,
        group: List[str],
        episode_id: Optional[str] = None,
        task_goal: str = "",
        rationale: str = "",
        thought_summary: str = "",
        team_process: Optional[Dict[str, Any]] = None,
        pivot_fn: Optional[Callable] = None,
        commit_fn: Optional[Callable] = None,
        repair_fn: Optional[Callable] = None,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
    ) -> "TeamProcessResult":
        """Open, run, and close a team-process episode in one call."""
        ep = self.open_team_process(
            concept_id=concept_id,
            group=group,
            episode_id=episode_id,
            task_goal=task_goal,
            rationale=rationale,
            thought_summary=thought_summary,
            team_process=team_process,
            pivot_fn=pivot_fn,
            commit_fn=commit_fn,
            repair_fn=repair_fn,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
        )
        ep.run()
        return TeamProcessResult(
            mpc=ep.mpc,
            gar=ep.gar,
            scr=ep.scr,
            winning_position=ep._winning_position or {},
            resolution_label=ep._resolution_label or "",
        )

    def run_taskwork(
        self,
        concept_id: str,
        group: List[str],
        controller_position: Dict[str, Any],
        specialist_positions: Dict[str, Any],
        episode_id: Optional[str] = None,
        task_goal: str = "",
        accept_threshold: float = 0.15,
        max_rounds: int = 2,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        repair_fn: Any = None,
        pivot_fn: Optional[Callable] = None,
    ) -> "TaskworkResult":
        """Open and run a taskwork SIEP debate in one call.

        Each specialist independently fetches its own prior from team-memory
        inside _on_debate_round for the :tw episode.  Returns specialist
        positions updated by the SIEP debate.
        """
        ep = self.open_taskwork(
            concept_id=concept_id,
            group=group,
            episode_id=episode_id,
            task_goal=task_goal,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
            repair_fn=repair_fn,
            pivot_fn=pivot_fn,
        )
        ep.run(
            controller_position=controller_position,
            specialist_positions=specialist_positions,
            task_goal=task_goal,
            accept_threshold=accept_threshold,
            max_rounds=max_rounds,
        )
        return TaskworkResult(
            specialist_positions=specialist_positions,
            winning_position=ep.winning_position or {},
            resolution_label=ep.resolution_label or "timeout_majority",
            episode_id=ep.episode_id,
            mpc=ep.mpc,
            gar=ep.gar,
            scr=ep.scr,
        )

    def run_task(
        self,
        concept_id: str,
        group: List[str],
        controller_position: Dict[str, Any],
        specialist_positions: Dict[str, Any],
        episode_id: Optional[str] = None,
        task_goal: str = "",
        accept_threshold: float = 0.1,
        max_rounds: int = 2,
        max_extra_rounds: int = 3,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        repair_fn: Any = None,
        task_name: str = "task",
        pivot_fn: Optional[Callable] = None,
    ) -> "TaskResult":
        """Open, run, and announce a SIEP task episode in one call."""
        ep = self.open_task(
            concept_id=concept_id,
            group=group,
            episode_id=episode_id,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
            repair_fn=repair_fn,
            task_name=task_name,
            pivot_fn=pivot_fn,
        )
        ep.run(
            controller_position=controller_position,
            specialist_positions=specialist_positions,
            task_goal=task_goal,
            accept_threshold=accept_threshold,
            max_rounds=max_rounds,
            max_extra_rounds=max_extra_rounds,
        )
        ep.announce(
            concept_id=ep.winning_position_key,
            posterior=ep.mpc,
            gar=ep.gar,
            scr=ep.scr,
        )
        return TaskResult(
            winning_position=ep.winning_position or {},
            winning_position_key=ep.winning_position_key,
            resolution_label=ep.resolution_label or "timeout_majority",
            episode_id=ep.episode_id,
            mpc=ep.mpc,
            gar=ep.gar,
            scr=ep.scr,
        )

    def announce_knowledge(
        self,
        concept_id: str,
        posterior: float,
        gar: float,
        scr: float,
        episode_id: Optional[str] = None,
    ) -> str:
        """Emit a standalone kind=knowledge announcement outside a task episode.

        Used when the coordinator has already-computed convergence results
        (e.g. from ConvergenceStore) and wants to write them to the wire
        without re-opening a task episode.  Returns the knowledge message id.
        """
        provenance_weight = round((1.0 - scr) * gar, 4)
        h = _emit_knowledge_announcement(
            self._bus,
            sender=self._agent_id,
            concept_id=concept_id,
            posterior=posterior,
            gar=gar,
            scr=scr,
            provenance_weight=provenance_weight,
            revision_cause="converged_episode",
            episode_id=episode_id,
        )
        return h["message"]["id"]

    def receive_peer_turn(
        self,
        envelope: Dict[str, Any],
        *,
        replica: Optional[Any] = None,
        belief_store: Optional[Any] = None,
        common_ground_store: Optional[Any] = None,
        use_case: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Verify CIP contingency for an inbound peer turn and update epistemic stores.

        Delegates to :func:`SSTP.l9.grounding.receive_peer_turn`.
        Returns None on success, or the emitted repair header on grounding failure.
        """
        return _receive_peer_turn(
            self._bus,
            envelope,
            replica=replica,
            belief_store=belief_store,
            common_ground_store=common_ground_store,
            use_case=use_case,
        )

    def join(self, intent_envelope: Dict[str, Any]) -> Episode:
        """Join an existing episode as a participant.

        1. Reads team_prior from intent payload.
        2. Reads agent prior from belief_store.
        3. Blends prior.
        4. Returns Episode with .prior set.

        The caller should then call episode.say(...) or episode.done(...).
        """
        payload = intent_envelope.get("payload", [])
        concept_id = None
        team_prior_payload = None
        team_process_payload: Optional[Dict[str, Any]] = None
        for part in payload:
            if part.get("type") == "utterance":
                content = part.get("content", "")
                if isinstance(content, str) and content.startswith("episode:open subject="):
                    concept_id = content[len("episode:open subject="):]
            elif part.get("type") == "team_prior":
                team_prior_payload = part.get("content", {})
            elif part.get("type") == "team_process":
                team_process_payload = part.get("content")

        concept_id = concept_id or ""
        episode_id = intent_envelope.get("message", {}).get("episode", "")

        team_prior_obj: Optional[TeamPrior] = None
        if team_prior_payload and team_prior_payload.get("found", True):
            team_prior_obj = TeamPrior(
                confidence=team_prior_payload.get("confidence", 0.5),
                provenance_weight=team_prior_payload.get("provenance_weight", 0.0),
                episode_count=team_prior_payload.get("episode_count", 0),
            )
        agent_prior_obj = self._get_agent_prior(concept_id)
        blended = blend_prior(agent_prior_obj, team_prior_obj)

        ep = Episode(
            bus=self._bus,
            agent_id=self._agent_id,
            concept_id=concept_id,
            episode_id=episode_id,
            initiator=False,
            prior=blended,
        )
        ep.team_process = team_process_payload  # type: ignore[attr-defined]
        return ep

    def on_intent(self, handler: Callable) -> Callable:
        """Decorator: register a handler called when an intent arrives.

        The handler receives an :class:`Episode` already joined. It should
        call ``episode.say(...)`` or ``episode.done(...)`` and return.

        Usage::

            @l9.on_intent
            def handle(episode: Episode) -> None:
                episode.say("My assessment.", posterior=0.71, final=True)
        """
        self._intent_handler = handler
        return handler

    def dispatch_intent(self, envelope: Dict[str, Any]) -> None:
        """Dispatch an incoming intent envelope to the registered handler."""
        if self._intent_handler is None:
            return
        episode = self.join(envelope)
        self._intent_handler(episode)

    # ── Participant-side CIP helpers ───────────────────────────────────────

    def receive(self, intent_envelope: Dict[str, Any]) -> Episode:
        """Join an episode from an incoming intent envelope (participant side)."""
        return self.join(intent_envelope)

    def send(
        self,
        episode: Episode,
        utterance: str,
        posterior: float,
        *,
        final: bool = False,
        rationale: str = "",
        thought_summary: str = "",
        evidence: Optional[List[str]] = None,
    ) -> str:
        """Emit via episode.say() (participant side). Returns message_id."""
        return episode.say(
            utterance, posterior,
            final=final, rationale=rationale,
            thought_summary=thought_summary,
            evidence=evidence or [],
        )

    # ── SIEP debate-round helpers (participant side) ───────────────────────

    def on_debate_round(self, handler: Callable) -> Callable:
        """Decorator: register a handler called for each SIEP debate round.

        The handler receives a :class:`DebateRoundEpisode` and must call
        ``round_ep.respond(operation, position)`` before returning.

        Usage::

            @l9.on_debate_round
            def handle_round(round_ep: DebateRoundEpisode) -> None:
                round_ep.respond("accept", round_ep.member_pos)
        """
        self._debate_round_handler = handler
        return handler

    def join_debate_round(self, ctx: "DebateRoundContext") -> "DebateRoundEpisode":
        """Create a DebateRoundEpisode for this specialist from the round context."""
        _, DebateRoundEpisodeCls = _get_debate_types()
        return DebateRoundEpisodeCls(ctx, self._agent_id)

    def dispatch_debate_round(self, ctx: "DebateRoundContext") -> "DebateRoundEpisode":
        """Dispatch a debate round to the registered handler; return the episode.

        If no handler is registered the episode is returned with respond() not
        yet called — the caller must call respond() directly.
        """
        round_ep = self.join_debate_round(ctx)
        if self._debate_round_handler is not None:
            self._debate_round_handler(round_ep)
        return round_ep

    # ── Session factory ────────────────────────────────────────────────────

    def open_session(
        self,
        session_id: str,
        concept_id: str,
        group: List[str],
        task_goal: str = "",
        session_plan: Optional["SessionPlan"] = None,
    ) -> "L9Session":
        """Emit the session-level SIEP opening intent and return an L9Session.

        The opening intent carries the :class:`SessionPlan` (phases, subprotocol,
        contingency protocol) as a payload part.  Each participant in *group*
        receives an exchange:received ACK on the same session URN immediately
        after.  Seeds ToM peer models for the full group.
        """
        self._seed_tom_peers(group, task_goal or self._task_goal)
        plan = session_plan or SessionPlan()
        _emit_intent(
            self._bus,
            sender=self._agent_id,
            receiver=None,
            subject=concept_id,
            episode_id=session_id,
            rationale=task_goal or self._task_goal,
            thought_summary=(
                f"Opening session {session_id}: "
                f"phases={plan.phases} subprotocol={plan.subprotocol} "
                f"contingency={plan.contingency}"
            ),
            recipients=group,
            session_plan={
                "phases": plan.phases,
                "subprotocol": plan.subprotocol,
                "contingency": plan.contingency,
            },
            label="session:open",
        )
        # Each participant acknowledges the session plan (exchange:received).
        opening_header = self._bus.messages[-1]
        opening_msg_id = (opening_header.get("message") or {}).get("id", "")
        for recipient in group:
            _emit_wire_received(
                self._bus,
                msg_id=opening_msg_id,
                recipient_id=recipient,
                sender_id=self._agent_id,
                episode_id=session_id,
            )
        return L9Session(
            session_id=session_id,
            concept_id=concept_id,
            group=group,
            task_goal=task_goal or self._task_goal,
            plan=plan,
            _l9=self,
        )

    # ── Prior helpers ──────────────────────────────────────────────────────

    def _get_team_prior(
        self, concept_id: str, convergence_store: Any = None
    ) -> Optional[TeamPrior]:
        # Prefer direct store access — no bus involvement, no trace pollution.
        if convergence_store is not None:
            truth = convergence_store.latest(concept_id)
            if truth is None:
                return None
            gar = getattr(truth, "genuine_agreement_ratio", 0.0)
            scr = getattr(truth, "social_compliance_ratio", 0.0)
            posterior = getattr(truth, "consensus_posterior", 0.5)
            records = list(convergence_store.records() or [])
            episode_count = sum(1 for t in records if t.concept_id == concept_id)
            return TeamPrior(
                confidence=posterior,
                provenance_weight=round((1.0 - scr) * gar, 4),
                episode_count=episode_count,
            )
        return None

    def _get_agent_prior(self, concept_id: str) -> Optional[AgentPrior]:
        if self._belief_store is None:
            return None
        try:
            state = self._belief_store.get(self._agent_id, concept_id)
            if state is None:
                return None
            return AgentPrior(
                confidence=state.current_confidence,
                episode_count=getattr(state, "revision_count", 1),
                specialty_match=1.0,
            )
        except Exception:
            return None


def _get_debate_types() -> tuple:
    from SSTP.subprotocol.siep.src.panel import DebateRoundContext, DebateRoundEpisode
    return DebateRoundContext, DebateRoundEpisode


# Re-export so importers can do: from SSTP.l9.episode import DebateRoundContext
def __getattr__(name: str) -> Any:
    if name in ("DebateRoundContext", "DebateRoundEpisode"):
        ctx_cls, ep_cls = _get_debate_types()
        if name == "DebateRoundContext":
            return ctx_cls
        return ep_cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass
class TeamProcessResult:
    """Returned by :meth:`L9.run_team_process`."""
    mpc: float
    gar: float
    scr: float
    winning_position: Dict[str, Any]
    resolution_label: str


@dataclass
class TaskworkResult:
    """Returned by :meth:`L9.run_taskwork`."""
    specialist_positions: Dict[str, Any]
    winning_position: Dict[str, Any]
    resolution_label: str
    episode_id: str
    mpc: float
    gar: float
    scr: float


@dataclass
class TaskResult:
    """Returned by :meth:`L9.run_task`."""
    winning_position: Dict[str, Any]
    winning_position_key: str
    resolution_label: str
    episode_id: str
    mpc: float
    gar: float
    scr: float


class L9Session:
    """Ordered three-phase session: team-process → taskwork → task.

    Returned by :meth:`L9.open_session`. Holds the shared outer episode ID
    and forwards phase-scoped episode IDs to each run_* call automatically.
    Enforces sequencing: each phase must complete before the next begins.

    Usage::

        session = ctrl_l9.open_session(
            session_id=episode_id,
            concept_id=patient_id,
            group=all_ids,
            task_goal=session_objective,
        )
        session.run_team_process(team_process=..., pivot_fn=..., ...)
        tw_result = session.run_taskwork(
            controller_position=..., specialist_positions=..., ...
        )
        task_result = session.run_task(
            controller_position=..., specialist_positions=..., ...
        )
    """

    def __init__(
        self,
        session_id: str,
        concept_id: str,
        group: List[str],
        task_goal: str,
        _l9: "L9",
        plan: Optional["SessionPlan"] = None,
    ) -> None:
        self.session_id = session_id
        self.concept_id = concept_id
        self.group = group
        self.task_goal = task_goal
        self._l9 = _l9
        self.plan: SessionPlan = plan or SessionPlan()
        self._phase: str = ""  # "" | "tp" | "tw" | "t"

    _COMMIT_SUFFIXES = ("majority", "consensus", "casting_vote", "converged")

    @property
    def tp_episode_id(self) -> str:
        return f"{self.session_id}:tp"

    @property
    def tw_episode_id(self) -> str:
        return f"{self.session_id}:tw"

    @property
    def t_episode_id(self) -> str:
        return f"{self.session_id}:t"

    def run_team_process(
        self,
        *,
        team_process: Optional[Dict[str, Any]] = None,
        pivot_fn: Optional[Callable] = None,
        commit_fn: Optional[Callable] = None,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        repair_fn: Any = None,
        rationale: str = "",
        thought_summary: str = "",
    ) -> "TeamProcessResult":
        """Run the team-process phase. Must be called first."""
        if self._phase != "":
            raise RuntimeError("run_team_process must be the first phase")
        result = self._l9.run_team_process(
            concept_id=self.concept_id,
            group=self.group,
            episode_id=self.tp_episode_id,
            task_goal=self.task_goal,
            team_process=team_process,
            pivot_fn=pivot_fn,
            commit_fn=commit_fn,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
            repair_fn=repair_fn,
            rationale=rationale,
            thought_summary=thought_summary,
        )
        if not any(result.resolution_label.endswith(s) for s in self._COMMIT_SUFFIXES):
            raise SessionAbortedError("team_process", result.resolution_label)
        self._phase = "tp"
        return result

    def run_taskwork(
        self,
        controller_position: Dict[str, Any],
        specialist_positions: Dict[str, Any],
        *,
        accept_threshold: float = 0.15,
        max_rounds: int = 2,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        repair_fn: Any = None,
        pivot_fn: Optional[Callable] = None,
    ) -> "TaskworkResult":
        """Run the taskwork phase. Requires team-process to have completed."""
        if self._phase != "tp":
            raise RuntimeError("run_taskwork requires run_team_process to have completed")
        result = self._l9.run_taskwork(
            concept_id=self.concept_id,
            group=self.group,
            episode_id=self.tw_episode_id,
            controller_position=controller_position,
            specialist_positions=specialist_positions,
            task_goal=self.task_goal,
            accept_threshold=accept_threshold,
            max_rounds=max_rounds,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
            repair_fn=repair_fn,
            pivot_fn=pivot_fn,
        )
        if not any(result.resolution_label.endswith(s) for s in self._COMMIT_SUFFIXES):
            raise SessionAbortedError("taskwork", result.resolution_label)
        self._phase = "tw"
        return result

    def run_task(
        self,
        controller_position: Dict[str, Any],
        specialist_positions: Dict[str, Any],
        *,
        concept_id: Optional[str] = None,
        accept_threshold: float = 0.1,
        max_rounds: int = 2,
        max_extra_rounds: int = 3,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        repair_fn: Any = None,
        task_name: str = "task",
        pivot_fn: Optional[Callable] = None,
    ) -> "TaskResult":
        """Run the task debate phase. Requires taskwork to have completed."""
        if self._phase != "tw":
            raise RuntimeError("run_task requires run_taskwork to have completed")
        result = self._l9.run_task(
            concept_id=concept_id or self.concept_id,
            group=self.group,
            episode_id=self.t_episode_id,
            controller_position=controller_position,
            specialist_positions=specialist_positions,
            task_goal=self.task_goal,
            accept_threshold=accept_threshold,
            max_rounds=max_rounds,
            max_extra_rounds=max_extra_rounds,
            convergence_store=convergence_store,
            semantic_rule_store=semantic_rule_store,
            repair_fn=repair_fn,
            task_name=task_name,
            pivot_fn=pivot_fn,
        )
        if not any(result.resolution_label.endswith(s) for s in self._COMMIT_SUFFIXES):
            raise SessionAbortedError("task", result.resolution_label)
        self._phase = "t"
        _emit_episode_close(
            self._l9._bus,
            coordinator=self._l9._agent_id,
            subject=self.concept_id,
            accepted=True,
            episode_id=self.session_id,
            rationale=f"Session complete: {result.resolution_label}",
            recipients=self.group,
            label="session:close",
        )
        return result


__all__ = [
    "Episode", "TaskEpisode", "TeamProcessEpisode",
    "TaskworkParticipant", "L9", "L9Session", "blend_prior", "AgentPrior", "TeamPrior",
    "TeamProcessResult", "TaskworkResult", "TaskResult",
    "SessionPlan", "SessionAbortedError", "PlanAdherenceError",
    "DebateRoundContext", "DebateRoundEpisode",
]

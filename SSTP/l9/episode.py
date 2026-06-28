# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/l9/episode.py — Application-facing L9 Episode API.

Application writers import :class:`L9` and the relevant Episode subclass.
They never call ``AgentBus`` or any ``emit_*`` method directly.

Three episode kinds, each fully encapsulating its protocol mechanics::

    # Episode A — team process
    tp_ep = ctrl_l9.open_team_process(
        concept_id=patient_id, group=all_ids, agreement=agreement, task_goal=...
    )
    tp_ep.run()
    tp_ep.close(rationale=..., thought_summary=...)

    # Episode B — taskwork
    participants = [
        TaskworkParticipant(agent_id=..., utterance=..., posterior=...,
                            concept_id=..., belief_store=agent.belief_store),
        ...
    ]
    tw_ep = ctrl_l9.open_taskwork(
        concept_id=patient_id, group=all_ids, participants=participants, task_goal=...
    )
    tw_ep.run()
    tw_ep.close(rationale=..., thought_summary=...)

    # Episode C — SIEP panel
    task_ep = ctrl_l9.open_task(
        concept_id="concept:drug_interaction",
        group=all_ids,
        convergence_store=..., semantic_rule_store=...,
        peer_interaction_store=..., belief_store=...,
        tom_engine=..., repair_fn=...,
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

from SSTP.examples.hcpanel.agent_bus import AgentBus

_LOGGER = logging.getLogger("sstp.l9")


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


# ── Taskwork participant ──────────────────────────────────────────────────────


@dataclass
class TaskworkParticipant:
    """Data carrier for one specialist's contribution to a taskwork episode.

    Built by the orchestrator from domain position dicts. Passed to
    :meth:`L9.open_taskwork`; the resulting :class:`TaskworkEpisode` uses
    these fields inside :meth:`TaskworkEpisode.run`.
    """
    agent_id: str
    utterance: str
    posterior: float
    concept_id: str
    belief_store: Any = None
    thought_summary: str = ""
    evidence: Optional[List[str]] = field(default=None)


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

    clarif_hdr = bus.emit_epistemic_clarification(
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

    bus.emit_taskwork_result(
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
    bus.emit_repair_resolved(
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
        bus: AgentBus,
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
            h = self._bus._emit_exchange_ready(
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
            h = self._bus.emit_grounding_turn(
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
        h = self._bus._emit_ready(
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
        h = self._bus.emit_semantic_repair(
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
        with self._bus._lifecycle_emit():
            h = self._bus.emit_peer_turn(
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

        h = self._bus._emit_episode_close(
            coordinator=self._agent_id,
            subject=self._concept_id,
            accepted=accepted,
            episode_id=self._episode_id,
            rationale=rationale,
            thought_summary=thought_summary,
            summary=summary,
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
        team-epistemic-memory. Returns the knowledge message id.
        """
        if self._commit_message_id is None:
            raise RuntimeError("Cannot announce before close()")
        provenance_weight = (1.0 - scr) * gar
        h = self._bus._emit_knowledge_announcement(
            sender=self._agent_id,
            concept_id=concept_id,
            posterior=posterior,
            gar=gar,
            scr=scr,
            provenance_weight=provenance_weight,
            parent_id=self._commit_message_id,
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
            peer_interaction_store=..., belief_store=...,
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
    - :attr:`snp_trace` — SIEP messages from this task episode
    """

    def __init__(
        self,
        bus: AgentBus,
        agent_id: str,
        concept_id: str,
        episode_id: str,
        group: Optional[List[str]] = None,
        prior: float = 0.5,
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        peer_interaction_store: Any = None,
        belief_store: Any = None,
        tom_engine: Any = None,
        repair_fn: Any = None,
        task_name: str = "task",
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
        self._peer_interaction_store = peer_interaction_store
        self._siep_belief_store = belief_store
        self._tom_engine = tom_engine
        self._repair_fn = repair_fn
        self._task_name = task_name
        self._winning_position: Any = None
        self._resolution_label: Optional[str] = None
        self._snp_trace: List[Dict[str, Any]] = []

    @property
    def winning_position(self) -> Any:
        """Winning position dict — available after run()."""
        return self._winning_position

    @property
    def winning_position_key(self) -> str:
        """Concept key string from the winning position — available after run()."""
        from SSTP.examples.hcpanel.panel_bus import StarNegotiation
        return StarNegotiation._position_key(self._winning_position) if self._winning_position is not None else ""

    @property
    def resolution_label(self) -> Optional[str]:
        """Resolution label — available after run()."""
        return self._resolution_label

    @property
    def snp_trace(self) -> List[Dict[str, Any]]:
        """SIEP messages from this task episode — available after run()."""
        return self._snp_trace

    def run(
        self,
        controller_position: Dict[str, Any],
        specialist_positions: Dict[str, Any],
        task_goal: str = "",
        accept_threshold: float = 0.1,
        max_rounds: int = 2,
    ) -> None:
        """Execute the SIEP star negotiation and close the episode.

        On return, :attr:`mpc`, :attr:`gar`, :attr:`scr`,
        :attr:`winning_position`, :attr:`winning_position_key`,
        :attr:`resolution_label`, and :attr:`snp_trace` are all set.

        The commit:converged and SemanticRule recording are handled inside
        StarNegotiation; this method records the results on the episode so
        that announce() can be called immediately afterward.
        """
        from SSTP.examples.hcpanel.panel_bus import PanelBus, StarNegotiation

        panel_bus = PanelBus(
            panel_name=self._task_name,
            ie_bus=self._bus,
            use_case=self._bus.use_case,
            tom_engine=self._tom_engine,
            repair_fn=self._repair_fn,
            convergence_store=self._convergence_store,
            belief_store=self._siep_belief_store,
            semantic_rule_store=self._semantic_rule_store,
            peer_interaction_store=self._peer_interaction_store,
        )

        star = StarNegotiation(panel_bus, panel_name=self._task_name)
        winning_position, resolution_label, snp_trace = star.run(
            controller_id=self._agent_id,
            member_ids=list(self._group),
            controller_position=controller_position,
            specialist_positions=specialist_positions,
            task_goal=task_goal,
            accept_threshold=accept_threshold,
            max_rounds=max_rounds,
        )

        self._winning_position = winning_position
        self._resolution_label = resolution_label
        self._snp_trace = snp_trace

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
            agreement=agreement,
            task_goal=task_goal,
        )
        tp_ep.run()
        tp_ep.close(rationale=..., thought_summary=...)
    """

    def __init__(
        self,
        bus: AgentBus,
        agent_id: str,
        concept_id: str,
        episode_id: str,
        group: Optional[List[str]] = None,
        prior: float = 0.5,
        agreement: Any = None,
        tom_engine: Any = None,
        task_goal: str = "",
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
        self._agreement = agreement
        self._tom_engine = tom_engine
        self._task_goal = task_goal

    def run(self) -> None:
        """Emit process proposals and collect acceptances for all group members.

        ToM assessment is called per exchange but is a no-op for
        process_proposal:/process_accepted: prefixed utterances.
        """
        for specialist_id in self._group:
            prop_hdr = self._bus.emit_process_proposal(
                sender=self._agent_id,
                receiver=specialist_id,
                agreement=self._agreement,
                episode_id=self._episode_id,
            )
            prop_utterance = (prop_hdr.get("payload") or [{}])[0].get("content", "")
            _safe_tom_assess(
                self._tom_engine, prop_utterance,
                self._agent_id, specialist_id,
                self._task_goal, self._bus.use_case,
            )
            acc_hdr = self._bus.emit_process_acceptance(
                sender=specialist_id,
                receiver=self._agent_id,
                parent_id=prop_hdr["message"]["id"],
                episode_id=self._episode_id,
            )
            acc_utterance = (acc_hdr.get("payload") or [{}])[0].get("content", "")
            _safe_tom_assess(
                self._tom_engine, acc_utterance,
                specialist_id, self._agent_id,
                self._task_goal, self._bus.use_case,
                prior_utterance=prop_utterance,
            )
            self._record_done(specialist_id, 1.0)

    def say(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("TeamProcessEpisode does not support say() — use run() instead.")

    def done(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("TeamProcessEpisode does not support done() — use run() instead.")


# ── TaskworkEpisode ───────────────────────────────────────────────────────────


class TaskworkEpisode(Episode):
    """Application-facing handle for a taskwork episode (Episode B).

    Returned by :meth:`L9.open_taskwork`. Extends :class:`Episode` with
    :meth:`run` which executes belief seeding, exchange emission, ToM
    assessment, and contingency repair for each participant inside the
    package boundary.

    The orchestrator's view::

        participants = [
            TaskworkParticipant(
                agent_id=agent.agent_id,
                utterance=utterance,
                posterior=posterior,
                concept_id=concept_id,
                belief_store=agent.belief_store,
                thought_summary=thought,
            )
            for agent in all_specialists
        ]
        tw_ep = ctrl_l9.open_taskwork(
            concept_id=patient_id,
            group=all_ids,
            participants=participants,
            task_goal=task_goal,
        )
        tw_ep.run()
        tw_ep.close(rationale=..., thought_summary=...)
    """

    def __init__(
        self,
        bus: AgentBus,
        agent_id: str,
        concept_id: str,
        episode_id: str,
        group: Optional[List[str]] = None,
        prior: float = 0.5,
        participants: Optional[List[TaskworkParticipant]] = None,
        tom_engine: Any = None,
        coordinator_id: Optional[str] = None,
        task_goal: str = "",
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
        self._participants = participants or []
        self._tom_engine = tom_engine
        self._coordinator_id = coordinator_id or agent_id
        self._task_goal = task_goal

    def run(self) -> None:
        """Seed beliefs, emit exchanges, assess via ToM, repair if needed."""
        from SSTP.subprotocol.siep.src.epistemic.stores import BeliefRevision

        for p in self._participants:
            # Seed belief store with prior if not already populated
            if p.belief_store is not None:
                if not p.belief_store.current_belief(p.agent_id, p.concept_id, self._bus.use_case):
                    p.belief_store.set_prior(
                        p.agent_id, p.concept_id, self._bus.use_case, p.posterior, 1.0
                    )
                    p.belief_store.record_revision(
                        p.agent_id, p.concept_id, self._bus.use_case,
                        self._episode_id,
                        BeliefRevision(
                            revision_id=str(uuid.uuid4()),
                            timestamp_ms=int(time.time() * 1000),
                            episode_id=self._episode_id,
                            message_id=None,
                            confidence_before=p.posterior,
                            confidence_after=p.posterior,
                            cause="semantic_memory",
                            caused_by_agent=None,
                            argument_concept_ids=[p.concept_id],
                        ),
                        new_status="held",
                        new_public_confidence=p.posterior,
                    )

            # Emit exchange
            agent_ep = Episode(
                bus=self._bus,
                agent_id=p.agent_id,
                concept_id=p.concept_id,
                episode_id=self._episode_id,
                initiator=False,
            )
            msg_id = agent_ep.say(
                p.utterance,
                posterior=p.posterior,
                rationale=p.utterance,
                thought_summary=p.thought_summary,
                evidence=p.evidence,
            )

            # ToM assessment
            assessment = _safe_tom_assess(
                self._tom_engine, p.utterance,
                p.agent_id, self._coordinator_id,
                self._task_goal, self._bus.use_case,
                belief_store=p.belief_store,
                concept_id=p.concept_id,
            )

            # Contingency repair if grounding failed or utterance was ambiguous
            if assessment.get("ambiguous") or assessment.get("grounding_failure"):
                _handle_contingency(
                    bus=self._bus,
                    tom_engine=self._tom_engine,
                    coordinator_id=self._coordinator_id,
                    agent_id=p.agent_id,
                    episode_id=self._episode_id,
                    concept_id=p.concept_id,
                    utterance=p.utterance,
                    posterior=p.posterior,
                    evidence=p.evidence,
                    task_goal=self._task_goal,
                    original_msg_id=msg_id,
                    assessment=assessment,
                    belief_store=p.belief_store,
                )

            self._record_done(p.agent_id, p.posterior)

    def say(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("TaskworkEpisode does not support say() — use run() instead.")

    def done(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("TaskworkEpisode does not support done() — use run() instead.")


# ── L9 ────────────────────────────────────────────────────────────────────────


class L9:
    """Entry point for application agents.

    Encapsulates AgentBus and TeamEpistemicMemory access. Application agents
    call :meth:`open_team_process`, :meth:`open_taskwork`, :meth:`open_task`,
    :meth:`open` (generic CIP), or register :meth:`on_intent` handlers.
    They never interact with the bus directly.

    ``tom_engine`` and ``task_goal`` are injected once at construction and
    forwarded to all episode subclasses automatically.
    """

    def __init__(
        self,
        bus: AgentBus,
        agent_id: str,
        belief_store: Any = None,
        team_epistemic_agent: Any = None,
        tom_engine: Any = None,
        task_goal: str = "",
    ) -> None:
        self._bus = bus
        self._agent_id = agent_id
        self._belief_store = belief_store
        self._team_epistemic = team_epistemic_agent
        self._tom_engine = tom_engine
        self._task_goal = task_goal
        self._intent_handler: Optional[Callable] = None

    # ── Episode lifecycle ──────────────────────────────────────────────────

    def open_team_process(
        self,
        concept_id: str,
        group: List[str],
        agreement: Any,
        episode_id: Optional[str] = None,
        task_goal: str = "",
        rationale: str = "",
        thought_summary: str = "",
    ) -> TeamProcessEpisode:
        """Open a team-process episode as initiator.

        Emits kind=intent. Returns a :class:`TeamProcessEpisode`; call
        :meth:`TeamProcessEpisode.run` to execute the proposal/acceptance
        loop, then :meth:`Episode.close`.
        """
        team_prior_obj = self._get_team_prior(concept_id)
        agent_prior_obj = self._get_agent_prior(concept_id)
        blended = blend_prior(agent_prior_obj, team_prior_obj)

        eid = episode_id or (
            f"urn:ioc:{self._bus.use_case}:tp"
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

        self._bus._emit_intent(
            sender=self._agent_id,
            receiver=None,
            subject=concept_id,
            episode_id=eid,
            team_prior=team_prior_payload,
            rationale=rationale,
            thought_summary=thought_summary,
            recipients=group,
        )

        return TeamProcessEpisode(
            bus=self._bus,
            agent_id=self._agent_id,
            concept_id=concept_id,
            episode_id=eid,
            group=group,
            prior=blended,
            agreement=agreement,
            tom_engine=self._tom_engine,
            task_goal=task_goal or self._task_goal,
        )

    def open_taskwork(
        self,
        concept_id: str,
        group: List[str],
        participants: List[TaskworkParticipant],
        episode_id: Optional[str] = None,
        task_goal: str = "",
        coordinator_id: Optional[str] = None,
        team_process: Optional[Dict[str, Any]] = None,
        rationale: str = "",
        thought_summary: str = "",
    ) -> TaskworkEpisode:
        """Open a taskwork episode as initiator.

        Emits kind=intent with optional team_process payload. Returns a
        :class:`TaskworkEpisode`; call :meth:`TaskworkEpisode.run` to execute
        belief seeding, exchange emission, ToM assessment, and contingency
        repair for each participant, then :meth:`Episode.close`.
        """
        team_prior_obj = self._get_team_prior(concept_id)
        agent_prior_obj = self._get_agent_prior(concept_id)
        blended = blend_prior(agent_prior_obj, team_prior_obj)

        eid = episode_id or (
            f"urn:ioc:{self._bus.use_case}:tw"
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

        self._bus._emit_intent(
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

        return TaskworkEpisode(
            bus=self._bus,
            agent_id=self._agent_id,
            concept_id=concept_id,
            episode_id=eid,
            group=group,
            prior=blended,
            participants=participants,
            tom_engine=self._tom_engine,
            coordinator_id=coordinator_id or self._agent_id,
            task_goal=task_goal or self._task_goal,
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
        team_prior_obj = self._get_team_prior(concept_id)
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

        self._bus._emit_intent(
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
        peer_interaction_store: Any = None,
        belief_store: Any = None,
        tom_engine: Any = None,
        repair_fn: Any = None,
        task_name: str = "task",
    ) -> "TaskEpisode":
        """Open a SIEP task episode as initiator.

        Returns a :class:`TaskEpisode`. Call :meth:`TaskEpisode.run` to
        execute the negotiation, then :meth:`Episode.announce` to write the
        knowledge outcome.

        The kind=intent for the task is emitted inside
        ``TaskEpisode.run()`` by ``StarNegotiation``, which owns the
        SIEP wire format for the task open.
        """
        team_prior_obj = self._get_team_prior(concept_id)
        agent_prior_obj = self._get_agent_prior(concept_id)
        blended = blend_prior(agent_prior_obj, team_prior_obj)

        eid = episode_id or (
            f"urn:ioc:{self._bus.use_case}:task"
            f":{concept_id.replace(':', '-')}:{int(time.time() * 1000)}"
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
            peer_interaction_store=peer_interaction_store,
            belief_store=belief_store,
            tom_engine=tom_engine or self._tom_engine,
            repair_fn=repair_fn,
            task_name=task_name,
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
        for part in payload:
            if part.get("type") == "utterance":
                content = part.get("content", "")
                if isinstance(content, str) and content.startswith("episode:open subject="):
                    concept_id = content[len("episode:open subject="):]
            elif part.get("type") == "team_prior":
                team_prior_payload = part.get("content", {})

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

        return Episode(
            bus=self._bus,
            agent_id=self._agent_id,
            concept_id=concept_id,
            episode_id=episode_id,
            initiator=False,
            prior=blended,
        )

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

    # ── Prior helpers ──────────────────────────────────────────────────────

    def _get_team_prior(self, concept_id: str) -> Optional[TeamPrior]:
        if self._team_epistemic is None:
            return None
        result = self._team_epistemic.get(concept_id)
        if result is None:
            return None
        return result

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


__all__ = [
    "Episode", "TaskEpisode", "TeamProcessEpisode", "TaskworkEpisode",
    "TaskworkParticipant", "L9", "blend_prior", "AgentPrior", "TeamPrior",
]

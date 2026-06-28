# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/l9/episode.py — Application-facing L9 Episode API.

Application writers import :class:`L9` and :class:`Episode`. They never
call ``AgentBus`` or any ``emit_*`` method directly.

Usage::

    l9 = L9(bus, agent_id="pharmacologist")
    episode = l9.open(concept_id="concept:drug_interaction", group=["cardiologist", "neurologist"])
    episode.say("I see a high-risk interaction.", posterior=0.82)
    episode.done(posterior=0.82)
    episode.close()
    episode.announce(concept_id="concept:drug_interaction", posterior=0.82, gar=0.9, scr=0.1)

For SIEP panel episodes::

    panel_ep = ctrl_l9.open_panel(
        concept_id="concept:drug_interaction",
        group=all_ids,
        episode_id=panel_episode_id,
        convergence_store=convergence_store,
        semantic_rule_store=semantic_rule_store,
        peer_interaction_store=peer_interaction_store,
        belief_store=belief_store,
        tom_engine=tom_engine,
        repair_fn=repair_fn,
    )
    panel_ep.run(
        controller_position=controller_position,
        specialist_positions=all_positions,
        task_goal=task_goal,
        accept_threshold=0.1,
        max_rounds=2,
    )
    panel_ep.announce(
        concept_id=panel_ep.winning_position_key,
        posterior=panel_ep.mpc, gar=panel_ep.gar, scr=panel_ep.scr,
    )

For receiving agents::

    @l9.on_intent
    def handle_intent(episode: Episode) -> None:
        episode.say("My assessment is...", posterior=0.71, final=True)

Note: this module imports directly from SSTP.* source. Import paths and
call signatures are expected to change once the SSTP Python wheel is available.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from SSTP.examples.hcpanel.agent_bus import AgentBus


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

    # ── Internal — set by PanelEpisode after negotiation ──────────────────

    def _set_commit(self, commit_message_id: str, mpc: float, gar: float, scr: float) -> None:
        """Record commit result without emitting — used by PanelEpisode after StarNegotiation."""
        self._commit_message_id = commit_message_id
        self._mpc = mpc
        self._gar = gar
        self._scr = scr
        self._last_message_id = commit_message_id


# ── PanelEpisode ──────────────────────────────────────────────────────────────


class PanelEpisode(Episode):
    """Application-facing handle for a SIEP panel episode.

    Returned by :meth:`L9.open_panel`. Extends :class:`Episode` with
    :meth:`run` which executes the full SIEP star negotiation loop
    (including CIP grounding gates, ToM predictions, Bayesian belief
    revision, GAR/SCR/MPC computation, and convergence/knowledge emit)
    inside the package boundary.

    The orchestrator's view::

        panel_ep = ctrl_l9.open_panel(
            concept_id="urn:concept:healthcare:drug_interaction",
            group=all_specialist_ids,
            episode_id=panel_episode_id,
            convergence_store=...,
            semantic_rule_store=...,
            peer_interaction_store=...,
            belief_store=...,
            tom_engine=...,
            repair_fn=...,
        )
        panel_ep.run(
            controller_position=controller_position,
            specialist_positions=all_positions,
            task_goal=task_goal,
            accept_threshold=0.1,
            max_rounds=2,
        )
        panel_ep.announce(
            concept_id=panel_ep.winning_position_key,
            posterior=panel_ep.mpc, gar=panel_ep.gar, scr=panel_ep.scr,
        )

    After :meth:`run`:
    - :attr:`mpc`, :attr:`gar`, :attr:`scr` — convergence metrics
    - :attr:`winning_position` — the winning position dict
    - :attr:`winning_position_key` — ``str`` concept key from the winning position
    - :attr:`resolution_label` — ``"consensus"``, ``"majority"``, etc.
    - :attr:`snp_trace` — SIEP messages from this panel
    """

    def __init__(
        self,
        bus: AgentBus,
        agent_id: str,
        concept_id: str,
        episode_id: str,
        group: Optional[List[str]] = None,
        prior: float = 0.5,
        # SIEP-specific stores (passed through to PanelBus)
        convergence_store: Any = None,
        semantic_rule_store: Any = None,
        peer_interaction_store: Any = None,
        belief_store: Any = None,
        tom_engine: Any = None,
        repair_fn: Any = None,
        panel_name: str = "panel",
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
        self._panel_name = panel_name
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
        """SIEP messages from this panel — available after run()."""
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
            panel_name=self._panel_name,
            ie_bus=self._bus,
            use_case=self._bus.use_case,
            tom_engine=self._tom_engine,
            repair_fn=self._repair_fn,
            convergence_store=self._convergence_store,
            belief_store=self._siep_belief_store,
            semantic_rule_store=self._semantic_rule_store,
            peer_interaction_store=self._peer_interaction_store,
        )

        star = StarNegotiation(panel_bus, panel_name=self._panel_name)
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

        # Harvest the commit:converged message that StarNegotiation already emitted
        # so that announce() has a parent id to parent the knowledge message on.
        commit_id: Optional[str] = None
        for msg in reversed(self._bus.messages):
            if msg.get("kind") == "commit" and msg.get("subkind") == "converged":
                commit_id = msg.get("message", {}).get("id")
                break

        # Harvest GAR/SCR/MPC from the snp-convergence payload part
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
            # StarNegotiation had no convergence_store — set metrics manually
            self._mpc = mpc
            self._gar = gar
            self._scr = scr

    def close(self, **kwargs: Any) -> str:
        raise RuntimeError(
            "PanelEpisode does not support close() — the panel loop calls it internally. "
            "Call run() then announce()."
        )

    def say(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("PanelEpisode does not support say() — use run() instead.")

    def done(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("PanelEpisode does not support done() — use run() instead.")


# ── L9 ────────────────────────────────────────────────────────────────────────


class L9:
    """Entry point for application agents.

    Encapsulates AgentBus and TeamEpistemicMemory access. Application agents
    call :meth:`open`, :meth:`join`, :meth:`open_panel`, or register
    :meth:`on_intent` handlers. They never interact with the bus directly.
    """

    def __init__(
        self,
        bus: AgentBus,
        agent_id: str,
        belief_store: Any = None,
        team_epistemic_agent: Any = None,
    ) -> None:
        self._bus = bus
        self._agent_id = agent_id
        self._belief_store = belief_store
        self._team_epistemic = team_epistemic_agent
        self._intent_handler: Optional[Callable] = None

    # ── Episode lifecycle ──────────────────────────────────────────────────

    def open(
        self,
        concept_id: str,
        group: List[str],
        episode_id: Optional[str] = None,
        team_process: Optional[Dict[str, Any]] = None,
        rationale: str = "",
        thought_summary: str = "",
    ) -> Episode:
        """Open a new coordination episode as initiator.

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

    def open_panel(
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
        panel_name: str = "panel",
    ) -> "PanelEpisode":
        """Open a SIEP panel episode as initiator.

        Returns a :class:`PanelEpisode`. Call :meth:`PanelEpisode.run` to
        execute the negotiation, then :meth:`Episode.announce` to write the
        knowledge outcome.

        The kind=intent for the panel is emitted inside
        ``PanelEpisode.run()`` by ``StarNegotiation``, which owns the
        SIEP wire format for the panel open.
        """
        team_prior_obj = self._get_team_prior(concept_id)
        agent_prior_obj = self._get_agent_prior(concept_id)
        blended = blend_prior(agent_prior_obj, team_prior_obj)

        eid = episode_id or (
            f"urn:ioc:{self._bus.use_case}:panel"
            f":{concept_id.replace(':', '-')}:{int(time.time() * 1000)}"
        )

        return PanelEpisode(
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
            tom_engine=tom_engine,
            repair_fn=repair_fn,
            panel_name=panel_name,
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


__all__ = ["Episode", "PanelEpisode", "L9", "blend_prior", "AgentPrior", "TeamPrior"]

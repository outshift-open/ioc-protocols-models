# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
siep/src/panel.py — SIEP panel session abstractions.

NetworkHandle
    Abstract base class for the per-episode network transport.  Concrete
    implementations live in the application layer and are passed in at
    episode creation time.  SIEP/CIP/L9 never create or import a concrete
    network handle.

NegotiationContext
    State bag for one SIEP panel session: stores, use_case, ID generators,
    ToM engine, persistence.  The "how to debate" half — carries no network
    or transport logic.

DebateRoundContext / DebateRoundEpisode
    Per-specialist round DTOs passed through the specialist L9 dispatch path.

get_debate_convergence_metrics
    Header-parsing utility for commit:converged messages.
"""

from __future__ import annotations

import abc
import json as _json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from SSTP.subprotocol.siep.src.epistemic.stores import (
    ConvergenceStore,
    NegotiationIndex,
    NegotiationStore,
    ProposalStore,
    RoundStore,
    SemanticRuleStore,
)

if TYPE_CHECKING:
    from SSTP.subprotocol.siep.src.epistemic.stores import ConvergenceStore, SemanticRuleStore


# ── Network transport abstraction ────────────────────────────────────────────

class NetworkHandle(abc.ABC):
    """Abstract network transport passed to episodes by the application.

    Concrete subclasses must set this instance attribute in __init__:
        messages: List[Dict[str, Any]]  — ordered L9 wire headers

    And implement the abstract methods below.  All other transport
    behaviour (routing, delivery, IE repair) is the application's
    responsibility.
    """

    # Expected instance attribute — set by concrete subclass __init__
    messages: List[Dict[str, Any]]

    @abc.abstractmethod
    def register_handler(self, agent_id: str, handler: Callable) -> None:
        """Register a per-agent round handler for SIEP debate dispatch."""

    @abc.abstractmethod
    def get_handler(self, agent_id: str) -> Optional[Callable]:
        """Return the registered handler for agent_id, or None."""

    @abc.abstractmethod
    def send(self, header: Dict[str, Any]) -> None:
        """Append a fully-constructed L9 header and deliver it."""

    @property
    def debate_trace(self) -> List[Dict[str, Any]]:
        """SIEP-only messages from self.messages.  May be overridden."""
        return [m for m in self.messages if m.get("subprotocol") == "SIEP"]


# ── Negotiation context ───────────────────────────────────────────────────────

class NegotiationContext:
    """State bag for one SIEP panel negotiation session.

    Holds the debate-layer state: stores, use_case, ID generators, ToM engine,
    and persistence path.  Carries no network or transport logic — the
    NetworkHandle is kept separate and passed alongside this object wherever
    both are needed.

    Parameters
    ----------
    panel_name      : logical name of the panel (e.g. "diagnostics")
    use_case        : domain label written into L9 headers and episode URNs
    tom_engine      : optional Theory-of-Mind engine handle (application-supplied)
    """

    def __init__(
        self,
        panel_name: str,
        use_case: str,
        tom_engine: Any = None,
        repair_fn: Optional[Callable] = None,
        convergence_store: Optional[ConvergenceStore] = None,
        semantic_rule_store: Optional[SemanticRuleStore] = None,
        proposal_store: Optional[ProposalStore] = None,
        persistence_path: Optional[str] = None,
    ) -> None:
        self.panel_name = panel_name
        self.use_case = use_case
        self.tom_engine = tom_engine
        self.repair_fn = repair_fn
        self.convergence_store = convergence_store
        self.semantic_rule_store = semantic_rule_store
        self.proposal_store = proposal_store
        self.persistence_path = persistence_path
        self.debate_store = NegotiationStore()
        self.debate_index = NegotiationIndex()
        self.round_store = RoundStore()
        self._debate_id: str = str(uuid.uuid4())
        self._common_ground_ids: List[str] = []
        if persistence_path:
            self._load_cross_episode_state(persistence_path)

    def reset(self, negotiation_id: Optional[str] = None) -> None:
        self._common_ground_ids = []
        self._debate_id = negotiation_id or str(uuid.uuid4())

    def _load_cross_episode_state(self, path: str) -> None:
        import os
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = _json.load(fh)
        except (OSError, ValueError):
            return
        if self.semantic_rule_store is not None and "semantic_rules" in data:
            self.semantic_rule_store._restore_flat(data["semantic_rules"])

    def _save_cross_episode_state(self, path: str) -> None:
        data: Dict[str, Any] = {}
        if self.semantic_rule_store is not None:
            data["semantic_rules"] = self.semantic_rule_store._store_flat()
        try:
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(data, fh, indent=2)
        except OSError:
            pass

    def _episode_id(self) -> str:
        return f"urn:ioc:{self.use_case}:panel:{self.panel_name}:{self._debate_id}"

    def _proposal_id(self, turn: int, sender: str) -> str:
        return f"panel-{self.panel_name}-{self._debate_id[:8]}-t{turn}-{sender}"


# ── Round DTOs ────────────────────────────────────────────────────────────────

@dataclass
class DebateRoundContext:
    """Coordinator-computed context for one SIEP debate round, per specialist.

    All fields are plain serialisable data — no back-references to the negotiator.
    """
    controller_id: str
    turn: int
    ie_request_message_id: str
    ctrl_position_key: str
    ctrl_conf: float
    accept_threshold: float
    member_pos: Dict[str, Any]
    ctrl_pos: Dict[str, Any]
    task_goal: str
    tom_ctx: Dict[str, Any]
    # Plain-data substitutes for NegotiationContext back-ref
    use_case: str = ""
    debate_id: str = ""
    panel_episode_id: str = ""
    network: Any = None       # NetworkHandle — needed by respond() to append the header


class DebateRoundEpisode:
    """Episode object the specialist joins for each SIEP debate round."""

    def __init__(self, ctx: DebateRoundContext, agent_id: str) -> None:
        self._ctx = ctx
        self._agent_id = agent_id
        self.operation: Optional[str] = None
        self.position: Optional[Dict[str, Any]] = None
        self.exchange_header: Optional[Dict[str, Any]] = None

    @property
    def member_pos(self) -> Dict[str, Any]:
        return self._ctx.member_pos

    @property
    def ctrl_pos(self) -> Dict[str, Any]:
        return self._ctx.ctrl_pos

    @property
    def task_goal(self) -> str:
        return self._ctx.task_goal

    @property
    def tom_ctx(self) -> Dict[str, Any]:
        return self._ctx.tom_ctx

    @property
    def ctrl_position_key(self) -> str:
        return self._ctx.ctrl_position_key

    @property
    def accept_threshold(self) -> float:
        return self._ctx.accept_threshold

    @property
    def panel_episode_id(self) -> str:
        return self._ctx.panel_episode_id

    def respond(self, operation: str, position: Dict[str, Any]) -> None:
        """Emit the SIEP accept/counter response onto the network."""
        from SSTP.subprotocol.siep.src.builder import emit_specialist_response
        self.operation = operation
        self.position = position

        class _CtxShim:
            """Minimal shim exposing the three fields emit_specialist_response needs."""
            def __init__(self, use_case: str, debate_id: str, episode_id: str, turn: int, panel_name: str = "") -> None:
                self.use_case = use_case
                self._debate_id = debate_id
                self._panel_name = panel_name
                self._ep_id = episode_id
                self._turn = turn

            def _proposal_id(self, t: int, sender: str) -> str:
                return f"panel-{self._panel_name or 'panel'}-{self._debate_id[:8]}-t{t}-{sender}"

            def _episode_id(self) -> str:
                return self._ep_id

        ctx = self._ctx
        shim = _CtxShim(
            use_case=ctx.use_case,
            debate_id=ctx.debate_id,
            episode_id=ctx.panel_episode_id,
            turn=ctx.turn,
        )
        self.exchange_header = emit_specialist_response(
            shim,
            ctx.network,
            specialist=self._agent_id,
            controller=ctx.controller_id,
            position=position,
            operation=operation,
            turn=ctx.turn,
            ie_request_message_id=ctx.ie_request_message_id,
            ctrl_position_key=ctx.ctrl_position_key,
            ctrl_conf=ctx.ctrl_conf,
            accept_threshold=ctx.accept_threshold,
        )


# ── Utility ───────────────────────────────────────────────────────────────────

def get_debate_convergence_metrics(header: Dict[str, Any]) -> Dict[str, Any]:
    """Return convergence metrics from a commit:converged L9 header.

    Reads from payload[type=snp-convergence].content.
    Keys: mpc, gar, scr, participant_ids, episode_id.
    """
    for part in header.get("payload") or []:
        if part.get("type") == "snp-convergence":
            return dict(part.get("content") or {})
    return {}


__all__ = [
    "NetworkHandle",
    "NegotiationContext",
    "DebateRoundContext",
    "DebateRoundEpisode",
    "get_debate_convergence_metrics",
]

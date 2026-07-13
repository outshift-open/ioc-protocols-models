# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/examples/hcpanel/agent_bus.py — Per-episode L9 message bus for hcpanel.

All L9 wire-message construction lives in SSTP.l9.emit — MessageBus itself
knows nothing about L9 vocabulary.  Its only responsibilities are:
  - hold self.messages (ordered L9 header list)
  - implement NetworkHandle (register_handler / get_handler / send)
  - route inbound messages to per-agent handlers via _deliver

CIP inbound grounding lives in SSTP.l9.grounding, exposed via L9.receive_peer_turn().
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from SSTP.l9.deliver import deliver_header
from SSTP.subprotocol.siep.src.panel import NetworkHandle


class ProtocolViolation(RuntimeError):
    """Raised when application code attempts to emit a lifecycle kind directly."""



class MessageBus(NetworkHandle):
    """Per-episode L9 message bus shared by all agents in a session.

    Application code never calls emit_* on this class — all L9 header
    construction lives in SSTP.l9.emit as free functions.
    """

    def __init__(
        self,
        run_id: str,
        conversation_id: str,
        use_case: str = "healthcare",
        sensitivity: str = "internal",
        taskwork_episode_id: str = "",
    ) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.use_case = use_case
        self.sensitivity = sensitivity
        self.taskwork_episode_id = taskwork_episode_id
        self.messages: List[Dict[str, Any]] = []
        self._current_phase: str = "taskwork"
        self._taskwork_store: Optional[Any] = None
        self._protocol_context: bool = False
        self._handlers: Dict[str, Any] = {}
        self._max_delivery_attempts: int = 3
        self._dead_letter: List[Dict[str, Any]] = []
        self.specialist_l9s: Dict[str, Any] = {}
        # Structured message identity counters (scoped to this session)
        self._session_id: str = run_id
        self._episode_seq: int = 0
        self._msg_seq: int = 0
        self._episode_registry: Dict[str, int] = {}

    # ── NetworkHandle implementation ──────────────────────────────────────

    def register_handler(self, agent_id: str, handler: Any) -> None:
        self._handlers[agent_id] = handler

    def get_handler(self, agent_id: str) -> Optional[Any]:
        return self._handlers.get(agent_id)

    def send(self, header: Dict[str, Any]) -> None:
        """Append a fully-constructed L9 header and deliver it."""
        self.messages.append(header)
        self._deliver(header)

    # ── Internal transport ────────────────────────────────────────────────

    def _deliver(self, header: Dict[str, Any]) -> None:
        deliver_header(self, header)

    @property
    def debate_trace(self) -> List[Dict[str, Any]]:
        return [m for m in self.messages if m.get("subprotocol") == "SIEP"]

    def _next_msg_id(self, episode_id: str) -> Tuple[str, str, int]:
        """Return (message_id_urn, episode_urn, msg_seq) for the next message in episode_id."""
        if episode_id not in self._episode_registry:
            self._episode_seq += 1
            self._episode_registry[episode_id] = self._episode_seq
        ep_seq = self._episode_registry[episode_id]
        phase = self._current_phase  # "team_process" | "taskwork" | "task"
        self._msg_seq += 1
        ep_urn = f"urn:session:{self._session_id}:phase:{phase}:episode:{ep_seq}"
        msg_urn = f"{ep_urn}:msg:{self._msg_seq}"
        return msg_urn, ep_urn, self._msg_seq


__all__ = ["MessageBus", "ProtocolViolation"]

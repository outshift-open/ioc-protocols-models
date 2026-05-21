# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/transport/a2a_adapter.py — A2A transport adapter for L9 messages.

L9 messages ride inside A2A DataParts. This adapter wraps and unwraps them,
maps L9 kinds to A2A task states, and fans out one-to-many SNP broadcasts
into separate point-to-point A2A tasks sharing a common sessionId (soid).

Field mapping:
    A2A task.id          ← L9 negotiation_id or episode_id
    A2A task.sessionId   ← L9 state_object_id (soid); groups all panel tasks
    A2A message.parts[0] ← DataPart: {l9_header: {...}, payload: {...}}
    A2A message.role     ← always "agent"
    A2A message.metadata ← {sender, receiver} from L9 header origin
    A2A task.artifacts   ← L9 messages with kind="commit"
    A2A task.status      ← derived from L9 kind (see task_status_for_kind)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── A2A task state ─────────────────────────────────────────────────────────────


class A2ATaskState(str, enum.Enum):
    """A2A task status values derived from L9 kind."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Lightweight A2A message representations ───────────────────────────────────
# These are plain dataclasses, not a full A2A SDK dependency.
# Replace with actual A2A SDK types when integrating against a live A2A runtime.


@dataclass
class A2ADataPart:
    """A2A DataPart carrying an L9 header + payload."""

    l9_header: Dict[str, Any]
    payload: Dict[str, Any]
    mime_type: str = "application/json"


@dataclass
class A2AMessage:
    """A2A message envelope."""

    role: str  # always "agent"
    parts: List[A2ADataPart]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class A2ATask:
    """A2A task descriptor."""

    task_id: str
    session_id: str  # soid — groups all panel tasks for one episode
    receiver: str
    message: A2AMessage
    status: A2ATaskState = A2ATaskState.SUBMITTED
    artifacts: List[A2ADataPart] = field(default_factory=list)


# ── Adapter ────────────────────────────────────────────────────────────────────


class A2ATransportAdapter:
    """Wraps L9 messages into A2A DataParts and unwraps them on receipt.

    This class is the only component that knows both about A2A structure and
    L9 header fields. All layers above it interact with L9 dicts directly.

    Usage::

        adapter = A2ATransportAdapter()

        # Outbound: wrap L9 for a single receiver
        task = adapter.wrap(l9_header, payload, receiver="cardiology", task_id="ep-001-card")

        # Fan-out: one A2A task per specialist, same soid
        tasks = adapter.fanout(l9_header, payload,
                               receivers=["pharmacology", "cardiology", "neurology", "mental_care"])

        # Inbound: unwrap A2A message back to L9
        l9_header, payload = adapter.unwrap(incoming_message)
    """

    # ── Kind → A2A task state ──────────────────────────────────────────────────

    _KIND_TO_STATUS: Dict[str, A2ATaskState] = {
        "delegation": A2ATaskState.WORKING,
        "query":      A2ATaskState.INPUT_REQUIRED,
        "commit":     A2ATaskState.COMPLETED,
        "knowledge":  A2ATaskState.WORKING,  # informational; caller may override
    }

    def task_status_for_kind(self, kind: str) -> A2ATaskState:
        """Map an L9 kind to an A2A task status.

        knowledge with an error payload should be overridden to FAILED by
        the caller; the adapter maps it to WORKING by default.
        """
        return self._KIND_TO_STATUS.get(kind, A2ATaskState.WORKING)

    # ── Wrap / unwrap ──────────────────────────────────────────────────────────

    def wrap(
        self,
        l9_header: Dict[str, Any],
        payload: Dict[str, Any],
        receiver: str,
        task_id: Optional[str] = None,
    ) -> A2ATask:
        """Wrap an L9 (header, payload) pair into an A2A task for a single receiver.

        The A2A task.sessionId is taken from l9_header["state_object_id"] (soid).
        The task status is derived from l9_header["kind"].
        """
        soid = l9_header.get("state_object_id", "")
        kind = l9_header.get("kind", "knowledge")
        sender = l9_header.get("origin", {}).get("actor_id", "unknown")
        derived_task_id = task_id or f"{l9_header.get('message_id', 'unknown')}-{receiver}"

        data_part = A2ADataPart(l9_header=l9_header, payload=payload)
        message = A2AMessage(
            role="agent",
            parts=[data_part],
            metadata={"sender": sender, "receiver": receiver},
        )
        status = self.task_status_for_kind(kind)
        task = A2ATask(
            task_id=derived_task_id,
            session_id=soid,
            receiver=receiver,
            message=message,
            status=status,
        )
        if kind == "commit":
            task.artifacts.append(data_part)
        return task

    def unwrap(self, message: A2AMessage) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Unwrap an A2A message back to (l9_header, payload).

        Returns the first DataPart's fields. Raises ValueError if no DataPart found.
        """
        for part in message.parts:
            if isinstance(part, A2ADataPart):
                return part.l9_header, part.payload
        raise ValueError("A2AMessage contains no A2ADataPart")

    # ── Fan-out ────────────────────────────────────────────────────────────────

    def fanout(
        self,
        l9_header: Dict[str, Any],
        payload: Dict[str, Any],
        receivers: List[str],
    ) -> List[A2ATask]:
        """Fan out one L9 message to multiple receivers as separate A2A tasks.

        All tasks share the same session_id (soid) so the panel bus can
        collect responses by soid. Each task gets a unique task_id derived
        from the message_id and the receiver name.
        """
        return [self.wrap(l9_header, payload, receiver=r) for r in receivers]


__all__ = [
    "A2ATaskState",
    "A2ADataPart",
    "A2AMessage",
    "A2ATask",
    "A2ATransportAdapter",
]

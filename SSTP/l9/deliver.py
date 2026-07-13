# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/l9/deliver.py — L9-aware message delivery as a free function.

deliver_header() contains all the routing + trace-emission logic that was
previously in MessageBus._deliver().  The bus calls this; the bus itself
remains vocabulary-free.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, TYPE_CHECKING

from SSTP.l9.emit import emit_semantic_repair, emit_wire_received
from SSTP.subprotocol.siep.src.epistemic.vocabulary import RepairReason

if TYPE_CHECKING:
    from SSTP.subprotocol.siep.src.panel import NetworkHandle

_LOG = logging.getLogger("sstp.l9.deliver")


def deliver_header(net: "NetworkHandle", header: Dict[str, Any]) -> None:
    """Route a fully-constructed L9 header to all recipient handlers.

    Called by NetworkHandle.send() implementations after appending the
    header to their message store.  Emits wire-received traces and
    semantic-repair records using the free functions in l9.emit.
    """
    ps = header.get("participants") or {}
    actors = ps.get("actors") or []
    if not actors:
        return

    sender_id = actors[0].get("id", "")
    msg_id = (header.get("message") or {}).get("id", "")
    episode_id = (header.get("message") or {}).get("episode")

    dead_letter = getattr(net, "_dead_letter", None)
    max_attempts = getattr(net, "_max_delivery_attempts", 3)

    for actor in actors[1:]:
        recipient_id = actor.get("id", "")
        if not recipient_id or recipient_id == sender_id:
            continue

        handler = net.get_handler(recipient_id)
        if handler is None:
            _LOG.warning(
                "deliver.no_handler recipient=%s msg_id=%s", recipient_id, msg_id
            )
            if dead_letter is not None:
                dead_letter.append({
                    "message_id": msg_id, "recipient_id": recipient_id,
                    "reason": "no_handler",
                })
            try:
                emit_semantic_repair(
                    net,
                    sender=sender_id, receiver=recipient_id,
                    target_message_id=msg_id,
                    repair_reason=RepairReason.DELIVERY_FAILURE,
                    episode_id=episode_id,
                )
            except Exception:
                pass
            continue

        kind = header.get("kind", "")
        if kind not in ("commit", "convergence", "knowledge"):
            emit_wire_received(
                net,
                msg_id=msg_id,
                recipient_id=recipient_id,
                sender_id=sender_id,
                episode_id=episode_id,
            )

        delivered = False
        last_exc: "BaseException | None" = None
        for attempt in range(1, max_attempts + 1):
            try:
                handler(header)
                delivered = True
                break
            except Exception as exc:
                _LOG.warning(
                    "deliver.handler_error attempt=%d recipient=%s error=%s",
                    attempt, recipient_id, exc,
                )
                last_exc = exc

        if not delivered:
            if dead_letter is not None:
                dead_letter.append({
                    "message_id": msg_id, "recipient_id": recipient_id,
                    "reason": "handler_exhausted", "error": str(last_exc),
                })
            try:
                emit_semantic_repair(
                    net,
                    sender=sender_id, receiver=recipient_id,
                    target_message_id=msg_id,
                    repair_reason=RepairReason.DELIVERY_FAILURE,
                    episode_id=episode_id,
                )
            except Exception:
                pass


__all__ = ["deliver_header"]

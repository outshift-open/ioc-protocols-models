# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
L9 message format — the fundamental unit of communication in the IoC protocol stack.

An L9 message consists of a Header (routing + metadata) and a Payload (the actual data).
The `kind` field in the header drives routing decisions, directing the message to the
appropriate handler for processing.

Kind values and their meaning:
  exchange     — direct message transfer between participants
  intent       — participants negotiate shared understanding of intent/ambiguity
  contingency  — fallback handling: negotiation, repair, or escalation
  commit       — participants commit to a shared understanding before acting
  knowledge    — knowledge-base update or retrieval
"""

from typing import Optional
from enum import Enum
from pydantic import BaseModel

from src.primitives import ParticipantSet, PolicyLabel, Message, Context


# ── Enums ─────────────────────────────────────────────────────────────────────
class Kind(str, Enum):
    intent      = "intent"
    contingency = "contingency"
    exchange    = "exchange"
    commit      = "commit"
    knowledge   = "knowledge"


class L9Payload(BaseModel):
    """
    The actual content being carried by an L9 message.
    The `type` field describes the payload format; `data` holds the content.
    """
    type: str   # payload content type, e.g. "text", "json-schema", "task"
    data: dict  # free-form payload data — structure is defined by `type`


class L9Header(BaseModel):
    """
    Routing and metadata envelope for every L9 message.
    The routing layer reads the header — especially `kind` and `subkind` —
    to decide which handler should process the message.
    """
    protocol: str                          # protocol name, e.g. "MyProtocol"
    subprotocol: str                       # subprotocol name, e.g. "MySubprotocol"
    version: str                           # protocol version string, e.g. "1.0"
    kind: Kind                             # one of: intent | contingency | exchange | commit | knowledge
    subkind: Optional[str] = None          # free-form classification within the kind
    participants: ParticipantSet           # all participants: sender(s), receiver(s), observers
    message: Optional[Message] = None
    policy: Optional[PolicyLabel] = None   # optional data governance labels
    attributes: Optional[dict] = None
    context: Optional[Context] = None      # optional context


class L9(BaseModel):
    """
    A complete L9 message: header (routing/metadata) + payload (content).
    This is the top-level structure passed between participants in the IoC protocol.
    """
    header: L9Header
    payload: L9Payload

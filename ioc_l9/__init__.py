"""
ioc_l9 package — L9 message format for the IOC protocol stack.

An L9 message is the fundamental unit of communication between agents.
It consists of a Header (routing + metadata) and a Payload (the actual data).

The `kind` field in the header drives CFN routing decisions, directing the
message to the appropriate Cognitive Engine (CE) for processing.

Kind values and their meaning:
  exchange     — direct message transfer between agents
  intent       — agents negotiate shared understanding of intent/ambiguity
  contingency  — fallback handling: negotiation, repair, or escalation
  commit       — agents commit to a shared understanding before acting
  knowledge    — knowledge-base update or retrieval
"""

from typing import Optional
from pydantic import BaseModel

from ioc_l9.primitives import Actor, SemanticContext, PolicyLabel, Provenance, Group
from ioc_l9.epistemic import Epistemic


class L9Header(BaseModel):
    """
    Routing and metadata envelope for every L9 message.
    The CFN layer reads the header — especially `kind` and `sub_kind` —
    to decide which Cognitive Engine (CE) should handle the message.
    """
    protocol: str                        # protocol name, e.g. "SSTP"
    version: str                         # protocol version string, e.g. "1.0"
    kind: str                            # message kind — drives CFN routing (see module docstring)
    sub_kind: str                        # finer-grained classification within the kind
    group: Group                         # group/session context this message belongs to
    actors: list[Actor]                  # all participants: sender(s), receiver(s), observers
    semantic: SemanticContext            # ontological/schema context for interpreting the payload
    policy: Optional[PolicyLabel] = None      # optional data governance labels
    provenance: Optional[Provenance] = None   # optional origin/lineage tracking
    epistemic: Optional[Epistemic] = None     # optional agent belief/knowledge state


class L9Payload(BaseModel):
    """
    The actual content being carried by an L9 message.
    The `type` field describes the payload format; `data` holds the content.
    """
    type: str   # payload content type, e.g. "text", "json-schema", "task"
    data: dict  # free-form payload data — structure is defined by `type`


class L9(BaseModel):
    """
    A complete L9 message: header (routing/metadata) + payload (content).
    This is the top-level structure passed between agents and through the CFN.
    """
    header: L9Header
    payload: L9Payload
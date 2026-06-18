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
from enum import Enum
from pydantic import BaseModel, model_validator

from ioc_l9.src.primitives import ParticipantSet, PolicyLabel, Message, Context

# ── Enums ─────────────────────────────────────────────────────────────────────
class Kind(str, Enum):
    intent      = "intent"
    contingency = "contingency"
    exchange    = "exchange"
    commit      = "commit"
    knowledge   = "knowledge"

class Subkind(str, Enum):
    # knowledge
    query        = "query"
    distillation = "distillation"
    extraction   = "extraction"
    feedback     = "feedback"
    # commit
    converged    = "converged"
    resolved     = "resolved"
    abort        = "abort"
    # exchange
    teamwork     = "teamwork"
    conversation = "conversation"

# Allowed subkinds per kind (None = subkind must be null, ... = any free-form string)
SUBKIND_MAP: dict[Kind, set[Subkind] | None] = {
    Kind.knowledge:  {Subkind.query, Subkind.distillation, Subkind.extraction, Subkind.feedback},
    Kind.commit:     {Subkind.converged, Subkind.resolved, Subkind.abort},
    Kind.exchange:   {Subkind.teamwork, Subkind.conversation},
    Kind.contingency: None,   # subkind must be null
    Kind.intent:     ...,     # any free-form string allowed
}

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
    The CFN layer reads the header — especially `kind` and `subkind` —
    to decide which Cognitive Engine (CE) should handle the message.
    """
    protocol: str                          # protocol name, e.g. "SSTP"
    subprotocol: str                       # subprotocol name, e.g. "CIP"
    version: str                           # protocol version string, e.g. "1.0"
    kind: Kind                      # one of: intent | contingency | exchange | commit | knowledge
    subkind: Optional[Subkind] = None  # finer-grained classification within the kind (see SUBKIND_MAP)
    participants: ParticipantSet           # all participants: sender(s), receiver(s), observers
    message: Optional[Message] = None
    policy: Optional[PolicyLabel] = None   # optional data governance labels
    attributes: Optional[dict] = None
    context: Optional[Context] = None      # optional context

    @model_validator(mode="after")
    def validate_kind_and_subkind(self) -> "L9Header":
        kind = self.kind
        subkind = self.subkind
        rule = SUBKIND_MAP[kind]

        if rule is None:
            if subkind is not None:
                raise ValueError(
                    f"kind='{kind.value}' does not allow a subkind (must be null), got '{subkind.value}'"
                )
        elif rule is not ...:
            if subkind not in rule:
                raise ValueError(
                    f"Invalid subkind '{subkind}' for kind='{kind.value}'. "
                    f"Must be one of: {sorted(s.value for s in rule)}"
                )

        return self


class L9(BaseModel):
    """
    A complete L9 message: header (routing/metadata) + payload (content).
    This is the top-level structure passed between agents and through the CFN.
    """
    header: L9Header
    payload: L9Payload
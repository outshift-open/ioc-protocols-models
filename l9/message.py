"""
L9 Message — envelope combining L9Header and L9Payload.

Structure:
    L9
    ├── header: L9Header   (routing, identity, protocol metadata)
    └── payload: L9Payload (phase, kind, action, data, evidence)

Usage:
    from l9.message import L9, L9Header, L9Payload
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums shared by header / payload
# ─────────────────────────────────────────────────────────────────────────────


##
# 1. intent KIND 
# Defines goals, constraints, and success criteria

# 2. delegation SUBKIND of Planning 
# Defines structured task assignment

# 3. knowledge KIND
# Represents assertions, hypotheses, or proposals

# 4. query SUBKIND of knowledge
# Requests missing information

# 5. evidence_bundle SUBKIND of knowledge
# Provides validation artifacts

# 6. commit SUBKIND of knowledge
# Represents stabilized shared state

# 7. memory_delta SUBKIND of knowledge
##

class L9Phase(int, Enum):
    TEAMWORK      = 1
    GOAL_INTENT   = 2
    PLANNING      = 3
    CONVERSATION = 4
    VALIDATION    = 5


class L9Kind(str, Enum):
    INTENT   = "Intent"
    KNOWLEDGE = "Knowledge"
    REPAIR    = "Repair"

class L9SubKind(str, Enum):
    intent_ambiguity_decttor = "intent_ambiguity_decttor" ## This is only valid when kind == Intent
    intent_congitgenction_decetor = "intent_congitgenction_decetor" ## This is only valid when kind == Intent
    repair_template = "repair_template" ## This is only valid when kind == Repair
    repair_negotiation = "repair_negotiation" ## This is only valid when kind == Intent
## Lets assume that ambugity detector is of kind == Repair and sub_kind == ambiguity_decttor
## Lets assume that semantic negotiation is a method to repair intent and is of kind == Intent and sub_kind == repair
## Lets assume we have ask actor to clarify a specific aspect of the intent and that is of kind == Intent and sub_kind == intent_analyze
## 

class L9MessageType(str, Enum):
    REQUEST  = "request"
    RESPONSE = "response"
    EVENT    = "event"
    ERROR    = "error"


# ─────────────────────────────────────────────────────────────────────────────
# L9Header — routing, identity, protocol metadata
# ─────────────────────────────────────────────────────────────────────────────


###
#   "actors": {
#     "identity": {
#       "actor_type": "SOURCE",
#       "identifier-type" : "URL",
#       "identifiers": [
#             "https://myagent1:8080"
#         ]
#     },
#     "identity": {
#       "actor_type": "DESTINATION",
#       "identifier-type" : "URL",
#       "identifiers": "https://myagent2:9090"
#     },
#     "identity": {
#       "actor_type": "USER",
#       "identifier-type" : "Email",
#       "identifiers": "john@cisco.com"
#     },
#     "identity": {
#       "actor_type": "ANOTHER ACTOR TYPE",
#       "identifier-type" : "SSN",
#       "identifiers": "john@cisco.com"
#     }
#   }
##

class Identity(BaseModel):
    """Represents an agent or service identity in the L9 protocol."""
    type: str ## e.g. "OpenClaw", "", etc.
    attestation: Optional[str] = None  # e.g. JWT, certificate fingerprint, etc.   
    identifiers: Optional[List[Dict[str, str]]] = None # e.g. [{"URL": "http://host1:portN", "agent_id": "OC1::Agent1"}] ## TODO add validator for 1 more identifier per identity

class Actor(BaseModel):
    """Represents an actor in the L9 protocol, which can be a source, destination, user, CFN,  etc."""
    actor_type: str
    identity: Identity

class L9Header(BaseModel):
    """
    Metadata envelope for an L9 message.

    Fields:
        message_id     — unique ID for this message (auto-generated)
        correlation_id — links related messages in the same workflow
        version        — protocol version
        message_type   — request | response | event | error
        phase          — lifecycle phase (1–5)
        kind           — the Kind being addressed
        sender         — agent / service originating the message
        receiver       — agent / service this message is addressed to
        timestamp      — ISO-8601 UTC creation time (auto-generated)
        ttl            — time-to-live in seconds (None = no expiry)
    """

    message_id:     str             = Field(default_factory=lambda: str(uuid.uuid4()))
    version:        str             = "0.0.1"
    kind:           L9Kind          = L9Kind.INTENT
    sub_kind: L9SubKind             = L9SubKind.intent_ambiguity_detector
    creation_timestamp: str         = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actors:         List[Actor] = None  ## TODO add validator to gurantee a minimum of one SOURCE and zero or more DESTINATION actor 


# ─────────────────────────────────────────────────────────────────────────────
# L9Payload — phase-specific content
# ─────────────────────────────────────────────────────────────────────────────

class L9Payload(BaseModel):
    """
    Content envelope for an L9 message.

    Fields:
        sub_kind  — the SubKind being operated on (e.g. "evidence_bundle")
        action    — the Action being executed (e.g. "ingest")
        events    — ordered list of events produced by this action
        data      — action-specific body (free-form dict or nested model)
        error     — populated when message_type == error
    """

    # cognition_profile: Optional[str] = None
    sub_protocol: Optional[str] = None ## Friendly name that defines an implementation approach i.e., 
    sub_protocol_schema: Optional[str] = None ## Schema defines the expected structure of the data field for this sub_protocol
    semantic_context: Optional[Dict[str, Any]] = None ## 
    # error:    Optional[str]       = None


# ─────────────────────────────────────────────────────────────────────────────
# L9 — combined message
# ─────────────────────────────────────────────────────────────────────────────

class L9(BaseModel):
    """
    A complete L9 protocol message.

        {
            "header":  L9Header,
            "payload": L9Payload
        }
    """

    header:  L9Header  = Field(default_factory=L9Header)
    payload: L9Payload = Field(default_factory=L9Payload)

    @classmethod
    def create(
        cls,
        phase: L9Phase,
        kind: L9Kind,
        action: str,
        sender: str = "",
        receiver: str = "",
        sub_kind: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        events: Optional[List[str]] = None,
        message_type: L9MessageType = L9MessageType.REQUEST,
        correlation_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> L9:
        """Convenience factory to build an L9 message in one call."""
        return cls(
            header=L9Header(
                phase=phase,
                kind=kind,
                sender=sender,
                receiver=receiver,
                message_type=message_type,
                correlation_id=correlation_id,
                ttl=ttl,
            ),
            payload=L9Payload(
                sub_kind=sub_kind,
                action=action,
                events=events or [],
                data=data or {},
            ),
        )

    def reply(
        self,
        data: Optional[Dict[str, Any]] = None,
        events: Optional[List[str]] = None,
        error: Optional[str] = None,
    ) -> L9:
        """Create a response message correlated to this one, swapping sender/receiver."""
        return L9(
            header=L9Header(
                phase=self.header.phase,
                kind=self.header.kind,
                sender=self.header.receiver,
                receiver=self.header.sender,
                message_type=L9MessageType.ERROR if error else L9MessageType.RESPONSE,
                correlation_id=self.header.message_id,
                version=self.header.version,
            ),
            payload=L9Payload(
                sub_kind=self.payload.sub_kind,
                action=self.payload.action,
                events=events or [],
                data=data or {},
                error=error,
            ),
        )

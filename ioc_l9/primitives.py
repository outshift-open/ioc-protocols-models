"""
L9 header sub-structures — the building blocks of every L9 message envelope.

These types map directly to the sub-fields listed in Figure 1 of the L9 spec.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class Group(BaseModel):
    """
    Logical grouping of actors — e.g. a team, session, or panel.
    Scopes the message to a shared coordination context.
    """
    id: str    # unique group identifier
    name: str  # human-readable label


class ActorRef(BaseModel):
    """
    Identity of the message sender (L9 header §actor).
    attestation may be omitted when the transport layer uniquely identifies the sender.
    """
    id: str
    attestation: Optional[str] = "self-attested-local"


class MessageRef(BaseModel):
    """
    Content-addressed message identity (L9 header §message).
      id      — UUIDv4 wire key; the only message key on the wire
      parents — list of UUIDs this message refers to (causal chain)
      episode — URN grouping all messages in one coordination cycle
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parents: List[str] = Field(default_factory=list)
    episode: str = ""


class SemanticCtx(BaseModel):
    """
    Ontological context for payload interpretation (L9 header §semantic).
    Selects the appropriate cognitive engine for this message.
    """
    schema_id: Optional[str] = None     # URN identifying the payload schema/format
    ontology_ref: Optional[str] = None  # URI of the shared domain ontology


class PolicyCtx(BaseModel):
    """Data-governance and access-control labels (L9 header §policy)."""
    sensitivity: str = "internal"              # "public" | "internal" | "restricted" | "confidential"
    propagation: str = "restricted"            # "forward" | "restricted" | "no_forward"
    retention_policy: Optional[str] = None    # retention policy URN


class AttributesCtx(BaseModel):
    """Message provenance and timing (L9 header §attributes)."""
    msg_sources: List[str] = Field(default_factory=list)
    msg_transforms: List[str] = Field(default_factory=list)
    msg_created: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    msg_expiry: Optional[str] = None

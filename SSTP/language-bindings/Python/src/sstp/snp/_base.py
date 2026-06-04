# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
snp/_base.py — Shared literals, sub-models, and envelope base for SSTP.

Imported by every kind module; do not import this directly from outside
the package — use ``from sstp.snp import ...`` instead.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Literals / type aliases
# ---------------------------------------------------------------------------

ProtocolType = Literal["SSTP"]
SensitivityType = Literal["public", "internal", "restricted", "confidential"]
PropagationType = Literal["forward", "restricted", "no_forward"]
EncodingType = Literal["json", "structured_text", "hybrid"]
MergeStrategy = Literal["add", "replace", "merge", "crdt"]
PayloadRefType = Literal["inline", "external"]


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class Origin(BaseModel):
    """Who produced this message."""

    actor_id: str
    """ID of the agent, engine, or memory node that created the message."""

    attestation: str | None = None
    """Optional credential or signature proving identity."""


class SemanticContext(BaseModel):
    """Schema identity for the payload."""

    schema_id: str
    """Canonical schema URN (e.g. ``urn:ioc:schema:intent:v1``)."""



class PolicyLabels(BaseModel):
    """Data-handling policy annotations."""

    sensitivity: SensitivityType
    propagation: PropagationType
    retention_policy: str
    """Reference to a retention policy by ID."""


class Provenance(BaseModel):
    """Lineage of this message."""

    sources: list[str] = Field(default_factory=list)
    """Source references (URNs, message IDs, document refs)."""

class PayloadRef(BaseModel):
    """A reference to where payload content is stored."""

    type: PayloadRefType
    ref: str
    """URI pointing at the actual payload content."""


class LogicalClock(BaseModel):
    """Lamport scalar or vector clock snapshot."""

    type: Literal["lamport", "vector"] = "lamport"
    value: int | dict[str, int] = 0
    """Scalar int for lamport; ``{actor_id: counter}`` dict for vector."""


# ---------------------------------------------------------------------------
# Common envelope base
# ---------------------------------------------------------------------------


class _STBaseMessage(BaseModel):
    """Internal base — do not use directly; import one of the kind models."""

    # protocol: ProtocolType = "SSTP"
    version: str = "0"

    # -- required envelope -------------------------------------------------
    message_id: str
    """UUIDv4 or content-addressed hash identifying this message."""

    dt_created: str
    """ISO 8601 creation timestamp (e.g. ``2026-02-27T10:00:00Z``)."""

    origin: Origin
    semantic_context: SemanticContext
    policy_labels: PolicyLabels
    provenance: Provenance

    # -- payload (kind-specific, kept as open dict for flexibility) --------
    payload: dict[str, Any] = Field(default_factory=dict)

    # -- optional general fields -------------------------------------------
    episode_id: str | None = None
    """URN or fabric address of the state object this message targets."""

    parent_ids: list[str] = Field(default_factory=list)
    """Message IDs this message is a reply to or derived from."""

    payload_refs: list[PayloadRef] = Field(default_factory=list)
    """External or split-payload references."""

    ttl_seconds: int | None = None
    """Time-to-live in seconds. None = no expiry."""




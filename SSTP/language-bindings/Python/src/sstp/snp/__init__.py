# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
snp — Semantic Negotiation Protocol: all SSTP/SNP protocol assets.
================================================================================
Single home for every protocol asset: L9 header primitives, Pydantic v2
envelope models, SNP operation vocabulary and mapping, SAO negotiation state
types, and the bridge that converts between them.

The ``kind`` field is the discriminator. All kinds share a common envelope
(origin, semantic_context, policy_labels, provenance, payload_hash) plus a
set of optional general fields.  ``kind="commit"`` promotes several of those
optional fields to **required**.

Kind taxonomy
-------------
``intent | exchange | contingency | commit | convergence``

Legacy kinds (backward compat during transition):
``delegation | knowledge | query | memory_delta | evidence_bundle``

NegMAS SAO extension: ``negotiate``

For ``kind="negotiate"`` the ``semantic_context`` field is typed as
:class:`NegotiateSemanticContext` which carries a full NegMAS SAO snapshot
(``SAOState``, ``SAOResponse``, optional ``SAONMI``).

Usage
-----
    from sstp.snp import STPMessage

    # build from a dict / JSON
    msg = STPMessage.model_validate({
        "version": "0",
        "kind": "intent",
        "message_id": "01920000-0000-7000-8000-000000000001",
        "dt_created": "2026-02-27T10:00:00Z",
        "origin": {
            "actor_id": "agent:planner-7",
            "tenant_id": "acme",
            "attestation": "sha256:abc123",
        },
        "semantic_context": {
            "schema_id": "urn:ioc:schema:intent:v1",
            "schema_version": "1.0",
            "encoding": "json",
        },
        "payload_hash": "sha256:deadbeef",
        "policy_labels": {
            "sensitivity": "internal",
            "propagation": "forward",
            "retention_policy": "pol-90d",
        },
        "provenance": {"sources": ["urn:doc:abc"], "transforms": []},
        "payload": {"goal": "book flight", "priority": "high"},
    })
"""

from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field

#: Semantic version of the SNP/SSTP protocol package.
#: Bump this when the envelope schema or any kind model changes.
__version__: str = "1.0.0"

# ── Base L9 constants (shared across all L9 protocols) ────────────────────────
from sstp.l9_base import (
    L9_PROTOCOL,
    L9_VERSION,
    normalize_use_case,
    schema_trust_level_for_kind,
    schema_version_for_kind,
)

# ── SNP L9 primitives ──────────────────────────────────────────────────────────
from .l9 import (
    SNP_ONTOLOGY_REFERENCE,
    SNP_PROFILE,
    NegotiationOperation,
    NegotiationStatus,
    SNPL9HeaderBuilder,
    build_snp_l9_header,
    build_snp_payload,
    snp_event_type_for_operation,
)

# ── Theory-of-Mind wire types (canonical home: protocol.ie.tom) ───────────────
from sstp.ie.tom import (
    AgentResponsibility,
    DiscourseEntry,
    GraphEdge,
    GraphNode,
    KnowledgeGraphNode,
    KnowledgeGraphVisualization,
    normalize_alignment,
    normalize_tom_snapshot,
)

# ── Base models and literals ───────────────────────────────────────────────────
from ._base import (
    EncodingType,
    LogicalClock,
    MergeStrategy,
    Origin,
    PayloadRef,
    PayloadRefType,
    PolicyLabels,
    PropagationType,
    ProtocolType,
    Provenance,
    SemanticContext,
    SensitivityType,
    _STBaseMessage,
)

# ── Kind-specific message classes ─────────────────────────────────────────────
from .commit import NegotiateCommitSemanticContext, SSTPCommitMessage
from .contingency import ContingencyMessage
from .convergence import ConvergenceMessage
from .delegation import DelegationMessage
from .evidence_bundle import EvidenceBundleMessage
from .exchange import ExchangeMessage
from .intent import IntentMessage
from .knowledge import KnowledgeMessage
from .memory_delta import MemoryDeltaMessage
from .negotiate import SSTPNegotiateMessage, NegotiateSemanticContext
from .query import QueryMessage

# ── L9 ↔ Pydantic bridge ─────────────────────────────────────────────────────
from .l9_bridge import (
    l9_header_to_pydantic,
    pydantic_to_l9_header,
    build_negotiate_envelope,
    build_repair_required,
    build_repair_applied,
)

# ── Discriminated union ───────────────────────────────────────────────────────

STPMessage = Annotated[
    Union[
        # New 5-value session-flow vocabulary (preferred)
        IntentMessage,
        ExchangeMessage,
        ContingencyMessage,
        SSTPCommitMessage,
        ConvergenceMessage,
        # Legacy kinds (backward compat during transition)
        DelegationMessage,
        KnowledgeMessage,
        QueryMessage,
        MemoryDeltaMessage,
        EvidenceBundleMessage,
        # NegMAS SAO extension
        SSTPNegotiateMessage,
    ],
    Field(discriminator="kind"),
]
"""
Discriminated union of all SSTP message kinds.

Pydantic selects the concrete model based on the ``kind`` field value.
Use :func:`pydantic.TypeAdapter` or ``model_validate`` on the individual
concrete classes when you already know the kind; use ``STPMessage`` (via
``TypeAdapter``) when kind is unknown at parse time.

Example::

    from pydantic import TypeAdapter
    from sstp.snp import STPMessage

    adapter = TypeAdapter(STPMessage)
    msg = adapter.validate_python(raw_dict)
"""

__all__ = [
    # Package version
    "__version__",
    # Base L9 constants
    "L9_PROTOCOL",
    "L9_VERSION",
    "normalize_use_case",
    "schema_trust_level_for_kind",
    "schema_version_for_kind",
    # SNP L9 primitives
    "SNP_ONTOLOGY_REFERENCE",
    "SNP_PROFILE",
    "NegotiationOperation",
    "NegotiationStatus",
    "SNPL9HeaderBuilder",
    "build_snp_l9_header",
    "build_snp_payload",
    "snp_event_type_for_operation",
    # TOM wire types
    "KnowledgeGraphNode",
    "AgentResponsibility",
    "DiscourseEntry",
    "GraphEdge",
    "GraphNode",
    "KnowledgeGraphVisualization",
    "normalize_tom_snapshot",
    "normalize_alignment",
    # Literals & primitives
    "ProtocolType",
    "SensitivityType",
    "PropagationType",
    "EncodingType",
    "MergeStrategy",
    "PayloadRefType",
    # Sub-models
    "Origin",
    "SemanticContext",
    "PolicyLabels",
    "Provenance",
    "PayloadRef",
    "LogicalClock",
    # Base envelope
    "_STBaseMessage",
    # Kind message classes — new session-flow vocabulary
    "IntentMessage",
    "ExchangeMessage",
    "ContingencyMessage",
    "SSTPCommitMessage",
    "ConvergenceMessage",
    # Kind message classes — legacy (backward compat)
    "DelegationMessage",
    "KnowledgeMessage",
    "QueryMessage",
    "NegotiateCommitSemanticContext",
    "MemoryDeltaMessage",
    "EvidenceBundleMessage",
    "NegotiateSemanticContext",
    "SSTPNegotiateMessage",
    # Union
    "STPMessage",
    # L9 ↔ Pydantic bridge
    "l9_header_to_pydantic",
    "pydantic_to_l9_header",
    "build_negotiate_envelope",
    "build_repair_required",
    "build_repair_applied",
]

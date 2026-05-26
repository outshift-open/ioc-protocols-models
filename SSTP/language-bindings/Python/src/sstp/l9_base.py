# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
protocol/l9_base.py — Generic L9 header builder base class.

Defines the common L9 envelope structure and the abstract ``L9HeaderBuilder``
base class that all protocol specialisations (SNP, IE, …) subclass.

Protocol specialisations live in sub-packages:

- ``protocol.snp``  — Semantic Negotiation Protocol (SSTP kinds + SNP operation vocabulary)
- ``protocol.ie``   — Interaction Engine (conversational event types)

Adding a new protocol
---------------------
1. Create ``protocol/<name>/l9.py``.
2. Subclass ``L9HeaderBuilder``.
3. Implement ``kind_for_event_type``, ``schema_id_for``, and optionally
   ``ttl_for_event_type``.
4. Expose a module-level convenience function that calls ``self.build(...)``.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List
from uuid import NAMESPACE_URL, uuid5

# ── Wire-level constants ──────────────────────────────────────────────────────


class L9Transport(str, enum.Enum):
    """L9 transport modality identifier placed in the ``protocol`` envelope field.

    Three modalities are defined:

    ``SSTP`` — Structured Semantic Transport Protocol
        Carries structured (JSON / dict) semantic state.  Used for reasoning,
        negotiation, commits, and conversational traces.  All current L9
        sub-protocols (SNP, IE) run over SSTP.

    ``CSTP`` — Continuous Semantic Transport Protocol
        Carries embedding or vector payloads.  Used for similarity search,
        semantic clustering, and dense-retrieval coordination between agents
        and Cognition Engines.

    ``LSTP`` — Latent Semantic Transport Protocol
        Carries latent or tensor payloads.  Used for high-fidelity cognitive
        coordination where full distributional representations must be
        propagated (e.g. cross-model knowledge distillation).

    Because ``L9Transport`` is a ``str`` subclass, instances compare and
    serialise identically to their string values::

        L9Transport.SSTP == "SSTP"          # True
        json.dumps(L9Transport.SSTP)        # '"SSTP"'

    Sub-protocols declare their transport by setting the ``PROTOCOL`` class
    attribute on their :class:`L9HeaderBuilder` subclass::

        class MyEmbeddingBuilder(L9HeaderBuilder):
            PROTOCOL = L9Transport.CSTP
            ...
    """

    SSTP = "SSTP"
    CSTP = "CSTP"
    LSTP = "LSTP"


L9_PROTOCOL: L9Transport = L9Transport.SSTP
"""Default L9 transport.  All current sub-protocols (SNP, IE) use SSTP."""

L9_VERSION: str = "0"
"""Current L9 envelope version."""

# ── Shared utilities ──────────────────────────────────────────────────────────

_CERTIFIED_KINDS: frozenset = frozenset({"commit", "convergence"})

# ── Schema lifecycle stages (§5 of the canonical model spec) ─────────────────
#
# Three stages define how mature and registered a schema is:
#
#   "inline"     Exploratory.  The schema definition is fully embedded inside
#                the message header (via ``schema_inline``).  Used internally,
#                not registered in any schema registry.  Flexible and subject
#                to change.  schema_version = "0.0".
#
#   "draft"      Registered.  The schema exists in the schema registry but has
#                not yet been approved for canonical use.  Structured and shared
#                within a domain.  schema_version = "0.1".
#
#   "certified"  Canonical.  Approved, signed, and required for stabilisation
#                boundaries: ``commit`` events, cross-tenant communication, and
#                memory propagation.  schema_version = "1.0".

_SCHEMA_TRUST_LEVELS: frozenset = frozenset({"inline", "draft", "certified"})


def normalize_use_case(use_case: str) -> str:
    """Normalise a use-case label to a lowercase snake_case string."""
    return str(use_case).strip().lower().replace("-", "_").replace(" ", "_")


def schema_trust_level_for_kind(kind: str) -> str:
    """Return the default schema trust level for a given L9 kind.

    ``"certified"`` for stable kinds (``commit``, ``memory_delta``),
    ``"draft"`` for all others.  Callers may override via the
    ``schema_trust_level`` parameter of :meth:`L9HeaderBuilder.build`.
    """
    return "certified" if kind in _CERTIFIED_KINDS else "draft"


def schema_version_for_trust_level(trust_level: str) -> str:
    """Return the schema version string for a given schema trust level.

    ``"inline"`` → ``"0.0"``,  ``"draft"`` → ``"0.1"``,
    ``"certified"`` → ``"1.0"``.  Unknown values default to ``"0.1"``.
    """
    if trust_level == "certified":
        return "1.0"
    if trust_level == "inline":
        return "0.0"
    return "0.1"


def schema_version_for_kind(kind: str) -> str:
    """Return the schema version string for a given L9 kind.

    Convenience wrapper over :func:`schema_version_for_trust_level` using
    the default trust level derived from *kind*.  Retained for backwards
    compatibility; prefer ``schema_version_for_trust_level`` when the
    resolved trust level is already available.
    """
    return schema_version_for_trust_level(schema_trust_level_for_kind(kind))


def _iso8601_from_timestamp_ms(timestamp_ms: int) -> str:
    return (
        datetime.fromtimestamp(max(0, timestamp_ms) / 1000.0, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _message_id_seed(
    *,
    use_case: str,
    event_type: str,
    sender: str,
    receiver: str | None,
    turn_depth: int | None,
    utterance: str,
    timestamp_ms: int,
) -> str:
    return "|".join(
        [
            normalize_use_case(use_case),
            str(event_type).strip().lower(),
            str(sender or "unknown"),
            str(receiver or "none"),
            str(turn_depth if turn_depth is not None else "none"),
            utterance,
            str(max(0, timestamp_ms)),
        ]
    )


# ── Abstract base class ───────────────────────────────────────────────────────


class L9HeaderBuilder:
    """Abstract base for L9 protocol header building.

    Subclass for each protocol (SNP, IE, …).  Subclasses must implement
    :meth:`kind_for_event_type` and :meth:`schema_id_for`; the base
    :meth:`build` method assembles the common envelope dict and delegates
    protocol-specific decisions to those methods.

    Example::

        class MyProtocolBuilder(L9HeaderBuilder):
            def kind_for_event_type(self, event_type: str) -> str:
                return {"foo_event": "intent", "bar_event": "commit"}.get(event_type, "knowledge")

            def schema_id_for(self, use_case, event_type, kind, trust_level):
                return f"urn:my:{use_case}:{kind}:v1"

        header = MyProtocolBuilder().build(
            use_case="demo", event_type="foo_event",
            sender="agent-1", receiver=None, timestamp_ms=0,
        )
    """

    PROTOCOL: L9Transport = L9Transport.SSTP
    VERSION: str = L9_VERSION

    # -- Protocol-specific hooks (subclasses must implement) ------------------

    def kind_for_event_type(self, event_type: str) -> str:
        """Map an event_type string to an L9 kind.

        Must be overridden by every concrete subclass.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement kind_for_event_type"
        )

    def schema_id_for(
        self,
        use_case: str,
        event_type: str,
        kind: str,
        schema_trust_level: str,
    ) -> str:
        """Return the canonical schema URN for this (use_case, event_type, kind).

        Must be overridden by every concrete subclass.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement schema_id_for"
        )

    def ttl_for_event_type(self, event_type: str) -> int:
        """Return the TTL in seconds for this event type.

        Override in subclasses to provide event-type-specific TTLs.
        Default is 7 days (604 800 s).
        """
        return 604800

    # -- Common envelope builder ----------------------------------------------

    def build(
        self,
        *,
        use_case: str,
        event_type: str,
        sender: str,
        receiver: str | None,
        timestamp_ms: int,
        tenant_id: str | None = None,
        sensitivity: str = "internal",
        propagation: str = "restricted",
        turn_depth: int | None = None,
        utterance: str = "",
        parent_ids: Iterable[str] | None = None,
        confidence_score: float | None = None,
        risk_score: float | None = None,
        state_object_id: str | None = None,
        merge_strategy: str = "merge",
        provenance_sources: Iterable[str] | None = None,
        provenance_transforms: Iterable[str] | None = None,
        payload_refs: List[Dict[str, str]] | None = None,
        schema_inline: Dict[str, Any] | None = None,
        schema_trust_level: str | None = None,
        message_id: str | None = None,
        ontology_ref: str | None = None,
        cognition_profile_id: str | None = None,
        cognition_protocol: str | None = None,
        epistemic: Dict[str, Any] | None = None,
        state_sequence: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Assemble the common L9 envelope dict.

        Normalises all inputs, derives the kind and schema URN from the
        protocol-specific hooks, and returns a plain dict ready to embed
        as an ``l9_header`` field in any protocol event.

        ``parent_ids`` is reserved for RPC request/response pairing: a
        response carries the request's ``message_id`` here.  General causal
        chaining (e.g. repair chains) is enforced at the delivery layer via
        parent-gated dispatch, not in this field.

        ``turn_depth`` represents the nesting level of this message.
        Sub-protocol events that fire *inside* an enclosing exchange (e.g. an
        IE correction inside an SNP turn) MUST carry ``turn_depth = parent + 1``
        and a child ``state_object_id`` scoped to the enclosing exchange.
        """
        normalized_use_case = normalize_use_case(use_case)
        canonical_type = str(event_type).strip().lower()
        kind = self.kind_for_event_type(canonical_type)
        trust_level = schema_trust_level or schema_trust_level_for_kind(kind)

        derived_message_id = message_id or str(
            uuid5(
                NAMESPACE_URL,
                _message_id_seed(
                    use_case=normalized_use_case,
                    event_type=canonical_type,
                    sender=sender,
                    receiver=receiver,
                    turn_depth=turn_depth,
                    utterance=utterance,
                    timestamp_ms=timestamp_ms,
                ),
            )
        )

        parent_id_list = [str(i) for i in (parent_ids or []) if i]
        source_list = [str(i) for i in (provenance_sources or []) if i]
        transform_list = [str(i) for i in (provenance_transforms or []) if i]
        payload_ref_list = payload_refs or [
            {"type": "inline", "ref": f"urn:ioc:payload:{derived_message_id}"}
        ]

        header: Dict[str, Any] = {
            "protocol": self.PROTOCOL,
            "version": self.VERSION,
            "kind": kind,
            "message_id": derived_message_id,
            "dt_created": _iso8601_from_timestamp_ms(timestamp_ms),
            "origin": {
                "actor_id": str(sender or "unknown"),
                "tenant_id": tenant_id or f"ioc-demo-{normalized_use_case}",
                "attestation": "self_attested_local",
            },
            "semantic_context": {
                "schema_id": self.schema_id_for(
                    normalized_use_case, canonical_type, kind, trust_level
                ),
                "schema_version": schema_version_for_trust_level(trust_level),
                "encoding": "structured_text",
                "schema_trust_level": trust_level,
                "ontology_ref": ontology_ref,
                "cognition_profile_id": cognition_profile_id,
                "cognition_protocol": cognition_protocol,
            },
            "policy_labels": {
                "sensitivity": sensitivity,
                "propagation": propagation,
                "retention_policy": f"policy.{normalized_use_case}.default",
            },
            "provenance": {
                "sources": source_list,
                "transforms": transform_list,
            },
            "state_object_id": state_object_id
            or f"urn:ioc:{normalized_use_case}:state:shared_dialogue",
            "parent_ids": parent_id_list,
            "confidence_score": confidence_score,
            "risk_score": risk_score,
            "ttl_seconds": self.ttl_for_event_type(canonical_type),
            "merge_strategy": merge_strategy,
            "epistemic": epistemic,
            "state_sequence": state_sequence,
            "payload_refs": payload_ref_list,
        }

        if schema_inline:
            header["semantic_context"]["schema_inline"] = dict(schema_inline)
        return header


__all__ = [
    "L9Transport",
    "L9_PROTOCOL",
    "L9_VERSION",
    "_SCHEMA_TRUST_LEVELS",
    "normalize_use_case",
    "schema_trust_level_for_kind",
    "schema_version_for_trust_level",
    "schema_version_for_kind",
    "L9HeaderBuilder",
]

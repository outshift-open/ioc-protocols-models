# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/l9_base.py — Generic, config-driven L9 header builder.

Defines the common L9 envelope structure and the concrete ``L9HeaderBuilder``
class used by every protocol specialisation (SNP/SIEP, IE/CIP, …). Everything
that differs between protocols — the event-type → kind mapping, schema URN
topics, default epistemic stance, and short-TTL event types — is *data*
supplied at construction time, not code. There is no abstract base to
subclass.

Protocol specialisations live in sub-packages:

- ``SSTP.subprotocol.siep`` — Semantic Interaction & Epistemic Protocol (SNP)
- ``SSTP.subprotocol.cip``  — Contingency & Interaction Protocol (IE)

Adding a new protocol
---------------------
1. In ``SSTP/subprotocol/<name>/src/l9.py``, declare your protocol's lookup
   tables (``kind_by_event_type``, optionally ``schema_topic_by_event_type``,
   ``default_epistemic_by_event_type``, ``short_ttl_event_types``, event-type
   aliases).
2. Construct one module-level ``L9HeaderBuilder(subprotocol="<NAME>", ...)``
   instance with those tables — no subclass required.
3. Expose a module-level convenience function that calls
   ``_BUILDER.build(...)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List
import uuid as _uuid


# ── Wire-level constants ──────────────────────────────────────────────────────


L9_PROTOCOL: str = "SSTP"
L9_VERSION: str = "0.0.5"

# ── Shared utilities ──────────────────────────────────────────────────────────

_CERTIFIED_KINDS: frozenset = frozenset({"commit"})

_SCHEMA_TRUST_LEVELS: frozenset = frozenset({"inline", "draft", "certified"})


def normalize_use_case(use_case: str) -> str:
    """Normalise a use-case label to a lowercase snake_case string."""
    return str(use_case).strip().lower().replace("-", "_").replace(" ", "_")


def schema_trust_level_for_kind(kind: str) -> str:
    """Return ``"certified"`` for stable kinds (``commit``), ``"draft"`` otherwise."""
    return "certified" if kind in _CERTIFIED_KINDS else "draft"


def schema_version_for_trust_level(trust_level: str) -> str:
    if trust_level == "certified":
        return "1.0"
    if trust_level == "inline":
        return "0.0"
    return "0.1"


def schema_version_for_kind(kind: str) -> str:
    return schema_version_for_trust_level(schema_trust_level_for_kind(kind))


def _iso8601_from_timestamp_ms(timestamp_ms: int) -> str:
    return (
        datetime.fromtimestamp(max(0, timestamp_ms) / 1000.0, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ── Concrete, config-driven builder ───────────────────────────────────────────


class L9HeaderBuilder:
    """Concrete L9 header builder, parameterised by per-protocol lookup tables.

    Every protocol (CIP, SIEP, …) constructs one instance with its own
    vocabulary — no subclassing needed:

        _BUILDER = L9HeaderBuilder(
            subprotocol="CIP",
            kind_by_event_type=_KIND_BY_EVENT_TYPE,
            schema_topic_by_event_type=_SCHEMA_TOPIC_BY_EVENT_TYPE,
            default_epistemic_by_event_type=_DEFAULT_EPISTEMIC,
            short_ttl_event_types=_SHORT_TTL_EVENT_TYPES,
        )

    :param subprotocol: Default ``header.subprotocol`` value (e.g. ``"CIP"``).
    :param kind_by_event_type: Canonical event_type → SSTP ``kind`` mapping.
    :param event_type_aliases: Optional alias/synonym → canonical event_type map.
    :param schema_topic_by_event_type: Canonical event_type → ``(area, topic)``
        tuple used to build ``context.semantic.schema_id``. Event types not
        present fall back to ``(default_schema_area, event_type)``.
    :param default_schema_area: Fallback schema area (default ``"coordination"``).
    :param default_epistemic_by_event_type: Canonical event_type → pre-built
        epistemic block dict (e.g. via ``make_epistemic_block``), used when the
        caller does not pass an explicit ``epistemic=`` block to :meth:`build`.
    :param default_epistemic: Fallback epistemic block for event types not
        present in ``default_epistemic_by_event_type``.
    :param short_ttl_event_types: Event types considered short-lived by
        :meth:`ttl_for_event_type`.
    :param default_kind: Fallback ``kind`` for unmapped event types.
    """

    PROTOCOL: str = "SSTP"

    def __init__(
        self,
        *,
        subprotocol: str,
        kind_by_event_type: Dict[str, str],
        event_type_aliases: "Dict[str, str] | None" = None,
        schema_topic_by_event_type: "Dict[str, tuple] | None" = None,
        default_schema_area: str = "coordination",
        default_epistemic_by_event_type: "Dict[str, Dict[str, Any]] | None" = None,
        default_epistemic: "Dict[str, Any] | None" = None,
        short_ttl_event_types: frozenset = frozenset(),
        default_kind: str = "exchange",
        version: str = L9_VERSION,
    ) -> None:
        self.subprotocol = subprotocol
        self.VERSION = version
        self._kind_by_event_type = dict(kind_by_event_type)
        self._event_type_aliases = dict(event_type_aliases or {})
        self._schema_topic_by_event_type = dict(schema_topic_by_event_type or {})
        self._default_schema_area = default_schema_area
        self._default_epistemic_by_event_type = dict(default_epistemic_by_event_type or {})
        self._default_epistemic = default_epistemic
        self._short_ttl_event_types = frozenset(short_ttl_event_types)
        self._default_kind = default_kind

    def canonical_event_type(self, event_type: str) -> str:
        """Resolve an alias/synonym to its canonical event_type."""
        candidate = str(event_type).strip().lower()
        return self._event_type_aliases.get(candidate, candidate)

    def kind_for_event_type(self, event_type: str) -> str:
        return self._kind_by_event_type.get(self.canonical_event_type(event_type), self._default_kind)

    def schema_id_for(self, use_case: str, event_type: str, kind: str, schema_trust_level: str) -> str:
        normalized_use_case = normalize_use_case(use_case)
        canonical = self.canonical_event_type(event_type)
        area, topic = self._schema_topic_by_event_type.get(canonical, (self._default_schema_area, canonical))
        version = schema_version_for_kind(kind)
        if schema_trust_level == "certified":
            return f"urn:ioc:{normalized_use_case}:{area}:{topic}:v{version}"
        return f"urn:ioc:draft:{normalized_use_case}:{area}:{topic}:v{version}"

    def ttl_for_event_type(self, event_type: str) -> int:
        return 86400 if self.canonical_event_type(event_type) in self._short_ttl_event_types else 604800

    def build(
        self,
        *,
        use_case: str,
        event_type: str,
        sender: str,
        receiver: str | None,
        timestamp_ms: int,
        sensitivity: str = "internal",
        propagation: str = "restricted",
        utterance: str = "",
        parent_ids: Iterable[str] | None = None,
        episode_id: str | None = None,
        provenance_sources: Iterable[str] | None = None,
        provenance_expiry: str | None = None,
        message_id: str | None = None,
        ontology_ref: str | None = None,
        subprotocol: str | None = None,
        epistemic: Dict[str, Any] | None = None,
        topic: str | None = None,
        kind_override: str | None = None,
        subkind: str | None = None,
        sequence_number: int | None = None,
        payload_parts: "List[Dict[str, Any]] | None" = None,
        role: "str | None" = None,
        recipients: "List[str] | None" = None,
    ) -> Dict[str, Any]:
        normalized_use_case = normalize_use_case(use_case)
        canonical_type = self.canonical_event_type(event_type)
        kind = kind_override or self._kind_by_event_type.get(canonical_type, self._default_kind)

        if epistemic is None:
            default_block = self._default_epistemic_by_event_type.get(canonical_type, self._default_epistemic)
            epistemic = dict(default_block) if default_block is not None else None

        if ":" in kind:
            kind, _auto_subkind = kind.split(":", 1)
            if subkind is None:
                subkind = _auto_subkind

        trust_level = schema_trust_level_for_kind(kind)
        effective_subprotocol = subprotocol if subprotocol is not None else self.subprotocol

        derived_message_id = message_id or str(_uuid.uuid4())

        parent_id_list = [str(i) for i in (parent_ids or []) if i]
        source_list = [str(i) for i in (provenance_sources or []) if i]

        sender_id = str(sender or "unknown")
        sender_role = role or sender_id
        # Build the full recipient set: explicit recipients list takes precedence;
        # if omitted but a single receiver is named, auto-include it so the actors
        # list always reflects the actual addressees of the message.
        _recipient_ids = list(recipients) if recipients is not None else (
            [str(receiver)] if receiver and str(receiver) != sender_id else []
        )
        recipient_actors = [
            {"id": r, "role": r, "participant_type": "recipient", "attestation": None}
            for r in _recipient_ids
            if r != sender_id
        ]

        header: Dict[str, Any] = {
            "protocol":    self.PROTOCOL,
            "version":     self.VERSION,
            "kind":        kind,
            "subprotocol": effective_subprotocol,
            "subkind":     subkind,
            "participants": {
                "actors": [
                    {"id": sender_id, "role": sender_role, "participant_type": "sender", "attestation": "self_attested_local"},
                    *recipient_actors,
                ],
                "groups": None,
            },
            "message": {
                "id":      derived_message_id,
                "parents": parent_id_list,
                "episode": episode_id or f"urn:ioc:{normalized_use_case}:state:shared_dialogue",
            },
            "context": {
                "topic":    topic or None,
                "epistemic": epistemic,
                "semantic": {
                    "schema_id":    self.schema_id_for(
                        normalized_use_case, canonical_type, kind, trust_level
                    ),
                    "ontology_ref": ontology_ref,
                },
            },
            "policy": {
                "sensitivity":      sensitivity,
                "propagation":      propagation,
                "retention_policy": f"policy.{normalized_use_case}.default",
            },
            "attributes": {
                "msg_sources":    source_list,
                "msg_transforms": [],
                "msg_created":    _iso8601_from_timestamp_ms(timestamp_ms),
                "msg_expiry":     provenance_expiry,
            },
            "payload":   list(payload_parts) if payload_parts is not None else [],
        }

        return header


__all__ = [
    "L9_PROTOCOL",
    "L9_VERSION",
    "_SCHEMA_TRUST_LEVELS",
    "normalize_use_case",
    "schema_trust_level_for_kind",
    "schema_version_for_trust_level",
    "schema_version_for_kind",
    "L9HeaderBuilder",
]

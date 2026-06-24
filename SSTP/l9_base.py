# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/l9_base.py — Generic L9 header builder base class.

Defines the common L9 envelope structure and the abstract ``L9HeaderBuilder``
base class that all protocol specialisations (SNP/SIEP, IE/CIP, …) subclass.

Protocol specialisations live in sub-packages:

- ``SSTP.subprotocol.siep`` — Semantic Interaction & Epistemic Protocol (SNP)
- ``SSTP.subprotocol.cip``  — Contingency & Interaction Protocol (IE)

Adding a new protocol
---------------------
1. Create ``SSTP/subprotocol/<name>/src/l9.py``.
2. Subclass ``L9HeaderBuilder``.
3. Implement ``kind_for_event_type``, ``schema_id_for``, and optionally
   ``ttl_for_event_type``.
4. Expose a module-level convenience function that calls ``self.build(...)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List
import uuid as _uuid


# ── Wire-level constants ──────────────────────────────────────────────────────


L9_PROTOCOL: str = "SSTP"
L9_VERSION: str = "0"

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


# ── Abstract base class ───────────────────────────────────────────────────────


class L9HeaderBuilder:
    """Abstract base for L9 protocol header building.

    Subclass for each protocol (SIEP/SNP, CIP/IE, …).  Subclasses must
    implement :meth:`kind_for_event_type` and :meth:`schema_id_for`.
    """

    PROTOCOL: str = "SSTP"
    VERSION: str = L9_VERSION

    def kind_for_event_type(self, event_type: str) -> str:
        raise NotImplementedError(f"{type(self).__name__} must implement kind_for_event_type")

    def schema_id_for(self, use_case: str, event_type: str, kind: str, schema_trust_level: str) -> str:
        raise NotImplementedError(f"{type(self).__name__} must implement schema_id_for")

    def ttl_for_event_type(self, event_type: str) -> int:
        return 604800

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
        canonical_type = str(event_type).strip().lower()
        kind = kind_override or self.kind_for_event_type(canonical_type)

        if ":" in kind:
            kind, _auto_subkind = kind.split(":", 1)
            if subkind is None:
                subkind = _auto_subkind

        trust_level = schema_trust_level_for_kind(kind)
        effective_subprotocol = subprotocol

        derived_message_id = message_id or str(_uuid.uuid4())

        parent_id_list = [str(i) for i in (parent_ids or []) if i]
        source_list = [str(i) for i in (provenance_sources or []) if i]

        sender_id = str(sender or "unknown")
        sender_role = role or sender_id
        recipient_actors = [
            {"id": r, "role": r, "attestation": None}
            for r in (recipients or [])
            if r != sender_id
        ]

        header: Dict[str, Any] = {
            "protocol":    self.PROTOCOL,
            "version":     self.VERSION,
            "kind":        kind,
            "subprotocol": effective_subprotocol,
            "subkind":     subkind,
            "topic":       topic or None,
            "participants": {
                "actors": [
                    {"id": sender_id, "role": sender_role, "attestation": "self_attested_local"},
                    *recipient_actors,
                ],
                "groups": None,
            },
            "message": {
                "id":      derived_message_id,
                "parents": parent_id_list,
                "episode": episode_id or f"urn:ioc:{normalized_use_case}:state:shared_dialogue",
            },
            "semantic": {
                "schema_id":    self.schema_id_for(
                    normalized_use_case, canonical_type, kind, trust_level
                ),
                "ontology_ref": ontology_ref,
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
            "epistemic": epistemic,
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

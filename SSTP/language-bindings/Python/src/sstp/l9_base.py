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

_CERTIFIED_KINDS: frozenset = frozenset({"commit:converged", "commit:abort"})

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

    ``"certified"`` for stable kinds (``commit``),
    ``"draft"`` for all others.
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
    sequence_number: int | None = None,
) -> str:
    # Spec §6.4: 8-field seed — use_case|event_type|sender|receiver|sequence_number|turn_depth|utterance|timestamp_ms
    return "|".join(
        [
            normalize_use_case(use_case),
            str(event_type).strip().lower(),
            str(sender or "unknown"),
            str(receiver or "none"),
            str(sequence_number if sequence_number is not None else "none"),
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
                return {"foo_event": "intent", "bar_event": "commit:converged"}.get(event_type, "knowledge")

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
        sensitivity: str = "internal",
        propagation: str = "restricted",
        utterance: str = "",
        parent_ids: Iterable[str] | None = None,
        episode_id: str | None = None,
        provenance_sources: Iterable[str] | None = None,
        provenance_expiry: str | None = None,
        message_id: str | None = None,
        ontology_ref: str | None = None,
        sub_protocol: str | None = None,
        epistemic: Dict[str, Any] | None = None,
        kind_override: str | None = None,
        subkind: str | None = None,
        sequence_number: int | None = None,
        payload_parts: "List[Dict[str, Any]] | None" = None,
        # Deprecated params — accepted but ignored for backwards compat
        turn_depth: int | None = None,
        payload_refs: "Any | None" = None,
        state_sequence: "Any | None" = None,
        conversation_id: str | None = None,
        cognition_protocol: str | None = None,
        provenance_transforms: "Any | None" = None,
        group: "Any | None" = None,
    ) -> Dict[str, Any]:
        """Assemble the L9 envelope dict per the current wire format.

        New wire shape (2026 revision):
          protocol, version, kind, subkind
          actors    — list of {id, attestation} for senders
          message   — {id, parents, episode}
          semantic  — {schema_id, ontology_ref, sub_protocol}
          policy    — {sensitivity, propagation, retention_policy}
          attributes — {msg_sources, msg_transforms, msg_created, msg_expiry}
          epistemic — {speech_act, state, belief_status, concept_id, uncertainty}
          payload   — list of PayloadPart: [{type, location, content|ref}]

        Group membership is a transport concern (pub-sub topic subscription).
        It is not carried in the L9 header.

        ``payload_parts`` declares the payload parts carried by this message.
        ``kind_override`` bypasses the event-type-to-kind mapping.
        ``subkind`` is supportive of kind: "converged" | "abort" | null.
        ``sub_protocol`` identifies the sub-protocol: "IE" | "SNP".
        ``provenance_expiry`` is an ISO 8601 UTC string or null.
        """
        normalized_use_case = normalize_use_case(use_case)
        canonical_type = str(event_type).strip().lower()
        kind = kind_override or self.kind_for_event_type(canonical_type)
        trust_level = schema_trust_level_for_kind(kind)

        # backwards compat: cognition_protocol falls back to sub_protocol
        effective_sub_protocol = sub_protocol or cognition_protocol

        derived_message_id = message_id or str(
            uuid5(
                NAMESPACE_URL,
                _message_id_seed(
                    use_case=normalized_use_case,
                    event_type=canonical_type,
                    sender=sender,
                    receiver=receiver,
                    turn_depth=None,
                    utterance=utterance,
                    timestamp_ms=timestamp_ms,
                    sequence_number=sequence_number,
                ),
            )
        )

        parent_id_list = [str(i) for i in (parent_ids or []) if i]
        source_list = [str(i) for i in (provenance_sources or []) if i]

        header: Dict[str, Any] = {
            "protocol": self.PROTOCOL,
            "version":  self.VERSION,
            "kind":     kind,
            "subkind":  subkind,
            "actors":   [{"id": str(sender or "unknown"), "attestation": "self_attested_local"}],
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
                "sub_protocol": effective_sub_protocol,
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

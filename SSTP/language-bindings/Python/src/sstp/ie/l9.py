# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
protocol/ie/l9.py — Interaction Engine specialisation of the L9 header builder.

SSTP L9 headers are carried inside Interaction Engine protocol events.
The wire envelope is governed by ``interaction_engine_protocol v1.0.0``
(schema: protocol/ie/interaction_engine_protocol.schema.json).
This module constructs and validates the ``l9_header`` field within those
envelopes; it does not define the envelope fields themselves.

The :class:`IEL9HeaderBuilder` subclasses :class:`~protocol.l9_base.L9HeaderBuilder`
and maps IE event types to SSTP kinds (5-value session-flow vocabulary):

    turn_ingested           → exchange
    peer_turn               → exchange
    repair_required         → contingency
    repair_applied          → commit
    epistemic_clarification → contingency
    decision_emitted        → commit      (terminal SNP decision; closes contingency branch)
    episode_persisted       → commit
    conversation_terminated → commit
    rule_update             → knowledge   (team-level grounded truth written to SemanticMemory)
    prior_query             → exchange
    prior_injection         → exchange
    outcome_reported        → exchange

The module-level :func:`build_l9_header` is the backwards-compatible
convenience function used by IE orchestrators.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from sstp.epistemic.vocabulary import SpeechAct, TaskPhase, make_epistemic_block
from sstp.l9_base import (
    L9HeaderBuilder,
    normalize_use_case,
    schema_trust_level_for_kind,
    schema_version_for_kind,
)

# ── IE protocol identifiers ───────────────────────────────────────────────────

INTERACTION_ENGINE_PROTOCOL: str = "interaction_engine_protocol"
INTERACTION_ENGINE_PROTOCOL_VERSION: str = "1.0.0"

# ── IE event-type mappings ────────────────────────────────────────────────────

_EVENT_TYPE_ALIASES: Dict[str, str] = {
    "message": "peer_turn",
    "peer_repair": "repair_applied",
    "repair_applied": "repair_applied",
    "conversation_terminated": "conversation_terminated",
}

_KIND_BY_EVENT_TYPE: Dict[str, str] = {
    "turn_ingested":           "exchange",
    "peer_turn":               "exchange",
    "repair_required":         "contingency",
    "repair_applied":          "commit:converged",
    "decision_emitted":        "commit:converged",
    "episode_persisted":       "commit:converged",
    "conversation_terminated": "commit:converged",
    "epistemic_clarification": "contingency",
    # SemanticMemory interactions (Coordinator ↔ SemanticMemory agent)
    "prior_query":             "exchange",
    "prior_injection":         "exchange",
    "rule_update":             "knowledge",
    "outcome_reported":        "exchange",
}

_SCHEMA_TOPIC_BY_EVENT_TYPE: Dict[str, tuple[str, str]] = {
    "turn_ingested":           ("intake", "turn"),
    "peer_turn":               ("coordination", "peer_message"),
    "repair_required":         ("coordination", "repair_request"),
    "repair_applied":          ("coordination", "repair_message"),
    "decision_emitted":        ("coordination", "decision"),
    "episode_persisted":       ("memory", "episode_commit"),
    "conversation_terminated": ("coordination", "termination_notice"),
    "epistemic_clarification": ("coordination", "epistemic_repair"),
    # SemanticMemory interactions
    "prior_query":             ("memory", "prior_query"),
    "prior_injection":         ("memory", "prior_injection"),
    "rule_update":             ("memory", "rule_update"),
    "outcome_reported":        ("memory", "outcome_reported"),
}

# Default (SpeechAct, TaskPhase) per IE event_type — used when caller passes epistemic=None.
_IE_DEFAULT_EPISTEMIC: Dict[str, tuple] = {
    "turn_ingested":           (SpeechAct.BELIEF_ASSERTION, TaskPhase.TASKWORK),
    "peer_turn":               (SpeechAct.BELIEF_ASSERTION, TaskPhase.ACTION),
    "repair_required":         (SpeechAct.HELP_REQUEST,     TaskPhase.INTERPERSONAL),
    "repair_applied":          (SpeechAct.BELIEF_ASSERTION, TaskPhase.INTERPERSONAL),
    "decision_emitted":        (SpeechAct.BELIEF_ASSERTION, TaskPhase.ACTION),
    "episode_persisted":       (SpeechAct.BELIEF_ASSERTION, TaskPhase.TASKWORK),
    "epistemic_clarification": (SpeechAct.HELP_REQUEST,     TaskPhase.INTERPERSONAL),
    # SemanticMemory interactions — all TASKWORK (pre-episode priors and post-episode updates)
    "prior_query":             (SpeechAct.HELP_REQUEST,     TaskPhase.TASKWORK),
    "prior_injection":         (SpeechAct.BELIEF_ASSERTION, TaskPhase.TASKWORK),
    "rule_update":             (SpeechAct.BELIEF_ASSERTION, TaskPhase.TASKWORK),
    "outcome_reported":        (SpeechAct.BELIEF_ASSERTION, TaskPhase.TASKWORK),
}

# Short-TTL event types (1 day instead of the 7-day default)
_SHORT_TTL_EVENT_TYPES: frozenset = frozenset(
    {"peer_turn", "repair_required", "repair_applied", "epistemic_clarification"}
)


# ── IE-specific helper functions ──────────────────────────────────────────────


def canonical_event_type(event_type: str) -> str:
    """Normalise an IE event_type string, resolving aliases."""
    candidate = str(event_type).strip().lower()
    return _EVENT_TYPE_ALIASES.get(candidate, candidate)


def kind_for_event_type(event_type: str) -> str:
    """Return the SSTP kind for an IE event_type string."""
    return _KIND_BY_EVENT_TYPE.get(canonical_event_type(event_type), "exchange")


def schema_id_for(
    use_case: str,
    event_type: str,
    kind: str,
    schema_trust_level: str,
) -> str:
    """Return the canonical schema URN for an IE (use_case, event_type, kind)."""
    normalized_use_case = normalize_use_case(use_case)
    area, topic = _SCHEMA_TOPIC_BY_EVENT_TYPE.get(
        canonical_event_type(event_type), ("coordination", kind)
    )
    version = schema_version_for_kind(kind)
    if schema_trust_level == "certified":
        return f"urn:ioc:{normalized_use_case}:{area}:{topic}:v{version}"
    return f"urn:ioc:draft:{normalized_use_case}:{area}:{topic}:v{version}"


# ── IEL9HeaderBuilder ─────────────────────────────────────────────────────────


class IEL9HeaderBuilder(L9HeaderBuilder):
    """Interaction Engine specialisation of :class:`~protocol.l9_base.L9HeaderBuilder`.

    Maps IE event types to SSTP kinds and derives IE-specific schema URNs.
    Instantiate once or use the module-level :func:`build_l9_header` convenience
    function.
    """

    def kind_for_event_type(self, event_type: str) -> str:
        return kind_for_event_type(event_type)

    def schema_id_for(
        self,
        use_case: str,
        event_type: str,
        kind: str,
        schema_trust_level: str,
    ) -> str:
        return schema_id_for(use_case, event_type, kind, schema_trust_level)

    def ttl_for_event_type(self, event_type: str) -> int:
        return 86400 if event_type in _SHORT_TTL_EVENT_TYPES else 604800

    def build(  # type: ignore[override]
        self,
        *,
        use_case: str,
        event_type: str,
        sender: str,
        receiver: str | None,
        timestamp_ms: int,
        cognition_protocol: str | None = "IE",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Build an IE L9 header, normalising the event_type alias first.

        If epistemic is not provided by the caller, a default block is inferred
        from the event_type. Callers may pass an explicit epistemic block to
        override the default (e.g. for a response peer_turn carrying TASKWORK vs ACTION).
        """
        canonical = canonical_event_type(event_type)
        if kwargs.get("epistemic") is None:
            sa, tp = _IE_DEFAULT_EPISTEMIC.get(
                canonical, (SpeechAct.BELIEF_ASSERTION, TaskPhase.ACTION)
            )
            kwargs["epistemic"] = make_epistemic_block(speech_act=sa, task_phase=tp)
        return super().build(
            use_case=use_case,
            event_type=canonical,
            sender=sender,
            receiver=receiver,
            timestamp_ms=timestamp_ms,
            cognition_protocol=cognition_protocol,
            **kwargs,
        )


# ── Module-level convenience function (backwards-compatible public API) ───────

_DEFAULT_BUILDER = IEL9HeaderBuilder()


def build_l9_header(
    *,
    use_case: str,
    event_type: str,
    sender: str,
    receiver: str | None,
    timestamp_ms: int,
    sensitivity: str = "internal",
    propagation: str = "restricted",
    turn_depth: int | None = None,
    utterance: str = "",
    parent_ids: Iterable[str] | None = None,
    episode_id: str | None = None,
    provenance_sources: Iterable[str] | None = None,
    payload_refs: List[Dict[str, str]] | None = None,
    message_id: str | None = None,
    ontology_ref: str | None = None,
    cognition_protocol: str | None = "IE",
    epistemic: Dict[str, Any] | None = None,
    state_sequence: Dict[str, Any] | None = None,
    kind_override: str | None = None,
    conversation_id: str | None = None,
    sequence_number: int | None = None,
) -> Dict[str, Any]:
    """Build an Interaction Engine SSTP L9 header dict.

    Convenience wrapper around :class:`IEL9HeaderBuilder`.  This is the
    function called by IE orchestrators to stamp each event with an SSTP
    L9 header.

    ``event_type`` is normalised via :func:`canonical_event_type` so
    aliases like ``"message"`` resolve correctly.

    The returned dict includes these envelope fields:

    ``message_id`` — UUID (UUIDv5 derived from event inputs, or caller-
        supplied).  The sole message identifier on the wire.  There is no
        sequence number or Lamport clock in the IE L9 header.

    ``dt_created`` — ISO 8601 wall-clock timestamp (UTC) derived from
        ``timestamp_ms``.  Intended for audit and observability only;
        no ordering or monotonicity is guaranteed.

    ``parent_ids`` — list of ``message_id`` values for RPC pairing
        (response carries its request's id).  Causal repair links
        (``repair_applied`` → ``peer_turn``) are carried in the event
        payload's ``repair.trigger_message_id`` field, not here.

    All other envelope fields (``kind``, ``schema_id``, ``cognition_protocol``,
    ``ttl_seconds``, ``origin``, ``policy_labels``, ``provenance``,
    ``episode_id``, ``payload_refs``) are derived
    automatically from the event type and use-case.
    """
    return _DEFAULT_BUILDER.build(
        use_case=use_case,
        event_type=event_type,
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        sensitivity=sensitivity,
        propagation=propagation,
        turn_depth=turn_depth,
        utterance=utterance,
        parent_ids=parent_ids,
        episode_id=episode_id,
        provenance_sources=provenance_sources,
        payload_refs=payload_refs,
        message_id=message_id,
        ontology_ref=ontology_ref,
        cognition_protocol=cognition_protocol,
        epistemic=epistemic,
        state_sequence=state_sequence,
        kind_override=kind_override,
        conversation_id=conversation_id,
        sequence_number=sequence_number,
    )


__all__ = [
    "INTERACTION_ENGINE_PROTOCOL",
    "INTERACTION_ENGINE_PROTOCOL_VERSION",
    "canonical_event_type",
    "kind_for_event_type",
    "schema_id_for",
    "IEL9HeaderBuilder",
    "build_l9_header",
]

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/subprotocol/cip/src/l9.py — CIP event-type vocabulary for the L9 header builder.

CIP (Contingency & Interaction Protocol) L9 config — maps CIP event types
to SSTP kinds/schema topics/epistemic defaults and constructs a single
``L9HeaderBuilder`` instance (see ``SSTP.l9_base``) from that vocabulary.
No subclassing is required — the builder is generic, this module only
supplies data.

Maps CIP/IE event types to SSTP kinds (5-value session-flow vocabulary):

    turn_ingested           → exchange
    peer_turn               → exchange
    repair_required         → contingency
    repair_applied          → commit
    epistemic_clarification → contingency
    decision_emitted        → commit
    episode_persisted       → commit
    conversation_terminated → commit
    rule_update             → knowledge
    prior_query             → exchange
    initial_prior           → exchange
    outcome_reported        → exchange
    process_proposed        → exchange
    process_accepted        → commit
    process_challenged      → contingency

The module-level :func:`build_l9_header` is the backwards-compatible
convenience function used by CIP/IE orchestrators.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from SSTP.subprotocol.siep.src.epistemic.vocabulary import SpeechAct, EpistemicState, make_epistemic_block
from SSTP.l9_base import L9HeaderBuilder

# ── CIP protocol identifiers ─────────────────────────────────────────────────

CIP_PROTOCOL: str = "interaction_engine_protocol"
CIP_PROTOCOL_VERSION: str = "1.0.0"

# ── CIP event-type mappings ──────────────────────────────────────────────────

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
    "repair_applied":          "commit",
    "decision_emitted":        "commit",
    "episode_persisted":       "commit",
    "conversation_terminated": "commit",
    "epistemic_clarification": "contingency",
    "process_proposed":        "exchange",
    "process_accepted":        "commit",
    "process_challenged":      "contingency",
    "prior_query":             "exchange",
    "initial_prior":           "exchange",
    "rule_update":             "knowledge",
    "outcome_reported":        "exchange",
}

_SCHEMA_TOPIC_BY_EVENT_TYPE: Dict[str, tuple] = {
    "turn_ingested":           ("intake",        "turn"),
    "peer_turn":               ("coordination",  "peer_message"),
    "repair_required":         ("coordination",  "repair_request"),
    "repair_applied":          ("coordination",  "repair_message"),
    "decision_emitted":        ("coordination",  "decision"),
    "episode_persisted":       ("memory",        "episode_commit"),
    "conversation_terminated": ("coordination",  "termination_notice"),
    "epistemic_clarification": ("coordination",  "epistemic_repair"),
    "process_proposed":        ("coordination",  "process_proposal"),
    "process_accepted":        ("coordination",  "process_acceptance"),
    "process_challenged":      ("coordination",  "process_challenge"),
    "prior_query":             ("memory",        "prior_query"),
    "initial_prior":           ("memory",        "initial_prior"),
    "rule_update":             ("memory",        "rule_update"),
    "outcome_reported":        ("memory",        "outcome_reported"),
}

_CIP_DEFAULT_EPISTEMIC: Dict[str, tuple] = {
    "turn_ingested":           (SpeechAct.ASSERTION, EpistemicState.TASKWORK),
    "peer_turn":               (SpeechAct.ASSERTION, EpistemicState.GROUNDING),
    "repair_required":         (SpeechAct.ASSERTION, EpistemicState.GROUNDING),
    "repair_applied":          (SpeechAct.ASSERTION, EpistemicState.GROUNDING),
    "decision_emitted":        (SpeechAct.ASSERTION, EpistemicState.GROUNDING),
    "episode_persisted":       (SpeechAct.ASSERTION, EpistemicState.TASKWORK),
    "epistemic_clarification": (SpeechAct.ASSERTION, EpistemicState.GROUNDING),
    "process_proposed":        (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS),
    "process_accepted":        (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS),
    "process_challenged":      (SpeechAct.CHALLENGE, EpistemicState.TEAM_PROCESS),
    "prior_query":             (SpeechAct.ASSERTION, EpistemicState.TASKWORK),
    "initial_prior":           (SpeechAct.ASSERTION, EpistemicState.TASKWORK),
    "rule_update":             (SpeechAct.ASSERTION, EpistemicState.TASKWORK),
    "outcome_reported":        (SpeechAct.ASSERTION, EpistemicState.TASKWORK),
}

_SHORT_TTL_EVENT_TYPES: frozenset = frozenset(
    {"peer_turn", "repair_required", "repair_applied", "epistemic_clarification"}
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def canonical_event_type(event_type: str) -> str:
    candidate = str(event_type).strip().lower()
    return _EVENT_TYPE_ALIASES.get(candidate, candidate)


def kind_for_event_type(event_type: str) -> str:
    return _BUILDER.kind_for_event_type(event_type)


def schema_id_for(use_case: str, event_type: str, kind: str, schema_trust_level: str) -> str:
    return _BUILDER.schema_id_for(use_case, event_type, kind, schema_trust_level)


def get_topic(header: Dict[str, Any]) -> "str | None":
    """Return the topic concept_id from an L9 header."""
    ctx = header.get("context") or {}
    return ctx.get("topic") or (ctx.get("epistemic") or {}).get("concept_id")


# ── CIP L9HeaderBuilder instance ─────────────────────────────────────────────

# Pre-built epistemic blocks per event type (module load time — pure/stateless).
_DEFAULT_EPISTEMIC_BY_EVENT_TYPE: Dict[str, Dict[str, Any]] = {
    event_type: make_epistemic_block(speech_act=sa, epistemic_state=es)
    for event_type, (sa, es) in _CIP_DEFAULT_EPISTEMIC.items()
}

_BUILDER = L9HeaderBuilder(
    subprotocol="CIP",
    kind_by_event_type=_KIND_BY_EVENT_TYPE,
    event_type_aliases=_EVENT_TYPE_ALIASES,
    schema_topic_by_event_type=_SCHEMA_TOPIC_BY_EVENT_TYPE,
    default_epistemic_by_event_type=_DEFAULT_EPISTEMIC_BY_EVENT_TYPE,
    default_epistemic=make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING
    ),
    short_ttl_event_types=_SHORT_TTL_EVENT_TYPES,
    default_kind="exchange",
)


# ── Module-level convenience function ────────────────────────────────────────

_DEFAULT_BUILDER = _BUILDER


def build_l9_header(
    *,
    use_case: str,
    event_type: str,
    sender: str,
    receiver: "str | None",
    timestamp_ms: int,
    sensitivity: str = "internal",
    propagation: str = "restricted",
    utterance: str = "",
    parent_ids: "Iterable[str] | None" = None,
    episode_id: "str | None" = None,
    provenance_sources: "Iterable[str] | None" = None,
    payload_parts: "List[Dict[str, Any]] | None" = None,
    message_id: "str | None" = None,
    ontology_ref: "str | None" = None,
    subprotocol: "str | None" = "CIP",
    epistemic: "Dict[str, Any] | None" = None,
    topic: "str | None" = None,
    kind_override: "str | None" = None,
    sequence_number: "int | None" = None,
    role: "str | None" = None,
    recipients: "List[str] | None" = None,
) -> Dict[str, Any]:
    """Build a CIP/IE SSTP L9 header dict.

    Build a CIP L9 header dict with all SSTP.* namespace imports.
    """
    return _DEFAULT_BUILDER.build(
        use_case=use_case,
        event_type=event_type,
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        sensitivity=sensitivity,
        propagation=propagation,
        utterance=utterance,
        parent_ids=parent_ids,
        episode_id=episode_id,
        provenance_sources=provenance_sources,
        payload_parts=payload_parts,
        message_id=message_id,
        ontology_ref=ontology_ref,
        subprotocol=subprotocol,
        epistemic=epistemic,
        topic=topic,
        kind_override=kind_override,
        sequence_number=sequence_number,
        role=role,
        recipients=recipients,
    )


__all__ = [
    "CIP_PROTOCOL",
    "CIP_PROTOCOL_VERSION",
    "canonical_event_type",
    "kind_for_event_type",
    "schema_id_for",
    "get_topic",
    "build_l9_header",
]

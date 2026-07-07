# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/subprotocol/siep/src/l9.py — SIEP/SNP vocabulary for the L9 header builder.

SIEP (Semantic Interaction & Epistemic Protocol) L9 config — maps SNP
operations to SSTP event_types/kinds and constructs a single
``L9HeaderBuilder`` instance (see ``SSTP.l9_base``) from that vocabulary.
No subclassing is required — the builder is generic, this module only
supplies data plus the ``operation → event_type`` translation that SNP
needs on top of it (:func:`build_snp_l9_header`).

Maps SNP operations to SSTP event_types and then to SSTP kinds:

    propose / consider / evaluate / review / negotiate   → peer_turn  → exchange
    counter_proposal                                     → peer_turn  → contingency
    accept / reject                                      → decision_emitted → commit
    convergence_emitted                                  → convergence_emitted → commit

The module-level :func:`build_snp_l9_header` and :func:`build_snp_payload`
are the backwards-compatible public API used by PanelBus and StarNegotiation.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from SSTP.subprotocol.siep.src.epistemic.vocabulary import (
    SpeechAct,
    EpistemicState,
    make_epistemic_block,
)
from SSTP.l9_base import L9HeaderBuilder

# ── SNP/SIEP profile constants ────────────────────────────────────────────────

SNP_PROFILE: str = "semantic_negotiation"
SNP_ONTOLOGY_REFERENCE: str = "protocol/ontology/snp_ontology.ttl"

# ── SNP operation vocabulary ──────────────────────────────────────────────────


class NegotiationOperation:
    """SNP operation vocabulary."""

    PROPOSE = "propose"
    CONSIDER_PROPOSAL = "consider_proposal"
    EVALUATE_PROPOSAL = "evaluate_proposal"
    REVIEW_PROPOSAL = "review_proposal"
    COUNTER_PROPOSAL = "counter_proposal"
    ACCEPT = "accept"
    REJECT = "reject"
    NEGOTIATE = "negotiate"

    ALL: frozenset = frozenset({
        PROPOSE, CONSIDER_PROPOSAL, EVALUATE_PROPOSAL, REVIEW_PROPOSAL,
        COUNTER_PROPOSAL, ACCEPT, REJECT, NEGOTIATE,
    })
    TERMINAL: frozenset = frozenset({ACCEPT, REJECT})


class NegotiationStatus:
    """SNP status vocabulary."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    INCORPORATED = "incorporated"
    RESOLVED = "resolved"

    ALL: frozenset = frozenset({PENDING, REVIEWED, INCORPORATED, RESOLVED})


# ── Default epistemic blocks per operation ────────────────────────────────────

_SNP_DEFAULT_EPISTEMIC: Dict[str, tuple] = {
    NegotiationOperation.PROPOSE:           (SpeechAct.ASSERTION,  EpistemicState.TEAM_PROCESS),
    NegotiationOperation.CONSIDER_PROPOSAL: (SpeechAct.ASSERTION,  EpistemicState.TEAM_PROCESS),
    NegotiationOperation.EVALUATE_PROPOSAL: (SpeechAct.ASSERTION,  EpistemicState.TEAM_PROCESS),
    NegotiationOperation.REVIEW_PROPOSAL:   (SpeechAct.ASSERTION,  EpistemicState.TEAM_PROCESS),
    NegotiationOperation.COUNTER_PROPOSAL:  (SpeechAct.CHALLENGE,  EpistemicState.TEAM_PROCESS),
    NegotiationOperation.NEGOTIATE:         (SpeechAct.ASSERTION,  EpistemicState.TEAM_PROCESS),
    NegotiationOperation.ACCEPT:            (SpeechAct.ASSERTION,  EpistemicState.TEAM_PROCESS),
    NegotiationOperation.REJECT:            (SpeechAct.CHALLENGE,  EpistemicState.TEAM_PROCESS),
}

# ── SNP operation → SSTP event_type mapping ──────────────────────────────────

_SNP_OPERATION_TO_EVENT_TYPE: Dict[str, str] = {
    NegotiationOperation.PROPOSE:           "peer_turn",
    NegotiationOperation.CONSIDER_PROPOSAL: "peer_turn",
    NegotiationOperation.EVALUATE_PROPOSAL: "peer_turn",
    NegotiationOperation.REVIEW_PROPOSAL:   "peer_turn",
    NegotiationOperation.COUNTER_PROPOSAL:  "peer_turn",
    NegotiationOperation.NEGOTIATE:         "peer_turn",
    NegotiationOperation.ACCEPT:            "decision_emitted",
    NegotiationOperation.REJECT:            "decision_emitted",
}

_SNP_EVENT_TYPE_TO_KIND: Dict[str, str] = {
    "peer_turn":           "exchange",
    "decision_emitted":    "commit",
    "convergence_emitted": "commit",
}


def snp_event_type_for_operation(operation: str) -> str:
    op = operation.value if hasattr(operation, "value") else str(operation)
    result = _SNP_OPERATION_TO_EVENT_TYPE.get(op)
    if result is None:
        raise ValueError(f"Unknown SNP operation: {operation!r}")
    return result


# ── SNP payload builder ───────────────────────────────────────────────────────


def build_snp_payload(
    *,
    operation: str,
    proposal_id: str,
    content: str,
    status: str,
    negotiation_id: str | None = None,
    proposal_payload: Dict[str, Any] | None = None,
    posterior: Optional[float] = None,
    supporting_evidence: Optional[List[str]] = None,
    against_evidence: Optional[List[str]] = None,
    reasoning_summary: Optional[str] = None,
    addresses_evidence: Optional[List[str]] = None,
    deferred_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a NegotiationPayload for use inside an L9 message."""
    op = operation.value if hasattr(operation, "value") else str(operation)
    st = status.value if hasattr(status, "value") else str(status)
    if op not in NegotiationOperation.ALL:
        raise ValueError(f"Invalid SNP operation: {operation!r}")
    if st not in NegotiationStatus.ALL:
        raise ValueError(f"Invalid SNP status: {status!r}")
    out: Dict[str, Any] = {
        "profile": SNP_PROFILE,
        "operation": op,
        "proposal_id": proposal_id,
        "content": content,
        "status": st,
    }
    if negotiation_id is not None:
        out["negotiation_id"] = negotiation_id
    reasoning: Dict[str, Any] = {}
    if posterior is not None:
        reasoning["posterior"] = round(float(posterior), 4)
    if supporting_evidence:
        reasoning["supporting_evidence"] = list(supporting_evidence)
    if against_evidence:
        reasoning["against_evidence"] = list(against_evidence)
    if reasoning_summary:
        reasoning["reasoning_summary"] = str(reasoning_summary)
    if addresses_evidence:
        reasoning["addresses_evidence"] = list(addresses_evidence)
    if deferred_to:
        reasoning["deferred_to"] = str(deferred_to)
    merged = {**(proposal_payload or {}), **reasoning}
    if merged:
        out["proposal_payload"] = merged
    return out


# ── SIEP L9HeaderBuilder instance ────────────────────────────────────────────

_SNP_SHORT_TTL_EVENTS: frozenset = frozenset({"peer_turn", "repair_required", "repair_applied"})

_BUILDER = L9HeaderBuilder(
    subprotocol="SIEP",
    kind_by_event_type=_SNP_EVENT_TYPE_TO_KIND,
    default_schema_area="coordination",
    short_ttl_event_types=_SNP_SHORT_TTL_EVENTS,
    default_kind="exchange",
)


def build_snp(
    *,
    operation: str,
    use_case: str,
    sender: str,
    receiver: str | None,
    timestamp_ms: int,
    proposal_id: str,
    utterance: str = "",
    parent_ids: Iterable[str] | None = None,
    episode_id: str | None = None,
    provenance_sources: Iterable[str] | None = None,
    message_id: str | None = None,
    subprotocol: str | None = "SIEP",
    epistemic: Dict[str, Any] | None = None,
    topic: str | None = None,
    kind_override: str | None = None,
    sequence_number: int | None = None,
    payload_parts: List[Dict[str, Any]] | None = None,
    role: str | None = None,
    recipients: List[str] | None = None,
) -> Dict[str, Any]:
    """Build an L9 header for an SNP ``operation``.

    SNP's epistemic default is keyed by *operation* (propose/counter_proposal/
    accept/reject/…), which is finer-grained than the L9 ``event_type`` those
    operations collapse to (several operations map to the same ``peer_turn``
    event_type but carry different speech acts) — so that resolution happens
    here, one level above the generic, event-type-keyed ``L9HeaderBuilder``.
    """
    op = operation.value if hasattr(operation, "value") else str(operation)
    if epistemic is None:
        sa, es = _SNP_DEFAULT_EPISTEMIC.get(
            op, (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS)
        )
        epistemic = make_epistemic_block(speech_act=sa, epistemic_state=es)
    event_type = snp_event_type_for_operation(op)
    return _BUILDER.build(
        use_case=use_case,
        event_type=event_type,
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        utterance=utterance,
        parent_ids=parent_ids,
        episode_id=episode_id,
        provenance_sources=provenance_sources,
        ontology_ref=SNP_ONTOLOGY_REFERENCE,
        message_id=message_id,
        subprotocol=subprotocol,
        epistemic=epistemic,
        topic=topic,
        kind_override=kind_override,
        sequence_number=sequence_number,
        payload_parts=payload_parts,
        role=role,
        recipients=recipients,
    )


# ── Module-level convenience functions ───────────────────────────────────────

_DEFAULT_BUILDER = _BUILDER


def build_snp_l9_header(
    *,
    operation: str,
    use_case: str,
    sender: str,
    receiver: str | None,
    timestamp_ms: int,
    proposal_id: str,
    utterance: str = "",
    parent_ids: Iterable[str] | None = None,
    episode_id: str | None = None,
    provenance_sources: Iterable[str] | None = None,
    message_id: str | None = None,
    subprotocol: str | None = "SIEP",
    epistemic: Dict[str, Any] | None = None,
    topic: str | None = None,
    kind_override: str | None = None,
    sequence_number: int | None = None,
    payload_parts: List[Dict[str, Any]] | None = None,
    role: str | None = None,
    recipients: List[str] | None = None,
) -> Dict[str, Any]:
    """Build an SSTP L9 header for a SIEP/SNP message.

    Build a SIEP L9 header dict with all SSTP.* namespace imports.
    """
    return build_snp(
        operation=operation,
        use_case=use_case,
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        proposal_id=proposal_id,
        utterance=utterance,
        parent_ids=parent_ids,
        episode_id=episode_id,
        provenance_sources=provenance_sources,
        message_id=message_id,
        subprotocol=subprotocol,
        epistemic=epistemic,
        topic=topic,
        kind_override=kind_override,
        sequence_number=sequence_number,
        payload_parts=payload_parts,
        role=role,
        recipients=recipients,
    )


__all__ = [
    "SNP_PROFILE",
    "SNP_ONTOLOGY_REFERENCE",
    "NegotiationOperation",
    "NegotiationStatus",
    "snp_event_type_for_operation",
    "build_snp_payload",
    "build_snp",
    "build_snp_l9_header",
]

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
protocol/snp/l9.py — Semantic Negotiation Protocol specialisation of the L9 header builder.

SNP is a negotiation profile that runs on top of the SSTP envelope.
Full specification: protocol/snp/SEMANTIC_NEGOTIATION_PROTOCOL.md

:class:`SNPL9HeaderBuilder` subclasses :class:`~protocol.l9_base.L9HeaderBuilder`
and maps SNP operation vocabulary (§1.1) to SSTP event_types and then to SSTP kinds:

    propose / consider_proposal / evaluate_proposal / …  → peer_turn   → delegation
    accept / reject                                       → decision_emitted → commit

Rule: SNP does NOT add new SSTP base kinds.  Negotiation semantics are
represented at the payload level via an ``operation`` field.

The module-level :func:`build_snp_l9_header` and :func:`build_snp_payload`
are the backwards-compatible public API used by the semantic_negotiation package.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sstp.epistemic.vocabulary import SpeechAct, TaskPhase, make_epistemic_block
from sstp.l9_base import (
    L9HeaderBuilder,
    L9_PROTOCOL,
    L9_VERSION,
    normalize_use_case,
    schema_trust_level_for_kind,
    schema_version_for_kind,
)

# Re-export base constants so existing `from sstp.snp.l9 import L9_PROTOCOL`
# imports continue to work.
__all_base__ = [L9_PROTOCOL, L9_VERSION, normalize_use_case]

# ── SNP profile constants ─────────────────────────────────────────────────────

SNP_PROFILE: str = "semantic_negotiation"
SNP_ONTOLOGY_REFERENCE: str = "protocol/ontology/snp_ontology.ttl"

# ── SNP operation vocabulary ──────────────────────────────────────────────────

# Default (SpeechAct, TaskPhase) per SNP operation — used when caller passes epistemic=None.
# ACCEPT defaults to ACTION/genuine; callers with confidence context should pass an
# explicit block via infer_snp_epistemic() to get DELIBERATION_PASS/INTERPERSONAL if forced.
_SNP_DEFAULT_EPISTEMIC: Dict[str, tuple] = {}  # populated after NegotiationOperation is defined


class NegotiationOperation:
    """SNP operation vocabulary (§1.1 of SEMANTIC_NEGOTIATION_PROTOCOL.md)."""

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


_SNP_DEFAULT_EPISTEMIC = {
    NegotiationOperation.PROPOSE:           (SpeechAct.BELIEF_ASSERTION,    TaskPhase.TRANSITION),
    NegotiationOperation.CONSIDER_PROPOSAL: (SpeechAct.BELIEF_ASSERTION,    TaskPhase.ACTION),
    NegotiationOperation.EVALUATE_PROPOSAL: (SpeechAct.BELIEF_ASSERTION,    TaskPhase.ACTION),
    NegotiationOperation.REVIEW_PROPOSAL:   (SpeechAct.BELIEF_ASSERTION,    TaskPhase.ACTION),
    NegotiationOperation.COUNTER_PROPOSAL:  (SpeechAct.ALIGNMENT_CHALLENGE, TaskPhase.INTERPERSONAL),
    NegotiationOperation.NEGOTIATE:         (SpeechAct.BELIEF_ASSERTION,    TaskPhase.ACTION),
    NegotiationOperation.ACCEPT:            (SpeechAct.BELIEF_ASSERTION,    TaskPhase.ACTION),
    NegotiationOperation.REJECT:            (SpeechAct.ALIGNMENT_CHALLENGE, TaskPhase.INTERPERSONAL),
}


class NegotiationStatus:
    """SNP status vocabulary (§1.2 of SEMANTIC_NEGOTIATION_PROTOCOL.md)."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    INCORPORATED = "incorporated"
    RESOLVED = "resolved"

    ALL: frozenset = frozenset({PENDING, REVIEWED, INCORPORATED, RESOLVED})


# ── SNP operation → SSTP event_type mapping (§3.1) ───────────────────────────

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

# SSTP kind for each SNP-derived event_type (peer_turn → delegation, decision_emitted → commit)
_SNP_EVENT_TYPE_TO_KIND: Dict[str, str] = {
    "peer_turn": "delegation",
    "decision_emitted": "commit",
}


def snp_event_type_for_operation(operation: str) -> str:
    """Return the canonical SSTP event_type for an SNP operation (§3.1).

    The result feeds into the SSTP kind rule:
    ``peer_turn`` → ``delegation``, ``decision_emitted`` → ``commit``.
    """
    result = _SNP_OPERATION_TO_EVENT_TYPE.get(operation)
    if result is None:
        raise ValueError(f"Unknown SNP operation: {operation!r}")
    return result


# ── SNP payload builder (§3.2) ────────────────────────────────────────────────


def build_snp_payload(
    *,
    operation: str,
    proposal_id: str,
    content: str,
    status: str,
    negotiation_id: str | None = None,
    payload_hash: str | None = None,
    proposal_payload: Dict[str, Any] | None = None,
    posterior: Optional[float] = None,
    supporting_evidence: Optional[List[str]] = None,
    against_evidence: Optional[List[str]] = None,
    reasoning_summary: Optional[str] = None,
    addresses_evidence: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a NegotiationPayload for use inside an Interaction Engine event.

    Implements §3.2 of SEMANTIC_NEGOTIATION_PROTOCOL.md.

    Layer 4 reasoning chain fields (PROPOSE and COUNTER_PROPOSAL):
        posterior            — Bayesian posterior for the asserted conclusion
        supporting_evidence  — concept_ids supporting the conclusion
        against_evidence     — concept_ids arguing against the conclusion
        reasoning_summary    — human-readable synthesis (LLM-generated)
        addresses_evidence   — concept_ids from the prior PROPOSE that this
                               COUNTER_PROPOSAL engages with (IE Layer 3 check)
    """
    if operation not in NegotiationOperation.ALL:
        raise ValueError(f"Invalid SNP operation: {operation!r}")
    if status not in NegotiationStatus.ALL:
        raise ValueError(f"Invalid SNP status: {status!r}")
    out: Dict[str, Any] = {
        "profile": SNP_PROFILE,
        "operation": operation,
        "proposal_id": proposal_id,
        "content": content,
        "status": status,
    }
    if negotiation_id is not None:
        out["negotiation_id"] = negotiation_id
    if payload_hash is not None:
        out["payload_hash"] = payload_hash

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

    merged = {**(proposal_payload or {}), **reasoning}
    if merged:
        out["proposal_payload"] = merged
    return out


# ── SNPL9HeaderBuilder ────────────────────────────────────────────────────────


class SNPL9HeaderBuilder(L9HeaderBuilder):
    """SNP specialisation of :class:`~protocol.l9_base.L9HeaderBuilder`.

    Derives the SSTP kind from the SNP operation → event_type pipeline.
    Accepts either a canonical ``event_type`` string (``peer_turn``,
    ``decision_emitted``) or, via :meth:`build_snp`, an SNP ``operation``
    string that is mapped automatically.
    """

    def kind_for_event_type(self, event_type: str) -> str:
        return _SNP_EVENT_TYPE_TO_KIND.get(event_type, "knowledge")

    def schema_id_for(
        self,
        use_case: str,
        event_type: str,
        kind: str,
        schema_trust_level: str,
    ) -> str:
        normalized = normalize_use_case(use_case)
        version = schema_version_for_kind(kind)
        if schema_trust_level == "certified":
            return f"urn:ioc:{normalized}:coordination:{event_type}:v{version}"
        return f"urn:ioc:draft:{normalized}:coordination:{event_type}:v{version}"

    def ttl_for_event_type(self, event_type: str) -> int:
        return 86400 if event_type == "peer_turn" else 604800

    def build_snp(
        self,
        *,
        operation: str,
        use_case: str,
        sender: str,
        receiver: str | None,
        timestamp_ms: int,
        proposal_id: str,
        turn_depth: int | None = None,
        utterance: str = "",
        parent_ids: Iterable[str] | None = None,
        confidence_score: float | None = None,
        risk_score: float | None = None,
        state_object_id: str | None = None,
        merge_strategy: str = "merge",
        provenance_sources: Iterable[str] | None = None,
        provenance_transforms: Iterable[str] | None = None,
        message_id: str | None = None,
        cognition_profile_id: str | None = "semantic_alignment:v1",
        cognition_protocol: str | None = "SNP",
        epistemic: Dict[str, Any] | None = None,
        state_sequence: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Build an SNP L9 header from an SNP *operation* (§3.1 mapping).

        If epistemic is None, a default block is inferred from the operation.
        Callers with position/confidence context should pass an explicit block
        via infer_snp_epistemic() to get accurate DELIBERATION_PASS annotation
        for forced ACCEPTs.
        """
        if epistemic is None:
            sa, tp = _SNP_DEFAULT_EPISTEMIC.get(
                operation, (SpeechAct.BELIEF_ASSERTION, TaskPhase.ACTION)
            )
            epistemic = make_epistemic_block(speech_act=sa, task_phase=tp)
        event_type = snp_event_type_for_operation(operation)
        return self.build(
            use_case=use_case,
            event_type=event_type,
            sender=sender,
            receiver=receiver,
            timestamp_ms=timestamp_ms,
            turn_depth=turn_depth,
            utterance=utterance,
            parent_ids=parent_ids,
            confidence_score=confidence_score,
            risk_score=risk_score,
            state_object_id=state_object_id,
            merge_strategy=merge_strategy,
            provenance_sources=provenance_sources,
            provenance_transforms=provenance_transforms,
            payload_refs=[{
                "type": "inline",
                "ref": f"urn:ioc:snp:{normalize_use_case(use_case)}:{proposal_id}",
            }],
            schema_inline={"profile": SNP_PROFILE, "operation": operation},
            ontology_ref=SNP_ONTOLOGY_REFERENCE,
            message_id=message_id,
            cognition_profile_id=cognition_profile_id,
            cognition_protocol=cognition_protocol,
            epistemic=epistemic,
            state_sequence=state_sequence,
        )


# ── Module-level convenience functions (backwards-compatible public API) ──────

_DEFAULT_BUILDER = SNPL9HeaderBuilder()


def build_snp_l9_header(
    *,
    operation: str,
    use_case: str,
    sender: str,
    receiver: str | None,
    timestamp_ms: int,
    proposal_id: str,
    turn_depth: int | None = None,
    utterance: str = "",
    parent_ids: Iterable[str] | None = None,
    confidence_score: float | None = None,
    risk_score: float | None = None,
    state_object_id: str | None = None,
    merge_strategy: str = "merge",
    provenance_sources: Iterable[str] | None = None,
    provenance_transforms: Iterable[str] | None = None,
    message_id: str | None = None,
    cognition_profile_id: str | None = "semantic_alignment:v1",
    cognition_protocol: str | None = "SNP",
    epistemic: Dict[str, Any] | None = None,
    state_sequence: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build an SSTP L9 header for a Semantic Negotiation sub-protocol message.

    Convenience wrapper around :class:`SNPL9HeaderBuilder`.
    The SSTP event_type is derived from *operation* using the SNP mapping
    (§3.1 of SEMANTIC_NEGOTIATION_PROTOCOL.md).
    """
    return _DEFAULT_BUILDER.build_snp(
        operation=operation,
        use_case=use_case,
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        proposal_id=proposal_id,
        turn_depth=turn_depth,
        utterance=utterance,
        parent_ids=parent_ids,
        confidence_score=confidence_score,
        risk_score=risk_score,
        state_object_id=state_object_id,
        merge_strategy=merge_strategy,
        provenance_sources=provenance_sources,
        provenance_transforms=provenance_transforms,
        message_id=message_id,
        cognition_profile_id=cognition_profile_id,
        cognition_protocol=cognition_protocol,
        epistemic=epistemic,
        state_sequence=state_sequence,
    )


__all__ = [
    # Re-exported base constants
    "L9_PROTOCOL",
    "L9_VERSION",
    "normalize_use_case",
    "schema_trust_level_for_kind",
    "schema_version_for_kind",
    # SNP profile
    "SNP_PROFILE",
    "SNP_ONTOLOGY_REFERENCE",
    # SNP vocabulary
    "NegotiationOperation",
    "NegotiationStatus",
    # SNP helpers
    "snp_event_type_for_operation",
    "build_snp_payload",
    # Builder class
    "SNPL9HeaderBuilder",
    # Convenience function
    "build_snp_l9_header",
]

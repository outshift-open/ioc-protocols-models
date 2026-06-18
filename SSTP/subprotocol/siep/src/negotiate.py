# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Negotiation message models for SIEP."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict


class LogicalClock(BaseModel):
    type: str = "lamport"
    value: int


class Origin(BaseModel):
    actor_id: str
    attestation: str | None = None


class PolicyLabels(BaseModel):
    sensitivity: str = "internal"
    propagation: str = "restricted"
    retention_policy: str = "default"


class Provenance(BaseModel):
    msg_sources: list[str] = Field(default_factory=list)
    msg_transforms: list[str] = Field(default_factory=list)
    msg_created: str = ""
    msg_expiry: int | None = None

    @property
    def sources(self) -> list[str]:
        return list(self.msg_sources)


class SAOState(BaseModel):
    model_config = ConfigDict(extra="allow")


class SAOResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class SAONMI(BaseModel):
    model_config = ConfigDict(extra="allow")


class SemanticContext(BaseModel):
    schema_id: str = ""


class BaseSSTPMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    version: str = "0.0.3"
    message_id: str
    dt_created: str = ""
    origin: Origin
    semantic_context: SemanticContext
    policy_labels: PolicyLabels = Field(default_factory=PolicyLabels)
    attributes: Provenance = Field(default_factory=Provenance)
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_ids: list[str] = Field(default_factory=list)
    episode_id: str | None = None
    logical_clock: LogicalClock | None = None
    ttl_seconds: int | None = None
    payload_refs: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def provenance(self) -> Provenance:
        return self.attributes


class NegotiateSemanticContext(SemanticContext):
    """Semantic context for ``kind='negotiate'`` messages."""

    schema_id: str = "urn:ioc:schema:negotiate:negmas-sao:v1"
    session_id: str
    issues: list[str] = Field(default_factory=list)
    options_per_issue: dict[str, list[str]] = Field(default_factory=dict)
    sao_state: SAOState | None = None
    sao_response: SAOResponse | None = None
    nmi: SAONMI | None = None


class SSTPNegotiateMessage(BaseSSTPMessage):
    kind: Literal["negotiate"]
    semantic_context: NegotiateSemanticContext


__all__ = [
    "BaseSSTPMessage",
    "LogicalClock",
    "NegotiateSemanticContext",
    "Origin",
    "PolicyLabels",
    "Provenance",
    "SAONMI",
    "SAOResponse",
    "SAOState",
    "SSTPNegotiateMessage",
    "SemanticContext",
]


# ── SIEP negotiation vocabulary (moved from l9.py) ───────────────────────────

from typing import Dict, Iterable, List, Optional
from SSTP.subprotocol.siep.src.epistemic.vocabulary import SpeechAct, EpistemicState, make_epistemic_block
from SSTP.l9_base import (
    L9HeaderBuilder,
    L9_PROTOCOL,
    L9_VERSION,
    normalize_use_case,
    schema_trust_level_for_kind,
    schema_version_for_kind,
)

SNP_PROFILE: str = "semantic_negotiation"
SNP_ONTOLOGY_REFERENCE: str = "protocol/ontology/snp_ontology.ttl"


class NegotiationOperation:
    """SIEP operation vocabulary."""
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
    """SIEP status vocabulary."""
    PENDING = "pending"
    REVIEWED = "reviewed"
    INCORPORATED = "incorporated"
    RESOLVED = "resolved"
    ALL: frozenset = frozenset({PENDING, REVIEWED, INCORPORATED, RESOLVED})


_SIEP_DEFAULT_EPISTEMIC: Dict[str, tuple] = {
    NegotiationOperation.PROPOSE:           (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS),
    NegotiationOperation.CONSIDER_PROPOSAL: (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS),
    NegotiationOperation.EVALUATE_PROPOSAL: (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS),
    NegotiationOperation.REVIEW_PROPOSAL:   (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS),
    NegotiationOperation.COUNTER_PROPOSAL:  (SpeechAct.CHALLENGE, EpistemicState.TEAM_PROCESS),
    NegotiationOperation.NEGOTIATE:         (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS),
    NegotiationOperation.ACCEPT:            (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS),
    NegotiationOperation.REJECT:            (SpeechAct.CHALLENGE, EpistemicState.TEAM_PROCESS),
}

_SIEP_OPERATION_TO_EVENT_TYPE: Dict[str, str] = {
    NegotiationOperation.PROPOSE:           "peer_turn",
    NegotiationOperation.CONSIDER_PROPOSAL: "peer_turn",
    NegotiationOperation.EVALUATE_PROPOSAL: "peer_turn",
    NegotiationOperation.REVIEW_PROPOSAL:   "peer_turn",
    NegotiationOperation.COUNTER_PROPOSAL:  "peer_turn",
    NegotiationOperation.NEGOTIATE:         "peer_turn",
    NegotiationOperation.ACCEPT:            "decision_emitted",
    NegotiationOperation.REJECT:            "decision_emitted",
}

_SIEP_EVENT_TYPE_TO_KIND: Dict[str, str] = {
    "peer_turn":           "exchange",
    "decision_emitted":    "commit",
    "convergence_emitted": "commit",
}


def snp_event_type_for_operation(operation: str) -> str:
    result = _SIEP_OPERATION_TO_EVENT_TYPE.get(operation)
    if result is None:
        raise ValueError(f"Unknown SIEP operation: {operation!r}")
    return result


def build_snp_payload(
    *,
    operation: str,
    proposal_id: str,
    content: str,
    status: str,
    negotiation_id: Optional[str] = None,
    proposal_payload: Optional[Dict[str, Any]] = None,
    posterior: Optional[float] = None,
    supporting_evidence: Optional[List[str]] = None,
    against_evidence: Optional[List[str]] = None,
    reasoning_summary: Optional[str] = None,
    addresses_evidence: Optional[List[str]] = None,
    deferred_to: Optional[str] = None,
) -> Dict[str, Any]:
    if operation not in NegotiationOperation.ALL:
        raise ValueError(f"Invalid SIEP operation: {operation!r}")
    if status not in NegotiationStatus.ALL:
        raise ValueError(f"Invalid SIEP status: {status!r}")
    out: Dict[str, Any] = {
        "profile": SNP_PROFILE,
        "operation": operation,
        "proposal_id": proposal_id,
        "content": content,
        "status": status,
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


_SHORT_TTL_EVENTS: frozenset = frozenset({"peer_turn", "repair_required", "repair_applied"})


class SNPL9HeaderBuilder(L9HeaderBuilder):
    """SIEP specialisation of L9HeaderBuilder."""

    def kind_for_event_type(self, event_type: str) -> str:
        return _SIEP_EVENT_TYPE_TO_KIND.get(event_type, "exchange")

    def schema_id_for(self, use_case: str, event_type: str, kind: str, schema_trust_level: str) -> str:
        normalized = normalize_use_case(use_case)
        version = schema_version_for_kind(kind)
        if schema_trust_level == "certified":
            return f"urn:ioc:{normalized}:coordination:{event_type}:v{version}"
        return f"urn:ioc:draft:{normalized}:coordination:{event_type}:v{version}"

    def ttl_for_event_type(self, event_type: str) -> int:
        return 86400 if event_type in _SHORT_TTL_EVENTS else 604800

    def build_snp(self, *, operation: str, use_case: str, sender: str,
                  receiver: Optional[str], timestamp_ms: int, proposal_id: str,
                  turn_depth: Optional[int] = None, utterance: str = "",
                  parent_ids: Optional[Iterable[str]] = None,
                  episode_id: Optional[str] = None,
                  provenance_sources: Optional[Iterable[str]] = None,
                  message_id: Optional[str] = None, subprotocol: Optional[str] = "SIEP",
                  epistemic: Optional[Dict[str, Any]] = None,
                  state_sequence: Optional[Dict[str, Any]] = None,
                  kind_override: Optional[str] = None,
                  sequence_number: Optional[int] = None,
                  payload_parts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if epistemic is None:
            sa, es = _SIEP_DEFAULT_EPISTEMIC.get(operation, (SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS))
            epistemic = make_epistemic_block(speech_act=sa, epistemic_state=es)
        event_type = snp_event_type_for_operation(operation)
        return self.build(
            use_case=use_case, event_type=event_type, sender=sender,
            receiver=receiver, timestamp_ms=timestamp_ms, turn_depth=turn_depth,
            utterance=utterance, parent_ids=parent_ids, episode_id=episode_id,
            provenance_sources=provenance_sources, ontology_ref=SNP_ONTOLOGY_REFERENCE,
            message_id=message_id, subprotocol=subprotocol, epistemic=epistemic,
            state_sequence=state_sequence, kind_override=kind_override,
            sequence_number=sequence_number, payload_parts=payload_parts,
        )


_DEFAULT_BUILDER = SNPL9HeaderBuilder()


def build_snp_l9_header(
    *, operation: str, use_case: str, sender: str, receiver: Optional[str],
    timestamp_ms: int, proposal_id: str, turn_depth: Optional[int] = None,
    utterance: str = "", parent_ids: Optional[Iterable[str]] = None,
    episode_id: Optional[str] = None, provenance_sources: Optional[Iterable[str]] = None,
    message_id: Optional[str] = None, subprotocol: Optional[str] = "SIEP",
    epistemic: Optional[Dict[str, Any]] = None, state_sequence: Optional[Dict[str, Any]] = None,
    kind_override: Optional[str] = None, sequence_number: Optional[int] = None,
    payload_parts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return _DEFAULT_BUILDER.build_snp(
        operation=operation, use_case=use_case, sender=sender, receiver=receiver,
        timestamp_ms=timestamp_ms, proposal_id=proposal_id, turn_depth=turn_depth,
        utterance=utterance, parent_ids=parent_ids, episode_id=episode_id,
        provenance_sources=provenance_sources, message_id=message_id,
        subprotocol=subprotocol, epistemic=epistemic, state_sequence=state_sequence,
        kind_override=kind_override, sequence_number=sequence_number, payload_parts=payload_parts,
    )

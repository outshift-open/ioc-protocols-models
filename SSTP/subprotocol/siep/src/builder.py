# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Compact SIEP message model, fluent builder, and legacy flat-header adapters."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional
import uuid

from ai.outshift.data_model import L9, L9Header, L9Payload, Actor, Context, Semantic, Kind, ParticipantSet as Actors, Message, PolicyLabel
from SSTP.subprotocol.siep.src.siep_payload import (
    SIEPMessagePayload,
    SIEPBeliefBlock,
    SIEPGroundingBlock,
    SIEPUtteranceBlock,
    SIEP_ONTOLOGY_REF,
    SIEP_SCHEMA_URN,
)
from SSTP.subprotocol._l9_compat import (
    flatten_legacy_header,
    normalize_use_case,
    schema_trust_level_for_kind,
    schema_version_for_kind,
)
from SSTP.subprotocol.siep.src.epistemic.vocabulary import make_epistemic_block

SNP_PROFILE: str = "semantic_negotiation"
SNP_ONTOLOGY_REFERENCE: str = "protocol/ontology/snp_ontology.ttl"


class NegotiationOperation:
    PROPOSE = "propose"
    CONSIDER_PROPOSAL = "consider_proposal"
    EVALUATE_PROPOSAL = "evaluate_proposal"
    REVIEW_PROPOSAL = "review_proposal"
    COUNTER_PROPOSAL = "counter_proposal"
    ACCEPT = "accept"
    REJECT = "reject"
    NEGOTIATE = "negotiate"

    ALL: frozenset[str] = frozenset({
        PROPOSE,
        CONSIDER_PROPOSAL,
        EVALUATE_PROPOSAL,
        REVIEW_PROPOSAL,
        COUNTER_PROPOSAL,
        ACCEPT,
        REJECT,
        NEGOTIATE,
    })
    TERMINAL: frozenset[str] = frozenset({ACCEPT, REJECT})


class NegotiationStatus:
    PENDING = "pending"
    REVIEWED = "reviewed"
    INCORPORATED = "incorporated"
    RESOLVED = "resolved"

    ALL: frozenset[str] = frozenset({PENDING, REVIEWED, INCORPORATED, RESOLVED})


_SNP_DEFAULT_EPISTEMIC: Dict[str, Dict[str, Any]] = {
    NegotiationOperation.PROPOSE: make_epistemic_block(speech_act="assertion", epistemic_state="team_process"),
    NegotiationOperation.CONSIDER_PROPOSAL: make_epistemic_block(speech_act="assertion", epistemic_state="team_process"),
    NegotiationOperation.EVALUATE_PROPOSAL: make_epistemic_block(speech_act="assertion", epistemic_state="team_process"),
    NegotiationOperation.REVIEW_PROPOSAL: make_epistemic_block(speech_act="assertion", epistemic_state="team_process"),
    NegotiationOperation.COUNTER_PROPOSAL: make_epistemic_block(speech_act="challenge", epistemic_state="team_process"),
    NegotiationOperation.NEGOTIATE: make_epistemic_block(speech_act="assertion", epistemic_state="team_process"),
    NegotiationOperation.ACCEPT: make_epistemic_block(speech_act="assertion", epistemic_state="team_process"),
    NegotiationOperation.REJECT: make_epistemic_block(speech_act="challenge", epistemic_state="team_process"),
}

_SNP_OPERATION_TO_EVENT_TYPE: Dict[str, str] = {
    NegotiationOperation.PROPOSE: "peer_turn",
    NegotiationOperation.CONSIDER_PROPOSAL: "peer_turn",
    NegotiationOperation.EVALUATE_PROPOSAL: "peer_turn",
    NegotiationOperation.REVIEW_PROPOSAL: "peer_turn",
    NegotiationOperation.COUNTER_PROPOSAL: "peer_turn",
    NegotiationOperation.NEGOTIATE: "peer_turn",
    NegotiationOperation.ACCEPT: "decision_emitted",
    NegotiationOperation.REJECT: "decision_emitted",
}

_SNP_EVENT_TYPE_TO_KIND: Dict[str, str] = {
    "peer_turn": "exchange",
    "decision_emitted": "commit",
    "convergence_emitted": "commit",
}


def snp_event_type_for_operation(operation: str) -> str:
    op = operation.value if hasattr(operation, "value") else str(operation)
    result = _SNP_OPERATION_TO_EVENT_TYPE.get(op)
    if result is None:
        raise ValueError(f"Unknown SNP operation: {operation!r}")
    return result


def schema_id_for(use_case: str, event_type: str, kind: str, schema_trust_level: str) -> str:
    normalized_use_case = normalize_use_case(use_case)
    canonical = str(event_type).strip().lower()
    version = schema_version_for_kind(kind)
    if schema_trust_level == "certified":
        return f"urn:ioc:{normalized_use_case}:coordination:{canonical}:v{version}"
    return f"urn:ioc:draft:{normalized_use_case}:coordination:{canonical}:v{version}"


def _default_epistemic_for_operation(operation: str) -> Dict[str, Any]:
    op = operation.value if hasattr(operation, "value") else str(operation)
    return dict(_SNP_DEFAULT_EPISTEMIC.get(op, make_epistemic_block(
        speech_act="assertion",
        epistemic_state="team_process",
    )))


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



class SubKind(str, Enum):
    converged = "converged"
    rejected = "rejected"


class EpistemicState(str, Enum):
    taskwork = "taskwork"
    grounding = "grounding"
    team_process = "team_process"


class MessageAct(str, Enum):
    assertion = "assertion"
    challenge = "challenge"


class BeliefStatus(str, Enum):
    asserted = "asserted"
    challenged = "challenged"
    revised = "revised"
    unresolved = "unresolved"


class RepairReason(str, Enum):
    grounding_failure = "grounding_failure"
    scope_mismatch = "scope_mismatch"
    ungroundable_novelty = "ungroundable_novelty"


class RevisionCause(str, Enum):
    semantic_memory = "semantic_memory"
    grounded_argument = "grounded_argument"
    repair_resolution = "repair_resolution"


@dataclass
class ActorRef:
    id: str


@dataclass
class MessageRef:
    id: str
    parents: List[str]
    episode: str


@dataclass
class PayloadPart:
    type: str
    location: str
    content: Any


@dataclass
class SIEPUtterance:
    text: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    addresses_evidence: List[str] = field(default_factory=list)
    ring_round: int = 0
    repair_depth: int = 0


@dataclass
class SIEPGrounding:
    contingency_verified: Optional[bool] = None
    contingency_score: Optional[float] = None
    repair_reason: Optional[RepairReason] = None
    challenges: List[str] = field(default_factory=list)


@dataclass
class SIEPBelief:
    prior: float = 0.5
    posterior: float = 0.5
    revision_cause: Optional[RevisionCause] = None


@dataclass
class SIEPPayload:
    utterance: SIEPUtterance = field(default_factory=SIEPUtterance)
    grounding: SIEPGrounding = field(default_factory=SIEPGrounding)
    belief: SIEPBelief = field(default_factory=SIEPBelief)


@dataclass
class SIEPEpistemic:
    message_act: Optional[MessageAct] = None
    state: Optional[EpistemicState] = None
    belief_status: Optional[BeliefStatus] = None
    concept_id: Optional[str] = None
    uncertainty: float = 0.0
    epistemic_kind: str = "siep"


@dataclass
class L9Message:
    """Internal compatibility dataclass retained for non-wire SIEP uses."""

    kind: Kind
    actor: ActorRef
    message: MessageRef
    epistemic: SIEPEpistemic
    payload: List[PayloadPart] = field(default_factory=list)
    protocol: str = "SSTP"
    version: str = "0.0.3"
    subprotocol: str = "SIEP"
    subkind: Optional[SubKind] = None

    def siep_payload(self) -> Optional[SIEPPayload]:
        for part in self.payload:
            if part.type == "siep" and isinstance(part.content, SIEPPayload):
                return part.content
        return None


def contingency_score(evidence: List[str], prior_evidence: List[str]) -> float:
    if not prior_evidence:
        return 1.0
    return len(set(evidence) & set(prior_evidence)) / len(prior_evidence)


class SIEPMessageBuilder:
    def __init__(self, episode_urn: str, sender: str) -> None:
        self._ep = episode_urn
        self._sender = sender
        self._receivers: List[str] = []
        self._kind: Optional[Kind] = None
        self._subkind: Optional[SubKind] = None
        self._parents: List[str] = []
        self._msg_act: Optional[MessageAct] = None
        self._ep_state: Optional[EpistemicState] = None
        self._belief_status: Optional[BeliefStatus] = None
        self._concept: Optional[str] = None
        self._uncertainty: float = 0.0
        self._siep_payload: Optional[SIEPPayload] = None
        self._text: Optional[str] = None
        # Additive fields for the full SNP operation vocabulary (see .operation()).
        # Unused by engine.py's narrower usage; None means "use the fixed
        # SIEP_SCHEMA_URN / no policy block", preserving today's behaviour.
        self._operation: Optional[str] = None
        self._use_case: Optional[str] = None
        self._sequence_number: Optional[int] = None
        self._provenance_sources: List[str] = []
        self._sensitivity: Optional[str] = None
        self._propagation: Optional[str] = None
        self._retention_policy: Optional[str] = None

    def intent(self) -> "SIEPMessageBuilder":
        self._kind = Kind.intent
        return self

    def to(self, *receivers: str) -> "SIEPMessageBuilder":
        """Set one or more receiver agent IDs."""
        self._receivers = list(receivers)
        return self

    # Alias for `.to()` — matches the legacy flat-header adapter API.
    recipients = to

    def use_case(self, value: str) -> "SIEPMessageBuilder":
        self._use_case = value
        return self

    def operation(self, operation: str) -> "SIEPMessageBuilder":
        """Configure kind/epistemic defaults for an SNP ``operation``."""
        op = operation.value if hasattr(operation, "value") else str(operation)
        self._operation = op
        event_type = snp_event_type_for_operation(op)
        self._kind = Kind(_SNP_EVENT_TYPE_TO_KIND.get(event_type, "exchange"))
        default_epistemic = _default_epistemic_for_operation(op)
        self._msg_act = MessageAct(default_epistemic["message_act"])
        self._ep_state = EpistemicState(default_epistemic["state"])
        if self._belief_status is None:
            self._belief_status = BeliefStatus(default_epistemic["belief_status"])
        return self

    def sequence_number(self, value: int) -> "SIEPMessageBuilder":
        self._sequence_number = value
        return self

    def provenance_sources(self, *sources: str) -> "SIEPMessageBuilder":
        self._provenance_sources = list(sources)
        return self

    def policy(
        self,
        *,
        sensitivity: str = "internal",
        propagation: str = "restricted",
        retention_policy: Optional[str] = None,
    ) -> "SIEPMessageBuilder":
        self._sensitivity = sensitivity
        self._propagation = propagation
        self._retention_policy = retention_policy or (
            f"policy.{self._use_case}.default" if self._use_case else None
        )
        return self

    def exchange(self) -> "SIEPMessageBuilder":
        self._kind = Kind.exchange
        return self

    def commit_converged(self) -> "SIEPMessageBuilder":
        self._kind = Kind.commit
        self._subkind = SubKind.converged
        return self

    def commit_rejected(self) -> "SIEPMessageBuilder":
        self._kind = Kind.commit
        self._subkind = SubKind.rejected
        return self

    def taskwork(self) -> "SIEPMessageBuilder":
        self._ep_state = EpistemicState.taskwork
        return self

    def grounding(self) -> "SIEPMessageBuilder":
        self._ep_state = EpistemicState.grounding
        return self

    def team_process(self) -> "SIEPMessageBuilder":
        self._ep_state = EpistemicState.team_process
        return self

    def asserted(self) -> "SIEPMessageBuilder":
        self._belief_status = BeliefStatus.asserted
        self._msg_act = MessageAct.assertion
        return self

    def challenged(self) -> "SIEPMessageBuilder":
        self._belief_status = BeliefStatus.challenged
        self._msg_act = MessageAct.challenge
        return self

    def revised(self) -> "SIEPMessageBuilder":
        self._belief_status = BeliefStatus.revised
        self._msg_act = MessageAct.assertion
        return self

    def unresolved(self) -> "SIEPMessageBuilder":
        self._belief_status = BeliefStatus.unresolved
        return self

    def concept(self, concept_id: str) -> "SIEPMessageBuilder":
        self._concept = concept_id
        return self

    def uncertainty(self, value: float) -> "SIEPMessageBuilder":
        self._uncertainty = value
        return self

    def parents(self, *ids: str) -> "SIEPMessageBuilder":
        self._parents = list(ids)
        return self

    def payload(self, payload: SIEPPayload) -> "SIEPMessageBuilder":
        self._siep_payload = payload
        return self

    def text(self, utterance: str) -> "SIEPMessageBuilder":
        self._text = utterance
        return self

    def build(self) -> L9:
        if self._kind is None:
            raise ValueError("Set a kind before calling build().")

        msg_id = str(uuid.uuid4())
        payload = self._to_pydantic_payload()
        siep_ep = SIEPEpistemic(
            message_act=self._msg_act.value if self._msg_act else None,
            state=self._ep_state.value if self._ep_state else None,
            belief_status=self._belief_status.value if self._belief_status else None,
            concept_id=self._concept,
            uncertainty=self._uncertainty,
        )
        attributes = {
            "utterance_text": self._text,
            "epistemic": asdict(siep_ep),
        }
        if self._sequence_number is not None:
            attributes["sequence_number"] = self._sequence_number
        if self._provenance_sources:
            attributes["msg_sources"] = list(self._provenance_sources)

        schema_id = SIEP_SCHEMA_URN
        if self._operation is not None and self._use_case is not None:
            trust_level = schema_trust_level_for_kind(self._kind.value)
            event_type = snp_event_type_for_operation(self._operation)
            schema_id = schema_id_for(self._use_case, event_type, self._kind.value, trust_level)

        policy = None
        if self._sensitivity is not None or self._propagation is not None:
            policy = PolicyLabel(
                sensitivity=self._sensitivity or "internal",
                propagation=self._propagation or "restricted",
                retention_policy=self._retention_policy or "policy.default",
            )

        l9 = L9(
            header=L9Header(
                protocol="SSTP",
                subprotocol="SIEP",
                version="0.0.3",
                kind=self._kind.value,
                subkind=self._subkind.value if isinstance(self._subkind, SubKind) else self._subkind,
                participants=Actors(actors=[
                    Actor(id=self._sender, role="sender"),
                    *[Actor(id=r, role="receiver") for r in self._receivers],
                ], groups=None).model_dump(),
                message=Message(id=msg_id, parents=list(self._parents), episode=self._ep).model_dump(),
                attributes=attributes,
                policy=policy,
                context=Context(
                    topic=self._concept or "",
                    semantic=Semantic(
                        schema_id=schema_id,
                        ontology_ref=SIEP_ONTOLOGY_REF,
                    ),
                ),
            ),
            payload=L9Payload(
                type="siep",
                data=payload.model_dump(),
            ),
        )
        return l9

    def _to_pydantic_payload(self) -> SIEPMessagePayload:
        internal = self._siep_payload or SIEPPayload()
        return SIEPMessagePayload(
            utterance=SIEPUtteranceBlock(
                text=self._text or internal.utterance.text,
                evidence=list(internal.utterance.evidence),
                addresses_evidence=list(internal.utterance.addresses_evidence),
                ring_round=internal.utterance.ring_round,
                repair_depth=internal.utterance.repair_depth,
            ),
            grounding=SIEPGroundingBlock(
                contingency_verified=internal.grounding.contingency_verified,
                contingency_score=internal.grounding.contingency_score,
                repair_reason=(
                    internal.grounding.repair_reason.value
                    if internal.grounding.repair_reason
                    else None
                ),
                challenges=list(internal.grounding.challenges),
            ),
            belief=SIEPBeliefBlock(
                prior=internal.belief.prior,
                posterior=internal.belief.posterior,
                revision_cause=(
                    internal.belief.revision_cause.value
                    if internal.belief.revision_cause
                    else None
                ),
            ),
        )


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
    normalized_use_case = normalize_use_case(use_case)
    builder = SIEPMessageBuilder(
        episode_urn=episode_id or f"urn:ioc:{normalized_use_case}:state:shared_dialogue",
        sender=str(sender or "unknown"),
    ).use_case(use_case).operation(operation)
    effective_recipients = list(recipients) if recipients is not None else (
        [str(receiver)] if receiver and str(receiver) != str(sender or "unknown") else []
    )
    if effective_recipients:
        builder.to(*effective_recipients)
    if kind_override:
        kind_value = kind_override
        subkind: str | None = None
        if ":" in kind_value:
            kind_value, subkind = kind_value.split(":", 1)
        builder._kind = Kind(kind_value)
        builder._subkind = SubKind(subkind) if subkind in {item.value for item in SubKind} else subkind
    if topic is not None:
        builder.concept(topic)
    if utterance:
        builder.text(utterance)
    if parent_ids:
        builder.parents(*[str(parent_id) for parent_id in parent_ids if parent_id])
    if sequence_number is not None:
        builder.sequence_number(sequence_number)
    source_list = [str(source) for source in (provenance_sources or []) if source]
    if source_list:
        builder.provenance_sources(*source_list)
    builder.policy(
        sensitivity="internal",
        propagation="restricted",
        retention_policy=f"policy.{normalized_use_case}.default",
    )
    l9_obj = builder.build()
    header_dump = l9_obj.header.model_dump(mode="json", exclude_none=False)
    kind = header_dump.get("kind") or _SNP_EVENT_TYPE_TO_KIND.get(
        snp_event_type_for_operation(operation),
        "exchange",
    )
    return flatten_legacy_header(
        builder_header={
            **header_dump,
            "kind": kind,
            "subkind": header_dump.get("subkind"),
        },
        sender=sender,
        receiver=receiver,
        role=role,
        recipients=recipients,
        use_case=use_case,
        timestamp_ms=timestamp_ms,
        message_id=message_id,
        episode_id=episode_id,
        topic=topic,
        epistemic=epistemic if epistemic is not None else _default_epistemic_for_operation(operation),
        schema_id=schema_id_for(
            use_case,
            snp_event_type_for_operation(operation),
            kind,
            schema_trust_level_for_kind(kind),
        ),
        ontology_ref=SNP_ONTOLOGY_REFERENCE,
        subprotocol=subprotocol,
        payload_parts=payload_parts,
        sensitivity="internal",
        propagation="restricted",
        provenance_sources=provenance_sources,
    )


__all__ = [
    "ActorRef",
    "BeliefStatus",
    "EpistemicState",
    "Kind",
    "L9Message",
    "MessageAct",
    "MessageRef",
    "PayloadPart",
    "RepairReason",
    "RevisionCause",
    "SIEPBelief",
    "SIEPEpistemic",
    "SIEPGrounding",
    "SIEPMessageBuilder",
    "SIEPPayload",
    "SIEPUtterance",
    "SubKind",
    "SNP_ONTOLOGY_REFERENCE",
    "SNP_PROFILE",
    "NegotiationOperation",
    "NegotiationStatus",
    "build_snp_l9_header",
    "build_snp_payload",
    "contingency_score",
    "schema_id_for",
    "snp_event_type_for_operation",
]

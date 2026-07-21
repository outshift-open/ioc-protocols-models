# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Compact SIEP message model, fluent builder, and legacy flat-header adapters."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional
import uuid

from ai.outshift.data_model import L9, L9Header, L9Payload, Actor, Context, Semantic, Kind, ParticipantSet as Actors, Message, PolicyLabel, Episode, Session
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
from SSTP.subprotocol.siep.src.epistemic.vocabulary import (
    make_epistemic_block,
    SpeechAct,
    EpistemicState as _EpistemicStateVocab,
    BeliefStatus as _BeliefStatusVocab,
    infer_snp_epistemic,
)

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
        raise ValueError(f"Unknown SIEP operation: {operation!r}")
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
        raise ValueError(f"Invalid SIEP operation: {operation!r}")
    if st not in NegotiationStatus.ALL:
        raise ValueError(f"Invalid SIEP status: {status!r}")
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
        # Additive fields for the full SIEP operation vocabulary (see .operation()).
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
        """Configure kind/epistemic defaults for a SIEP ``operation``."""
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

        # Build stateful session with episode and message
        session = Session(
            id=self._session_id if hasattr(self, '_session_id') and self._session_id else "default-session",
            episodes=[
                Episode(
                    id=self._ep,
                    messages=[Message(id=msg_id)]
                )
            ]
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
                session=session,
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



# ── SIEP emit helpers ───────────────────────────────────────────────────────────
# Each function takes two objects:
#   context : NegotiationContext  — debate state (use_case, stores, ID generators)
#   network : NetworkHandle       — transport (appends headers to network.messages)
# SIEP never creates or imports a concrete network implementation.


def _snp_position_key(pos: Any) -> str:
    if isinstance(pos, dict):
        return str(pos.get("likely_cause") or pos.get("risk_bucket") or pos.get("decision_key") or pos)
    return str(pos)


def _snp_confidence(pos: Any) -> float:
    if isinstance(pos, dict):
        return float(pos.get("confidence") or pos.get("roi_score") or 0.5)
    return 0.5


def emit_wire_received(
    context: Any,
    network: Any,
    debate_header: Dict[str, Any],
    recipient: str,
) -> None:
    """Append a WIRE received trace entry to the network for the recipient of a SIEP message."""
    from SSTP.subprotocol.cip.src.builder import build_l9_header
    msg_id = (debate_header.get("message") or {}).get("id", "")
    episode_id = (debate_header.get("message") or {}).get("episode")
    actors = (debate_header.get("participants") or {}).get("actors") or []
    sender_id = actors[0].get("id", "") if actors else ""
    _recv_utt = f"received:{msg_id.split(':')[-1] if ':' in msg_id else msg_id}"
    _recv_header = build_l9_header(
        use_case=context.use_case,
        event_type="peer_turn",
        sender=recipient,
        receiver=sender_id,
        timestamp_ms=int(time.time() * 1000),
        sensitivity="internal",
        utterance=_recv_utt,
        parent_ids=[msg_id] if msg_id else None,
        episode_id=episode_id,
        kind_override="exchange",
        subprotocol="SIEP",
        payload_parts=[{
            "type": "utterance", "location": "inline",
            "content": _recv_utt,
            "rationale": f"received from {sender_id}",
        }],
    )
    network.messages.append(_recv_header)


def emit_propose(
    context: Any,
    network: Any,
    controller: str,
    specialist: str,
    position: Any,
    turn: int,
) -> Dict[str, Any]:
    """Emit a PROPOSE header from controller to specialist; append to network."""
    from SSTP.subprotocol.siep.src.epistemic.stores import SemanticProposal
    conf = _snp_confidence(position)
    key = _snp_position_key(position)
    utterance = f"{controller} proposes {key} confidence={conf:.2f}"
    proposal_id = context._proposal_id(turn, controller)
    ts = int(time.time() * 1000)
    pos_dict = position if isinstance(position, dict) else {}
    _ep_state = _EpistemicStateVocab.TASKWORK if turn == 0 else _EpistemicStateVocab.TEAM_PROCESS
    epistemic_block = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION,
        epistemic_state=_ep_state,
        belief_status=_BeliefStatusVocab.ASSERTED,
        uncertainty=round(1.0 - conf, 4),
    )
    _tp_terms = pos_dict.get("team_process_terms")
    _debate_payload = build_snp_payload(
        operation=NegotiationOperation.PROPOSE,
        proposal_id=proposal_id,
        content=key,
        status=NegotiationStatus.PENDING,
        negotiation_id=context._debate_id,
        posterior=pos_dict.get("posterior") or conf,
        supporting_evidence=pos_dict.get("supporting_evidence"),
        against_evidence=pos_dict.get("against_evidence"),
        reasoning_summary=pos_dict.get("reasoning_summary") or pos_dict.get("rationale"),
        proposal_payload=_tp_terms if _tp_terms else None,
    )
    _ctrl_rationale = str(pos_dict.get("rationale") or pos_dict.get("reasoning_summary") or "").strip()
    _ctrl_thought = str(pos_dict.get("thought_summary") or "").strip()
    _ctrl_utt_part: Dict[str, Any] = {"type": "utterance", "location": "inline", "content": utterance}
    if _ctrl_rationale:
        _ctrl_utt_part["rationale"] = _ctrl_rationale
    if _ctrl_thought:
        _ctrl_utt_part["thought_summary"] = _ctrl_thought
    debate_header = build_snp_l9_header(
        operation=NegotiationOperation.PROPOSE,
        use_case=context.use_case,
        sender=controller,
        receiver=specialist,
        timestamp_ms=ts,
        proposal_id=proposal_id,
        utterance=utterance,
        episode_id=context._episode_id(),
        topic=key if key else None,
        epistemic=epistemic_block,
        payload_parts=[
            _ctrl_utt_part,
            {"type": "siep", "location": "inline", "content": _debate_payload},
        ],
    )
    if context.proposal_store is not None:
        context.proposal_store.record(SemanticProposal(
            proposal_id=proposal_id,
            concept_id=key or "",
            episode_id=context._episode_id(),
            sender=controller,
            receiver=specialist,
            payload=pos_dict,
            timestamp_ms=ts,
        ))
    network.messages.append(debate_header)
    emit_wire_received(context, network, debate_header, specialist)
    return debate_header


def emit_specialist_response(
    context: Any,
    network: Any,
    specialist: str,
    controller: str,
    position: Any,
    operation: str,
    turn: int,
    ie_request_message_id: str,
    ctrl_position_key: str = "",
    ctrl_conf: float = 0.5,
    accept_threshold: float = 0.1,
) -> Dict[str, Any]:
    """Emit a specialist ACCEPT/COUNTER-PROPOSAL response header; append to network."""
    key = _snp_position_key(position)
    conf = _snp_confidence(position)
    verb = "accepts" if operation == NegotiationOperation.ACCEPT else "counter-proposes"
    utterance = f"{specialist} {verb} {key} confidence={conf:.2f}"
    proposal_id = context._proposal_id(turn, specialist)
    ts = int(time.time() * 1000)
    op_str = operation.value if hasattr(operation, "value") else str(operation)
    speech_act, epistemic_state = infer_snp_epistemic(
        operation=op_str,
        ctrl_position_key=ctrl_position_key,
        member_position_key=key,
        ctrl_conf=ctrl_conf,
        member_conf=conf,
        accept_threshold=accept_threshold,
    )
    belief_status = _BeliefStatusVocab.DEFERRED if speech_act == SpeechAct.COMPLIANCE else _BeliefStatusVocab.ASSERTED
    pos_dict = position if isinstance(position, dict) else {}
    addresses_ev: Optional[List[str]] = (
        pos_dict.get("addresses_evidence")
        or pos_dict.get("supporting_evidence")
        or ([ctrl_position_key] if ctrl_position_key and operation in (
            NegotiationOperation.COUNTER_PROPOSAL, NegotiationOperation.ACCEPT
        ) else None)
    )
    _is_delib_pass = speech_act in (SpeechAct.COMPLIANCE, SpeechAct.DELIBERATION_PASS)
    epistemic_block = make_epistemic_block(
        speech_act=speech_act,
        epistemic_state=epistemic_state,
        belief_status=belief_status,
        uncertainty=round(1.0 - conf, 4),
    )
    _debate_payload = build_snp_payload(
        operation=operation,
        proposal_id=proposal_id,
        content=key,
        status=NegotiationStatus.PENDING,
        negotiation_id=context._debate_id,
        posterior=pos_dict.get("posterior") or conf,
        supporting_evidence=pos_dict.get("supporting_evidence"),
        against_evidence=pos_dict.get("against_evidence"),
        reasoning_summary=pos_dict.get("reasoning_summary") or pos_dict.get("rationale"),
        addresses_evidence=addresses_ev,
        deferred_to=controller if _is_delib_pass else None,
    )
    _spec_rationale = str(pos_dict.get("rationale") or pos_dict.get("reasoning_summary") or "").strip()
    _spec_thought = str(pos_dict.get("thought_summary") or "").strip()
    _spec_utt_part: Dict[str, Any] = {"type": "utterance", "location": "inline", "content": utterance}
    if _spec_rationale:
        _spec_utt_part["rationale"] = _spec_rationale
    if _spec_thought:
        _spec_utt_part["thought_summary"] = _spec_thought
    debate_header = build_snp_l9_header(
        operation=operation,
        use_case=context.use_case,
        sender=specialist,
        receiver=controller,
        timestamp_ms=ts,
        proposal_id=proposal_id,
        utterance=utterance,
        episode_id=context._episode_id(),
        topic=ctrl_position_key if ctrl_position_key else None,
        epistemic=epistemic_block,
        kind_override="exchange",
        payload_parts=[
            _spec_utt_part,
            {"type": "siep", "location": "inline", "content": _debate_payload},
        ],
    )
    network.messages.append(debate_header)
    emit_wire_received(context, network, debate_header, controller)
    return debate_header


def emit_final_decision(
    context: Any,
    network: Any,
    controller: str,
    specialist: str,
    position: Any,
    turn: int,
    ie_request_message_id: str,
    specialist_position: Any = None,
    accept_threshold: float = 0.1,
) -> Dict[str, Any]:
    """Emit the controller's COMMIT (final per-specialist close) header; append to network."""
    conf = _snp_confidence(position)
    key = _snp_position_key(position)
    utterance = f"{controller} commits {key} confidence={conf:.2f}"
    proposal_id = context._proposal_id(turn, controller)
    ts = int(time.time() * 1000)
    spec_key = _snp_position_key(specialist_position) if specialist_position is not None else key
    if spec_key != key:
        _sa: SpeechAct = SpeechAct.COMPLIANCE
        _es: _EpistemicStateVocab = _EpistemicStateVocab.TEAM_PROCESS
        _bs: _BeliefStatusVocab = _BeliefStatusVocab.DEFERRED
    else:
        _sa = SpeechAct.ASSERTION
        _es = _EpistemicStateVocab.TEAM_PROCESS
        _bs = _BeliefStatusVocab.ASSERTED
    epistemic_block = make_epistemic_block(
        speech_act=_sa, epistemic_state=_es, belief_status=_bs,
        uncertainty=round(1.0 - conf, 4),
    )
    debate_header = build_snp_l9_header(
        operation=NegotiationOperation.ACCEPT,
        use_case=context.use_case,
        sender=controller,
        receiver=specialist,
        timestamp_ms=ts,
        proposal_id=proposal_id,
        utterance=utterance,
        episode_id=context._episode_id(),
        epistemic=epistemic_block,
        kind_override="commit",
    )
    network.messages.append(debate_header)
    return debate_header


def emit_negotiate(
    context: Any,
    network: Any,
    *,
    sender: str,
    receiver: str,
    utterance: str,
    turn: int,
    confidence: float,
    parent_debate_id: Optional[str] = None,
    epistemic_state: _EpistemicStateVocab = _EpistemicStateVocab.TEAM_PROCESS,
) -> Dict[str, Any]:
    """Emit a NEGOTIATE header (ring peer pass); append to network."""
    proposal_id = context._proposal_id(turn, sender)
    ts = int(time.time() * 1000)
    epistemic_block = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION,
        epistemic_state=epistemic_state,
        belief_status=_BeliefStatusVocab.ASSERTED,
        uncertainty=round(1.0 - confidence, 4),
    )
    debate_header = build_snp_l9_header(
        operation=NegotiationOperation.NEGOTIATE,
        use_case=context.use_case,
        sender=sender,
        receiver=receiver,
        timestamp_ms=ts,
        proposal_id=proposal_id,
        utterance=utterance,
        parent_ids=[parent_debate_id] if parent_debate_id else None,
        episode_id=context._episode_id(),
        epistemic=epistemic_block,
    )
    network.messages.append(debate_header)
    return debate_header


def emit_decision(
    context: Any,
    network: Any,
    *,
    sender: str,
    receiver: str,
    utterance: str,
    operation: str,
    turn: int,
    confidence: float,
    ie_request_message_id: str,
    parent_debate_id: Optional[str] = None,
    ctrl_position_key: str = "",
    ctrl_conf: float = 0.5,
    accept_threshold: float = 0.1,
) -> Dict[str, Any]:
    """Emit an ACCEPT/REJECT decision header (ring response); append to network."""
    proposal_id = context._proposal_id(turn, sender)
    ts = int(time.time() * 1000)
    op_str = operation.value if hasattr(operation, "value") else str(operation)
    speech_act, epistemic_state = infer_snp_epistemic(
        operation=op_str,
        ctrl_position_key=ctrl_position_key,
        member_position_key=ctrl_position_key,
        ctrl_conf=ctrl_conf,
        member_conf=confidence,
        accept_threshold=accept_threshold,
    )
    belief_status = _BeliefStatusVocab.DEFERRED if speech_act == SpeechAct.COMPLIANCE else _BeliefStatusVocab.ASSERTED
    epistemic_block = make_epistemic_block(
        speech_act=speech_act,
        epistemic_state=epistemic_state,
        belief_status=belief_status,
        uncertainty=round(1.0 - confidence, 4),
    )
    debate_header = build_snp_l9_header(
        operation=operation,
        use_case=context.use_case,
        sender=sender,
        receiver=receiver,
        timestamp_ms=ts,
        proposal_id=proposal_id,
        utterance=utterance,
        parent_ids=[parent_debate_id] if parent_debate_id else None,
        episode_id=context._episode_id(),
        topic=ctrl_position_key if ctrl_position_key else None,
        epistemic=epistemic_block,
    )
    network.messages.append(debate_header)
    return debate_header


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
    "emit_wire_received",
    "emit_propose",
    "emit_specialist_response",
    "emit_final_decision",
    "emit_negotiate",
    "emit_decision",
]

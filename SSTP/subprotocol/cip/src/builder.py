# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Compact CIP message model, fluent builder, and legacy flat-header adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional
import uuid

from ai.outshift.data_model import L9, L9Header, L9Payload, Actor, ParticipantSet, Context, Semantic, Epistemic, PolicyLabel, Kind  # noqa: E402 — requires language_bindings/python on sys.path
from SSTP.subprotocol.cip.src.cip_payload import (
    CIPBeliefBlock,
    CIPGroundingBlock,
    CIPMessagePayload,
    CIPUtteranceBlock,
    CIP_ONTOLOGY_REF,
    CIP_SCHEMA_URN,
    RepairReason as _RepairReasonBase,
)
from SSTP.subprotocol._l9_compat import (
    flatten_legacy_header,
    normalize_use_case,
    schema_trust_level_for_kind,
    schema_version_for_kind,
)
from SSTP.subprotocol.siep.src.epistemic.vocabulary import make_epistemic_block


RepairReason = _RepairReasonBase  # re-export from cip_payload (no wheel dep)

# Kind is imported directly from the generated L9Schema (ai.outshift.data_model)
# — the canonical 5-value enum (intent, contingency, exchange, commit,
# knowledge) — not redeclared here, so CIP can never drift from the schema.
# (SIEP's builder.py already followed this pattern; CIP previously had its
# own local 2-member duplicate — fixed to match.)


CIP_PROTOCOL: str = "interaction_engine_protocol"
CIP_PROTOCOL_VERSION: str = "1.0.0"

_EVENT_TYPE_ALIASES: Dict[str, str] = {
    "message": "peer_turn",
    "peer_repair": "repair_applied",
    "repair_applied": "repair_applied",
    "conversation_terminated": "conversation_terminated",
}

_KIND_BY_EVENT_TYPE: Dict[str, str] = {
    "turn_ingested": "exchange",
    "peer_turn": "exchange",
    "repair_required": "contingency",
    "repair_applied": "commit",
    "decision_emitted": "commit",
    "episode_persisted": "commit",
    "conversation_terminated": "commit",
    "epistemic_clarification": "contingency",
    "process_proposed": "exchange",
    "process_accepted": "commit",
    "process_challenged": "contingency",
    "prior_query": "exchange",
    "initial_prior": "exchange",
    "rule_update": "knowledge",
    "outcome_reported": "exchange",
}

_SCHEMA_TOPIC_BY_EVENT_TYPE: Dict[str, tuple[str, str]] = {
    "turn_ingested": ("intake", "turn"),
    "peer_turn": ("coordination", "peer_message"),
    "repair_required": ("coordination", "repair_request"),
    "repair_applied": ("coordination", "repair_message"),
    "decision_emitted": ("coordination", "decision"),
    "episode_persisted": ("memory", "episode_commit"),
    "conversation_terminated": ("coordination", "termination_notice"),
    "epistemic_clarification": ("coordination", "epistemic_repair"),
    "process_proposed": ("coordination", "process_proposal"),
    "process_accepted": ("coordination", "process_acceptance"),
    "process_challenged": ("coordination", "process_challenge"),
    "prior_query": ("memory", "prior_query"),
    "initial_prior": ("memory", "initial_prior"),
    "rule_update": ("memory", "rule_update"),
    "outcome_reported": ("memory", "outcome_reported"),
}

_DEFAULT_EPISTEMIC_BY_EVENT_TYPE: Dict[str, Dict[str, Any]] = {
    "turn_ingested": make_epistemic_block(speech_act="assertion", epistemic_state="taskwork"),
    "peer_turn": make_epistemic_block(speech_act="assertion", epistemic_state="grounding"),
    "repair_required": make_epistemic_block(speech_act="assertion", epistemic_state="grounding"),
    "repair_applied": make_epistemic_block(speech_act="assertion", epistemic_state="grounding"),
    "decision_emitted": make_epistemic_block(speech_act="assertion", epistemic_state="grounding"),
    "episode_persisted": make_epistemic_block(speech_act="assertion", epistemic_state="taskwork"),
    "epistemic_clarification": make_epistemic_block(speech_act="assertion", epistemic_state="grounding"),
    "process_proposed": make_epistemic_block(speech_act="assertion", epistemic_state="team_process"),
    "process_accepted": make_epistemic_block(speech_act="assertion", epistemic_state="team_process"),
    "process_challenged": make_epistemic_block(speech_act="challenge", epistemic_state="team_process"),
    "prior_query": make_epistemic_block(speech_act="assertion", epistemic_state="taskwork"),
    "initial_prior": make_epistemic_block(speech_act="assertion", epistemic_state="taskwork"),
    "rule_update": make_epistemic_block(speech_act="assertion", epistemic_state="taskwork"),
    "outcome_reported": make_epistemic_block(speech_act="assertion", epistemic_state="taskwork"),
}

_DEFAULT_EPISTEMIC = make_epistemic_block(
    speech_act="assertion",
    epistemic_state="grounding",
)


def canonical_event_type(event_type: str) -> str:
    candidate = str(event_type).strip().lower()
    return _EVENT_TYPE_ALIASES.get(candidate, candidate)


def kind_for_event_type(event_type: str) -> str:
    return _KIND_BY_EVENT_TYPE.get(canonical_event_type(event_type), "exchange")


def schema_id_for(use_case: str, event_type: str, kind: str, schema_trust_level: str) -> str:
    normalized_use_case = normalize_use_case(use_case)
    canonical = canonical_event_type(event_type)
    area, topic = _SCHEMA_TOPIC_BY_EVENT_TYPE.get(canonical, ("coordination", canonical))
    version = schema_version_for_kind(kind)
    if schema_trust_level == "certified":
        return f"urn:ioc:{normalized_use_case}:{area}:{topic}:v{version}"
    return f"urn:ioc:draft:{normalized_use_case}:{area}:{topic}:v{version}"


def get_topic(header: Dict[str, Any]) -> "str | None":
    ctx = header.get("context") or {}
    return ctx.get("topic") or (ctx.get("epistemic") or {}).get("concept_id")


def _default_epistemic_for_event_type(event_type: str) -> Dict[str, Any]:
    return dict(_DEFAULT_EPISTEMIC_BY_EVENT_TYPE.get(canonical_event_type(event_type), _DEFAULT_EPISTEMIC))


class RevisionCause(str, Enum):
    semantic_memory = "semantic_memory"
    grounded_argument = "grounded_argument"
    repair_resolution = "repair_resolution"
    repair_guidance = "repair_guidance"


class EpistemicState(str, Enum):
    taskwork = "taskwork"
    grounding = "grounding"
    team_process = "team_process"


class MessageAct(str, Enum):
    assertion = "assertion"
    challenge = "challenge"
    compliance = "compliance"


class BeliefStatus(str, Enum):
    asserted = "asserted"
    deferred = "deferred"
    retracted = "retracted"
    revised = "revised"
    challenged = "challenged"
    unresolved = "unresolved"


@dataclass
class CIPUtterance:
    text: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    addresses_evidence: List[str] = field(default_factory=list)
    ring_round: int = 0
    repair_depth: int = 0


@dataclass
class CIPGrounding:
    contingency_verified: Optional[bool] = None
    contingency_score: Optional[float] = None
    repair_reason: Optional[RepairReason] = None
    challenges: List[str] = field(default_factory=list)


@dataclass
class CIPBelief:
    prior: float = 0.5
    posterior: float = 0.5
    revision_cause: Optional[RevisionCause] = None


@dataclass
class CIPPayload:
    utterance: CIPUtterance = field(default_factory=CIPUtterance)
    grounding: CIPGrounding = field(default_factory=CIPGrounding)
    belief: CIPBelief = field(default_factory=CIPBelief)


class CIPMessageBuilder:
    def __init__(self, episode_urn: str, sender: str) -> None:
        self._ep = episode_urn
        self._sender = sender
        self._receivers: List[str] = []
        self._kind: Optional[Kind] = None
        self._subkind: Optional[str] = None
        self._parents: List[str] = []
        self._msg_act: Optional[MessageAct] = None
        self._ep_state: Optional[EpistemicState] = None
        self._belief_status: Optional[BeliefStatus] = None
        self._concept: Optional[str] = None
        self._cip_payload: Optional[CIPPayload] = None
        self._text: Optional[str] = None
        self._uncertainty: float = 0.0
        # Additive fields for the full CIP event-type vocabulary (see .event_type()).
        # Unused by processor.py's narrower repair-loop usage; None means "use the
        # fixed CIP_SCHEMA_URN / no policy block", preserving today's behaviour.
        self._event_type: Optional[str] = None
        self._use_case: Optional[str] = None
        self._sequence_number: Optional[int] = None
        self._provenance_sources: List[str] = []
        self._sensitivity: Optional[str] = None
        self._propagation: Optional[str] = None
        self._retention_policy: Optional[str] = None

    def contingency(self) -> "CIPMessageBuilder":
        self._kind = Kind.contingency
        return self

    def to(self, *receivers: str) -> "CIPMessageBuilder":
        """Set one or more receiver agent IDs."""
        self._receivers = list(receivers)
        return self

    # Alias for `.to()` — matches the legacy flat-header adapter API.
    recipients = to

    def use_case(self, value: str) -> "CIPMessageBuilder":
        self._use_case = value
        return self

    def event_type(
        self,
        event_type: str,
        *,
        kind_override: Optional[str] = None,
        subkind: Optional[str] = None,
    ) -> "CIPMessageBuilder":
        """Configure kind/subkind/schema/epistemic defaults for a CIP event_type."""
        canonical = canonical_event_type(event_type)
        self._event_type = canonical
        kind_value = kind_override or kind_for_event_type(canonical)
        if ":" in kind_value:
            kind_value, auto_subkind = kind_value.split(":", 1)
            subkind = subkind or auto_subkind
        self._kind = Kind(kind_value)
        if subkind is not None:
            self._subkind = subkind
        default_epistemic = _default_epistemic_for_event_type(canonical)
        self._msg_act = MessageAct(default_epistemic["message_act"])
        self._ep_state = EpistemicState(default_epistemic["state"])
        if self._belief_status is None:
            self._belief_status = BeliefStatus(default_epistemic["belief_status"])
        return self

    def sequence_number(self, value: int) -> "CIPMessageBuilder":
        self._sequence_number = value
        return self

    def provenance_sources(self, *sources: str) -> "CIPMessageBuilder":
        self._provenance_sources = list(sources)
        return self

    def policy(
        self,
        *,
        sensitivity: str = "internal",
        propagation: str = "restricted",
        retention_policy: Optional[str] = None,
    ) -> "CIPMessageBuilder":
        self._sensitivity = sensitivity
        self._propagation = propagation
        self._retention_policy = retention_policy or (
            f"policy.{self._use_case}.default" if self._use_case else None
        )
        return self

    def commit_resolved(self) -> "CIPMessageBuilder":
        self._kind = Kind.commit
        self._subkind = "resolved"
        return self

    def commit_exhausted(self) -> "CIPMessageBuilder":
        self._kind = Kind.commit
        self._subkind = "exhausted"
        return self

    def grounding(self) -> "CIPMessageBuilder":
        self._ep_state = EpistemicState.grounding
        return self

    def team_process(self) -> "CIPMessageBuilder":
        self._ep_state = EpistemicState.team_process
        return self

    def challenged(self) -> "CIPMessageBuilder":
        self._belief_status = BeliefStatus.challenged
        self._msg_act = MessageAct.challenge
        return self

    def revised(self) -> "CIPMessageBuilder":
        self._belief_status = BeliefStatus.revised
        self._msg_act = MessageAct.assertion
        return self

    def unresolved(self) -> "CIPMessageBuilder":
        self._belief_status = BeliefStatus.unresolved
        return self

    def concept(self, concept_id: str) -> "CIPMessageBuilder":
        self._concept = concept_id
        return self

    def parents(self, *ids: str) -> "CIPMessageBuilder":
        self._parents = list(ids)
        return self

    def payload(self, payload: CIPPayload) -> "CIPMessageBuilder":
        self._cip_payload = payload
        return self

    def text(self, utterance: str) -> "CIPMessageBuilder":
        self._text = utterance
        return self

    def build(self) -> L9:
        if self._kind is None:
            raise ValueError("Set a kind before calling build().")

        msg_id = str(uuid.uuid4())
        payload = self._to_pydantic_payload()
        attributes: Dict[str, Any] = {}
        if self._text:
            attributes["utterance_text"] = self._text
        if self._sequence_number is not None:
            attributes["sequence_number"] = self._sequence_number
        if self._provenance_sources:
            attributes["msg_sources"] = list(self._provenance_sources)

        schema_id = CIP_SCHEMA_URN
        if self._event_type is not None and self._use_case is not None:
            trust_level = schema_trust_level_for_kind(self._kind.value)
            schema_id = schema_id_for(self._use_case, self._event_type, self._kind.value, trust_level)

        policy = None
        if self._sensitivity is not None or self._propagation is not None:
            policy = PolicyLabel(
                sensitivity=self._sensitivity or "internal",
                propagation=self._propagation or "restricted",
                retention_policy=self._retention_policy or "policy.default",
            )

        return L9(
            header=L9Header(
                protocol="SSTP",
                subprotocol="CIP",
                version="0.0.3",
                kind=self._kind.value,
                subkind=self._subkind,
                participants=ParticipantSet(actors=[
                    Actor(id=self._sender, role="sender"),
                    *[Actor(id=r, role="receiver") for r in self._receivers],
                ], groups=None),
                message={"id": msg_id, "parents": list(self._parents), "episode": self._ep},
                attributes=attributes or None,
                policy=policy,
                context=Context(
                    topic=self._concept or "",
                    epistemic=Epistemic(
                        message_act=self._msg_act.value if self._msg_act else None,
                        state=self._ep_state.value if self._ep_state else None,
                        belief_status=self._belief_status.value if self._belief_status else None,
                        concept_id=self._concept,
                        uncertainty=self._uncertainty,
                        epistemic_kind="cip",
                    ),
                    semantic=Semantic(
                        schema_id=schema_id,
                        ontology_ref=CIP_ONTOLOGY_REF,
                    ),
                ),
            ),
            payload=L9Payload(
                type="cip",
                data=payload.model_dump(),
            ),
        )

    def _to_pydantic_payload(self) -> CIPMessagePayload:
        internal = self._cip_payload or CIPPayload()
        return CIPMessagePayload(
            utterance=CIPUtteranceBlock(
                text=self._text or internal.utterance.text,
                evidence=list(internal.utterance.evidence),
                addresses_evidence=list(internal.utterance.addresses_evidence),
                ring_round=internal.utterance.ring_round,
                repair_depth=internal.utterance.repair_depth,
            ),
            grounding=CIPGroundingBlock(
                contingency_verified=internal.grounding.contingency_verified,
                contingency_score=internal.grounding.contingency_score,
                repair_reason=(
                    internal.grounding.repair_reason.value
                    if internal.grounding.repair_reason
                    else None
                ),
                challenges=list(internal.grounding.challenges),
            ),
            belief=CIPBeliefBlock(
                prior=internal.belief.prior,
                posterior=internal.belief.posterior,
                revision_cause=(
                    internal.belief.revision_cause.value
                    if internal.belief.revision_cause
                    else None
                ),
            ),
        )


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
    normalized_use_case = normalize_use_case(use_case)
    builder = CIPMessageBuilder(
        episode_urn=episode_id or f"urn:ioc:{normalized_use_case}:state:shared_dialogue",
        sender=str(sender or "unknown"),
    ).use_case(use_case).event_type(event_type, kind_override=kind_override)
    effective_recipients = list(recipients) if recipients is not None else (
        [str(receiver)] if receiver and str(receiver) != str(sender or "unknown") else []
    )
    if effective_recipients:
        builder.to(*effective_recipients)
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
        sensitivity=sensitivity,
        propagation=propagation,
        retention_policy=f"policy.{normalized_use_case}.default",
    )
    l9_obj = builder.build()
    header_dump = l9_obj.header.model_dump(mode="json", exclude_none=False)
    kind = header_dump.get("kind") or kind_override or kind_for_event_type(event_type)
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
        epistemic=epistemic if epistemic is not None else _default_epistemic_for_event_type(event_type),
        schema_id=schema_id_for(
            use_case,
            event_type,
            kind,
            schema_trust_level_for_kind(kind),
        ),
        ontology_ref=ontology_ref,
        subprotocol=subprotocol,
        payload_parts=payload_parts,
        sensitivity=sensitivity,
        propagation=propagation,
        provenance_sources=provenance_sources,
    )


__all__ = [
    "CIP_PROTOCOL",
    "CIP_PROTOCOL_VERSION",
    "BeliefStatus",
    "CIPBelief",
    "CIPGrounding",
    "CIPMessageBuilder",
    "CIPPayload",
    "CIPUtterance",
    "EpistemicState",
    "Kind",
    "MessageAct",
    "RepairReason",
    "RevisionCause",
    "_KIND_BY_EVENT_TYPE",
    "build_l9_header",
    "canonical_event_type",
    "get_topic",
    "kind_for_event_type",
    "schema_id_for",
]

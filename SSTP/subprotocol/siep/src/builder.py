# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Compact SIEP message model and fluent builder used by the demo."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, List, Optional
import json
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
# Reused, not duplicated: the SNP operation → event_type/kind/epistemic
# vocabulary already declared in l9.py. `.operation()` below builds on the
# same tables `build_snp_l9_header()` uses, so the two code paths stay in
# sync until hcpanel's call sites migrate onto this builder and
# l9.py/l9_base.py can be retired (see SSTP/l9_base.py docstring).
from SSTP.subprotocol.siep.src import l9 as _l9
from SSTP.l9_base import schema_trust_level_for_kind as _schema_trust_level_for_kind



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

    # Alias for `.to()` — matches the `recipients` terminology used by
    # l9_base.L9HeaderBuilder.build() for callers migrating off build_snp_l9_header().
    recipients = to

    def use_case(self, value: str) -> "SIEPMessageBuilder":
        self._use_case = value
        return self

    def operation(self, operation: str) -> "SIEPMessageBuilder":
        """Configure kind/epistemic defaults for an SNP ``operation``.

        Reuses the vocabulary already declared in ``l9.py``
        (``_SNP_OPERATION_TO_EVENT_TYPE``, ``_SNP_EVENT_TYPE_TO_KIND``,
        ``_SNP_DEFAULT_EPISTEMIC``) instead of redeclaring it, so this
        builder can eventually cover every SNP operation
        ``build_snp_l9_header()`` does today.
        """
        op = operation.value if hasattr(operation, "value") else str(operation)
        self._operation = op
        event_type = _l9.snp_event_type_for_operation(op)
        self._kind = Kind(_l9._SNP_EVENT_TYPE_TO_KIND.get(event_type, "exchange"))
        sa, es = _l9._SNP_DEFAULT_EPISTEMIC.get(
            op, (_l9.SpeechAct.ASSERTION, _l9.EpistemicState.TEAM_PROCESS)
        )
        self._msg_act = MessageAct(sa.value)
        self._ep_state = EpistemicState(es.value)
        if self._belief_status is None:
            self._belief_status = BeliefStatus.asserted
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
            trust_level = _schema_trust_level_for_kind(self._kind.value)
            event_type = _l9.snp_event_type_for_operation(self._operation)
            schema_id = _l9._BUILDER.schema_id_for(self._use_case, event_type, self._kind.value, trust_level)

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
                subkind=self._subkind.value if self._subkind else None,
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
    "contingency_score",
]

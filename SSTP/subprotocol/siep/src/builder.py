# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Compact SIEP message model and fluent builder used by the demo."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional
import uuid


class Kind(str, Enum):
    intent = "intent"
    exchange = "exchange"
    contingency = "contingency"
    commit = "commit"


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
    evidence: List[str] = field(default_factory=list)
    addresses_evidence: List[str] = field(default_factory=list)
    turn_depth: int = 0


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
    kind: Kind
    actor: ActorRef
    message: MessageRef
    epistemic: SIEPEpistemic
    payload: List[PayloadPart] = field(default_factory=list)
    protocol: str = "SSTP"
    version: str = "1.0.0"
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

    def intent(self) -> "SIEPMessageBuilder":
        self._kind = Kind.intent
        return self

    def exchange(self) -> "SIEPMessageBuilder":
        self._kind = Kind.exchange
        return self

    def contingency(self) -> "SIEPMessageBuilder":
        self._kind = Kind.contingency
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

    def build(self) -> L9Message:
        if self._kind is None:
            raise ValueError("Set a kind before calling build().")
        payload_parts: List[PayloadPart] = []
        if self._siep_payload is not None:
            payload_parts.append(PayloadPart(type="siep", location="inline", content=self._siep_payload))
        if self._text:
            payload_parts.append(PayloadPart(type="utterance", location="inline", content=self._text))
        return L9Message(
            protocol="SSTP",
            version="1.0.0",
            subprotocol="SIEP",
            kind=self._kind,
            subkind=self._subkind,
            actor=ActorRef(id=self._sender),
            message=MessageRef(id=str(uuid.uuid4()), parents=self._parents, episode=self._ep),
            epistemic=SIEPEpistemic(
                message_act=self._msg_act,
                state=self._ep_state,
                belief_status=self._belief_status,
                concept_id=self._concept,
                uncertainty=self._uncertainty,
            ),
            payload=payload_parts,
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

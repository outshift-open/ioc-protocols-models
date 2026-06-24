# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Compact CIP message model and fluent builder used by the processor/demo."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import json
import uuid

from ai.outshift.data_model import L9, L9Header, L9Payload, Actor, ParticipantSet, Context, Semantic, Epistemic  # noqa: E402 — requires language_bindings/python on sys.path
from SSTP.subprotocol.cip.src.cip_payload import (
    CIPBeliefBlock,
    CIPGroundingBlock,
    CIPMessagePayload,
    CIPUtteranceBlock,
    CIP_ONTOLOGY_REF,
    CIP_SCHEMA_URN,
    RepairReason as _RepairReasonBase,
)


RepairReason = _RepairReasonBase  # re-export from cip_payload (no wheel dep)


class Kind(str, Enum):
    contingency = "contingency"
    commit = "commit"


class RevisionCause(str, Enum):
    semantic_memory = "semantic_memory"
    grounded_argument = "grounded_argument"
    repair_resolution = "repair_resolution"
    repair_guidance = "repair_guidance"


class EpistemicState(str, Enum):
    grounding = "grounding"
    team_process = "team_process"


class MessageAct(str, Enum):
    assertion = "assertion"
    challenge = "challenge"


class BeliefStatus(str, Enum):
    challenged = "challenged"
    revised = "revised"
    unresolved = "unresolved"


@dataclass
class CIPUtterance:
    text: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    addresses_evidence: List[str] = field(default_factory=list)
    turn_depth: int = 0


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

    def contingency(self) -> "CIPMessageBuilder":
        self._kind = Kind.contingency
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
        attributes = {"utterance_text": self._text} if self._text else None
        return L9(
            header=L9Header(
                protocol="SSTP",
                subprotocol="CIP",
                version="0.0.3",
                kind=self._kind.value,
                subkind=self._subkind,
                participants=ParticipantSet(actors=[Actor(id=self._sender, role="sender")], groups=None),
                message={"id": msg_id, "parents": json.dumps(list(self._parents)), "episode": self._ep},
                attributes=attributes,
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
                        schema_id=CIP_SCHEMA_URN,
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
                turn_depth=internal.utterance.turn_depth,
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


__all__ = [
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
]

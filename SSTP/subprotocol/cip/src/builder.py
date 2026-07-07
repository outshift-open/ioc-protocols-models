# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Compact CIP message model and fluent builder used by the processor/demo."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import json
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
# Reused, not duplicated: the CIP event-type → kind/schema/epistemic vocabulary
# tables already declared in l9.py. `.event_type()` below builds on the same
# tables `build_l9_header()` uses, so the two code paths stay in sync until
# hcpanel's call sites migrate onto this builder and l9.py/l9_base.py can be
# retired (see SSTP/l9_base.py docstring).
from SSTP.subprotocol.cip.src import l9 as _l9
from SSTP.l9_base import schema_trust_level_for_kind as _schema_trust_level_for_kind


RepairReason = _RepairReasonBase  # re-export from cip_payload (no wheel dep)

# Kind is imported directly from the generated L9Schema (ai.outshift.data_model)
# — the canonical 5-value enum (intent, contingency, exchange, commit,
# knowledge) — not redeclared here, so CIP can never drift from the schema.
# (SIEP's builder.py already followed this pattern; CIP previously had its
# own local 2-member duplicate — fixed to match.)


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

    # Alias for `.to()` — matches the `recipients` terminology used by
    # l9_base.L9HeaderBuilder.build() for callers migrating off build_l9_header().
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
        """Configure kind/subkind/schema/epistemic defaults for a CIP event_type.

        Reuses the vocabulary tables already declared in ``l9.py``
        (``_KIND_BY_EVENT_TYPE``, ``_SCHEMA_TOPIC_BY_EVENT_TYPE``,
        ``_CIP_DEFAULT_EPISTEMIC``) instead of redeclaring them, so this
        builder can eventually cover every event type ``build_l9_header()``
        does today.
        """
        canonical = _l9.canonical_event_type(event_type)
        self._event_type = canonical
        kind_value = kind_override or _l9.kind_for_event_type(canonical)
        if ":" in kind_value:
            kind_value, auto_subkind = kind_value.split(":", 1)
            subkind = subkind or auto_subkind
        self._kind = Kind(kind_value)
        if subkind is not None:
            self._subkind = subkind
        sa, es = _l9._CIP_DEFAULT_EPISTEMIC.get(
            canonical, (_l9.SpeechAct.ASSERTION, _l9.EpistemicState.GROUNDING)
        )
        self._msg_act = MessageAct(sa.value)
        self._ep_state = EpistemicState(es.value)
        if self._belief_status is None:
            self._belief_status = BeliefStatus.asserted
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
            trust_level = _schema_trust_level_for_kind(self._kind.value)
            schema_id = _l9.schema_id_for(self._use_case, self._event_type, self._kind.value, trust_level)

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

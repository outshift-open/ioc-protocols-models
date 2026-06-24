# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""CIP processor — handles repair requests and closes repair branches."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ai.outshift.data_model import L9
from SSTP.subprotocol.cip.src.builder import (
    CIPBelief,
    CIPGrounding,
    CIPMessageBuilder,
    CIPPayload,
    CIPUtterance,
    RepairReason,
    RevisionCause,
)
from SSTP.subprotocol.cip.src.cip_payload import CIPMessagePayload
from SSTP.subprotocol.cip.src.engine import CIPEngine, CIPEngineConfig
from SSTP.subprotocol.cip.src.grounding import contingency_check, diagnose_repair_reason


def _make_llm_client():
    """Use LiteLLMClient if LLM env vars are set, otherwise None (template fallback)."""
    import os
    if os.environ.get("LLM_API_KEY") or os.environ.get("LLM_API_BASE"):
        from SSTP.utils.llm import LiteLLMClient
        return LiteLLMClient()
    return None

THETA_C = 0.40
D_MAX = 3


@dataclass
class RepairBranch:
    request: L9
    target_message_id: str
    reference_evidence: List[str]
    repair_reason: str
    depth: int = 0
    last_score: float = 0.0
    guidance_ids: set[str] = field(default_factory=set)


class CIPProcessor:
    def __init__(self, agent_id: str, episode_urn: str, config: CIPEngineConfig):
        self.agent_id = agent_id
        self.episode = episode_urn
        self._engine = CIPEngine(config=config, llm_client=_make_llm_client())
        self._repairs: Dict[str, RepairBranch] = {}

    def process(self, msg: L9) -> List[L9]:
        branch = self._find_branch(msg)
        if branch is not None:
            return self._on_repair_attempt(msg, branch)
        if msg.header.kind.value == "contingency":
            return self._on_repair_request(msg)
        return []

    def _on_repair_request(self, msg: L9) -> List[L9]:
        payload = _cip_payload(msg)
        score = float(payload.grounding.contingency_score or 0.0)
        repair_reason = payload.grounding.repair_reason or RepairReason.grounding_failure.value
        target_id = _first_parent(msg) or msg.header.message.id
        branch = RepairBranch(
            request=msg,
            target_message_id=target_id,
            reference_evidence=list(payload.grounding.challenges),
            repair_reason=repair_reason,
            last_score=score,
        )
        self._repairs[target_id] = branch
        guidance = self._repair_guidance(msg, score, repair_reason)
        branch.guidance_ids.add(guidance.header.message.id)
        return [guidance]

    def _on_repair_attempt(self, msg: L9, branch: RepairBranch) -> List[L9]:
        branch.depth += 1
        attempt_payload = _cip_payload(msg)

        request_epistemic = _epistemic_dict(branch.request)
        attempt_epistemic = _epistemic_dict(msg)
        anchor_concepts = [request_epistemic["concept_id"]] if request_epistemic.get("concept_id") else None
        attempt_concepts = list(attempt_payload.utterance.evidence) or (
            [attempt_epistemic["concept_id"]] if attempt_epistemic.get("concept_id") else None
        )

        verified, score = contingency_check(
            request_epistemic,
            attempt_epistemic,
            threshold=THETA_C,
            a_ie_concept_ids=anchor_concepts,
            a_ie_addresses_evidence=branch.reference_evidence or anchor_concepts,
            b_ie_concept_ids=attempt_concepts,
            b_ie_addresses_evidence=list(attempt_payload.utterance.addresses_evidence),
        )
        reason = diagnose_repair_reason(
            request_epistemic,
            attempt_epistemic,
            a_ie_concept_ids=anchor_concepts,
            a_ie_addresses_evidence=branch.reference_evidence or anchor_concepts,
            b_ie_concept_ids=attempt_concepts,
            b_ie_addresses_evidence=list(attempt_payload.utterance.addresses_evidence),
        )
        repair_reason = reason.value if reason is not None else branch.repair_reason
        branch.last_score = score

        contingency_action = self._engine.adaptive_contingency(
            alignment_score=score,
            disagreement=max(0.0, 1.0 - score),
            urgency=0.0,
            anchor_gap=max(0.0, 1.0 - score) if repair_reason == RepairReason.scope_mismatch.value else 0.0,
            ema_alignment=(branch.last_score + score) / 2,
            ambiguity_score=0.75 if repair_reason == RepairReason.grounding_failure.value else 0.0,
        )

        if verified and score >= THETA_C and contingency_action in {"normal_alignment", "expedite_decision"}:
            del self._repairs[branch.target_message_id]
            return [self._repair_resolved(msg, score)]

        if branch.depth >= D_MAX:
            del self._repairs[branch.target_message_id]
            return [self._repair_exhausted(msg, score, repair_reason, branch.depth)]

        guidance = self._repair_guidance(msg, score, repair_reason)
        branch.guidance_ids.add(guidance.header.message.id)
        return [guidance]

    def _repair_guidance(self, msg: L9, score: float, repair_reason: str) -> L9:
        payload = _cip_payload(msg)
        concept_id = _concept(msg) or ""
        listener = _sender_id(msg)
        contingency_action = self._engine.adaptive_contingency(
            alignment_score=score,
            disagreement=max(0.0, 1.0 - score),
            urgency=0.0,
            anchor_gap=max(0.0, 1.0 - score) if repair_reason == RepairReason.scope_mismatch.value else 0.0,
            ema_alignment=score,
            ambiguity_score=0.75 if repair_reason == RepairReason.grounding_failure.value else 0.0,
        )
        guidance, _ = self._engine.adaptive_agent_utterance(
            listener=listener,
            contingency=contingency_action,
            speaker=self.agent_id,
            task_goal=concept_id,
        )
        challenges = list(payload.grounding.challenges) or ([concept_id] if concept_id else [])
        repair_depth = payload.utterance.repair_depth + 1
        text = f"{guidance} reason={repair_reason}; address={challenges or ['current_concept']}"
        return (
            self._builder()
            .contingency().grounding().challenged()
            .concept(concept_id)
            .parents(msg.header.message.id)
            .payload(CIPPayload(
                utterance=CIPUtterance(
                    text=text,
                    evidence=[concept_id] if concept_id else [],
                    addresses_evidence=challenges,
                    ring_round=payload.utterance.ring_round,
                    repair_depth=repair_depth,
                ),
                grounding=CIPGrounding(
                    contingency_verified=False,
                    contingency_score=round(score, 4),
                    repair_reason=RepairReason(repair_reason),
                    challenges=challenges,
                ),
                belief=CIPBelief(
                    prior=0.5,
                    posterior=0.5,
                    revision_cause=RevisionCause.repair_guidance,
                ),
            ))
            .text(text)
            .build()
        )

    def _repair_resolved(self, msg: L9, score: float) -> L9:
        concept_id = _concept(msg) or ""
        payload = _cip_payload(msg)
        text = f"repair_verified:{_sender_id(msg)} re-anchored to {concept_id or 'shared scope'}"
        return (
            self._builder()
            .commit_resolved().grounding().revised()
            .concept(concept_id)
            .parents(msg.header.message.id)
            .payload(CIPPayload(
                utterance=CIPUtterance(
                    text=text,
                    evidence=list(payload.utterance.evidence),
                    addresses_evidence=list(payload.utterance.addresses_evidence),
                    ring_round=payload.utterance.ring_round,
                ),
                grounding=CIPGrounding(
                    contingency_verified=True,
                    contingency_score=round(score, 4),
                    challenges=list(payload.utterance.addresses_evidence),
                ),
                belief=CIPBelief(
                    prior=payload.belief.prior,
                    posterior=payload.belief.posterior,
                    revision_cause=RevisionCause.repair_resolution,
                ),
            ))
            .text(text)
            .build()
        )

    def _repair_exhausted(self, msg: L9, score: float, repair_reason: str, depth: int) -> L9:
        concept_id = _concept(msg) or ""
        text = f"repair_exhausted:reason={repair_reason}:depth={depth}:target={msg.header.message.id}"
        return (
            self._builder()
            .commit_exhausted().grounding().unresolved()
            .concept(concept_id)
            .parents(msg.header.message.id)
            .payload(CIPPayload(
                grounding=CIPGrounding(
                    contingency_verified=False,
                    contingency_score=round(score, 4),
                    repair_reason=RepairReason(repair_reason),
                ),
                belief=CIPBelief(revision_cause=RevisionCause.repair_resolution),
            ))
            .text(text)
            .build()
        )

    def _find_branch(self, msg: L9) -> Optional[RepairBranch]:
        parents = set(msg.header.message.parents if msg.header.message else [])
        if not parents:
            return None
        for branch in self._repairs.values():
            tracked = {branch.request.header.message.id, branch.target_message_id, *branch.guidance_ids}
            if parents & tracked:
                return branch
        return None

    def _builder(self) -> CIPMessageBuilder:
        return CIPMessageBuilder(self.episode, self.agent_id)


def _sender_id(msg: L9) -> str:
    actors = msg.header.participants.actors
    if not actors:
        raise ValueError("L9 message is missing a sender actor.")
    return actors[0].id


def _first_parent(msg: L9) -> Optional[str]:
    message = msg.header.message
    if message and message.parents:
        return message.parents[0]
    return None


def _concept(msg: L9) -> Optional[str]:
    context = msg.header.context
    if not context:
        return None
    # context.topic is the canonical concept_id location
    if context.topic:
        return context.topic
    epistemic = context.epistemic
    if epistemic is None:
        return None
    return getattr(epistemic, "concept_id", None)


def _epistemic_dict(msg: L9) -> dict:
    context = msg.header.context
    if not context:
        return {}
    result: dict = {}
    if context.topic:
        result["concept_id"] = context.topic
    epistemic = context.epistemic
    if epistemic is not None:
        dumped = epistemic.model_dump(exclude_none=True)
        # Merge, but don't override concept_id already set from topic
        for k, v in dumped.items():
            result.setdefault(k, v)
    return result


def _cip_payload(msg: L9) -> CIPMessagePayload:
    return CIPMessagePayload.model_validate(msg.payload.data)


__all__ = ["CIPProcessor", "D_MAX", "THETA_C"]

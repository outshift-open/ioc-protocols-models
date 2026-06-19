# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""SIEP grounding verifier and repair-cycle handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ioc_l9.src import L9
from SSTP.subprotocol.siep.src.builder import (
    EpistemicState,
    Kind,
    RepairReason,
    RevisionCause,
    SIEPBelief,
    SIEPGrounding,
    SIEPMessageBuilder,
    SIEPPayload,
    SIEPUtterance,
    contingency_score,
)
from SSTP.subprotocol.siep.src.siep_payload import SIEPMessagePayload
from SSTP.subprotocol.siep.src.tomcore.cognition import TheoryOfMindEngine
from SSTP.subprotocol.siep.src.tomcore.interaction import InteractionEngine
from SSTP.utils.llm import LiteLLMClient, NoOpLLMClient


def _make_llm_client():
    """Use LiteLLMClient if LLM env vars are set, otherwise fall back to NoOp."""
    import os
    if os.environ.get("LLM_API_KEY") or os.environ.get("LLM_BASE_URL"):
        return LiteLLMClient()
    return NoOpLLMClient()

THETA_C = 0.40
D_MAX = 3


def _concept(msg: L9) -> Optional[str]:
    context = msg.header.context
    epistemic = context.epistemic if context else None
    return epistemic.concept_id if epistemic else None


def _sender_id(msg: L9) -> str:
    actors = msg.header.actors.actors
    if not actors:
        raise ValueError("SIEP L9 message is missing a sender actor.")
    return actors[0].id


def _siep_payload(msg: L9) -> SIEPMessagePayload:
    return SIEPMessagePayload.model_validate(msg.payload.data)


@dataclass
class RepairBranch:
    contingency_msg_id: str
    bad_turn_id: str
    bad_turn_evidence: List[str]
    depth: int = 0


class SIEPEngine:
    def __init__(self, agent_id: str, episode_urn: str) -> None:
        self.agent_id = agent_id
        self.episode = episode_urn
        self._priors: Dict[Tuple[str, str], SIEPBelief] = {}
        self._last_exchange: Dict[str, L9] = {}
        self._repairs: Dict[str, RepairBranch] = {}
        self._tom = TheoryOfMindEngine(_make_llm_client())
        self._ie = InteractionEngine()
        self._seeded_peers: Set[str] = set()

    def process(self, msg: L9) -> List[L9]:
        if msg.header.kind == Kind.intent.value:
            return []
        if msg.header.kind == Kind.exchange.value:
            return self._on_exchange(msg)
        return []

    def _on_exchange(self, msg: L9) -> List[L9]:
        sender = _sender_id(msg)
        siep_payload = _siep_payload(msg)
        concept = _concept(msg) or ""
        utterance_text = siep_payload.utterance.text if siep_payload.utterance else ""

        # Seed TOM peer model on first contact
        if sender not in self._seeded_peers:
            self._tom.agent(self.agent_id).seed_peer(sender, sender, {"task_goal": concept})
            self._seeded_peers.add(sender)

        epistemic = msg.header.context.epistemic if msg.header.context else None
        if epistemic and epistemic.state == EpistemicState.taskwork.value:
            key = (sender, concept)
            if key not in self._priors:
                self._priors[key] = SIEPBelief(
                    prior=siep_payload.belief.prior,
                    posterior=siep_payload.belief.posterior,
                    revision_cause=RevisionCause.semantic_memory,
                )
            self._last_exchange[sender] = msg
            return []

        message = msg.header.message
        if message and message.parents:
            for branch in self._repairs.values():
                if branch.contingency_msg_id in message.parents:
                    return self._on_repair_attempt(msg, branch)

        prior = self._last_exchange.get(sender)
        prior_payload = _siep_payload(prior) if prior else None
        prior_evidence = prior_payload.utterance.evidence if prior_payload else []
        score = contingency_score(siep_payload.utterance.evidence, prior_evidence)
        self._last_exchange[sender] = msg

        # Process turn via InteractionEngine (infers intent, detects obvious repair need)
        turn = self._ie.process_turn(sender, utterance_text or " ")

        # Update TOM peer EMA with observed alignment score
        self._tom.agent(self.agent_id).update_peer(
            sender, utterance_text or "", concept, alignment_score=score
        )
        drift = self._tom.agent(self.agent_id).drift_signals()

        # Use adaptive_contingency to decide: TOM drift can escalate a borderline pass to a repair
        contingency_action = self._ie.adaptive_contingency(
            alignment_score=score,
            anchor_gap=drift.get("anchor_gap", 0.0),
            ema_alignment=drift.get("ema_alignment", 1.0),
        )
        force_repair = contingency_action in (
            "repair_hard_stop", "repair_anchor", "repair_alignment", "request_clarification"
        )

        if score >= THETA_C and not force_repair:
            return [self._grounding_ok(msg, score)]
        return [self._request_repair(msg, score, prior_evidence)]

    def _grounding_ok(self, prior: L9, score: float) -> L9:
        concept = _concept(prior)
        my_belief = self._priors.get((self.agent_id, concept or ""))
        evidence = _siep_payload(prior).utterance.evidence
        return (
            self._builder()
            .exchange().grounding().asserted()
            .concept(concept or "")
            .parents(prior.header.message.id)
            .payload(SIEPPayload(
                utterance=SIEPUtterance(evidence=evidence, addresses_evidence=evidence),
                grounding=SIEPGrounding(contingency_verified=True, contingency_score=round(score, 4)),
                belief=SIEPBelief(
                    prior=my_belief.prior if my_belief else 0.5,
                    posterior=my_belief.posterior if my_belief else 0.5,
                    revision_cause=RevisionCause.grounded_argument,
                ),
            ))
            .build()
        )

    def _request_repair(self, bad: L9, score: float, prior_evidence: List[str]) -> L9:
        bad_payload = _siep_payload(bad)
        reason = self._classify(bad_payload.utterance.evidence, prior_evidence)
        msg = (
            self._builder()
            .contingency().grounding().challenged()
            .concept(_concept(bad) or "")
            .parents(bad.header.message.id)
            .payload(SIEPPayload(
                grounding=SIEPGrounding(
                    contingency_verified=False,
                    contingency_score=round(score, 4),
                    repair_reason=reason,
                    challenges=prior_evidence,
                ),
            ))
            .text(f"repair_required:reason={reason.value}:target={bad.header.message.id}")
            .build()
        )
        self._repairs[bad.header.message.id] = RepairBranch(
            contingency_msg_id=msg.header.message.id,
            bad_turn_id=bad.header.message.id,
            bad_turn_evidence=prior_evidence,
        )
        return msg

    def _on_repair_attempt(self, msg: L9, branch: RepairBranch) -> List[L9]:
        branch.depth += 1
        siep_payload = _siep_payload(msg)
        score = contingency_score(
            siep_payload.utterance.evidence,
            branch.bad_turn_evidence,
        )
        if score >= THETA_C:
            del self._repairs[branch.bad_turn_id]
            return [self._close_repair(msg, score)]
        if branch.depth >= D_MAX:
            del self._repairs[branch.bad_turn_id]
            return [self._exhaust_repair(msg, branch)]
        return [self._request_repair(msg, score, branch.bad_turn_evidence)]

    def _close_repair(self, repair: L9, score: float) -> L9:
        return (
            self._builder()
            .commit_converged().grounding().revised()
            .concept(_concept(repair) or "")
            .parents(repair.header.message.id)
            .payload(SIEPPayload(
                grounding=SIEPGrounding(contingency_verified=True, contingency_score=round(score, 4)),
            ))
            .text(f"repair_verified:{_sender_id(repair)} re-anchored")
            .build()
        )

    def _exhaust_repair(self, last: L9, branch: RepairBranch) -> L9:
        return (
            self._builder()
            .commit_rejected().grounding().unresolved()
            .concept(_concept(last) or "")
            .parents(last.header.message.id)
            .text(f"repair_exhausted:depth={branch.depth}:target={branch.bad_turn_id}")
            .build()
        )

    def _builder(self) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(self.episode, self.agent_id)

    @staticmethod
    def _classify(evidence: List[str], prior_evidence: List[str]) -> RepairReason:
        if not evidence:
            return RepairReason.ungroundable_novelty
        if not set(evidence) & set(prior_evidence):
            return RepairReason.scope_mismatch
        return RepairReason.grounding_failure


__all__ = ["D_MAX", "THETA_C", "RepairBranch", "SIEPEngine"]

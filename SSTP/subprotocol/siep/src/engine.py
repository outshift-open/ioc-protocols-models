# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""SIEP grounding verifier and repair-cycle handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from SSTP.subprotocol.siep.src.builder import (
    EpistemicState,
    Kind,
    L9Message,
    RepairReason,
    RevisionCause,
    SIEPBelief,
    SIEPGrounding,
    SIEPMessageBuilder,
    SIEPPayload,
    SIEPUtterance,
    contingency_score,
)

THETA_C = 0.40
D_MAX = 3


def _concept(msg: L9Message) -> Optional[str]:
    return msg.epistemic.concept_id


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
        self._last_exchange: Dict[str, L9Message] = {}
        self._repairs: Dict[str, RepairBranch] = {}

    def process(self, msg: L9Message) -> List[L9Message]:
        if msg.kind == Kind.intent:
            return []
        if msg.kind == Kind.exchange:
            return self._on_exchange(msg)
        return []

    def _on_exchange(self, msg: L9Message) -> List[L9Message]:
        sender = msg.actor.id
        siep_payload = msg.siep_payload()
        if msg.epistemic.state == EpistemicState.taskwork and siep_payload:
            key = (sender, _concept(msg) or "")
            if key not in self._priors:
                self._priors[key] = SIEPBelief(
                    prior=siep_payload.belief.prior,
                    posterior=siep_payload.belief.posterior,
                    revision_cause=RevisionCause.semantic_memory,
                )
            self._last_exchange[sender] = msg
            return []

        if msg.message.parents:
            for branch in self._repairs.values():
                if branch.contingency_msg_id in msg.message.parents:
                    return self._on_repair_attempt(msg, branch)

        if siep_payload is None:
            self._last_exchange[sender] = msg
            return []

        prior = self._last_exchange.get(sender)
        prior_payload = prior.siep_payload() if prior else None
        prior_evidence = prior_payload.utterance.evidence if prior_payload else []
        score = contingency_score(siep_payload.utterance.evidence, prior_evidence)
        self._last_exchange[sender] = msg
        if score >= THETA_C:
            return [self._grounding_ok(msg, score)]
        return [self._request_repair(msg, score, prior_evidence)]

    def _grounding_ok(self, prior: L9Message, score: float) -> L9Message:
        concept = _concept(prior)
        my_belief = self._priors.get((self.agent_id, concept or ""))
        evidence = prior.siep_payload().utterance.evidence if prior.siep_payload() else []
        return (
            self._builder()
            .exchange().grounding().asserted()
            .concept(concept or "")
            .parents(prior.message.id)
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

    def _request_repair(self, bad: L9Message, score: float, prior_evidence: List[str]) -> L9Message:
        bad_payload = bad.siep_payload()
        reason = self._classify(bad_payload.utterance.evidence if bad_payload else [], prior_evidence)
        msg = (
            self._builder()
            .contingency().grounding().challenged()
            .concept(_concept(bad) or "")
            .parents(bad.message.id)
            .payload(SIEPPayload(
                grounding=SIEPGrounding(
                    contingency_verified=False,
                    contingency_score=round(score, 4),
                    repair_reason=reason,
                    challenges=prior_evidence,
                ),
            ))
            .text(f"repair_required:reason={reason.value}:target={bad.message.id}")
            .build()
        )
        self._repairs[bad.message.id] = RepairBranch(
            contingency_msg_id=msg.message.id,
            bad_turn_id=bad.message.id,
            bad_turn_evidence=prior_evidence,
        )
        return msg

    def _on_repair_attempt(self, msg: L9Message, branch: RepairBranch) -> List[L9Message]:
        branch.depth += 1
        siep_payload = msg.siep_payload()
        score = contingency_score(
            siep_payload.utterance.evidence if siep_payload else [],
            branch.bad_turn_evidence,
        )
        if score >= THETA_C:
            del self._repairs[branch.bad_turn_id]
            return [self._close_repair(msg, score)]
        if branch.depth >= D_MAX:
            del self._repairs[branch.bad_turn_id]
            return [self._exhaust_repair(msg, branch)]
        return [self._request_repair(msg, score, branch.bad_turn_evidence)]

    def _close_repair(self, repair: L9Message, score: float) -> L9Message:
        return (
            self._builder()
            .commit_converged().grounding().revised()
            .concept(_concept(repair) or "")
            .parents(repair.message.id)
            .payload(SIEPPayload(
                grounding=SIEPGrounding(contingency_verified=True, contingency_score=round(score, 4)),
            ))
            .text(f"repair_verified:{repair.actor.id} re-anchored")
            .build()
        )

    def _exhaust_repair(self, last: L9Message, branch: RepairBranch) -> L9Message:
        return (
            self._builder()
            .commit_rejected().grounding().unresolved()
            .concept(_concept(last) or "")
            .parents(last.message.id)
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

# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""IE payload v0.1 — single unified payload for the Interaction Engine.

IEPayload carries everything an IE message needs:
  utterance — what the sender is asserting and at what nesting depth
  grounding — contingency verification state (null on prior_injection turns)
  belief    — calibrated belief: prior (GAR anchor) and posterior
  taskwork  — Bayesian evidence chain; present only on prior_injection turns,
              null on all peer_turn / repair turns

This unification means prior_injection and peer_turn carry the same payload
type. The presence of taskwork distinguishes a prior declaration from a
grounding exchange; the presence of grounding.responds_to distinguishes a
response from an opening assertion.

ProcessPayload is kept separate — process negotiation precedes grounding
and is a to-be-defined SNP team-process round, not an IE concern.

Identity (group, episode, actors) is in the L9 header.
The primary concept is in the L9 header epistemic.concept_id — not repeated here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IEUtteranceBlock:
    """The sender's assertion in this turn.

    ``evidence`` carries supporting evidence concept URIs for the argument.
    The primary concept being asserted is in L9 epistemic.concept_id.

    ``turn_depth``:
      0 = top-level exchange or prior declaration
      >0 = inside a repair branch
    """
    content:            str          # assertion text
    evidence:           List[str]    # supporting evidence concept URIs
    addresses_evidence: List[str]    # concept URIs from the prior turn being engaged;
                                     # input to contingency_check(); empty on first turn
    inferred_intent:    str          # short semantic label
    turn_depth:         int = 0


@dataclass
class IEGroundingBlock:
    """Contingency verification state.

    Null on prior_injection turns (no peer to be contingent on).
    Sender fills responds_to; receiver fills contingency_verified and score.
    """
    responds_to:          Optional[str]   = None
    contingency_verified: Optional[bool]  = None
    contingency_score:    Optional[float] = None
    repair_reason:        Optional[str]   = None  # grounding_failure | scope_mismatch | ungroundable_novelty
    challenges:           List[str]       = field(default_factory=list)


@dataclass
class IEBeliefBlock:
    """Sender's calibrated belief on the concept being asserted.

    prior  — set at episode open from SemanticMemory; immutable per episode;
             the GAR anchor that measures whether the content round moved the agent
    posterior — current belief after all revisions this episode
    """
    prior:          float
    posterior:      float
    revision_cause: Optional[str] = None  # grounded_argument | social_compliance |
                                          # semantic_memory | new_evidence | repair_resolution


@dataclass
class IETaskworkBlock:
    """Bayesian evidence chain for prior_injection turns.

    Present only when epistemic_state=taskwork (prior declaration).
    Null on peer_turn / repair turns.

    findings   — structured observations extracted from patient/case data
    likelihoods — per-finding likelihood ratios used in Naive Bayes posterior
    reasoning_summary — LLM-generated explanation of the chain
    """
    findings:          List[dict]    # [{finding_id, value, source}]
    likelihoods:       List[tuple]   # [(finding_id, likelihood_ratio)]
    reasoning_summary: str = ""


@dataclass
class IEPayload:
    """IE payload v0.1 — unified payload for all IE turns.

    prior_injection: grounding=IEGroundingBlock() (all null), taskwork=IETaskworkBlock(...)
    peer_turn:       grounding=IEGroundingBlock(responds_to=...), taskwork=None
    repair_required: grounding=IEGroundingBlock(repair_reason=...), taskwork=None
    """
    utterance: IEUtteranceBlock
    grounding: IEGroundingBlock
    belief:    IEBeliefBlock
    taskwork:  Optional[IETaskworkBlock] = None  # present only on prior_injection turns

    def to_dict(self) -> dict:
        d: dict = {
            "utterance": {
                "content":            self.utterance.content,
                "evidence":           list(self.utterance.evidence),
                "addresses_evidence": list(self.utterance.addresses_evidence),
                "inferred_intent":    self.utterance.inferred_intent,
                "turn_depth":         self.utterance.turn_depth,
            },
            "grounding": {
                "responds_to":          self.grounding.responds_to,
                "contingency_verified": self.grounding.contingency_verified,
                "contingency_score":    self.grounding.contingency_score,
                "repair_reason":        self.grounding.repair_reason,
                "challenges":           list(self.grounding.challenges),
            },
            "belief": {
                "prior":          self.belief.prior,
                "posterior":      self.belief.posterior,
                "revision_cause": self.belief.revision_cause,
            },
        }
        if self.taskwork is not None:
            d["taskwork"] = {
                "findings":          list(self.taskwork.findings),
                "likelihoods":       [list(lr) for lr in self.taskwork.likelihoods],
                "reasoning_summary": self.taskwork.reasoning_summary,
            }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IEPayload":
        u = d.get("utterance", {})
        g = d.get("grounding", {})
        b = d.get("belief", {})
        tw = d.get("taskwork")
        return cls(
            utterance=IEUtteranceBlock(
                content=u.get("content", ""),
                evidence=list(u.get("evidence") or u.get("concept_ids", [])),
                addresses_evidence=list(u.get("addresses_evidence", [])),
                inferred_intent=u.get("inferred_intent", ""),
                turn_depth=int(u.get("turn_depth", 0)),
            ),
            grounding=IEGroundingBlock(
                responds_to=g.get("responds_to"),
                contingency_verified=g.get("contingency_verified"),
                contingency_score=g.get("contingency_score"),
                repair_reason=g.get("repair_reason"),
                challenges=list(g.get("challenges") or []),
            ),
            belief=IEBeliefBlock(
                prior=float(b.get("prior", 0.5)),
                posterior=float(b.get("posterior", 0.5)),
                revision_cause=b.get("revision_cause"),
            ),
            taskwork=IETaskworkBlock(
                findings=list(tw.get("findings", [])),
                likelihoods=[tuple(lr) for lr in tw.get("likelihoods", [])],
                reasoning_summary=tw.get("reasoning_summary", ""),
            ) if tw else None,
        )


# ── ProcessPayload — team process agreement (to-be-defined as SNP round) ─────

@dataclass
class ProcessPayload:
    """Process payload — carried on process_proposed/accepted/challenged turns.

    Placeholder until team-process is modelled as a proper SNP convergence round.
    """
    coordinator_id:   str
    participant_ids:  List[str] = field(default_factory=list)
    role_assignments: List[dict] = field(default_factory=list)
    challenge_reason: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {
            "coordinator_id":   self.coordinator_id,
            "participant_ids":  list(self.participant_ids),
            "role_assignments": list(self.role_assignments),
        }
        if self.challenge_reason is not None:
            d["challenge_reason"] = self.challenge_reason
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProcessPayload":
        return cls(
            coordinator_id=d.get("coordinator_id", ""),
            participant_ids=list(d.get("participant_ids", [])),
            role_assignments=list(d.get("role_assignments", [])),
            challenge_reason=d.get("challenge_reason"),
        )


def get_part(message: dict, type_: str) -> dict:
    """Extract the content of a payload part by type from an L9 message dict.

    Returns the content dict/str for the first matching inline part,
    or an empty dict if not found.  Accepts both new (payload list) and
    old (flat payload dict) message shapes for backwards compat.
    """
    parts = message.get("payload")
    if isinstance(parts, list):
        for p in parts:
            if p.get("type") == type_ and p.get("location", "inline") == "inline":
                return p.get("content") or {}
        return {}
    # old flat payload dict — return as-is for IE parts
    if isinstance(parts, dict) and type_ == "ie":
        return parts
    return {}


__all__ = [
    "IEUtteranceBlock",
    "IEGroundingBlock",
    "IEBeliefBlock",
    "IETaskworkBlock",
    "IEPayload",
    "ProcessPayload",
    "get_part",
]

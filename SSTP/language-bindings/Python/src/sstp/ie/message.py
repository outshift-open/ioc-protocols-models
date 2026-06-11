# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""IE payload v0.1 — Interaction Engine wire payload.

IEPayload carries the IE-specific content of a message:
  utterance — evidence URIs, addresses_evidence, turn_depth
  grounding — contingency verification state
  belief    — prior (GAR anchor) and posterior

IE is independent of taskwork and team_process. Those are internal agent
concerns — they do not appear on the IE wire.

Identity (group, episode, actors) is in the L9 header.
The primary concept is in the L9 header topic field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IEUtteranceBlock:
    """The sender's assertion in this turn.

    ``evidence`` carries supporting evidence concept URIs for the argument.
    The primary concept being asserted is in the L9 header topic field.

    ``turn_depth``:
      0 = top-level exchange or initial_prior
      >0 = inside a repair branch
    """
    evidence:           List[str]    # supporting evidence concept URIs
    addresses_evidence: List[str]    # concept URIs from the prior turn being engaged;
                                     # input to contingency_check(); empty on first turn
    turn_depth:         int = 0


@dataclass
class IEGroundingBlock:
    """Contingency verification state.

    Null fields on initial_prior turns (no peer to be contingent on).
    The message being responded to is in L9 message.parents — not repeated here.
    Receiver fills contingency_verified and score.
    """
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
class IEPayload:
    """IE payload v0.1 — utterance + grounding + belief.

    initial_prior: grounding=IEGroundingBlock() (all null)
    peer_turn:     grounding=IEGroundingBlock(contingency_verified=..., contingency_score=...)
    repair_*:      grounding=IEGroundingBlock(repair_reason=...)
    """
    utterance: IEUtteranceBlock
    grounding: IEGroundingBlock
    belief:    IEBeliefBlock

    def to_dict(self) -> dict:
        return {
            "utterance": {
                "evidence":           list(self.utterance.evidence),
                "addresses_evidence": list(self.utterance.addresses_evidence),
                "turn_depth":         self.utterance.turn_depth,
            },
            "grounding": {
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

    @classmethod
    def from_dict(cls, d: dict) -> "IEPayload":
        u = d.get("utterance", {})
        g = d.get("grounding", {})
        b = d.get("belief", {})
        return cls(
            utterance=IEUtteranceBlock(
                evidence=list(u.get("evidence") or u.get("concept_ids", [])),
                addresses_evidence=list(u.get("addresses_evidence", [])),
                turn_depth=int(u.get("turn_depth", 0)),
            ),
            grounding=IEGroundingBlock(
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
        )


# ── ProcessPayload — team process agreement ───────────────────────────────────

@dataclass
class ProcessPayload:
    """Process payload — carried on process_proposed/accepted/challenged turns."""
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
    """Extract the content of a payload part by type from an L9 message dict."""
    parts = message.get("payload")
    if isinstance(parts, list):
        for p in parts:
            if p.get("type") == type_ and p.get("location", "inline") == "inline":
                return p.get("content") or {}
        return {}
    if isinstance(parts, dict) and type_ == "ie":
        return parts
    return {}


__all__ = [
    "IEUtteranceBlock",
    "IEGroundingBlock",
    "IEBeliefBlock",
    "IEPayload",
    "ProcessPayload",
    "get_part",
]

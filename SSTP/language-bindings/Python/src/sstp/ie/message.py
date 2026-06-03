# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""IE payload v0.1 — pairwise grounding payload for the Interaction Engine.

IE exists solely to provide pairwise grounding: ensuring that when A asserts Y to B,
B has correctly understood and integrated Y before the exchange is treated as common
ground.  The IEPayload carries exactly the information needed for that purpose.

Identity (group, episode, actors) is in the L9 header — not repeated here.
Taskwork (independent prior formation) and process (role agreement) are separate
concerns with their own event types and payload structures; they are not part of
pairwise grounding and do not appear in IEPayload.

Three blocks:
  utterance — what the sender is asserting and at what nesting depth
  grounding — the contingency verification state, filled jointly by sender and receiver
  belief    — the sender's calibrated belief on the concept being asserted
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IEUtteranceBlock:
    """The sender's assertion in this grounding turn.

    ``turn_depth`` captures nesting within a repair branch:
      0 = top-level exchange
      >0 = repair branch (each nested repair increments depth)
    """
    content:            str          # assertion text
    concept_ids:        List[str]    # concept URIs this utterance asserts about
    addresses_evidence: List[str]    # concept URIs from the prior turn being engaged;
                                     # input to contingency_check(); empty on first turn
    inferred_intent:    str          # short semantic label: e.g. "assess_medication_risk"
    turn_depth:         int = 0      # 0 = top-level; >0 = inside repair branch


@dataclass
class IEGroundingBlock:
    """Contingency verification state — sender fills responds_to; receiver fills the rest."""
    responds_to:          Optional[str]   = None  # message.id of the utterance being responded to
    contingency_verified: Optional[bool]  = None  # None = not yet checked; receiver writes True/False
    contingency_score:    Optional[float] = None  # concept overlap ratio [0..1]; computed by receiver
    repair_reason:        Optional[str]   = None  # grounding_failure | scope_mismatch |
                                                   # ungroundable_novelty; set on repair_required turns
    challenges:           List[str]       = field(default_factory=list)  # message.ids challenged
                                                   # by alignment_challenge turns


@dataclass
class IEBeliefBlock:
    """Sender's calibrated belief on the concept being asserted.

    Feeds AgentBeliefStore and ReplicaEntry.  Both prior and posterior travel on
    every turn so the receiver can compute BeliefRevision and GAR without a store
    lookup.  prior is the taskwork value — immutable per episode and the GAR anchor.
    """
    concept_id:     str           # concept URI this belief is about
    prior:          float         # belief at episode open; immutable per episode
    posterior:      float         # current belief after all revisions this episode
    revision_cause: Optional[str] = None  # grounded_argument | social_compliance |
                                          # semantic_memory | new_evidence | repair_resolution


@dataclass
class IEPayload:
    """IE payload v0.1 — pairwise grounding payload carried alongside the L9 header.

    Identity (group, episode, actors) is in the L9 header.
    Taskwork and process payloads are separate — they are not grounding.
    """
    utterance: IEUtteranceBlock
    grounding: IEGroundingBlock
    belief:    IEBeliefBlock

    def to_dict(self) -> dict:
        return {
            "utterance": {
                "content":            self.utterance.content,
                "concept_ids":        list(self.utterance.concept_ids),
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
                "concept_id":     self.belief.concept_id,
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
                content=u.get("content", ""),
                concept_ids=list(u.get("concept_ids", [])),
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
                concept_id=b.get("concept_id", ""),
                prior=float(b.get("prior", 0.5)),
                posterior=float(b.get("posterior", 0.5)),
                revision_cause=b.get("revision_cause"),
            ),
        )


__all__ = [
    "IEUtteranceBlock",
    "IEGroundingBlock",
    "IEBeliefBlock",
    "IEPayload",
]

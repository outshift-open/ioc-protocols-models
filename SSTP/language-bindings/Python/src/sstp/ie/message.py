# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""IE payload v0.1 and companion payload types for the Interaction Engine.

Three payload types are defined here, each with a distinct purpose:

IEPayload — pairwise grounding (carried on peer_turn, repair_required, repair_applied)
  IE exists solely to verify that B understood A's specific claim.
  Identity is in the L9 header (group, message.episode, actors) — not repeated here.
  The primary concept is in the L9 header epistemic.concept_id — not repeated in belief.
  utterance.evidence carries supporting evidence concepts (not the primary claim).

TaskworkPayload — independent prior formation (carried on prior_injection turns)
  Each agent's independent Bayesian reasoning chain before any peer contact.
  Concept identity is in the L9 header epistemic.concept_id.

ProcessPayload — team process agreement (carried on process_proposed/accepted turns)
  Role assignments that precede SNP negotiation.
  SNP's NegotiationPayload (operation, proposal_id, posterior, etc.) identifies
  what is being negotiated in the convergence round — not repeated here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ── IEPayload — pairwise grounding ────────────────────────────────────────────

@dataclass
class IEUtteranceBlock:
    """The sender's assertion in this grounding turn.

    ``evidence`` carries the supporting evidence concepts for the argument.
    The primary concept being asserted is in the L9 header epistemic.concept_id.

    ``turn_depth`` captures nesting within a repair branch:
      0 = top-level exchange
      >0 = inside a repair branch (each nested repair increments depth)
    """
    content:            str          # assertion text
    evidence:           List[str]    # supporting evidence concept URIs
                                     # (L9 epistemic.concept_id is the primary claim)
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
                                                   # ungroundable_novelty; set on repair_required
    challenges:           List[str]       = field(default_factory=list)  # message.ids challenged
                                                   # by alignment_challenge turns


@dataclass
class IEBeliefBlock:
    """Sender's calibrated belief on the concept being asserted.

    The concept_id is implicit — it is in the L9 header epistemic.concept_id.
    Both prior and posterior travel on every turn so the receiver can compute
    BeliefRevision and GAR without a store lookup.
    prior is the taskwork value — immutable per episode and the GAR anchor.
    """
    prior:          float         # belief at episode open; immutable per episode
    posterior:      float         # current belief after all revisions this episode
    revision_cause: Optional[str] = None  # grounded_argument | social_compliance |
                                          # semantic_memory | new_evidence | repair_resolution


@dataclass
class IEPayload:
    """IE payload v0.1 — pairwise grounding payload carried alongside the L9 header.

    Identity (group, episode, actors) is in the L9 header.
    The primary concept is in the L9 header epistemic.concept_id.
    Taskwork and process payloads are separate — they are not grounding.
    """
    utterance: IEUtteranceBlock
    grounding: IEGroundingBlock
    belief:    IEBeliefBlock

    def to_dict(self) -> dict:
        return {
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

    @classmethod
    def from_dict(cls, d: dict) -> "IEPayload":
        u = d.get("utterance", {})
        g = d.get("grounding", {})
        b = d.get("belief", {})
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
        )


# ── TaskworkPayload — independent prior formation ─────────────────────────────

@dataclass
class TaskworkPayload:
    """Taskwork payload — carried on prior_injection turns.

    Each specialist's independent Bayesian reasoning chain formed before any
    peer contact.  The concept being assessed is in the L9 header epistemic.concept_id.
    prior and posterior mirror IEBeliefBlock but here they capture the full
    reasoning chain that produced the posterior.
    """
    prior:             float          # from SemanticMemory at episode open
    posterior:         float          # independent conclusion before any peer contact
    findings:          List[dict]     # [{finding_id, value, source}]
    likelihoods:       List[tuple]    # [(finding_id, likelihood_ratio)]
    reasoning_summary: str = ""       # LLM-generated explanation of the chain

    def to_dict(self) -> dict:
        return {
            "prior":             self.prior,
            "posterior":         self.posterior,
            "findings":          list(self.findings),
            "likelihoods":       [list(lr) for lr in self.likelihoods],
            "reasoning_summary": self.reasoning_summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskworkPayload":
        return cls(
            prior=float(d.get("prior", 0.5)),
            posterior=float(d.get("posterior", 0.5)),
            findings=list(d.get("findings", [])),
            likelihoods=[tuple(lr) for lr in d.get("likelihoods", [])],
            reasoning_summary=d.get("reasoning_summary", ""),
        )


# ── ProcessPayload — team process agreement ───────────────────────────────────

@dataclass
class ProcessPayload:
    """Process payload — carried on process_proposed/accepted/challenged turns.

    Establishes role assignments before SNP negotiation begins.
    SNP's NegotiationPayload (operation, proposal_id, posterior, reasoning chain)
    identifies what is being negotiated in the convergence round itself.
    """
    coordinator_id:   str
    participant_ids:  List[str] = field(default_factory=list)
    role_assignments: List[dict] = field(default_factory=list)  # [{agent_id, role, responsible_for}]
    challenge_reason: Optional[str] = None  # populated on process_challenged

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


__all__ = [
    # IEPayload v0.1 — pairwise grounding
    "IEUtteranceBlock",
    "IEGroundingBlock",
    "IEBeliefBlock",
    "IEPayload",
    # Companion payload types
    "TaskworkPayload",
    "ProcessPayload",
]

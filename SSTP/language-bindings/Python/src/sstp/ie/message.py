# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""IE payload schema — typed payload envelopes for the Interaction Engine subprotocol.

Every IE peer_turn carries an IEPayload alongside the L9 header.  The payload
carries the sender's grounding position and belief state so the receiver can:
  - run contingency_check() immediately on receipt
  - update BeliefState and write CommonGround records in real time
  - feed posterior and contingency_verified into LocalStateReplica entries

Hash chains (content_hash, prev_utterance_hash, signature) are NOT part of the IE
payload — the L9 message_id (UUIDv5), parent_ids, and state_sequence counter
already cover integrity, causality, and gap detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IEUtteranceBlock:
    """The sender's position in this turn."""
    content:             str               # assertion text
    concept_ids:         List[str]         # concepts this utterance addresses (scope URIs)
    addresses_evidence:  List[str]         # concept_ids from the prior turn being responded to;
                                           # input to contingency_check(); empty on first turn
    inferred_intent:     str               # short semantic label: "assess_symptoms" etc.
    turn_depth:          int = 0           # nesting level (0 = top-level, >0 = repair branch)


@dataclass
class IEGroundingBlock:
    """Grounding state for this exchange — partially filled by sender, completed by receiver."""
    responds_to:          Optional[str]   = None   # message_id of utterance being responded to
    contingency_verified: Optional[bool]  = None   # None = not yet; receiver writes True/False
    contingency_score:    Optional[float] = None   # overlap ratio [0..1]; computed by receiver
    repair_reason:        Optional[str]   = None   # grounding_failure | scope_mismatch |
                                                    # ungroundable_novelty; set on repair_required
    challenges:           List[str]       = field(default_factory=list)  # message_ids challenged
                                                    # by alignment_challenge turns


@dataclass
class IEBeliefBlock:
    """Sender's belief at time of utterance — feeds AgentBeliefStore and ReplicaEntry."""
    concept_id:     str                  # what this belief is about (URI)
    prior:          float                # belief at episode open; immutable per episode; GAR anchor
    posterior:      float                # current belief after all revisions this episode
    revision_cause: Optional[str] = None # grounded_argument | social_compliance |
                                         # semantic_memory | new_evidence | repair_resolution


@dataclass
class IETaskworkBlock:
    """Sender's full independent reasoning chain — emitted on prior_injection turns."""
    findings:          List[dict]         # [{finding_id, value, source}]
    likelihoods:       List[tuple]        # [(finding_id, likelihood_ratio)]
    reasoning_summary: str = ""


@dataclass
class IEProcessBlock:
    """Team process proposal or acknowledgement — emitted on process_proposed/accepted turns."""
    coordinator_id:   str
    participant_ids:  List[str] = field(default_factory=list)
    role_assignments: List[dict] = field(default_factory=list)  # [{agent_id, role, responsible_for}]
    challenge_reason: Optional[str] = None  # populated on process_challenged


@dataclass
class IEPayload:
    """Full IE payload carried alongside the L9 header on every peer_turn."""

    # Conversation identity
    conversation_id: str
    episode_id:      str
    run_id:          str

    # Sender's position
    utterance: IEUtteranceBlock

    # Grounding state — null fields filled in by receiver after contingency_check()
    grounding: IEGroundingBlock

    # Sender's belief at time of utterance
    belief: IEBeliefBlock

    # Optional: taskwork reasoning chain (present on prior_injection turns)
    taskwork: Optional[IETaskworkBlock] = None

    # Optional: team process proposal/acknowledgement (present on process_* turns)
    process: Optional[IEProcessBlock] = None

    def to_dict(self) -> dict:
        """Serialise to a plain dict for wire transmission."""
        d: dict = {
            "conversation_id": self.conversation_id,
            "episode_id":      self.episode_id,
            "run_id":          self.run_id,
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
        if self.taskwork is not None:
            d["taskwork"] = {
                "findings":          list(self.taskwork.findings),
                "likelihoods":       [list(lr) for lr in self.taskwork.likelihoods],
                "reasoning_summary": self.taskwork.reasoning_summary,
            }
        if self.process is not None:
            d["process"] = {
                "coordinator_id":   self.process.coordinator_id,
                "participant_ids":  list(self.process.participant_ids),
                "role_assignments": list(self.process.role_assignments),
                "challenge_reason": self.process.challenge_reason,
            }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IEPayload":
        """Deserialise from a plain dict."""
        u = d.get("utterance", {})
        g = d.get("grounding", {})
        b = d.get("belief", {})
        tw_raw = d.get("taskwork")
        pr_raw = d.get("process")

        taskwork = None
        if tw_raw:
            taskwork = IETaskworkBlock(
                findings=list(tw_raw.get("findings", [])),
                likelihoods=[tuple(lr) for lr in tw_raw.get("likelihoods", [])],
                reasoning_summary=tw_raw.get("reasoning_summary", ""),
            )
        process = None
        if pr_raw:
            process = IEProcessBlock(
                coordinator_id=pr_raw.get("coordinator_id", ""),
                participant_ids=list(pr_raw.get("participant_ids", [])),
                role_assignments=list(pr_raw.get("role_assignments", [])),
                challenge_reason=pr_raw.get("challenge_reason"),
            )

        return cls(
            conversation_id=d.get("conversation_id", ""),
            episode_id=d.get("episode_id", ""),
            run_id=d.get("run_id", ""),
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
            taskwork=taskwork,
            process=process,
        )


__all__ = [
    "IEUtteranceBlock",
    "IEGroundingBlock",
    "IEBeliefBlock",
    "IETaskworkBlock",
    "IEProcessBlock",
    "IEPayload",
]

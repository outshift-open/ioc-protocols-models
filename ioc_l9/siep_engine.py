"""
Semantic Interaction Exchange Protocol — grounding verifier and repair cycle handler.

Processes L9 messages on behalf of the *listener* agent.  On each incoming
exchange it:
  - Computes the contingency_score against the prior turn from that sender.
  - Emits kind=exchange (grounding_ok) when score ≥ θ_c.
  - Emits kind=contingency (repair_required) when score < θ_c.
  - Tracks open repair branches and closes them with kind=commit:converged
    once the sender re-anchors correctly.

Enforced spec invariants:
  T1  prior_declaration before first grounding exchange
  T2  belief.prior immutable after declaration
  G1  response.parents ⊇ { prior.id }
  G2  contingency_verified=True → belief_status ∈ {asserted, revised}
  R1  sender(contingency) = receiver(bad_turn)
  R2  sender(commit:converged) = sender(contingency)
  R3  repair depth ≤ D_MAX; exceeded → belief_status=unresolved
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ioc_l9 import SIEPBelief, SIEPGrounding, SIEPPayload, SIEPUtterance, Kind, L9Message, RepairReason, RevisionCause
from ioc_l9.epistemic import EpistemicState, SIEPEpistemic
from ioc_l9.siep_builder import SIEPMessageBuilder, contingency_score


THETA_C = 0.40   # grounding threshold (spec §IE Grounding Exchange — Normal)
D_MAX   = 3      # max repair attempts before declaring unresolved (spec invariant R3)


def _concept(msg: L9Message) -> Optional[str]:
    """Return concept_id from the epistemic block if it is an SIEPEpistemic."""
    ep = msg.epistemic
    return ep.concept_id if isinstance(ep, SIEPEpistemic) else None


@dataclass
class RepairBranch:
    """State for one open repair branch within an episode."""
    contingency_msg_id: str       # ID of the kind=contingency we emitted (R2: we close it)
    bad_turn_id: str              # ID of the bad exchange that triggered repair
    bad_turn_evidence: List[str]  # evidence that must be re-engaged
    depth: int = 0                # number of repair attempts made so far


class SIEPEngine:
    """
    IE engine for one agent (the *listener*) in an L9 episode.

    Instantiate once per episode, then call process() for each incoming message.
    The returned list contains any response messages this engine should emit.
    """

    def __init__(self, agent_id: str, episode_urn: str) -> None:
        self.agent_id = agent_id
        self.episode  = episode_urn
        # (sender_id, concept_id) → SIEPBelief  — immutable after prior declaration (T2)
        self._priors:        Dict[Tuple[str, str], SIEPBelief] = {}
        # sender_id → last exchange received from that sender
        self._last_exchange: Dict[str, L9Message] = {}
        # bad_turn_id → open RepairBranch
        self._repairs:       Dict[str, RepairBranch] = {}

    # ── public API ────────────────────────────────────────────────────────────

    def process(self, msg: L9Message) -> List[L9Message]:
        """Process one incoming message; return response messages, if any."""
        if msg.kind == Kind.intent:   return []
        if msg.kind == Kind.exchange: return self._on_exchange(msg)
        if msg.kind == Kind.commit:   return []
        return []

    # ── exchange ──────────────────────────────────────────────────────────────

    def _on_exchange(self, msg: L9Message) -> List[L9Message]:
        sender = msg.actor.id if msg.actor else "unknown"
        ie     = msg.siep_payload()

        # T1 / T2 — taskwork prior declaration; store belief, skip grounding check
        if msg.epistemic.state == EpistemicState.taskwork and ie:
            key = (sender, _concept(msg) or "")
            if key not in self._priors:
                self._priors[key] = SIEPBelief(
                    prior=ie.belief.prior,
                    posterior=ie.belief.posterior,
                    revision_cause=RevisionCause.semantic_memory,
                )
            self._last_exchange[sender] = msg
            return []

        # Is this a repair attempt? (parent points to one of our contingency messages)
        if msg.message.parents:
            for branch in self._repairs.values():
                if branch.contingency_msg_id in msg.message.parents:
                    return self._on_repair_attempt(msg, branch)

        # Normal grounding check
        if ie is None:
            self._last_exchange[sender] = msg
            return []

        prior    = self._last_exchange.get(sender)
        prior_ev = prior.siep_payload().utterance.evidence if (prior and prior.siep_payload()) else []
        score    = contingency_score(ie.utterance.evidence, prior_ev)
        self._last_exchange[sender] = msg

        return (
            [self._grounding_ok(msg, score)]
            if score >= THETA_C
            else [self._request_repair(msg, score, prior_ev)]
        )

    # ── grounding-ok response ─────────────────────────────────────────────────

    def _grounding_ok(self, prior: L9Message, score: float) -> L9Message:
        """Step 2 (normal path) — G2: belief_status ∈ {asserted, revised}."""
        concept = _concept(prior)
        my_b    = self._priors.get((self.agent_id, concept or ""))
        ev      = prior.siep_payload().utterance.evidence if prior.siep_payload() else []
        return (
            self._builder()
            .exchange().grounding().asserted()
            .concept(concept or "")
            .parents(prior.message.id)
            .payload(SIEPPayload(
                utterance=SIEPUtterance(evidence=ev, addresses_evidence=ev),
                grounding=SIEPGrounding(contingency_verified=True, contingency_score=round(score, 4)),
                belief=SIEPBelief(
                    prior=my_b.prior     if my_b else 0.5,
                    posterior=my_b.posterior if my_b else 0.5,
                    revision_cause=RevisionCause.grounded_argument,
                ),
            ))
            .build()
        )

    # ── repair request ────────────────────────────────────────────────────────

    def _request_repair(
        self, bad: L9Message, score: float, prior_ev: List[str],
    ) -> L9Message:
        """Step 2 (failure path) — R1: sender(contingency) = this engine."""
        reason = self._classify(
            bad.siep_payload().utterance.evidence if bad.siep_payload() else [], prior_ev
        )
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
                    challenges=prior_ev,
                ),
            ))
            .text(f"repair_required:reason={reason.value}:target={bad.message.id}")
            .build()
        )
        self._repairs[bad.message.id] = RepairBranch(
            contingency_msg_id=msg.message.id,
            bad_turn_id=bad.message.id,
            bad_turn_evidence=prior_ev,
        )
        return msg

    # ── repair verification ───────────────────────────────────────────────────

    def _on_repair_attempt(self, msg: L9Message, branch: RepairBranch) -> List[L9Message]:
        branch.depth += 1
        ie    = msg.siep_payload()
        score = contingency_score(ie.utterance.evidence if ie else [], branch.bad_turn_evidence)

        if score >= THETA_C:
            del self._repairs[branch.bad_turn_id]
            return [self._close_repair(msg, score)]

        if branch.depth >= D_MAX:
            del self._repairs[branch.bad_turn_id]
            return [self._exhaust_repair(msg, branch)]

        return [self._request_repair(msg, score, branch.bad_turn_evidence)]

    def _close_repair(self, repair: L9Message, score: float) -> L9Message:
        """Step 4 — R2: sender(commit:converged) = sender(contingency) = this engine."""
        sender_name = repair.actor.id if repair.actor else "?"
        return (
            self._builder()
            .commit_converged().grounding().revised()
            .concept(_concept(repair) or "")
            .parents(repair.message.id)
            .payload(SIEPPayload(
                grounding=SIEPGrounding(contingency_verified=True, contingency_score=round(score, 4)),
            ))
            .text(f"repair_verified:{sender_name} re-anchored")
            .build()
        )

    def _exhaust_repair(self, last: L9Message, branch: RepairBranch) -> L9Message:
        """R3: d_max exceeded → belief_status=unresolved."""
        return (
            self._builder()
            .commit_rejected().grounding().unresolved()
            .concept(_concept(last) or "")
            .parents(last.message.id)
            .text(f"repair_exhausted:depth={branch.depth}:target={branch.bad_turn_id}")
            .build()
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _builder(self) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(self.episode, self.agent_id)

    @staticmethod
    def _classify(evidence: List[str], prior_ev: List[str]) -> RepairReason:
        if not evidence:                            return RepairReason.ungroundable_novelty
        if not set(evidence) & set(prior_ev):       return RepairReason.scope_mismatch
        return RepairReason.grounding_failure

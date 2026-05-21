# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""
epistemic/tom.py — Deterministic Theory of Mind from a local replica.

ReplicaToM provides first-order ToM (what does agent B currently believe?)
deterministically from structured epistemic blocks — no LLM needed.

Methods:
  belief_model()              — current beliefs per agent, with task_phase tag
  alignment_matrix()          — pairwise agreement, optionally filtered by phase
  unresolved_challenges()     — open ALIGNMENT_CHALLENGEs
  epistemic_strength()        — overall genuine-assertion ratio (all phases)
  taskwork_independence_ratio() — genuine independent assessments / taskwork total
  social_compliance_ratio()   — forced accepts / interpersonal accepts
  social_influence_delta()    — per-agent: how much did peer pressure move beliefs?
  behavioural_trace_toward()  — structured evidence for second-order ToM inference
  phase_violations()          — entries whose task_phase mismatches expected phase
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sstp.epistemic.local_replica import LocalStateReplica, ReplicaEntry
from sstp.epistemic.stores import PeerInteractionStore


class ReplicaToM:
    """Deterministic first-order + behavioural second-order ToM from a replica."""

    def __init__(self, replica: LocalStateReplica, observer: str) -> None:
        self.replica = replica
        self.observer = observer

    def belief_model(self, agent_id: str) -> Dict[str, Any]:
        """What does agent_id currently assert, as seen by observer?

        Folds entries in order: later assertions on the same scope overwrite
        earlier ones. RETRACTED clears a scope. REVISED overwrites with the new
        belief (prior is gone, replacement is present). DEFERRED marks as deferred.
        UNRESOLVED is flagged.

        Each concept entry carries task_phase so callers can distinguish beliefs
        formed during independent taskwork from those formed under peer influence.
        """
        entries = [e for e in self.replica._entries if e.sender == agent_id]
        current: Dict[str, Any] = {}
        for entry in entries:
            ep = entry.epistemic or {}
            belief_status = ep.get("belief_status", "asserted")
            speech_act = ep.get("speech_act", "")
            uncertainty = ep.get("uncertainty", 0.0)
            task_phase = ep.get("task_phase", "")
            for concept in ep.get("scope", []):
                if belief_status == "retracted":
                    current.pop(concept, None)
                else:
                    current[concept] = {
                        "speech_act": speech_act,
                        "belief_status": "asserted" if belief_status == "revised" else belief_status,
                        "uncertainty": uncertainty,
                        "task_phase": task_phase,
                        "message_id": entry.message_id,
                        "sequence": entry.sequence,
                        "revised": belief_status == "revised",
                    }
        return current

    def alignment_matrix(
        self, task_phase: Optional[str] = None
    ) -> Dict[str, Dict[str, float]]:
        """Pairwise agreement scores across all participants.

        If task_phase is given, only concepts asserted in that phase are compared.
        This lets callers distinguish:
          alignment_matrix("taskwork")      — pre-social genuine divergence
          alignment_matrix("interpersonal") — post-negotiation agreement (may include compliance)
          alignment_matrix()                — all phases combined

        Score = fraction of shared scope concepts where both agents have
        non-deferred, non-unresolved assertions with the same speech_act.
        """
        participants = self.replica.get_derived_state()["participants"]

        if task_phase is not None:
            # Build phase-filtered belief models
            models: Dict[str, Dict[str, Any]] = {}
            for a in participants:
                full = self.belief_model(a)
                models[a] = {
                    concept: data for concept, data in full.items()
                    if data.get("task_phase") == task_phase
                }
        else:
            models = {a: self.belief_model(a) for a in participants}

        matrix: Dict[str, Dict[str, float]] = {}
        for a in participants:
            matrix[a] = {}
            for b in participants:
                if a == b:
                    continue
                shared = set(models[a]) & set(models[b])
                if not shared:
                    matrix[a][b] = 0.0
                    continue
                agreed = sum(
                    1 for s in shared
                    if models[a][s].get("speech_act") == models[b][s].get("speech_act")
                    and models[a][s].get("belief_status") not in ("deferred", "unresolved")
                    and models[b][s].get("belief_status") not in ("deferred", "unresolved")
                )
                matrix[a][b] = round(agreed / len(shared), 4)
        return matrix

    def unresolved_challenges(self) -> List[Dict[str, Any]]:
        """ALIGNMENT_CHALLENGEs not answered by retraction, re-assertion, or revision.

        A challenge is considered resolved if the challenged agent later emitted
        a BELIEF_ASSERTION, RETRACTED, or REVISED on the same scope.
        """
        challenges = [
            e for e in self.replica._entries
            if (e.epistemic or {}).get("speech_act") == "alignment_challenge"
        ]
        unresolved = []
        for ch in challenges:
            ch_ep = ch.epistemic or {}
            challenged_ids = set(ch_ep.get("challenges", []))
            challenged_entries = [
                e for e in self.replica._entries if e.message_id in challenged_ids
            ]
            for challenged in challenged_entries:
                sender = challenged.sender
                ch_scope = set((challenged.epistemic or {}).get("scope", []))
                later_entries = [
                    e for e in self.replica._entries
                    if e.sender == sender
                    and e.timestamp_ms > challenged.timestamp_ms
                    and set((e.epistemic or {}).get("scope", [])) & ch_scope
                    and (e.epistemic or {}).get("belief_status") in ("asserted", "retracted", "revised")
                ]
                if not later_entries:
                    unresolved.append({
                        "challenger": ch.sender,
                        "challenged_agent": sender,
                        "challenged_message_id": challenged.message_id,
                        "challenge_message_id": ch.message_id,
                        "scope": list(ch_scope),
                    })
        return unresolved

    def epistemic_strength(self) -> float:
        """Overall fraction of accepts that were genuine BELIEF_ASSERTIONs (all phases)."""
        return self.replica.get_derived_state().get("epistemic_strength", 0.0)

    def taskwork_independence_ratio(self) -> float:
        """Fraction of taskwork-phase entries that were genuine BELIEF_ASSERTIONs.

        High = agents formed independent views before peer interaction.
        Low = agents deferred even during their individual assessment phase.
        """
        return self.replica.get_derived_state().get("taskwork_independence_ratio", 1.0)

    def social_compliance_ratio(self) -> float:
        """Fraction of interpersonal-phase accepts that were DELIBERATION_PASS (forced).

        High = social compliance dominated the panel — consensus was achieved by
        pressure rather than genuine agreement.
        Low = panel reached genuine consensus.
        """
        return self.replica.get_derived_state().get("social_compliance_ratio", 0.0)

    def social_influence_delta(self) -> Dict[str, Dict[str, Any]]:
        """Per-agent: how much did peer pressure move beliefs after taskwork phase?

        For each agent, compares the position held during taskwork with the final
        position held after action/interpersonal phases. A moved concept indicates
        the agent updated their belief under peer influence.

        Returns dict keyed by agent_id:
          taskwork_concepts  — scope concepts asserted during taskwork
          moved_concepts     — concepts where final position differs from taskwork
          influence_ratio    — moved / shared (0.0 = no influence, 1.0 = fully moved)
        """
        participants = self.replica.get_derived_state()["participants"]
        result: Dict[str, Dict[str, Any]] = {}
        for agent in participants:
            entries = [e for e in self.replica._entries if e.sender == agent]
            taskwork_beliefs: Dict[str, str] = {}
            final_beliefs: Dict[str, str] = {}
            for e in entries:
                ep = e.epistemic or {}
                phase = ep.get("task_phase", "")
                sa = ep.get("speech_act", "")
                bs = ep.get("belief_status", "")
                for concept in ep.get("scope", []):
                    if phase == "taskwork" and bs in ("asserted",):
                        taskwork_beliefs[concept] = sa
                    if phase in ("action", "interpersonal") and bs in ("asserted", "revised"):
                        final_beliefs[concept] = sa
            shared = set(taskwork_beliefs) & set(final_beliefs)
            moved = [c for c in shared if taskwork_beliefs[c] != final_beliefs[c]]
            result[agent] = {
                "taskwork_concepts": sorted(taskwork_beliefs),
                "moved_concepts": moved,
                "influence_ratio": round(len(moved) / len(shared), 4) if shared else 0.0,
            }
        return result

    def behavioural_trace_toward(self, observer_id: str, subject_id: str) -> Dict[str, Any]:
        """What does observer_id's behaviour toward subject_id suggest about observer's model of subject?

        Returns structured evidence for second-order ToM inference.
        This is input to TheoryOfMindEngineBase.analyze_inter_agent_tom(), not a
        final answer — the LLM layer interprets this evidence.
        """
        interactions = [
            e for e in self.replica._entries
            if e.sender == observer_id
        ]
        challenges_to_subject = [
            e for e in interactions
            if (e.epistemic or {}).get("speech_act") == "alignment_challenge"
        ]
        accepts_from_subject_proposals = [
            e for e in interactions
            if (e.epistemic or {}).get("speech_act") in ("belief_assertion", "deliberation_pass")
            and e.operation in ("accept",)
        ]
        passes_to_subject = [
            e for e in interactions
            if (e.epistemic or {}).get("speech_act") == "deliberation_pass"
            and (e.epistemic or {}).get("deferred_to") == subject_id
        ]

        subject_model = self.belief_model(subject_id)
        observer_model = self.belief_model(observer_id)

        shared_scope = set(subject_model) & set(observer_model)
        disagreements = [
            s for s in shared_scope
            if subject_model[s].get("speech_act") != observer_model[s].get("speech_act")
        ]

        return {
            "observer": observer_id,
            "subject": subject_id,
            "challenges_issued": len(challenges_to_subject),
            "accepts_of_subject_proposals": len(accepts_from_subject_proposals),
            "deliberation_passes_to_subject": len(passes_to_subject),
            "shared_scope_concepts": sorted(shared_scope),
            "disagreement_concepts": disagreements,
            "inferred_trust": round(
                len(accepts_from_subject_proposals) /
                max(1, len(challenges_to_subject) + len(accepts_from_subject_proposals)),
                4,
            ),
        }

    def phase_violations(self, expected_phase: str) -> List[Dict[str, Any]]:
        """Find entries whose task_phase does not match the expected panel phase."""
        violations = []
        for e in self.replica._entries:
            ep = e.epistemic or {}
            actual_phase = ep.get("task_phase", "")
            if actual_phase and actual_phase != expected_phase:
                violations.append({
                    "message_id": e.message_id,
                    "sender": e.sender,
                    "expected_phase": expected_phase,
                    "actual_phase": actual_phase,
                    "speech_act": ep.get("speech_act"),
                })
        return violations


def predict_belief(
    peer_store: PeerInteractionStore,
    observer_id: str,
    subject_id: str,
    use_case: str,
    concept_id: str,
    new_evidence: List[str],
    prior_confidence: float = 0.5,
) -> Dict[str, Any]:
    """2nd-order ToM: predict what subject_id will conclude about concept_id
    when presented with new_evidence, using observer_id's cross-episode peer model.

    Uses Naive Bayes over evidence_weights when available, falls back to
    historical move rates, returns prior when no history exists.

    Returns:
        predicted_confidence  — posterior the subject is expected to hold
        basis                 — "evidence_weights" | "argument_history" | "prior_only"
        reliability           — discount: episode_count/5 × predictive_accuracy
        argument_types_that_move — argument types historically effective on subject
        evidence_overlap      — # new_evidence items matched in evidence_weights
    """
    record = peer_store.get_peer_record(observer_id, subject_id, use_case)

    if record is None or record.episode_count == 0:
        return {
            "predicted_confidence": round(prior_confidence, 4),
            "basis": "prior_only",
            "reliability": 0.0,
            "argument_types_that_move": [],
            "evidence_overlap": 0,
        }

    # Count evidence items that have known weights in subject's model
    evidence_overlap = sum(1 for ev in new_evidence if ev in record.evidence_weights)

    p = prior_confidence
    if evidence_overlap > 0:
        # Naive Bayes: P(H | e1..en) ∝ P(H) × ∏ evidence_weights[ei]
        basis = "evidence_weights"
        for ev in new_evidence:
            p *= record.evidence_weights.get(ev, 1.0)
        p = max(0.05, min(0.95, p))
    else:
        # Fall back to historical move rate for this concept
        concept_outcomes = [
            o for o in record.argument_outcomes
            if o.argument_concept_id == concept_id
        ]
        if concept_outcomes:
            basis = "argument_history"
            move_rate = sum(
                1 for o in concept_outcomes if o.moved and o.contingent
            ) / len(concept_outcomes)
            # Shift prior by (move_rate - 0.5) × 0.4 to stay within [0.3, 0.7]
            p = max(0.05, min(0.95, prior_confidence + (move_rate - 0.5) * 0.4))
        else:
            basis = "prior_only"

    reliability = round(
        min(1.0, record.episode_count / 5.0) * record.predictive_accuracy,
        4,
    )

    return {
        "predicted_confidence": round(p, 4),
        "basis": basis,
        "reliability": reliability,
        "argument_types_that_move": record.argument_types_that_move[:],
        "evidence_overlap": evidence_overlap,
    }


__all__ = ["ReplicaToM", "predict_belief"]

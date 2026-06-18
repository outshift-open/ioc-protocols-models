# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""
epistemic/tom.py — Deterministic Theory of Mind from a local replica.

ReplicaToM provides first-order ToM (what does agent B currently believe?)
deterministically from structured epistemic blocks — no LLM needed.

Methods:
  belief_model()              — current beliefs per agent, with epistemic_state tag
  alignment_matrix()          — pairwise agreement, optionally filtered by phase
  unresolved_challenges()     — open ALIGNMENT_CHALLENGEs
  epistemic_strength()        — overall genuine-assertion ratio (all phases)
  taskwork_independence_ratio() — genuine independent assessments / taskwork total
  social_compliance_ratio()   — forced accepts / interpersonal accepts
  social_influence_delta()    — per-agent: how much did peer pressure move beliefs?
  behavioural_trace_toward()  — structured evidence for second-order ToM inference
  phase_violations()          — entries whose epistemic_state mismatches expected phase
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from SSTP.subprotocol.siep.src.epistemic.local_replica import LocalStateReplica, ReplicaEntry


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

        Each concept entry carries epistemic_state so callers can distinguish beliefs
        formed during independent taskwork from those formed under peer influence.
        """
        entries = [e for e in self.replica._entries if e.sender == agent_id]
        current: Dict[str, Any] = {}
        for entry in entries:
            ep = entry.epistemic or {}
            belief_status = ep.get("belief_status", "asserted")
            speech_act = ep.get("speech_act", "")
            uncertainty = ep.get("uncertainty", 0.0)
            epistemic_state = ep.get("state", "")
            entry_data = {
                "speech_act": speech_act,
                "belief_status": "asserted" if belief_status == "revised" else belief_status,
                "uncertainty": uncertainty,
                "epistemic_state": epistemic_state,
                "posterior": entry.posterior,
                "contingency_verified": entry.contingency_verified,
                "message_id": entry.message_id,
                "sequence": entry.sequence,
                "revised": belief_status == "revised",
            }
            # Primary concept: concept_id field takes precedence over scope[0]
            primary = ep.get("concept_id") or (ep.get("scope") or [None])[0]
            if primary:
                if belief_status == "retracted":
                    current.pop(primary, None)
                else:
                    current[primary] = entry_data
            # Additional scope concepts (supporting evidence) — backwards compat
            for concept in ep.get("scope", []):
                if concept == primary:
                    continue  # already written above
                if belief_status == "retracted":
                    current.pop(concept, None)
                else:
                    current[concept] = entry_data
        return current

    # Maximum posterior difference still counted as agreement
    ALIGNMENT_TOLERANCE: float = 0.15

    def alignment_matrix(
        self, epistemic_state: Optional[str] = None
    ) -> Dict[str, Dict[str, float]]:
        """Pairwise agreement scores across all participants.

        If epistemic_state is given, only concepts asserted in that state are compared.
        This lets callers distinguish:
          alignment_matrix("taskwork")      — pre-social genuine divergence
          alignment_matrix("grounding")     — IE-verified exchange agreement
          alignment_matrix("team_process")  — post-negotiation agreement (may include compliance)
          alignment_matrix()                — all phases combined

        When both agents carry a ``posterior`` value for a concept, agreement is
        measured as posterior proximity (within ALIGNMENT_TOLERANCE).  When
        posterior is absent, the fallback is speech_act equality (backwards compat).
        """
        participants = self.replica.get_derived_state()["participants"]

        if epistemic_state is not None:
            models: Dict[str, Dict[str, Any]] = {}
            for a in participants:
                full = self.belief_model(a)
                models[a] = {
                    concept: data for concept, data in full.items()
                    if data.get("epistemic_state") == epistemic_state
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
                agreed = 0
                for s in shared:
                    da = models[a][s]
                    db = models[b][s]
                    if da.get("belief_status") in ("deferred", "unresolved"):
                        continue
                    if db.get("belief_status") in ("deferred", "unresolved"):
                        continue
                    pa = da.get("posterior")
                    pb = db.get("posterior")
                    if pa is not None and pb is not None:
                        if abs(pa - pb) <= self.ALIGNMENT_TOLERANCE:
                            agreed += 1
                    else:
                        # Fallback: speech_act equality
                        if da.get("speech_act") == db.get("speech_act"):
                            agreed += 1
                matrix[a][b] = round(agreed / len(shared), 4)
        return matrix

    def unresolved_challenges(self) -> List[Dict[str, Any]]:
        """ALIGNMENT_CHALLENGEs not answered by retraction, re-assertion, or revision.

        A challenge is considered resolved if the challenged agent later emitted
        a BELIEF_ASSERTION, RETRACTED, or REVISED on the same scope.
        """
        challenges = [
            e for e in self.replica._entries
            if (e.epistemic or {}).get("speech_act") in ("challenge", "alignment_challenge")
        ]
        unresolved = []
        for ch in challenges:
            ch_ep = ch.epistemic or {}
            # challenges field now lives in IEPayload.grounding — fall back to epistemic for compat
            challenged_ids = set(ch_ep.get("challenges", []))
            challenged_entries = [
                e for e in self.replica._entries if e.message_id in challenged_ids
            ]
            for challenged in challenged_entries:
                sender = challenged.sender
                # Use ie_concept_ids (from payload) as primary; fall back to scope/concept_id
                ch_scope = (
                    set(challenged.ie_concept_ids)
                    or ({(challenged.epistemic or {}).get("concept_id")} - {None})
                    or set((challenged.epistemic or {}).get("scope", []))
                )
                later_entries = [
                    e for e in self.replica._entries
                    if e.sender == sender
                    and e.timestamp_ms > challenged.timestamp_ms
                    and (
                        (set(e.ie_concept_ids) & ch_scope)
                        or ({(e.epistemic or {}).get("concept_id")} - {None}) & ch_scope
                        or set((e.epistemic or {}).get("scope", [])) & ch_scope
                    )
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
        # Minimum posterior shift to count as "moved" (filters noise)
        NOISE_THRESHOLD = 0.05

        participants = self.replica.get_derived_state()["participants"]
        result: Dict[str, Dict[str, Any]] = {}
        for agent in participants:
            entries = [e for e in self.replica._entries if e.sender == agent]
            # Store {concept: posterior_or_speech_act} for comparison
            taskwork_beliefs: Dict[str, Any] = {}
            final_beliefs: Dict[str, Any] = {}
            for e in entries:
                ep = e.epistemic or {}
                phase = ep.get("state", "")
                sa = ep.get("speech_act", "")
                bs = ep.get("belief_status", "")
                # Use concept_id as primary; fall back to scope iteration
                primary = ep.get("concept_id") or (ep.get("scope") or [None])[0]
                concepts = ([primary] if primary else []) + [
                    c for c in ep.get("scope", []) if c != primary
                ]
                for concept in concepts:
                    if not concept:
                        continue
                    if phase == "taskwork" and bs in ("asserted",):
                        taskwork_beliefs[concept] = {
                            "posterior": e.posterior,
                            "speech_act": sa,
                        }
                    if phase in ("grounding", "team_process") and bs in ("asserted", "revised"):
                        final_beliefs[concept] = {
                            "posterior": e.posterior,
                            "speech_act": sa,
                        }
            shared = set(taskwork_beliefs) & set(final_beliefs)
            moved = []
            for c in shared:
                tw = taskwork_beliefs[c]
                fi = final_beliefs[c]
                tw_p = tw.get("posterior")
                fi_p = fi.get("posterior")
                if tw_p is not None and fi_p is not None:
                    if abs(fi_p - tw_p) > NOISE_THRESHOLD:
                        moved.append(c)
                else:
                    # Fallback: speech_act change
                    if tw.get("speech_act") != fi.get("speech_act"):
                        moved.append(c)
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
            if (e.epistemic or {}).get("speech_act") in ("challenge", "alignment_challenge")
        ]
        accepts_from_subject_proposals = [
            e for e in interactions
            if (e.epistemic or {}).get("speech_act") in ("assertion", "compliance", "belief_assertion", "deliberation_pass")
            and e.operation in ("accept",)
        ]
        passes_to_subject = [
            e for e in interactions
            if (e.epistemic or {}).get("speech_act") in ("compliance", "deliberation_pass")
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
        """Find entries whose epistemic_state does not match the expected panel phase."""
        violations = []
        for e in self.replica._entries:
            ep = e.epistemic or {}
            actual_phase = ep.get("state", "")
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
    agent_tom: Any,
    *,
    subject_id: str = "",
    concept_id: str = "",
    new_evidence: Optional[List[str]] = None,
    prior_confidence: float = 0.5,
    peer_interaction_store: Optional[Any] = None,
) -> Dict[str, Any]:
    """2nd-order ToM: predict what subject_id will conclude about concept_id
    when presented with new_evidence.

    Reads the observer's persisted peer belief model from
    ``agent_tom._epistemic_store`` and uses the semantic belief confidence and
    prediction log as the prediction basis.

    Returns:
        predicted_confidence  — posterior the subject is expected to hold
        basis                 — "peer_model" | "prior_only"
        reliability           — discount: episode_count/5 × predictive_accuracy
        argument_types_that_move — always [] (future extension point)
        evidence_overlap      — # new_evidence items matched in inferred_constraints
    """
    new_evidence = new_evidence or []

    peer_model = agent_tom._epistemic_store.load_peer_model(subject_id)
    prediction_log = agent_tom._epistemic_store.load_prediction_log(subject_id)

    if peer_model is None:
        return {
            "predicted_confidence": round(prior_confidence, 4),
            "basis": "prior_only",
            "reliability": 0.0,
            "argument_types_that_move": [],
            "evidence_overlap": 0,
        }

    peer_confidence = float(peer_model.get("confidence", prior_confidence))
    inferred_constraints = peer_model.get("inferred_constraints", [])
    evidence_overlap = sum(
        1 for ev in new_evidence
        if any(ev.lower() in c.lower() for c in inferred_constraints)
    )

    _type_weights = {
        "grounded_evidence": 0.12,
        "role_authority":    0.07,
        "social_pressure":   0.02,
        "procedural":        0.01,
    }
    _types_that_move = peer_model.get("argument_types_that_move", [])
    _type_weight = max(
        (_type_weights.get(t, 0.06) for t in _types_that_move),
        default=0.06,
    )
    p = peer_confidence
    if evidence_overlap > 0:
        p = min(0.95, peer_confidence + _type_weight * evidence_overlap)

    # Fix 13b: cross-episode evidence_weights from PeerInteractionStore
    if peer_interaction_store is not None:
        _rec = peer_interaction_store.get_peer_record(
            getattr(agent_tom, "agent_id", ""), subject_id
        )
        if _rec is not None and _rec.evidence_weights:
            _weighted = sum(
                _rec.evidence_weights.get(ev, _type_weight)
                for ev in new_evidence
                if any(ev.lower() in c.lower() for c in inferred_constraints)
            )
            if _weighted > 0:
                p = min(0.95, peer_confidence + _weighted)

    episode_count = len(prediction_log)
    predictive_accuracy = 0.5
    if prediction_log:
        errors = [float(e.get("prediction_error", 0.5)) for e in prediction_log]
        predictive_accuracy = max(0.0, 1.0 - sum(errors) / len(errors))
    if peer_interaction_store is not None:
        _rec2 = peer_interaction_store.get_peer_record(
            getattr(agent_tom, "agent_id", ""), subject_id
        )
        if _rec2 is not None and _rec2.predictive_accuracy != 0.5:
            predictive_accuracy = _rec2.predictive_accuracy
            episode_count = max(episode_count, _rec2.episode_count)
    reliability = round(min(1.0, episode_count / 5.0) * predictive_accuracy, 4)

    return {
        "predicted_confidence": round(max(0.05, min(0.95, p)), 4),
        "basis": "peer_model",
        "reliability": reliability,
        "argument_types_that_move": list(peer_model.get("argument_types_that_move", [])),
        "evidence_overlap": evidence_overlap,
    }


__all__ = ["ReplicaToM", "predict_belief"]

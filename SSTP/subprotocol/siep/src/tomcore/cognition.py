# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""cognition.py — Per-agent Theory-of-Mind state with cross-episode peer modelling.

AgentTOM keeps only the prediction loop (2nd-order ToM) and drift signals.
LLM-based introspection (seed/update/assess_utterance/detect_ambiguity/peer_alignment)
has been removed — those functions are now handled structurally:
  - grounding checks: contingency_check() in SSTP.subprotocol.siep.src.grounding
  - belief tracking: AgentBeliefStore.record_revision() via receive_peer_turn()
  - drift: anchor_gap from TaskworkState.prior vs BeliefState.current_confidence
  - alignment: ReplicaToM.alignment_matrix() from epistemic replica
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from SSTP.subprotocol.siep.src.tomcore.llm import LLMClient
from SSTP.subprotocol.siep.src.tom import TheoryOfMindEngineBase
from SSTP.subprotocol.siep.src.epistemic.stores import AgentEpistemicStore

LOGGER = logging.getLogger("ioc")

_EMA_ALPHA = 0.3
_HISTORY_LIMIT = 10
_CHANGE_LOG_LIMIT = 10
_PEER_MODEL_REVISION_THRESHOLD = 0.35
_PEER_ERROR_WINDOW = 5


class AgentTOM:
    """Per-agent Theory-of-Mind state — prediction loop and drift signals only.

    Keeps:
      - Cross-episode peer belief model (_peer_beliefs, persisted in AgentEpistemicStore)
      - 2nd-order ToM prediction loop (predict_peer_response → update_peer → _revise_peer_model)
      - Peer-EMA tracking (_peer_ema) for drift_signals()

    Removed (replaced by structural equivalents):
      - seed() / update() — use AgentBeliefStore + TaskworkStore
      - assess_utterance() — use contingency_check() in SSTP.subprotocol.siep.src.grounding
      - assess_task_alignment() — use epistemic_state field in L9 header
      - detect_ambiguity() — use diagnose_repair_reason() in grounding.py
      - peer_alignment() — use ReplicaToM.alignment_matrix()
      - analyze_pairwise_agent_tom() — use ReplicaToM.alignment_matrix()
    """

    def __init__(
        self,
        agent_id: str,
        llm: LLMClient,
        epistemic_store: Optional[AgentEpistemicStore] = None,
    ) -> None:
        self.agent_id = agent_id
        self._llm = llm
        self._peer_beliefs: Dict[str, Dict[str, Any]] = {}
        self._peer_ema: Dict[str, float] = {}
        self._pending_predictions: Dict[str, Dict[str, Any]] = {}
        self._peer_prediction_log: Dict[str, List[Dict]] = {}
        self._epistemic_store: AgentEpistemicStore = (
            epistemic_store if epistemic_store is not None else AgentEpistemicStore(agent_id)
        )

    # ── Deprecated no-op stubs (kept for import compatibility) ────────────────

    def seed(self, role_description: str, session_context: Dict[str, Any]) -> Dict[str, Any]:
        """Deprecated. Use AgentBeliefStore + TaskworkStore instead."""
        return {"role": role_description, "objective": role_description,
                "context_summary": "", "inferred_constraints": [], "confidence": 0.5}

    def seed_peer(
        self,
        peer_id: str,
        role_description: str,
        session_context: Dict[str, Any],
    ) -> None:
        """Seed initial peer belief model.

        Uses a persisted model from the epistemic store as prior if available;
        otherwise seeds from role description via LLM.
        """
        persisted = self._epistemic_store.load_peer_model(peer_id)
        if persisted:
            self._peer_beliefs[peer_id] = persisted
            self._peer_ema.setdefault(peer_id, 1.0)
            LOGGER.debug(
                "tom.seed_peer agent=%s peer=%s source=persisted", self.agent_id, peer_id
            )
            return
        task_goal = session_context.get("task_goal", "")
        result = self._llm.complete_json("tom_belief_seed", {
            "agent_id": peer_id,
            "role_description": role_description,
            "task_goal": task_goal,
            "session_context": session_context,
        })
        peer_belief: Dict[str, Any] = {
            "role": result.get("role") or role_description,
            "objective": result.get("objective") or role_description,
            "context_summary": result.get("context_summary") or "",
            "inferred_constraints": (
                result.get("inferred_constraints")
                if isinstance(result.get("inferred_constraints"), list)
                else []
            ),
            "confidence": round(max(0.0, min(1.0, float(result.get("confidence", 0.5)))), 4),
        }
        self._peer_beliefs[peer_id] = peer_belief
        self._peer_ema[peer_id] = 1.0
        LOGGER.debug(
            "tom.seed_peer agent=%s peer=%s objective=%r",
            self.agent_id, peer_id, peer_belief["objective"][:60],
        )

    # ── Accessors ──────────────────────────────────────────────────────────────

    def belief(self) -> Dict[str, Any]:
        """Deprecated stub — own belief is now in AgentBeliefStore."""
        return {}

    def peer_belief(self, peer_id: str) -> Dict[str, Any]:
        """Return this agent's prediction-loop model of peer_id."""
        return dict(self._peer_beliefs.get(peer_id, {}))

    # ── Deprecated stubs ───────────────────────────────────────────────────────

    def update(self, utterance: str = "", task_goal: str = "", *args, **kwargs) -> Dict[str, Any]:
        """Deprecated. BeliefState is updated via AgentBeliefStore.record_revision()."""
        return {}

    def assess_utterance(self, utterance: str = "", task_goal: str = "", speaker: str = "",
                         listener: Optional[str] = None, history: Optional[List[str]] = None,
                         listener_prior_utterance: Optional[str] = None,
                         confidence_before: Optional[float] = None,
                         speaker_epistemic: Optional[Dict[str, Any]] = None,
                         listener_prior_epistemic: Optional[Dict[str, Any]] = None,
                         ) -> Dict[str, Any]:
        """Grounding check: structural when epistemic blocks available, LLM fallback otherwise."""
        from SSTP.subprotocol.siep.src.grounding import contingency_check, diagnose_repair_reason
        has_concepts = (
            bool((speaker_epistemic or {}).get("scope") or
                 (speaker_epistemic or {}).get("addresses_evidence"))
            or bool((listener_prior_epistemic or {}).get("scope"))
        )
        if has_concepts:
            verified, score = contingency_check(listener_prior_epistemic, speaker_epistemic)
            repair = diagnose_repair_reason(listener_prior_epistemic, speaker_epistemic)
            return {
                "aligned": verified,
                "alignment_score": score,
                "disagreement_score": round(1.0 - score, 4),
                "derailed": not verified,
                "derailment_cause": repair.value if repair is not None else None,
                "grounding_failure": not verified,
                "contingency_score": score,
                "ambiguous": False,
                "ambiguity_score": 0.0,
                "judge_confidence": 1.0,
                "critique": "structural_grounding_check",
            }
        # Fallback: LLM judge when no structured epistemic context is available
        payload: Dict[str, Any] = {
            "utterance": utterance,
            "task_goal": task_goal,
            "speaker": speaker,
            "listener": listener or self.agent_id,
            "speaker_belief": self._peer_beliefs.get(speaker, {}),
            "history": (history or [])[-4:],
        }
        if listener_prior_utterance is not None:
            payload["listener_prior_utterance"] = listener_prior_utterance
        if confidence_before is not None:
            payload["confidence_before"] = confidence_before
        result = self._llm.complete_json("ie_utterance_judge", payload)
        derailed = bool(result.get("derailed", False))
        ambiguous = bool(result.get("ambiguous", False))
        alignment_score = max(0.0, min(1.0, float(
            result.get("alignment_score", 0.25 if derailed else 0.82))))
        aligned = bool(result.get("aligned", not derailed and alignment_score >= 0.55))
        grounding_failure = bool(result.get("grounding_failure", False))
        contingency_score = max(0.0, min(1.0, float(
            result.get("contingency_score", 0.1 if grounding_failure else 1.0))))
        verdict: Dict[str, Any] = {
            "derailed": derailed,
            "derailment_cause": result.get("derailment_cause") or None,
            "grounding_failure": grounding_failure,
            "contingency_score": round(contingency_score, 4),
            "ambiguous": ambiguous,
            "ambiguity_score": round(max(0.0, min(1.0, float(
                result.get("ambiguity_score", 0.0)))), 4),
            "alignment_score": round(alignment_score, 4),
            "aligned": aligned,
            "judge_confidence": round(max(0.0, min(1.0, float(
                result.get("judge_confidence", 0.85)))), 4),
            "critique": str(result.get("critique", "")),
            "disagreement_score": round(max(0.0, min(1.0, 1.0 - alignment_score)), 4),
        }
        if "posterior_confidence" in result:
            verdict["posterior_confidence"] = round(max(0.0, min(1.0, float(
                result["posterior_confidence"]))), 4)
        return verdict

    def assess_task_alignment(self, task_goal: str = "", utterance: str = "") -> Dict[str, Any]:
        """Deprecated. epistemic_state in L9 header carries phase classification."""
        return {"actor": self.agent_id, "task_goal": task_goal,
                "aligned": True, "alignment_score": 0.5, "rationale": "structural"}

    def detect_ambiguity(self, utterance: str = "", task_goal: str = "") -> Dict[str, Any]:
        """Deprecated. diagnose_repair_reason() in grounding.py covers this."""
        return {"ambiguous": False, "ambiguity_score": 0.0,
                "ambiguous_spans": [], "plausible_interpretations": []}

    def peer_alignment(self, peer_id: str = "", task_goal: str = "",
                       peer_belief_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Deprecated. Use ReplicaToM.alignment_matrix() instead."""
        return {"task_goal": task_goal, "alignment_score": 0.5,
                "disagreement_score": 0.5, "attribution_accuracy": 0.5,
                "coherence_rationale": "structural", "role_objectives": {}}

    # ── Peer belief update ─────────────────────────────────────────────────────

    def update_peer(
        self,
        peer_id: str,
        utterance: str,
        task_goal: str,
        argument_direction: str = "neutral",
        alignment_score: float = 0.65,
        speaker_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update belief model of peer_id from peer's observed utterance.

        If a prediction was pending for this peer, computes prediction_error and
        appends to the prediction log.  Triggers peer model revision when the
        rolling mean error over the last _PEER_ERROR_WINDOW entries exceeds
        _PEER_MODEL_REVISION_THRESHOLD.
        """
        current_peer = self._peer_beliefs.get(peer_id) or {
            "role": peer_id,
            "objective": task_goal,
            "context_summary": "",
            "inferred_constraints": [],
            "confidence": 0.5,
        }
        result = self._llm.complete_json("tom_belief_update", {
            "agent_id": peer_id,
            "agent_role": current_peer.get("role", peer_id),
            "current_belief": current_peer,
            "utterance": utterance,
            "task_goal": task_goal,
            "argument_direction": argument_direction,
            "alignment_score": alignment_score,
            "speaker_role": speaker_role or "peer",
        })
        updated_peer = dict(current_peer)
        if isinstance(result.get("objective"), str) and result["objective"]:
            updated_peer["objective"] = result["objective"]
        if isinstance(result.get("context_summary"), str):
            updated_peer["context_summary"] = result["context_summary"]
        if isinstance(result.get("inferred_constraints"), list):
            updated_peer["inferred_constraints"] = result["inferred_constraints"]
        if isinstance(result.get("confidence"), (int, float)):
            updated_peer["confidence"] = round(
                max(0.0, min(1.0, float(result["confidence"]))), 4
            )
        updated_peer["delta_confidence"] = float(result.get("delta_confidence", 0.0))
        updated_peer["argument_type"] = str(result.get("argument_type", "neutral"))

        # Fix 12c: accumulate argument type history for 2nd-order ToM
        _arg_type = updated_peer["argument_type"]
        _delta = updated_peer["delta_confidence"]
        if _arg_type not in ("neutral", "procedural") and abs(_delta) > 0.03:
            _key = "argument_types_that_move" if _delta > 0 else "argument_types_ignored"
            _existing = list(dict.fromkeys(updated_peer.get(_key, []) + [_arg_type]))[-5:]
            updated_peer[_key] = _existing

        self._peer_beliefs[peer_id] = updated_peer

        # Alignment score used for both prediction error and peer EMA
        alignment_score = float(
            self.assess_task_alignment(task_goal, utterance).get("alignment_score", 0.5)
        )
        self._peer_ema[peer_id] = round(
            _EMA_ALPHA * alignment_score + (1 - _EMA_ALPHA) * self._peer_ema.get(peer_id, 1.0),
            4,
        )

        # C3: store the peer model's post-update confidence (not alignment score)
        # so that PredictionRecord.actual_confidence carries a belief-level value.
        actual_peer_confidence = updated_peer.get("confidence", alignment_score)

        pending = self._pending_predictions.pop(peer_id, None)
        if pending is not None:
            predicted_alignment = float(pending.get("predicted_alignment", 0.5))
            prediction_error = round(abs(predicted_alignment - alignment_score), 4)
            log_entry: Dict[str, Any] = {
                "utterance": utterance,
                "predicted_alignment": predicted_alignment,
                "observed_alignment": alignment_score,
                "actual_peer_confidence": actual_peer_confidence,
                "concept_id": task_goal,
                "prediction_error": prediction_error,
                "timestamp_ms": int(time.time() * 1000),
            }
            log = self._peer_prediction_log.setdefault(peer_id, [])
            log.append(log_entry)
            self._epistemic_store.save_peer_model(peer_id, updated_peer, log_entry)

            recent = log[-_PEER_ERROR_WINDOW:]
            mean_error = sum(e["prediction_error"] for e in recent) / len(recent)
            if mean_error > _PEER_MODEL_REVISION_THRESHOLD:
                self._revise_peer_model(peer_id, task_goal)
        else:
            self._epistemic_store.save_peer_model(peer_id, updated_peer)

        return updated_peer

    def _revise_peer_model(self, peer_id: str, task_goal: str) -> None:
        """Reconstruct peer belief model when prediction error accumulates."""
        current_peer = self._peer_beliefs.get(peer_id, {})
        recent_log = self._peer_prediction_log.get(peer_id, [])[-_PEER_ERROR_WINDOW:]
        result = self._llm.complete_json("tom_peer_model_revise", {
            "observer": self.agent_id,
            "subject": peer_id,
            "current_peer_belief": current_peer,
            "prediction_log": recent_log,
            "task_goal": task_goal,
        })
        revised = dict(current_peer)
        if isinstance(result.get("objective"), str) and result["objective"]:
            revised["objective"] = result["objective"]
        if isinstance(result.get("context_summary"), str):
            revised["context_summary"] = result["context_summary"]
        if isinstance(result.get("inferred_constraints"), list):
            revised["inferred_constraints"] = result["inferred_constraints"]
        if isinstance(result.get("confidence"), (int, float)):
            revised["confidence"] = round(max(0.0, min(1.0, float(result["confidence"]))), 4)
        self._peer_beliefs[peer_id] = revised
        self._peer_prediction_log[peer_id] = []  # reset accumulator after revision
        self._epistemic_store.save_peer_model(peer_id, revised)
        LOGGER.info(
            "tom.revise_peer agent=%s peer=%s new_objective=%r",
            self.agent_id, peer_id, revised.get("objective", "")[:60],
        )

    # ── Peer prediction (2nd-order ToM) ───────────────────────────────────────

    def predict_peer_response(
        self,
        peer_id: str,
        utterance: str,
        task_goal: str,
        history: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Predict how peer_id will react to utterance before it is sent.

        Returns a low-confidence stub when no peer model exists yet.
        Stores the prediction in _pending_predictions[peer_id] for comparison
        after the actual response is observed via update_peer().
        """
        peer_belief = self._peer_beliefs.get(peer_id)
        if not peer_belief:
            stub: Dict[str, Any] = {
                "predicted_response": "",
                "predicted_alignment": 0.5,
                "predicted_derailment": False,
                "predicted_contingency": "normal",
                "confidence": 0.1,
            }
            self._pending_predictions[peer_id] = stub
            return stub
        result = self._llm.complete_json("tom_peer_predict", {
            "speaker": self.agent_id,
            "listener": peer_id,
            "utterance": utterance,
            "task_goal": task_goal,
            "peer_belief": peer_belief,
            "history": (history or [])[-4:],
        })
        prediction: Dict[str, Any] = {
            "predicted_response": str(result.get("predicted_response", "")),
            "predicted_alignment": round(
                max(0.0, min(1.0, float(result.get("predicted_alignment", 0.5)))), 4
            ),
            "predicted_derailment": bool(result.get("predicted_derailment", False)),
            "predicted_contingency": str(result.get("predicted_contingency", "normal")),
            "confidence": round(
                max(0.0, min(1.0, float(result.get("confidence", 0.5)))), 4
            ),
        }
        self._pending_predictions[peer_id] = prediction
        LOGGER.debug(
            "tom.predict %s->%s alignment=%.4f derailment=%s confidence=%.4f",
            self.agent_id, peer_id,
            prediction["predicted_alignment"],
            prediction["predicted_derailment"],
            prediction["confidence"],
        )
        return prediction

    # ── Drift signals (calibrated from stores) ────────────────────────────────

    def drift_signals(
        self,
        concept_id: str = "",
        episode_id: str = "",
        belief_store: Optional[Any] = None,
        taskwork_store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Drift = how far posterior has moved from the taskwork prior.

        anchor_gap is computed from AgentBeliefStore.current_confidence vs
        TaskworkState.prior when stores and concept_id/episode_id are supplied.
        Falls back to 0.0 when stores are unavailable (e.g. early in episode).

        ema_alignment = mean of _peer_ema across all tracked peers; a proxy
        for whether peers are accepting this agent's arguments.
        """
        anchor_gap = 0.0
        if belief_store is not None and taskwork_store is not None and concept_id and episode_id:
            bs = belief_store.current_belief(self.agent_id, concept_id)
            tw = taskwork_store.get(self.agent_id, concept_id, episode_id)
            if bs is not None and tw is not None:
                anchor_gap = round(abs(bs.current_confidence - tw.prior), 4)

        ema = self._peer_ema
        peer_ema_mean = round(sum(ema.values()) / len(ema), 4) if ema else 1.0

        return {
            "agent_id":      self.agent_id,
            "ema_alignment": peer_ema_mean,
            "anchor_gap":    anchor_gap,
            "change_log":    [],
            "confidence":    0.5,
        }


# ── TheoryOfMindEngine ────────────────────────────────────────────────────────


class TheoryOfMindEngine(TheoryOfMindEngineBase):
    """Session coordinator for per-agent Theory-of-Mind state.

    Registry of AgentTOM instances keyed by agent_id. All live state lives
    in AgentTOM (prediction loop + drift signals). LLM introspection calls
    have been replaced by structural equivalents in SSTP.subprotocol.siep.src.grounding
    and epistemic stores.
    """

    def __init__(
        self,
        llm: LLMClient,
        epistemic_store_factory: Optional[Callable[[str], AgentEpistemicStore]] = None,
    ) -> None:
        self.llm = llm
        self._epistemic_store_factory = epistemic_store_factory
        self._agent_toms: Dict[str, AgentTOM] = {}
        self._attribution_scores: Dict[str, float] = {}

    def agent(self, agent_id: str) -> AgentTOM:
        """Return the AgentTOM for agent_id, creating it lazily on first access."""
        if agent_id not in self._agent_toms:
            store = (
                self._epistemic_store_factory(agent_id)
                if self._epistemic_store_factory is not None
                else AgentEpistemicStore(agent_id)
            )
            self._agent_toms[agent_id] = AgentTOM(agent_id, self.llm, store)
        return self._agent_toms[agent_id]

    # ── Deprecated no-op stubs ────────────────────────────────────────────────

    def seed_belief(self, agent_id: str, role_description: str,
                    session_context: Dict[str, Any]) -> Dict[str, Any]:
        """Deprecated. Use AgentBeliefStore + TaskworkStore."""
        return self.agent(agent_id).seed(role_description, session_context)

    def update_belief(self, agent_id: str, utterance: str,
                      task_goal: str) -> Dict[str, Any]:
        """Deprecated. BeliefState updated via receive_peer_turn()."""
        return self.agent(agent_id).update(utterance, task_goal)

    def detect_ambiguity(self, utterance: str, task_goal: str,
                         agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Deprecated. diagnose_repair_reason() in grounding.py covers this."""
        return {"ambiguous": False, "ambiguity_score": 0.0,
                "ambiguous_spans": [], "plausible_interpretations": []}

    def update(self, view: Dict[str, Any], utterance: str,
               task_goal: str, actor: str = "agent") -> Dict[str, Any]:
        """Deprecated. BeliefState updated via receive_peer_turn()."""
        return view if view else {}

    # ── Active methods ────────────────────────────────────────────────────────

    def drift_signals(self, agent_id: str, concept_id: str = "",
                      episode_id: str = "", belief_store: Optional[Any] = None,
                      taskwork_store: Optional[Any] = None) -> Dict[str, Any]:
        if agent_id not in self._agent_toms:
            return {"agent_id": agent_id, "ema_alignment": 1.0,
                    "anchor_gap": 0.0, "change_log": [], "confidence": 0.5}
        return self.agent(agent_id).drift_signals(
            concept_id=concept_id, episode_id=episode_id,
            belief_store=belief_store, taskwork_store=taskwork_store,
        )

    def assess_task_alignment(self, actor: str, task_goal: str, utterance: str,
                               schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Deprecated. epistemic_state in L9 header carries phase classification."""
        return {"actor": actor, "task_goal": task_goal,
                "aligned": True, "alignment_score": 0.5, "rationale": "structural"}

    def ie_utterance_judge(
        self,
        utterance: str,
        task_goal: str,
        speaker: str,
        listener: str,
        speaker_belief: Dict[str, Any],
        history: Optional[List[str]] = None,
        listener_belief: Optional[Dict[str, Any]] = None,
        listener_prior_utterance: Optional[str] = None,
        speaker_epistemic: Optional[Dict[str, Any]] = None,
        listener_prior_epistemic: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Structural grounding check replacing the LLM utterance judge."""
        return self.agent(listener).assess_utterance(
            utterance=utterance, task_goal=task_goal, speaker=speaker, listener=listener,
            history=history, listener_prior_utterance=listener_prior_utterance,
            speaker_epistemic=speaker_epistemic,
            listener_prior_epistemic=listener_prior_epistemic,
        )

    def belief_models(self) -> Dict[str, Dict[str, Any]]:
        return {aid: tom.belief() for aid, tom in self._agent_toms.items()}

    def utterance_history(self) -> Dict[str, List[str]]:
        return {aid: [] for aid in self._agent_toms}

    def attribution_scores(self) -> Dict[str, float]:
        return dict(self._attribution_scores)

    def analyze_pairwise_agent_tom(self, agent_views: Dict[str, Dict[str, Any]],
                                   task_goal: str) -> Dict[str, Any]:
        """Deprecated. Use ReplicaToM.alignment_matrix() instead."""
        return {f"{a}<->{b}": {"alignment_score": 0.5, "disagreement_score": 0.5,
                               "attribution_accuracy": 0.5, "coherence_rationale": "structural"}
                for i, a in enumerate(sorted(agent_views))
                for b in sorted(agent_views)[i+1:]}

    def analyze_inter_agent_tom(self, subject_view: Dict[str, Any],
                                speaker_belief: Dict[str, Any],
                                listener_belief: Dict[str, Any],
                                task_goal: str) -> Dict[str, Any]:
        raise RuntimeError(
            "analyze_inter_agent_tom is removed — use ReplicaToM.alignment_matrix()"
        )

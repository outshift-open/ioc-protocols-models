# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""cognition.py — Per-agent Theory-of-Mind state with cross-episode peer modelling."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from sstp.tomcore.llm import LLMClient
from sstp.ie.tom import TheoryOfMindEngineBase
from sstp.epistemic.stores import AgentEpistemicStore

LOGGER = logging.getLogger("ioc")

_EMA_ALPHA = 0.3
_HISTORY_LIMIT = 10
_CHANGE_LOG_LIMIT = 10
_PEER_MODEL_REVISION_THRESHOLD = 0.35
_PEER_ERROR_WINDOW = 5


class AgentTOM:
    """Per-agent Theory-of-Mind state.

    Owns this agent's belief about itself and a separate peer belief model for
    every peer it interacts with. All state is private; no other agent can
    read it directly.

    Prediction loop (2nd-order ToM):
      1. Before sending an utterance: call predict_peer_response(peer_id, ...)
         — stores prediction in _pending_predictions[peer_id].
      2. After observing the actual response: call update_peer(peer_id, ...)
         — computes prediction_error, appends to _peer_prediction_log, and
           triggers _revise_peer_model if the rolling mean error > threshold.
    """

    def __init__(
        self,
        agent_id: str,
        llm: LLMClient,
        epistemic_store: Optional[AgentEpistemicStore] = None,
    ) -> None:
        self.agent_id = agent_id
        self._llm = llm
        self._belief: Dict[str, Any] = {}
        self._anchor: Dict[str, Any] = {}
        self._ema_alignment: float = 1.0
        self._change_log: List[str] = []
        self._utterance_history: List[str] = []
        self._peer_beliefs: Dict[str, Dict[str, Any]] = {}
        self._peer_ema: Dict[str, float] = {}
        self._pending_predictions: Dict[str, Dict[str, Any]] = {}
        self._peer_prediction_log: Dict[str, List[Dict]] = {}
        self._epistemic_store: AgentEpistemicStore = (
            epistemic_store if epistemic_store is not None else AgentEpistemicStore(agent_id)
        )

    # ── Own belief seeding ─────────────────────────────────────────────────────

    def seed(self, role_description: str, session_context: Dict[str, Any]) -> Dict[str, Any]:
        """Seed own belief from role description; freeze anchor for drift detection."""
        task_goal = session_context.get("task_goal", "")
        result = self._llm.complete_json("tom_belief_seed", {
            "agent_id": self.agent_id,
            "role_description": role_description,
            "task_goal": task_goal,
            "session_context": session_context,
        })
        belief: Dict[str, Any] = {
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
        self._belief = belief
        self._anchor = dict(belief)
        self._utterance_history = []
        self._ema_alignment = 1.0
        self._change_log = []
        LOGGER.debug("tom.seed agent=%s objective=%r", self.agent_id, belief["objective"][:60])
        return belief

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
        """Return this agent's current self-belief dict."""
        return dict(self._belief)

    def peer_belief(self, peer_id: str) -> Dict[str, Any]:
        """Return this agent's belief model of peer_id (empty dict if not seeded)."""
        return dict(self._peer_beliefs.get(peer_id, {}))

    # ── Own belief update ──────────────────────────────────────────────────────

    def update(
        self,
        utterance: str,
        task_goal: str,
        argument_direction: str = "neutral",
        alignment_score: float = 0.65,
        speaker_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update own belief from an observed utterance; advance EMA and change_log."""
        current = self._belief or {
            "role": self.agent_id,
            "objective": task_goal,
            "context_summary": "",
            "inferred_constraints": [],
            "confidence": 0.5,
        }
        result = self._llm.complete_json("tom_belief_update", {
            "agent_id": self.agent_id,
            "agent_role": current.get("role", self.agent_id),
            "current_belief": current,
            "utterance": utterance,
            "task_goal": task_goal,
            "argument_direction": argument_direction,
            "alignment_score": alignment_score,
            "speaker_role": speaker_role or "peer",
        })
        updated = dict(current)
        if isinstance(result.get("objective"), str) and result["objective"]:
            updated["objective"] = result["objective"]
        if isinstance(result.get("context_summary"), str):
            updated["context_summary"] = result["context_summary"]
        if isinstance(result.get("inferred_constraints"), list):
            updated["inferred_constraints"] = result["inferred_constraints"]
        if isinstance(result.get("confidence"), (int, float)):
            updated["confidence"] = round(max(0.0, min(1.0, float(result["confidence"]))), 4)

        hist = self._utterance_history
        hist.append(utterance)
        if len(hist) > _HISTORY_LIMIT:
            hist[:] = hist[-_HISTORY_LIMIT:]

        change = result.get("change_summary", "")
        if isinstance(change, str) and change:
            self._change_log.append(change)
            if len(self._change_log) > _CHANGE_LOG_LIMIT:
                self._change_log[:] = self._change_log[-_CHANGE_LOG_LIMIT:]

        alignment_score = float(
            self.assess_task_alignment(task_goal, utterance).get("alignment_score", 0.5)
        )
        self._ema_alignment = round(
            _EMA_ALPHA * alignment_score + (1 - _EMA_ALPHA) * self._ema_alignment, 4
        )
        self._belief = updated
        LOGGER.debug(
            "tom.update agent=%s ema=%.4f confidence=%.4f change=%r",
            self.agent_id, self._ema_alignment, updated["confidence"],
            change[:60] if change else "",
        )
        return updated

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

    # ── Utterance judgement ────────────────────────────────────────────────────

    def assess_utterance(
        self,
        utterance: str,
        task_goal: str,
        speaker: str,
        listener: Optional[str] = None,
        history: Optional[List[str]] = None,
        listener_prior_utterance: Optional[str] = None,
        confidence_before: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Judge an incoming utterance using own belief context as the listener."""
        payload: Dict[str, Any] = {
            "utterance": utterance,
            "task_goal": task_goal,
            "speaker": speaker,
            "listener": listener or self.agent_id,
            "speaker_belief": self._peer_beliefs.get(speaker, {}),
            "history": (history or [])[-4:],
        }
        if self._belief:
            payload["listener_belief"] = self._belief
        if listener_prior_utterance is not None:
            payload["listener_prior_utterance"] = listener_prior_utterance
        if confidence_before is not None:
            payload["confidence_before"] = confidence_before
        result = self._llm.complete_json("ie_utterance_judge", payload)
        derailed = bool(result.get("derailed", False))
        ambiguous = bool(result.get("ambiguous", False))
        alignment_score = max(
            0.0, min(1.0, float(result.get("alignment_score", 0.25 if derailed else 0.82)))
        )
        aligned = bool(result.get("aligned", not derailed and alignment_score >= 0.55))
        grounding_failure = bool(result.get("grounding_failure", False))
        contingency_score = max(
            0.0,
            min(1.0, float(result.get("contingency_score", 0.1 if grounding_failure else 1.0))),
        )
        verdict = {
            "derailed": derailed,
            "derailment_cause": result.get("derailment_cause") or None,
            "grounding_failure": grounding_failure,
            "contingency_score": round(contingency_score, 4),
            "ambiguous": ambiguous,
            "ambiguity_score": round(
                max(0.0, min(1.0, float(result.get("ambiguity_score", 0.0)))), 4
            ),
            "alignment_score": round(alignment_score, 4),
            "aligned": aligned,
            "judge_confidence": round(
                max(0.0, min(1.0, float(result.get("judge_confidence", 0.85)))), 4
            ),
            "critique": str(result.get("critique", "")),
            "disagreement_score": round(max(0.0, min(1.0, 1.0 - alignment_score)), 4),
        }
        if "posterior_confidence" in result:
            verdict["posterior_confidence"] = round(
                max(0.0, min(1.0, float(result["posterior_confidence"]))), 4
            )
        LOGGER.debug(
            "ie_judge %s->%s derailed=%s grounding_failure=%s score=%.4f",
            speaker, listener or self.agent_id,
            verdict["derailed"], verdict["grounding_failure"], verdict["alignment_score"],
        )
        return verdict

    # ── Peer prediction (2nd-order ToM) ───────────────────────────────────────

    def predict_peer_response(
        self,
        peer_id: str,
        utterance: str,
        task_goal: str,
        history: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Predict how peer_id will react to utterance before it is sent.

        Returns a low-confidence stub when no peer model exists yet; the
        prediction signal is suppressed from derailment detection when
        confidence < 0.2.  Stores the prediction in
        _pending_predictions[peer_id] for comparison after the actual
        response is observed via update_peer().
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
            "observer_belief": dict(self._belief),
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

    # ── Peer alignment ─────────────────────────────────────────────────────────

    def peer_alignment(
        self,
        peer_id: str,
        task_goal: str,
        peer_belief_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compute alignment between own objective and peer's observed objective.

        Uses the stored peer belief model, or peer_belief_override if supplied.
        """
        peer = (
            peer_belief_override
            if peer_belief_override is not None
            else self._peer_beliefs.get(peer_id, {})
        )
        result = self._llm.complete_json("tom_peer_attribution", {
            "speaker_objective": self._belief.get("objective", ""),
            "speaker_context": self._belief.get("context_summary", ""),
            "listener_objective": peer.get("objective", str(peer)),
            "listener_context": peer.get("context_summary", ""),
            "task_goal": task_goal,
        })
        alignment_score, disagreement_score, attribution_accuracy, coherence_rationale = (
            _parse_attribution(result)
        )
        LOGGER.debug(
            "tom.peer_alignment agent=%s peer=%s alignment=%.4f",
            self.agent_id, peer_id, alignment_score,
        )
        return {
            "task_goal": task_goal,
            "alignment_score": alignment_score,
            "disagreement_score": disagreement_score,
            "attribution_accuracy": attribution_accuracy,
            "coherence_rationale": coherence_rationale,
            "role_objectives": {
                self.agent_id: self._belief.get("objective", ""),
                peer_id: peer.get("objective", ""),
            },
        }

    # ── Task alignment ─────────────────────────────────────────────────────────

    def assess_task_alignment(self, task_goal: str, utterance: str) -> Dict[str, Any]:
        """Task alignment check using own belief context."""
        result = self._llm.complete_json("tom_task_alignment", {
            "actor": self.agent_id,
            "task_goal": task_goal,
            "utterance": utterance,
            "current_objective": self._belief.get("objective", ""),
            "inferred_constraints": self._belief.get("inferred_constraints", []),
        })
        aligned = result.get("aligned")
        score = result.get("alignment_score")
        rationale = result.get("rationale", "fallback_heuristic")
        if not isinstance(aligned, bool) or not isinstance(score, (int, float)):
            score = 0.5
            aligned = True
            rationale = "fallback_no_llm"
        return {
            "actor": self.agent_id,
            "task_goal": task_goal,
            "aligned": bool(aligned),
            "alignment_score": round(max(0.0, min(1.0, float(score))), 4),
            "rationale": str(rationale),
        }

    # ── Ambiguity detection ────────────────────────────────────────────────────

    def detect_ambiguity(self, utterance: str, task_goal: str) -> Dict[str, Any]:
        """Detect ambiguity in utterance relative to own belief state."""
        result = self._llm.complete_json("detect_ambiguity", {
            "utterance": utterance,
            "task_goal": task_goal,
            "current_objective": self._belief.get("objective", ""),
            "inferred_constraints": self._belief.get("inferred_constraints", []),
        })
        ambiguous = result.get("ambiguous")
        if not isinstance(ambiguous, bool):
            ambiguous = False
        return {
            "ambiguous": ambiguous,
            "ambiguity_score": round(
                max(0.0, min(1.0, float(result.get("ambiguity_score", 0.0)))), 4
            ),
            "ambiguous_spans": (
                result.get("ambiguous_spans")
                if isinstance(result.get("ambiguous_spans"), list)
                else []
            ),
            "plausible_interpretations": (
                result.get("plausible_interpretations")
                if isinstance(result.get("plausible_interpretations"), list)
                else []
            ),
        }

    # ── Drift signals ──────────────────────────────────────────────────────────

    def drift_signals(self) -> Dict[str, Any]:
        """Return drift detection signals for this agent."""
        return {
            "agent_id": self.agent_id,
            "ema_alignment": self._ema_alignment,
            "anchor_gap": round(
                abs(
                    float(self._belief.get("confidence", 0.5))
                    - float(self._anchor.get("confidence", 0.5))
                ),
                4,
            ),
            "change_log": list(self._change_log),
            "confidence": float(self._belief.get("confidence", 0.5)),
        }


# ── TheoryOfMindEngine ────────────────────────────────────────────────────────


class TheoryOfMindEngine(TheoryOfMindEngineBase):
    """Session coordinator for per-agent Theory-of-Mind state.

    Maintains a registry of AgentTOM instances keyed by agent_id.  All belief
    state lives in AgentTOM; this class is a thin coordinator and
    backward-compatibility wrapper.

    An optional ``epistemic_store_factory`` can be supplied to wire each
    AgentTOM to a persistent store backed by the application's storage layer.
    The factory receives the agent_id and returns an AgentEpistemicStore.
    The default creates an in-memory store (safe for tests).
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

    # ── Backward-compat delegating wrappers ───────────────────────────────────

    def seed_belief(
        self, agent_id: str, role_description: str, session_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self.agent(agent_id).seed(role_description, session_context)

    def update_belief(
        self, agent_id: str, utterance: str, task_goal: str
    ) -> Dict[str, Any]:
        return self.agent(agent_id).update(utterance, task_goal)

    def detect_ambiguity(
        self,
        utterance: str,
        task_goal: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if agent_id is None:
            result = self.llm.complete_json("detect_ambiguity", {
                "utterance": utterance,
                "task_goal": task_goal,
                "current_objective": "",
                "inferred_constraints": [],
            })
            ambiguous = result.get("ambiguous")
            if not isinstance(ambiguous, bool):
                ambiguous = False
            return {
                "ambiguous": ambiguous,
                "ambiguity_score": round(
                    max(0.0, min(1.0, float(result.get("ambiguity_score", 0.0)))), 4
                ),
                "ambiguous_spans": (
                    result.get("ambiguous_spans")
                    if isinstance(result.get("ambiguous_spans"), list)
                    else []
                ),
                "plausible_interpretations": (
                    result.get("plausible_interpretations")
                    if isinstance(result.get("plausible_interpretations"), list)
                    else []
                ),
            }
        return self.agent(agent_id).detect_ambiguity(utterance, task_goal)

    def drift_signals(self, agent_id: str) -> Dict[str, Any]:
        if agent_id not in self._agent_toms:
            return {
                "agent_id": agent_id,
                "ema_alignment": 1.0,
                "anchor_gap": 0.0,
                "change_log": [],
                "confidence": 0.5,
            }
        return self.agent(agent_id).drift_signals()

    def assess_task_alignment(
        self,
        actor: str,
        task_goal: str,
        utterance: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.agent(actor).assess_task_alignment(task_goal, utterance)

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
    ) -> Dict[str, Any]:
        return self.agent(listener).assess_utterance(
            utterance, task_goal, speaker, listener,
            history=history,
            listener_prior_utterance=listener_prior_utterance,
        )

    def update(
        self,
        view: Dict[str, Any],
        utterance: str,
        task_goal: str,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        updated = self.agent(actor).update(utterance, task_goal)
        # Preserve legacy float-dict return contract for callers that relied on it
        if view and all(isinstance(v, (int, float)) for v in view.values()):
            return view
        return updated

    def belief_models(self) -> Dict[str, Dict[str, Any]]:
        return {aid: tom.belief() for aid, tom in self._agent_toms.items()}

    def utterance_history(self) -> Dict[str, List[str]]:
        return {
            aid: list(tom._utterance_history)
            for aid, tom in self._agent_toms.items()
        }

    def attribution_scores(self) -> Dict[str, float]:
        return dict(self._attribution_scores)

    # ── Pairwise analysis (kept for compat) ───────────────────────────────────

    def analyze_pairwise_agent_tom(
        self,
        agent_views: Dict[str, Dict[str, Any]],
        task_goal: str,
    ) -> Dict[str, Any]:
        pairwise: Dict[str, Any] = {}
        agents = sorted(agent_views.keys())
        for i, id_a in enumerate(agents):
            for id_b in agents[i + 1:]:
                metrics = self.agent(id_a).peer_alignment(
                    id_b, task_goal, peer_belief_override=agent_views[id_b]
                )
                pair_key = f"{id_a}<->{id_b}"
                self._attribution_scores[pair_key] = metrics.get("attribution_accuracy", 0.5)
                pairwise[pair_key] = metrics
        LOGGER.info("tom.pairwise task_goal=%r pairs=%d", task_goal, len(pairwise))
        return pairwise

    def analyze_inter_agent_tom(
        self,
        subject_view: Dict[str, Any],
        speaker_belief: Dict[str, Any],
        listener_belief: Dict[str, Any],
        task_goal: str,
    ) -> Dict[str, Any]:
        raise RuntimeError(
            "analyze_inter_agent_tom is removed — use agent(id).peer_alignment(peer_id, task_goal)"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_attribution(result: Dict[str, Any]) -> tuple[float, float, float, str]:
    a = result.get("alignment_score")
    d = result.get("disagreement_score")
    acc = result.get("attribution_accuracy")
    rat = result.get("coherence_rationale", "")
    if not isinstance(a, (int, float)):
        a = 0.5
    if not isinstance(d, (int, float)):
        d = round(1.0 - float(a), 4)
    if not isinstance(acc, (int, float)):
        acc = float(a)
    return (
        round(max(0.0, min(1.0, float(a))), 4),
        round(max(0.0, min(1.0, float(d))), 4),
        round(max(0.0, min(1.0, float(acc))), 4),
        str(rat),
    )

# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""cognition.py — Single semantic-belief Theory of Mind engine."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sstp.tomcore.llm import LLMClient
from sstp.ie.tom import TheoryOfMindEngineBase

LOGGER = logging.getLogger("ioc")

_EMA_ALPHA = 0.3
_HISTORY_LIMIT = 10
_CHANGE_LOG_LIMIT = 10


class TheoryOfMindEngine(TheoryOfMindEngineBase):
    """Single semantic-belief ToM engine.

    Replaces both the float-vector v1 engine and the narrative v2 engine.
    Belief state is a semantic dict (role, objective, context_summary,
    inferred_constraints, confidence) rather than a vector of named floats.

    Each agent's belief is seeded from a role description, frozen as an
    anchor, then updated incrementally from observed utterances.  Drift is
    detected via EMA alignment decay and anchor_gap.
    """

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._beliefs: Dict[str, Dict[str, Any]] = {}
        self._anchors: Dict[str, Dict[str, Any]] = {}
        self._utterance_history: Dict[str, List[str]] = {}
        self._ema_alignments: Dict[str, float] = {}
        self._change_logs: Dict[str, List[str]] = {}
        self._attribution_scores: Dict[str, float] = {}

    # ── Belief seeding ─────────────────────────────────────────────────────────

    def seed_belief(
        self,
        agent_id: str,
        role_description: str,
        session_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        task_goal = session_context.get("task_goal", "")
        result = self.llm.complete_json("tom_belief_seed", {
            "agent_id": agent_id,
            "role_description": role_description,
            "task_goal": task_goal,
            "session_context": session_context,
        })
        belief: Dict[str, Any] = {
            "role": result.get("role") or role_description,
            "objective": result.get("objective") or role_description,
            "context_summary": result.get("context_summary") or "",
            "inferred_constraints": result.get("inferred_constraints") if isinstance(result.get("inferred_constraints"), list) else [],
            "confidence": round(max(0.0, min(1.0, float(result.get("confidence", 0.5)))), 4),
        }
        self._beliefs[agent_id] = belief
        self._anchors[agent_id] = dict(belief)
        self._utterance_history[agent_id] = []
        self._ema_alignments[agent_id] = 1.0
        self._change_logs[agent_id] = []
        LOGGER.debug("tom.seed_belief agent=%s objective=%r", agent_id, belief["objective"][:60])
        return belief

    # ── Ambiguity detection ────────────────────────────────────────────────────

    def detect_ambiguity(
        self,
        utterance: str,
        task_goal: str,
        agent_id: str | None = None,
    ) -> Dict[str, Any]:
        belief = self._beliefs.get(agent_id, {}) if agent_id else {}
        result = self.llm.complete_json("detect_ambiguity", {
            "utterance": utterance,
            "task_goal": task_goal,
            "current_objective": belief.get("objective", ""),
            "inferred_constraints": belief.get("inferred_constraints", []),
        })
        ambiguous = result.get("ambiguous")
        if not isinstance(ambiguous, bool):
            ambiguous = False
        return {
            "ambiguous": ambiguous,
            "ambiguity_score": round(max(0.0, min(1.0, float(result.get("ambiguity_score", 0.0)))), 4),
            "ambiguous_spans": result.get("ambiguous_spans") if isinstance(result.get("ambiguous_spans"), list) else [],
            "plausible_interpretations": result.get("plausible_interpretations") if isinstance(result.get("plausible_interpretations"), list) else [],
        }

    # ── Belief update ──────────────────────────────────────────────────────────

    def update_belief(self, agent_id: str, utterance: str, task_goal: str) -> Dict[str, Any]:
        current = self._beliefs.get(agent_id, {
            "role": agent_id,
            "objective": task_goal,
            "context_summary": "",
            "inferred_constraints": [],
            "confidence": 0.5,
        })
        result = self.llm.complete_json("tom_belief_update", {
            "agent_id": agent_id,
            "current_belief": current,
            "utterance": utterance,
            "task_goal": task_goal,
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

        # Utterance history
        hist = self._utterance_history.setdefault(agent_id, [])
        hist.append(utterance)
        if len(hist) > _HISTORY_LIMIT:
            hist[:] = hist[-_HISTORY_LIMIT:]

        # Change log
        change = result.get("change_summary", "")
        if isinstance(change, str) and change:
            clog = self._change_logs.setdefault(agent_id, [])
            clog.append(change)
            if len(clog) > _CHANGE_LOG_LIMIT:
                clog[:] = clog[-_CHANGE_LOG_LIMIT:]

        # Alignment score for EMA
        alignment = self.assess_task_alignment(agent_id, task_goal, utterance)
        current_score = float(alignment.get("alignment_score", 0.5))
        prev_ema = self._ema_alignments.get(agent_id, 1.0)
        self._ema_alignments[agent_id] = round(_EMA_ALPHA * current_score + (1 - _EMA_ALPHA) * prev_ema, 4)

        self._beliefs[agent_id] = updated
        LOGGER.debug(
            "tom.update_belief agent=%s ema=%.4f confidence=%.4f change=%r",
            agent_id,
            self._ema_alignments[agent_id],
            updated["confidence"],
            change[:60] if change else "",
        )
        return updated

    # ── Interface compat: update() ─────────────────────────────────────────────

    def update(
        self,
        view: Dict[str, Any],
        utterance: str,
        task_goal: str,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        """Interface compat: delegates to update_belief.

        If view is a float dict (legacy caller), returns it unchanged.
        If view is a belief dict, returns the updated belief.
        """
        updated = self.update_belief(actor, utterance, task_goal)
        # If view looks like a float dict, preserve legacy return contract
        if view and all(isinstance(v, (int, float)) for v in view.values()):
            return view
        return updated

    # ── Alignment assessment ───────────────────────────────────────────────────

    def assess_task_alignment(
        self,
        actor: str,
        task_goal: str,
        utterance: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        belief = self._beliefs.get(actor, {})
        result = self.llm.complete_json("tom_task_alignment", {
            "actor": actor,
            "task_goal": task_goal,
            "utterance": utterance,
            "current_objective": belief.get("objective", ""),
            "inferred_constraints": belief.get("inferred_constraints", []),
        })
        aligned = result.get("aligned")
        score = result.get("alignment_score")
        rationale = result.get("rationale", "fallback_heuristic")
        if not isinstance(aligned, bool) or not isinstance(score, (int, float)):
            score = 0.5
            aligned = True
            rationale = "fallback_no_llm"
        return {
            "actor": actor,
            "task_goal": task_goal,
            "aligned": bool(aligned),
            "alignment_score": round(max(0.0, min(1.0, float(score))), 4),
            "rationale": str(rationale),
        }

    # ── Drift detection ────────────────────────────────────────────────────────

    def drift_signals(self, agent_id: str) -> Dict[str, Any]:
        belief = self._beliefs.get(agent_id, {})
        anchor = self._anchors.get(agent_id, {})
        ema = self._ema_alignments.get(agent_id, 1.0)
        anchor_confidence = float(anchor.get("confidence", 0.5))
        current_confidence = float(belief.get("confidence", 0.5))
        anchor_gap = round(abs(current_confidence - anchor_confidence), 4)
        return {
            "agent_id": agent_id,
            "ema_alignment": ema,
            "anchor_gap": anchor_gap,
            "change_log": list(self._change_logs.get(agent_id, [])),
            "confidence": current_confidence,
        }

    # ── Utterance judge ────────────────────────────────────────────────────────

    def ie_utterance_judge(
        self,
        utterance: str,
        task_goal: str,
        speaker: str,
        listener: str,
        speaker_belief: Dict[str, Any],
        history: List[str] | None = None,
        listener_belief: Dict[str, Any] | None = None,
        listener_prior_utterance: str | None = None,
    ) -> Dict[str, Any]:
        """Call the LLM ie_utterance_judge task and normalise the result."""
        payload: Dict[str, Any] = {
            "utterance": utterance,
            "task_goal": task_goal,
            "speaker": speaker,
            "listener": listener,
            "speaker_belief": speaker_belief,
            "history": (history or [])[-4:],
        }
        if listener_belief is not None:
            payload["listener_belief"] = listener_belief
        if listener_prior_utterance is not None:
            payload["listener_prior_utterance"] = listener_prior_utterance
        result = self.llm.complete_json("ie_utterance_judge", payload)
        derailed = bool(result.get("derailed", False))
        ambiguous = bool(result.get("ambiguous", False))
        alignment_score = max(0.0, min(1.0, float(result.get("alignment_score", 0.25 if derailed else 0.82))))
        aligned = bool(result.get("aligned", not derailed and alignment_score >= 0.55))
        ambiguity_score = max(0.0, min(1.0, float(result.get("ambiguity_score", 0.0))))
        judge_confidence = max(0.0, min(1.0, float(result.get("judge_confidence", 0.85))))
        critique = str(result.get("critique", ""))
        grounding_failure = bool(result.get("grounding_failure", False))
        contingency_score = max(0.0, min(1.0, float(result.get("contingency_score", 0.1 if grounding_failure else 1.0))))
        verdict = {
            "derailed": derailed,
            "derailment_cause": result.get("derailment_cause") or None,
            "grounding_failure": grounding_failure,
            "contingency_score": round(contingency_score, 4),
            "ambiguous": ambiguous,
            "ambiguity_score": round(ambiguity_score, 4),
            "alignment_score": round(alignment_score, 4),
            "aligned": aligned,
            "judge_confidence": round(judge_confidence, 4),
            "critique": critique,
            "disagreement_score": round(max(0.0, min(1.0, 1.0 - alignment_score)), 4),
        }
        LOGGER.debug(
            "ie_judge %s->%s derailed=%s cause=%s grounding_failure=%s contingency=%.4f ambiguous=%s score=%.4f confidence=%.4f",
            speaker, listener,
            verdict["derailed"], verdict["derailment_cause"],
            verdict["grounding_failure"], verdict["contingency_score"],
            verdict["ambiguous"], verdict["alignment_score"],
            verdict["judge_confidence"],
        )
        return verdict

    # ── Inter-agent analysis ───────────────────────────────────────────────────

    def analyze_inter_agent_tom(
        self,
        subject_view: Dict[str, Any],
        left_view: Dict[str, Any],
        right_view: Dict[str, Any],
        task_goal: str,
    ) -> Dict[str, Any]:
        left_model = self._beliefs.get("left", left_view)
        right_model = self._beliefs.get("right", right_view)
        result = self.llm.complete_json("tom_peer_attribution", {
            "left_belief_model": left_model.get("objective", str(left_view)),
            "left_context": left_model.get("context_summary", ""),
            "right_belief_model": right_model.get("objective", str(right_view)),
            "right_context": right_model.get("context_summary", ""),
            "task_goal": task_goal,
        })
        alignment_score, disagreement_score, attribution_accuracy, coherence_rationale = _parse_attribution(result)
        self._attribution_scores["left<->right"] = attribution_accuracy
        left_alignment = self.assess_task_alignment("left", task_goal, left_model.get("objective", ""))
        right_alignment = self.assess_task_alignment("right", task_goal, right_model.get("objective", ""))
        LOGGER.info("tom.inter_agent task_goal=%r alignment=%.4f attribution=%.4f", task_goal, alignment_score, attribution_accuracy)
        return {
            "task_goal": task_goal,
            "left_view": left_view,
            "right_view": right_view,
            "subject_view": subject_view,
            "dimension_agreements": {},
            "alignment_score": alignment_score,
            "disagreement_score": disagreement_score,
            "task_alignment": {"left": left_alignment, "right": right_alignment},
            "belief_models": {
                "left": left_model.get("objective", ""),
                "right": right_model.get("objective", ""),
            },
            "attribution_accuracy": attribution_accuracy,
            "coherence_rationale": coherence_rationale,
        }

    def analyze_pairwise_agent_tom(
        self,
        agent_views: Dict[str, Dict[str, Any]],
        task_goal: str,
    ) -> Dict[str, Any]:
        pairwise: Dict[str, Any] = {}
        agents = sorted(agent_views.keys())
        for i, left in enumerate(agents):
            for right in agents[i + 1:]:
                left_model = self._beliefs.get(left, agent_views[left])
                right_model = self._beliefs.get(right, agent_views[right])
                result = self.llm.complete_json("tom_peer_attribution", {
                    "left_belief_model": left_model.get("objective", str(agent_views[left])),
                    "left_context": left_model.get("context_summary", ""),
                    "right_belief_model": right_model.get("objective", str(agent_views[right])),
                    "right_context": right_model.get("context_summary", ""),
                    "task_goal": task_goal,
                })
                alignment_score, disagreement_score, attribution_accuracy, coherence_rationale = _parse_attribution(result)
                pair_key = f"{left}<->{right}"
                self._attribution_scores[pair_key] = attribution_accuracy
                left_alignment = self.assess_task_alignment(left, task_goal, left_model.get("objective", ""))
                right_alignment = self.assess_task_alignment(right, task_goal, right_model.get("objective", ""))
                pairwise[pair_key] = {
                    "task_goal": task_goal,
                    "alignment_score": alignment_score,
                    "disagreement_score": disagreement_score,
                    "dimension_agreements": {},
                    "left_view": agent_views[left],
                    "right_view": agent_views[right],
                    "task_alignment": {"left": left_alignment, "right": right_alignment},
                    "belief_models": {
                        "left": left_model.get("objective", ""),
                        "right": right_model.get("objective", ""),
                    },
                    "attribution_accuracy": attribution_accuracy,
                    "coherence_rationale": coherence_rationale,
                }
        LOGGER.info("tom.pairwise_agents task_goal=%r pairs=%d", task_goal, len(pairwise))
        return pairwise

    # ── Introspection accessors ────────────────────────────────────────────────

    def belief_models(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._beliefs)

    def utterance_history(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in self._utterance_history.items()}

    def attribution_scores(self) -> Dict[str, float]:
        return dict(self._attribution_scores)


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

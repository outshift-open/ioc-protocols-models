from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sstp.tomcore.llm import LLMClient
from sstp.ie.tom import TheoryOfMindEngineBase

LOGGER = logging.getLogger("ioc")

_HISTORY_LIMIT = 10
_HEALTHCARE_TOKENS = frozenset(
    {
        "symptom", "medication", "interaction", "allergy", "specialist",
        "insurance", "network", "cost", "schedule", "appointment",
        "route", "diagnosis", "patient", "treatment", "clinical",
    }
)


class TheoryOfMindEngine2(TheoryOfMindEngineBase):
    """Second-order, narrative belief-modelling ToM engine.

    Completely different from ToM1:

    ToM1 is *stateless and scalar* — it compares flat float vectors and
    asks the LLM to score dimensional agreement.

    ToM2 is *stateful and narrative* — it accumulates each agent's
    utterance history, infers a natural-language belief model per agent
    ("what does this agent believe about the task?"), and measures
    alignment through second-order attribution: how well does A's model
    of B's beliefs match B's actual utterances?

    Internal state
    --------------
    _utterance_history   agent_id → last N utterances
    _belief_models       agent_id → latest inferred belief narrative (str)
    _peer_predictions    agent_a  → {agent_b → predicted narrative}
    _attribution_scores  "a<->b"  → latest attribution accuracy score
    """

    def __init__(
        self,
        llm: LLMClient,
        dimensions: List[str],
        combining_instruction: str,
    ) -> None:
        # dimensions/combining_instruction accepted for interface compat but unused
        self.llm = llm
        self.dimensions = dimensions
        self.combining_instruction = combining_instruction
        self._utterance_history: Dict[str, List[str]] = {}
        self._belief_models: Dict[str, str] = {}
        self._peer_predictions: Dict[str, Dict[str, str]] = {}
        self._attribution_scores: Dict[str, float] = {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _infer_belief_model(self, actor: str, utterances: List[str], task_goal: str) -> str:
        """Call LLM to infer actor's belief model; cache result."""
        result = self.llm.complete_json(
            "tom2_belief_infer",
            {"actor": actor, "utterances": utterances, "task_goal": task_goal},
        )
        model = result.get("belief_model")
        if not isinstance(model, str) or not model:
            model = f"{actor} holds an unresolved belief about: {task_goal[:60]}"
        self._belief_models[actor] = model
        return model

    def _get_belief_model(self, actor: str, task_goal: str) -> str:
        """Return cached belief model, or a generic stub if not yet inferred."""
        return self._belief_models.get(
            actor, f"{actor} has not yet expressed beliefs about: {task_goal[:60]}"
        )

    # ── TheoryOfMindEngineBase implementation ─────────────────────────────────

    def update(
        self,
        view: Dict[str, float],
        utterance: str,
        task_goal: str,
        actor: str = "agent",
    ) -> Dict[str, float]:
        """Accumulate utterance and re-infer belief model for this actor.

        Unlike ToM1 (which is a no-op here), ToM2 actively uses update()
        to build its per-agent narrative state.
        """
        history = self._utterance_history.setdefault(actor, [])
        history.append(utterance)
        if len(history) > _HISTORY_LIMIT:
            history[:] = history[-_HISTORY_LIMIT:]

        model = self._infer_belief_model(actor, history, task_goal)
        LOGGER.debug(
            "tom2.update actor=%s task_goal=%r utterances=%d belief_model=%r",
            actor,
            task_goal,
            len(history),
            model[:60],
        )
        return view  # unchanged — interface compat

    def assess_task_alignment(
        self, actor: str, task_goal: str, utterance: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Infer actor's belief model from this utterance; score task alignment.

        ToM2 asks: given what this agent just said, what does it believe —
        and is that belief directed toward the task goal?
        """
        result = self.llm.complete_json(
            "tom2_belief_infer",
            {
                "actor": actor,
                "utterances": [utterance],
                "task_goal": task_goal,
            },
        )
        on_task = result.get("on_task")
        score = result.get("task_commitment_score")
        reasoning = result.get("reasoning", "fallback_heuristic")

        if not isinstance(on_task, bool) or not isinstance(score, (int, float)):
            on_task = True
            score = 0.5
            reasoning = "fallback_no_llm"

        score = round(max(0.0, min(1.0, float(score))), 4)
        LOGGER.debug(
            "tom2.assess_task_alignment actor=%s on_task=%s score=%.4f",
            actor,
            on_task,
            score,
        )
        return {
            "actor": actor,
            "task_goal": task_goal,
            "aligned": bool(on_task),
            "alignment_score": score,
            "rationale": str(reasoning),
            "tom_model": "v2",
        }

    def analyze_inter_agent_tom(
        self,
        subject_view: Dict[str, float],
        left_view: Dict[str, float],
        right_view: Dict[str, float],
        task_goal: str,
    ) -> Dict[str, Any]:
        """Measure belief-narrative compatibility between two agents.

        ToM2 derives alignment from whether the two agents' inferred
        belief narratives are coherent with each other — not from
        comparing scalar dimensions.
        """
        left_model = self._get_belief_model("left", task_goal)
        right_model = self._get_belief_model("right", task_goal)

        result = self.llm.complete_json(
            "tom2_peer_attribution",
            {
                "left_belief_model": left_model,
                "right_belief_model": right_model,
                "task_goal": task_goal,
            },
        )
        alignment_score = result.get("alignment_score")
        disagreement_score = result.get("disagreement_score")
        attribution_accuracy = result.get("attribution_accuracy")
        coherence_rationale = result.get("coherence_rationale", "")

        if not isinstance(alignment_score, (int, float)):
            alignment_score = 0.5
        if not isinstance(disagreement_score, (int, float)):
            disagreement_score = round(1.0 - float(alignment_score), 4)
        if not isinstance(attribution_accuracy, (int, float)):
            attribution_accuracy = float(alignment_score)

        alignment_score = round(max(0.0, min(1.0, float(alignment_score))), 4)
        disagreement_score = round(max(0.0, min(1.0, float(disagreement_score))), 4)
        attribution_accuracy = round(max(0.0, min(1.0, float(attribution_accuracy))), 4)

        left_alignment = self.assess_task_alignment("left", task_goal, left_model)
        right_alignment = self.assess_task_alignment("right", task_goal, right_model)

        LOGGER.info(
            "tom2.inter_agent task_goal=%r alignment=%.4f attribution=%.4f",
            task_goal,
            alignment_score,
            attribution_accuracy,
        )
        return {
            "task_goal": task_goal,
            "left_view": left_view,
            "right_view": right_view,
            "subject_view": subject_view,
            "dimension_agreements": {},  # ToM2 does not use scalar dimensions
            "alignment_score": alignment_score,
            "disagreement_score": disagreement_score,
            "task_alignment": {
                "left": left_alignment,
                "right": right_alignment,
            },
            "tom_model": "v2",
            "belief_models": {"left": left_model, "right": right_model},
            "attribution_accuracy": attribution_accuracy,
            "coherence_rationale": coherence_rationale,
        }

    def analyze_pairwise_agent_tom(
        self, agent_views: Dict[str, Dict[str, float]], task_goal: str
    ) -> Dict[str, Any]:
        """Second-order belief alignment across all agent pairs.

        For each pair, compares belief narratives rather than scalar
        dimensions, and reports attribution accuracy alongside alignment.
        """
        pairwise: Dict[str, Any] = {}
        agents = sorted(agent_views.keys())

        for index, left in enumerate(agents):
            for right in agents[index + 1:]:
                left_model = self._get_belief_model(left, task_goal)
                right_model = self._get_belief_model(right, task_goal)

                result = self.llm.complete_json(
                    "tom2_peer_attribution",
                    {
                        "left_belief_model": left_model,
                        "right_belief_model": right_model,
                        "task_goal": task_goal,
                    },
                )
                alignment_score = result.get("alignment_score")
                disagreement_score = result.get("disagreement_score")
                attribution_accuracy = result.get("attribution_accuracy")
                coherence_rationale = result.get("coherence_rationale", "")

                if not isinstance(alignment_score, (int, float)):
                    alignment_score = 0.5
                if not isinstance(disagreement_score, (int, float)):
                    disagreement_score = round(1.0 - float(alignment_score), 4)
                if not isinstance(attribution_accuracy, (int, float)):
                    attribution_accuracy = float(alignment_score)

                alignment_score = round(max(0.0, min(1.0, float(alignment_score))), 4)
                disagreement_score = round(max(0.0, min(1.0, float(disagreement_score))), 4)
                attribution_accuracy = round(max(0.0, min(1.0, float(attribution_accuracy))), 4)

                left_alignment = self.assess_task_alignment(left, task_goal, left_model)
                right_alignment = self.assess_task_alignment(right, task_goal, right_model)

                pair_key = f"{left}<->{right}"
                self._attribution_scores[pair_key] = attribution_accuracy
                pairwise[pair_key] = {
                    "task_goal": task_goal,
                    "alignment_score": alignment_score,
                    "disagreement_score": disagreement_score,
                    "dimension_agreements": {},
                    "left_view": agent_views[left],
                    "right_view": agent_views[right],
                    "task_alignment": {
                        "left": left_alignment,
                        "right": right_alignment,
                    },
                    "tom_model": "v2",
                    "belief_models": {"left": left_model, "right": right_model},
                    "attribution_accuracy": attribution_accuracy,
                    "coherence_rationale": coherence_rationale,
                }

        LOGGER.info(
            "tom2.pairwise_agents task_goal=%r pairs=%d", task_goal, len(pairwise)
        )
        return pairwise

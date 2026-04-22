from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sstp.tomcore.llm import LLMClient
from sstp.ie.tom import TheoryOfMindEngineBase

LOGGER = logging.getLogger("ioc")


class TheoryOfMindEngine(TheoryOfMindEngineBase):
    def __init__(self, llm: LLMClient, dimensions: List[str], combining_instruction: str) -> None:
        self.llm = llm
        self.dimensions = dimensions
        self.combining_instruction = combining_instruction

    @staticmethod
    def _bucket_score(value: float) -> str:
        if value >= 0.7:
            return "high"
        if value <= 0.35:
            return "low"
        return "moderate"

    def _agent_view_to_natural_language(self, agent_name: str, view: Dict[str, float], task_goal: str) -> str:
        parts = ", ".join(
            f"{dim} is {self._bucket_score(float(view.get(dim, 0.0)))}"
            for dim in self.dimensions
        )
        return f"{agent_name} is evaluating the task: {task_goal}. {parts}."

    def assess_task_alignment(self, actor: str, task_goal: str, utterance: str, schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "actor": actor,
            "task_goal": task_goal,
            "utterance": utterance,
        }
        result = self.llm.complete_json("tom_task_alignment", payload)
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
            "aligned": aligned,
            "alignment_score": round(float(score), 4),
            "rationale": str(rationale),
        }

    def update(self, view: Dict[str, float], utterance: str, task_goal: str, actor: str = "agent") -> Dict[str, float]:
        alignment = self.assess_task_alignment(actor=actor, task_goal=task_goal, utterance=utterance)
        result = self.llm.complete_json("tom_state_update", {
            "observer_role": "observer",
            "speaker_role": actor,
            "utterance": utterance,
            "task_goal": task_goal,
            "current_view": view,
        })

        def _clamp(x: float) -> float:
            return max(0.0, min(1.0, x))

        updated = dict(view)
        trust_delta = float(result.get("trust_delta", 0.0))
        urgency_delta = float(result.get("urgency_delta", 0.0))
        cost_sensitivity_delta = float(result.get("cost_sensitivity_delta", 0.0))
        follow_through_delta = float(result.get("follow_through_delta", 0.0))
        if "trust" in updated:
            updated["trust"] = round(_clamp(updated["trust"] + trust_delta), 4)
        if "urgency" in updated:
            updated["urgency"] = round(_clamp(updated["urgency"] + urgency_delta), 4)
        if "cost_sensitivity" in updated:
            updated["cost_sensitivity"] = round(_clamp(updated["cost_sensitivity"] + cost_sensitivity_delta), 4)
        if "follow_through" in updated:
            updated["follow_through"] = round(_clamp(updated["follow_through"] + follow_through_delta), 4)

        LOGGER.debug(
            "tom.update actor=%s task_goal=%r utterance=%r aligned=%s score=%.4f deltas=(trust=%+.4f urgency=%+.4f) view_after=%s",
            actor,
            task_goal,
            utterance,
            alignment["aligned"],
            alignment["alignment_score"],
            trust_delta,
            urgency_delta,
            updated,
        )
        return updated

    def analyze_inter_agent_tom(
        self,
        subject_view: Dict[str, float],
        left_view: Dict[str, float],
        right_view: Dict[str, float],
        task_goal: str,
    ) -> Dict[str, Any]:
        dimension_agreements = {
            dim: round(1.0 - min(1.0, abs(left_view.get(dim, 0.0) - right_view.get(dim, 0.0))), 4)
            for dim in self.dimensions
        }
        alignment_score = round(
            sum(dimension_agreements.values()) / len(dimension_agreements), 4
        ) if dimension_agreements else 0.5
        disagreement = round(1.0 - alignment_score, 4)

        left_alignment = self.assess_task_alignment(
            actor="peer_agent",
            task_goal=task_goal,
            utterance=self._agent_view_to_natural_language("left", left_view, task_goal),
        )
        right_alignment = self.assess_task_alignment(
            actor="peer_agent",
            task_goal=task_goal,
            utterance=self._agent_view_to_natural_language("right", right_view, task_goal),
        )
        LOGGER.info(
            "tom.inter_agent task_goal=%r alignment=%.4f disagreement=%.4f",
            task_goal,
            alignment_score,
            disagreement,
        )
        return {
            "task_goal": task_goal,
            "left_view": left_view,
            "right_view": right_view,
            "subject_view": subject_view,
            "dimension_agreements": dimension_agreements,
            "alignment_score": alignment_score,
            "disagreement_score": disagreement,
            "task_alignment": {
                "left": left_alignment,
                "right": right_alignment,
            },
        }

    def analyze_pairwise_agent_tom(self, agent_views: Dict[str, Dict[str, float]], task_goal: str) -> Dict[str, Any]:
        pairwise: Dict[str, Any] = {}
        agents = sorted(agent_views.keys())
        for index, left in enumerate(agents):
            for right in agents[index + 1:]:
                left_view = agent_views[left]
                right_view = agent_views[right]
                dimension_agreements = {
                    dim: round(1.0 - min(1.0, abs(left_view.get(dim, 0.0) - right_view.get(dim, 0.0))), 4)
                    for dim in self.dimensions
                }
                payload = {
                    "task_goal": task_goal,
                    "left_agent": left,
                    "right_agent": right,
                    "dimension_agreements": dimension_agreements,
                    "combining_instruction": self.combining_instruction,
                }
                result = self.llm.complete_json("tom_pairwise_alignment", payload)
                alignment_score = result.get("alignment_score")
                if not isinstance(alignment_score, (int, float)):
                    alignment_score = (
                        sum(dimension_agreements.values()) / len(dimension_agreements)
                        if dimension_agreements else 0.5
                    )
                alignment_score = round(float(alignment_score), 4)
                disagreement = round(1.0 - alignment_score, 4)

                left_alignment = self.assess_task_alignment(
                    actor="peer_agent",
                    task_goal=task_goal,
                    utterance=self._agent_view_to_natural_language(left, left_view, task_goal),
                )
                right_alignment = self.assess_task_alignment(
                    actor="peer_agent",
                    task_goal=task_goal,
                    utterance=self._agent_view_to_natural_language(right, right_view, task_goal),
                )
                pairwise[f"{left}<->{right}"] = {
                    "task_goal": task_goal,
                    "alignment_score": alignment_score,
                    "disagreement_score": disagreement,
                    "dimension_agreements": dimension_agreements,
                    "combining_instruction": self.combining_instruction,
                    "left_view": left_view,
                    "right_view": right_view,
                    "task_alignment": {
                        "left": left_alignment,
                        "right": right_alignment,
                    },
                }
        LOGGER.info("tom.pairwise_agents task_goal=%r pairs=%d", task_goal, len(pairwise))
        return pairwise

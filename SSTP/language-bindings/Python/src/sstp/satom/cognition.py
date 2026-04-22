# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
cognition.py — SA-ToM: Situation Awareness + Theory of Mind engine.

Organises multi-agent belief reasoning into Endsley's three SA levels:

    SA-L1 (Perception)
        Per-utterance signal extraction.  Detects attention cues, computes
        dimension deltas from the observed utterance.
        LLM task: ``sa_l1_perceive``

    SA-L2 (Comprehension)
        Multi-agent situation integration.  Synthesises the most-recent L1
        percepts from all known agents into a coherent alignment picture:
        alignment_level ("aligned" | "at_risk" | "misaligned"), risk_factors,
        alignment_score.
        LLM task: ``sa_l2_comprehend``

    SA-L3 (Projection)
        Future-state reasoning.  Given the L2 comprehension, projects
        derailment_risk, alignment_trajectory, and recommended_contingency.
        Output-only enrichment — does not alter orchestration control flow.
        LLM task: ``sa_l3_project``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sstp.tomcore.llm import LLMClient
from sstp.ie.tom import TheoryOfMindEngineBase

LOGGER = logging.getLogger("ioc")

_PERCEPT_LIMIT = 10
_DISCOURSE_LIMIT = 10


class SAToMEngine(TheoryOfMindEngineBase):
    """Situation Awareness + Theory of Mind engine.

    Implements ``TheoryOfMindEngineBase`` using a three-level SA pipeline:
    every operation runs SA-L1 (Perception), then optionally SA-L2
    (Comprehension) and SA-L3 (Projection), storing results for use in
    subsequent calls.

    Parameters
    ----------
    llm:
        LLM client used for all ``sa_l1_perceive``, ``sa_l2_comprehend``,
        and ``sa_l3_project`` calls.
    dimensions:
        ToM dimension names (e.g. ``["trust", "urgency", ...]``).  Accepted
        for interface compatibility; SA-L1 drives dimension updates.
    combining_instruction:
        Pairwise-alignment combining rule.  Accepted for interface compat.
    domain_schema:
        Optional domain concept schema used by SA-L1 for LLM-based grounding.
        Must contain ``schema_id`` (URN) and ``domain_concepts`` / ``risk_concepts``
        lists of ``{"concept_id": str, "labels": [str, ...]}`` dicts.
        When provided, L1 grounds perceived elements against the schema concept
        labels and returns a ``grounded_elements`` list alongside the existing
        ``perceived_elements`` surface strings.  Falls back to the backend's
        built-in vocabulary when absent.
    """

    def __init__(
        self,
        llm: LLMClient,
        dimensions: List[str],
        combining_instruction: str,
        domain_schema: Optional[Dict[str, Any]] = None,
        enable_judge: bool = False,
    ) -> None:
        self.llm = llm
        self.dimensions = dimensions
        self.combining_instruction = combining_instruction
        self._domain_schema = domain_schema
        self._enable_judge = enable_judge
        # SA internal state
        self._l1_percepts: Dict[str, List[Dict[str, Any]]] = {}
        self._l2_situation: Dict[str, Any] = {}
        self._l3_projection: Dict[str, Any] = {}
        self._l2_judge: Dict[str, Any] = {}
        self._discourse_window: List[str] = []
        # Track latest view per agent for L3 agent_views
        self._latest_views: Dict[str, Dict[str, float]] = {}

    # ── SA-L1 helpers ─────────────────────────────────────────────────────────

    def _sa_l1(
        self,
        actor: str,
        utterance: str,
        task_goal: str,
        view: Dict[str, float],
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call SA-L1 (Perception) and return the raw LLM result.

        The *schema* parameter takes priority over ``self._domain_schema`` when
        provided — it carries the schema received from the peer's L9 header.
        """
        effective_schema = schema if schema is not None else self._domain_schema
        payload: Dict[str, Any] = {
            "actor": actor,
            "utterance": utterance,
            "task_goal": task_goal,
            "current_view": view,
        }
        if effective_schema:
            payload["schema_id"] = effective_schema.get("schema_id")
            payload["domain_schema"] = effective_schema
        return self.llm.complete_json("sa_l1_perceive", payload)

    def _store_percept(self, actor: str, percept: Dict[str, Any]) -> None:
        history = self._l1_percepts.setdefault(actor, [])
        history.append(percept)
        if len(history) > _PERCEPT_LIMIT:
            history[:] = history[-_PERCEPT_LIMIT:]

    # ── Assessment layer ──────────────────────────────────────────────────────

    @staticmethod
    def _sa_assess(l1: Dict[str, Any], l2: Dict[str, Any]) -> Dict[str, Any]:
        """Combine L1 percepts with the cached L2 comprehension into an alignment assessment.

        If L2 has confirmed a safety violation in the discourse
        (``blatant_error_detected``), that overrides the L1 signal — the
        situation is unsafe regardless of what tokens L1 perceived.
        Otherwise, L1 on-task signals (0.82) or absence thereof (0.40)
        combine with the L2 alignment score (60/40 split).
        """
        l2_score = float(l2.get("alignment_score", 0.5))

        if l2.get("blatant_error_detected", False):
            utterance_score = 0.12
            rationale = "l2_unsafe_pattern"
        elif l1.get("perceived_elements"):
            utterance_score = 0.82
            rationale = "in_scope_healthcare"
        else:
            utterance_score = 0.40
            rationale = "off_task_weak_signal"

        combined = round(max(0.0, min(1.0, 0.6 * utterance_score + 0.4 * l2_score)), 4)
        return {
            "alignment_score": combined,
            "aligned": combined >= 0.55,
            "rationale": rationale,
            "utterance_score": utterance_score,
        }

    # ── SA-L2 helpers ─────────────────────────────────────────────────────────

    def _sa_l2(self, task_goal: str, discourse: List[str]) -> Dict[str, Any]:
        """Call SA-L2 (Comprehension) using the latest percept per known agent."""
        agent_percepts = [
            {
                "agent_id": agent_id,
                "perceived_elements": history[-1].get("perceived_elements", []) if history else [],
                "state": self._latest_views.get(agent_id, {}),
            }
            for agent_id, history in self._l1_percepts.items()
            if history
        ]
        return self.llm.complete_json("sa_l2_comprehend", {
            "agent_percepts": agent_percepts,
            "task_goal": task_goal,
            "discourse_window": discourse[-6:],
        })

    def _sa_l2_for_pair(
        self,
        left_id: str,
        left_view: Dict[str, float],
        left_percepts: List[str],
        right_id: str,
        right_view: Dict[str, float],
        right_percepts: List[str],
        task_goal: str,
    ) -> Dict[str, Any]:
        """SA-L2 scoped to a single agent pair."""
        return self.llm.complete_json("sa_l2_comprehend", {
            "agent_percepts": [
                {"agent_id": left_id, "perceived_elements": left_percepts, "state": left_view},
                {"agent_id": right_id, "perceived_elements": right_percepts, "state": right_view},
            ],
            "task_goal": task_goal,
            "discourse_window": [],
        })

    # ── SA-L2 judge ───────────────────────────────────────────────────────────

    def _sa_l2_judge(self, l2_input: Dict[str, Any], l2_output: Dict[str, Any]) -> Dict[str, Any]:
        """Call SA-L2 judge to evaluate the correctness of an L2 comprehension output."""
        return self.llm.complete_json("sa_l2_judge", {
            "l2_input": l2_input,
            "l2_output": l2_output,
        })

    # ── SA-L3 helpers ─────────────────────────────────────────────────────────

    def _sa_l3(self, l2: Dict[str, Any], agent_views: Dict[str, Dict[str, float]], task_goal: str) -> Dict[str, Any]:
        """Call SA-L3 (Projection) from an L2 comprehension result."""
        return self.llm.complete_json("sa_l3_project", {
            "situation_summary": l2.get("situation_summary", ""),
            "l2_alignment_level": l2.get("alignment_level", "at_risk"),
            "agent_views": agent_views,
            "task_goal": task_goal,
        })

    # ── Dimension-delta application ────────────────────────────────────────────

    @staticmethod
    def _apply_deltas(view: Dict[str, float], state_deltas: Dict[str, Any]) -> Dict[str, float]:
        def _clamp(x: float) -> float:
            return max(0.0, min(1.0, x))

        updated = dict(view)
        for dim, delta_key in [
            ("trust", "trust_delta"),
            ("urgency", "urgency_delta"),
            ("cost_sensitivity", "cost_sensitivity_delta"),
            ("follow_through", "follow_through_delta"),
        ]:
            if dim in updated:
                delta = float(state_deltas.get(delta_key, 0.0))
                updated[dim] = round(_clamp(updated[dim] + delta), 4)
        return updated

    # ── TheoryOfMindEngineBase implementation ─────────────────────────────────

    def update(
        self,
        view: Dict[str, float],
        utterance: str,
        task_goal: str,
        actor: str = "agent",
    ) -> Dict[str, float]:
        """SA-L1 → SA-L2 → SA-L3 pipeline; return updated dimension view.

        SA-L1 applies dimension deltas from the perceived utterance.
        SA-L2 refreshes the global situation comprehension.
        SA-L3 refreshes the projection (output-only; no control-flow effect).
        """
        # SA-L1: perceive (raw signals only — no deltas, no interpretation)
        l1 = self._sa_l1(actor, utterance, task_goal, view)
        self._store_percept(actor, l1)

        # Update discourse window
        self._discourse_window.append(f"{actor}: {utterance}")
        if len(self._discourse_window) > _DISCOURSE_LIMIT:
            self._discourse_window[:] = self._discourse_window[-_DISCOURSE_LIMIT:]

        # SA-L2: comprehend (produces state_deltas based on full multi-agent picture)
        l2_input = {
            "agent_percepts": [
                {"agent_id": aid, "perceived_elements": h[-1].get("perceived_elements", []) if h else [], "state": self._latest_views.get(aid, {})}
                for aid, h in self._l1_percepts.items() if h
            ],
            "task_goal": task_goal,
            "discourse_window": self._discourse_window[-6:],
        }
        l2 = self._sa_l2(task_goal, self._discourse_window)
        self._l2_situation = l2

        # SA-L2 judge (observation-only)
        if self._enable_judge:
            self._l2_judge = self._sa_l2_judge(l2_input, l2)
            LOGGER.debug(
                "sa_tom.judge verdict=%s confidence=%.2f level_correct=%s error_correct=%s",
                self._l2_judge.get("verdict"),
                float(self._l2_judge.get("judge_confidence", 0.0)),
                self._l2_judge.get("alignment_level_correct"),
                self._l2_judge.get("error_detection_correct"),
            )

        # Apply dimension deltas from L2 comprehension
        state_deltas = l2.get("state_deltas", {})
        updated = self._apply_deltas(view, state_deltas)
        self._latest_views[actor] = updated

        # SA-L3: project
        l3 = self._sa_l3(l2, self._latest_views, task_goal)
        self._l3_projection = l3

        LOGGER.debug(
            "sa_tom.update actor=%s task_goal=%r utterance=%r "
            "perceived=%s l2_level=%s l2_flagged=%s l3_risk=%.4f view_after=%s",
            actor,
            task_goal,
            utterance,
            l1.get("perceived_elements", []),
            l2.get("alignment_level", "?"),
            l2.get("blatant_error_detected", False),
            float(l3.get("derailment_risk", 0.0)),
            updated,
        )
        return updated

    def assess_task_alignment(
        self, actor: str, task_goal: str, utterance: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """SA-L1 perception → assessment layer → alignment result.

        SA-L1 returns raw percepts only (perceived_elements, attention_cues,
        blatant_error_detected, state_deltas).  The assessment layer
        (_sa_assess) converts those percepts plus the cached SA-L2 situation
        score into an alignment score.  The two concerns are explicitly
        separated: L1 observes, the assessment layer judges.
        """
        # SA-L1: perception only — schema from wire takes priority over static domain_schema
        l1 = self._sa_l1(actor, utterance, task_goal, {}, schema=schema)

        # Assessment: combine L1 percepts with cached L2 comprehension
        assessment = self._sa_assess(l1, self._l2_situation)

        LOGGER.debug(
            "sa_tom.assess_task_alignment actor=%s perceived=%s "
            "utterance_score=%.2f l2_score=%.4f combined=%.4f",
            actor,
            l1.get("perceived_elements", []),
            assessment["utterance_score"],
            float(self._l2_situation.get("alignment_score", 0.5)),
            assessment["alignment_score"],
        )
        return {
            "actor": actor,
            "task_goal": task_goal,
            "aligned": assessment["aligned"],
            "alignment_score": assessment["alignment_score"],
            "rationale": assessment["rationale"],
            "tom_model": "sa",
            "sa_l1": {
                "perceived_elements": l1.get("perceived_elements", []),
                "attention_cues": l1.get("attention_cues", []),
                "grounded_elements": l1.get("grounded_elements", []),
                "utterance_score": assessment["utterance_score"],
            },
            "sa_l2_context": {
                "situation_summary": self._l2_situation.get("situation_summary", ""),
                "alignment_level": self._l2_situation.get("alignment_level", "unknown"),
                "alignment_score": float(self._l2_situation.get("alignment_score", 0.5)),
                "blatant_error_detected": self._l2_situation.get("blatant_error_detected", False),
                "blatant_error_phrase": self._l2_situation.get("blatant_error_phrase"),
                "judge": self._l2_judge if self._enable_judge else None,
            },
        }

    def analyze_inter_agent_tom(
        self,
        subject_view: Dict[str, float],
        left_view: Dict[str, float],
        right_view: Dict[str, float],
        task_goal: str,
    ) -> Dict[str, Any]:
        """SA-L2 + SA-L3 for a single agent pair.

        Returns the standard inter-agent dict (same top-level keys as v1/v2)
        enriched with ``sa_l2`` and ``sa_l3`` fields.
        """
        left_percepts = self._l1_percepts.get("left", [])
        right_percepts = self._l1_percepts.get("right", [])
        left_elements = left_percepts[-1].get("perceived_elements", []) if left_percepts else []
        right_elements = right_percepts[-1].get("perceived_elements", []) if right_percepts else []

        l2_input = {
            "agent_percepts": [
                {"agent_id": "left", "perceived_elements": left_elements, "state": left_view},
                {"agent_id": "right", "perceived_elements": right_elements, "state": right_view},
            ],
            "task_goal": task_goal,
            "discourse_window": [],
        }
        l2 = self._sa_l2_for_pair("left", left_view, left_elements, "right", right_view, right_elements, task_goal)
        l3 = self._sa_l3(l2, {"left": left_view, "right": right_view}, task_goal)

        judge = self._sa_l2_judge(l2_input, l2) if self._enable_judge else {}

        alignment_score = round(max(0.0, min(1.0, float(l2.get("alignment_score", 0.5)))), 4)
        disagreement = round(max(0.0, min(1.0, float(l2.get("disagreement_score", 1.0 - alignment_score)))), 4)

        left_alignment = self.assess_task_alignment("left", task_goal, str(left_elements))
        right_alignment = self.assess_task_alignment("right", task_goal, str(right_elements))

        LOGGER.info(
            "sa_tom.inter_agent task_goal=%r alignment=%.4f l2_level=%s l3_risk=%.4f",
            task_goal,
            alignment_score,
            l2.get("alignment_level", "?"),
            float(l3.get("derailment_risk", 0.0)),
        )
        return {
            "task_goal": task_goal,
            "left_view": left_view,
            "right_view": right_view,
            "subject_view": subject_view,
            "dimension_agreements": {},
            "alignment_score": alignment_score,
            "disagreement_score": disagreement,
            "task_alignment": {
                "left": left_alignment,
                "right": right_alignment,
            },
            "tom_model": "sa",
            "sa_l2": l2,
            "sa_l2_judge": judge,
            "sa_l3": l3,
        }

    def analyze_pairwise_agent_tom(
        self, agent_views: Dict[str, Dict[str, float]], task_goal: str
    ) -> Dict[str, Any]:
        """SA-L2 + SA-L3 across all agent pairs.

        Returns the standard pairwise dict enriched with ``sa_l2`` and
        ``sa_l3`` per pair.
        """
        pairwise: Dict[str, Any] = {}
        agents = sorted(agent_views.keys())

        for index, left in enumerate(agents):
            for right in agents[index + 1:]:
                left_view = agent_views[left]
                right_view = agent_views[right]

                left_hist = self._l1_percepts.get(left, [])
                right_hist = self._l1_percepts.get(right, [])
                left_elements = left_hist[-1].get("perceived_elements", []) if left_hist else []
                right_elements = right_hist[-1].get("perceived_elements", []) if right_hist else []

                l2_input = {
                    "agent_percepts": [
                        {"agent_id": left, "perceived_elements": left_elements, "state": left_view},
                        {"agent_id": right, "perceived_elements": right_elements, "state": right_view},
                    ],
                    "task_goal": task_goal,
                    "discourse_window": [],
                }
                l2 = self._sa_l2_for_pair(left, left_view, left_elements, right, right_view, right_elements, task_goal)
                l3 = self._sa_l3(l2, {left: left_view, right: right_view}, task_goal)

                judge = self._sa_l2_judge(l2_input, l2) if self._enable_judge else {}

                alignment_score = round(max(0.0, min(1.0, float(l2.get("alignment_score", 0.5)))), 4)
                disagreement = round(max(0.0, min(1.0, float(l2.get("disagreement_score", 1.0 - alignment_score)))), 4)

                left_alignment = self.assess_task_alignment(left, task_goal, str(left_elements))
                right_alignment = self.assess_task_alignment(right, task_goal, str(right_elements))

                pair_key = f"{left}<->{right}"
                pairwise[pair_key] = {
                    "task_goal": task_goal,
                    "alignment_score": alignment_score,
                    "disagreement_score": disagreement,
                    "dimension_agreements": {},
                    "left_view": left_view,
                    "right_view": right_view,
                    "task_alignment": {
                        "left": left_alignment,
                        "right": right_alignment,
                    },
                    "tom_model": "sa",
                    "sa_l2": l2,
                    "sa_l2_judge": judge,
                    "sa_l3": l3,
                }

        LOGGER.info("sa_tom.pairwise_agents task_goal=%r pairs=%d", task_goal, len(pairwise))
        return pairwise

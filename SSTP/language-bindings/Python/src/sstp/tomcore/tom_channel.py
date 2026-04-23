from __future__ import annotations

from typing import Any, Dict, List, Optional

from sstp.tomcore.cognition import TheoryOfMindEngine
from sstp.ie.tom import TOMPairChannelBase


class TOMPairChannel(TOMPairChannelBase):
    """TOM-based alignment/repair channel for one agent pair.

    Create one per pair where interaction-repair monitoring is desired and
    pass ``enabled=False`` to skip TOM for a pair while SSTP remains active
    for all agents unconditionally.

    When disabled every method returns a deterministic neutral result, so
    callers need no ``if channel.enabled:`` guards.
    """

    def __init__(
        self,
        agent_a: str,
        agent_b: str,
        tom_engine: TheoryOfMindEngine,
        *,
        enabled: bool = True,
    ) -> None:
        self.agent_a = agent_a
        self.agent_b = agent_b
        self.tom_engine = tom_engine
        self.enabled = enabled

    # ── Assessment ────────────────────────────────────────────────────────────

    def assess(
        self,
        speaker_view: Dict[str, Any],
        listener_view: Dict[str, Any],
        subject_view: Dict[str, Any],
        task_goal: str,
    ) -> Dict[str, Any]:
        """Return inter-agent TOM metrics, or a neutral stub if disabled."""
        if not self.enabled:
            return {
                "task_goal": task_goal,
                "left_view": speaker_view,
                "right_view": listener_view,
                "subject_view": subject_view,
                "dimension_agreements": {},
                "alignment_score": 0.5,
                "disagreement_score": 0.0,
                "task_alignment": {},
                "tom_enabled": False,
            }
        return {
            **self.tom_engine.analyze_inter_agent_tom(
                subject_view, speaker_view, listener_view, task_goal=task_goal
            ),
            "tom_enabled": True,
        }

    def assess_utterance(
        self,
        utterance: str,
        task_goal: str,
        speaker: str | None = None,
        listener: str | None = None,
        speaker_belief: Dict[str, Any] | None = None,
        history: List[str] | None = None,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return task-alignment assessment for a single utterance, or neutral stub if disabled."""
        if not self.enabled:
            return {
                "aligned": True, "alignment_score": 1.0, "disagreement_score": 0.0,
                "derailed": False, "derailment_cause": None,
                "ambiguous": False, "ambiguity_score": 0.0,
                "judge_confidence": 1.0, "critique": "tom_disabled",
            }
        if hasattr(self.tom_engine, "ie_utterance_judge"):
            return self.tom_engine.ie_utterance_judge(
                utterance=utterance,
                task_goal=task_goal,
                speaker=speaker or self.agent_a,
                listener=listener or self.agent_b,
                speaker_belief=speaker_belief or {},
                history=history,
            )
        # fallback for engines that don't implement ie_utterance_judge
        return self.tom_engine.assess_task_alignment(speaker or self.agent_a, task_goal, utterance, schema)

    # ── State update ──────────────────────────────────────────────────────────

    def update(
        self,
        view: Dict[str, Any],
        utterance: str,
        task_goal: str,
        actor: str = "peer_agent",
    ) -> Dict[str, Any]:
        """Update the TOM belief for the listener side; returns updated view. No-op if disabled."""
        if self.enabled:
            return self.tom_engine.update(view, utterance, task_goal=task_goal, actor=actor)
        return dict(view)

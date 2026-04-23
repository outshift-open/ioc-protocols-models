from __future__ import annotations

from typing import Any, Dict, Optional

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
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return task-alignment assessment for a single utterance, or neutral stub if disabled."""
        if not self.enabled:
            return {
                "actor": "peer_agent",
                "task_goal": task_goal,
                "aligned": True,
                "alignment_score": 1.0,
                "rationale": "tom_disabled",
                "tom_enabled": False,
            }
        return {
            **self.tom_engine.assess_task_alignment(
                actor="peer_agent", task_goal=task_goal, utterance=utterance, schema=schema
            ),
            "tom_enabled": True,
        }

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

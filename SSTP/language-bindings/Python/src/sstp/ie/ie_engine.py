# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/ie/ie_engine.py — Domain-agnostic Interaction Engine.

IEEngineConfig carries all domain-specific content as injectable data:
  - derailment_causes:        Dict[str, Sequence[str]]  — cause → utterance templates
  - nonsense_derailment_causes: Set[str]               — subset flagged as blatant errors
  - intent_keywords:          Dict[str, List[str]]      — intent_label → keyword list
  - role_bias_adjustments:    Dict[str, Dict[str, float]] — role → cause → score delta
  - repair_utterances:        Dict[str, str]            — contingency → repair text
  - normal_utterance_template: str                      — fallback normal-path utterance
  - nonsense_markers:         List[str]                 — substring markers for nonsense detection

IEEngine contains all the logic; zero domain strings are hard-coded.

The application defines a config constant and passes it at construction::

    MYAPP_IE_CONFIG = IEEngineConfig(
        derailment_causes={...},
        intent_keywords={...},
        ...
    )
    engine = IEEngine(config=MYAPP_IE_CONFIG, llm_client=llm)
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set


@dataclass
class IEEngineConfig:
    """All domain-specific content for an IEEngine instance.

    derailment_causes:
        Maps cause_id to a sequence of utterance template strings.
        Templates may contain {speaker}, {listener}, {contingency}, {task_goal}.

    nonsense_derailment_causes:
        Subset of derailment_causes keys that are classified as blatant errors
        (is_nonsense_utterance returns True for these regardless of content).

    intent_keywords:
        Maps intent_label to a list of keywords that trigger that label when
        found (case-insensitive) in an utterance.  Checked in order; first
        match wins.  "information_request" is the built-in fallback for "?" /
        "can you".  "acceptance_signal" checks yes/agree/ok/sounds good if
        not overridden.

    role_bias_adjustments:
        Maps role_id → {cause_id: delta} score adjustments applied on top of
        the confidence-based scoring in _select_derailment_cause.

    repair_utterances:
        Maps contingency → repair utterance template (supports {listener}).
        A "default" key is used as fallback.

    normal_utterance_template:
        Utterance returned on the normal (non-derailed) path when no
        contingency-specific template is defined.  Supports {listener}.

    nonsense_markers:
        Substring list; if any marker appears in an utterance (lowercase),
        is_nonsense_utterance returns True.
    """

    derailment_causes: Dict[str, Sequence[str]]
    nonsense_derailment_causes: Set[str] = field(default_factory=set)
    intent_keywords: Dict[str, List[str]] = field(default_factory=dict)
    role_bias_adjustments: Dict[str, Dict[str, float]] = field(default_factory=dict)
    repair_utterances: Dict[str, str] = field(default_factory=dict)
    normal_utterance_template: str = "{listener}, continue coordinated task execution."
    nonsense_markers: List[str] = field(default_factory=list)


class IEEngine:
    """Domain-agnostic Interaction Engine.

    Governs per-turn contingency assessment, utterance generation (normal and
    derailed paths), intent inference, and repair classification.  All
    domain-specific strings come from IEEngineConfig.

    The LLM client (optional) is used for the natural generation path in
    adaptive_agent_utterance; template fallback is used when absent or when
    the LLM returns an empty string.
    """

    def __init__(
        self,
        config: IEEngineConfig,
        llm_client: Any = None,
    ) -> None:
        self._config = config
        self.llm_client = llm_client
        self.turn_target_ms = 180

    # ── derailment helpers ────────────────────────────────────────────────────

    def _templates_for_cause(self, cause: str) -> tuple:
        raw = self._config.derailment_causes.get(cause)
        if isinstance(raw, str):
            return (raw,) if raw.strip() else ()
        if raw is not None:
            t = tuple(str(s) for s in raw if str(s).strip())
            return t if t else ()
        return ()

    def _select_derailment_cause(
        self,
        *,
        speaker: str,
        contingency: str,
        speaker_belief: Optional[Dict[str, Any]],
    ) -> str:
        available = {c for c in self._config.derailment_causes if self._templates_for_cause(c)}
        if not available:
            return next(iter(self._config.derailment_causes), "")
        if len(available) == 1:
            return next(iter(available))

        if speaker_belief is None:
            options = sorted(available)
            return random.choice(options)

        confidence = float(speaker_belief.get("confidence", 0.5))
        safety_blindness = max(0.0, 0.48 - confidence)
        cost_overfit = max(0.0, confidence - 0.68)
        urgency_overfit = max(0.0, confidence - 0.78)
        trust_drop = max(0.0, 0.5 - confidence)
        follow_overfit = max(0.0, confidence - 0.78)

        base_scores = {
            c: (0.04 + 0.96 * safety_blindness
                + 0.05 + 0.95 * cost_overfit
                + 0.12 + 0.7 * urgency_overfit
                + 0.1 + 0.8 * trust_drop
                + 0.1 + 0.65 * follow_overfit) / 5
            for c in available
        }

        if contingency in ("repair_alignment", "repair_anchor", "repair_hard_stop"):
            for c in available:
                base_scores[c] += 0.05
        elif contingency == "expedite_decision":
            for c in available:
                base_scores[c] += 0.04

        for c, delta in (self._config.role_bias_adjustments.get(speaker) or {}).items():
            if c in base_scores:
                base_scores[c] += delta

        candidates = [(c, max(0.02, base_scores[c]) + 0.04) for c in available]
        total = sum(w for _, w in candidates)
        threshold = random.random() * total
        cumulative = 0.0
        for c, w in candidates:
            cumulative += w
            if cumulative >= threshold:
                return c
        return candidates[-1][0]

    def _derailed_utterance(
        self,
        *,
        cause: str,
        speaker: str,
        listener: str,
        contingency: str,
        task_goal: str | None,
    ) -> str:
        templates = self._templates_for_cause(cause)
        if templates:
            template = random.choice(list(templates))
            return template.format(
                speaker=speaker,
                listener=listener,
                contingency=contingency,
                task_goal=task_goal or "task execution",
            )
        return (
            f"{listener}, I am pausing the current task to handle unrelated work."
        )

    def _normal_utterance(self, listener: str, contingency: str) -> str:
        repair_map = self._config.repair_utterances
        if contingency in repair_map:
            return repair_map[contingency].format(listener=listener)
        return self._config.normal_utterance_template.format(listener=listener)

    # ── public API ────────────────────────────────────────────────────────────

    def infer_intent(self, utterance: str) -> str:
        text = utterance.lower()
        if "?" in text or "can you" in text:
            return "information_request"
        for intent, keywords in self._config.intent_keywords.items():
            if any(kw in text for kw in keywords):
                return intent
        if any(token in text for token in ["yes", "agree", "ok", "sounds good"]):
            return "acceptance_signal"
        return "generic_turn"

    def maybe_repair(self, utterance: str) -> bool:
        return len(utterance.strip()) < 3 or utterance.strip().lower() in {"what?", "huh?"}

    def process_turn(self, speaker: str, utterance: str, message_number: int = 0) -> Dict[str, Any]:
        return {
            "speaker": speaker,
            "utterance": utterance,
            "inferred_intent": self.infer_intent(utterance),
            "timestamp_ms": int(time.time() * 1000) + self.turn_target_ms,
            "message_number": message_number,
            "repaired": self.maybe_repair(utterance),
        }

    def adaptive_contingency(
        self,
        alignment_score: float,
        disagreement: float,
        urgency: float,
        anchor_gap: float = 0.0,
        ema_alignment: float = 1.0,
        ambiguity_score: float = 0.0,
    ) -> str:
        if alignment_score < 0.30 or disagreement > 0.70:
            return "repair_hard_stop"
        if ambiguity_score > 0.60:
            return "request_clarification"
        if anchor_gap > 0.30:
            return "repair_anchor"
        if alignment_score < 0.55 or disagreement > 0.35 or ema_alignment < 0.55:
            return "repair_alignment"
        if urgency > 0.72:
            return "expedite_decision"
        return "normal_alignment"

    def adaptive_agent_utterance(
        self,
        listener: str,
        contingency: str,
        speaker: str | None = None,
        speaker_belief: Optional[Dict[str, Any]] = None,
        task_goal: str | None = None,
        history: List[str] | None = None,
        enable_derailment: bool = True,
        derail_probability: float = 0.0,
        prior_speaker_ie: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """Return (utterance, derailment_cause_or_None).

        ``prior_speaker_ie`` is the IEPayload dict from the most recent turn emitted
        by the *listener* (i.e. the agent that spoke before the current speaker).
        When supplied, the LLM receives the prior speaker's concept_ids and posterior
        so the response can explicitly engage those claims.
        """
        speaker_name = speaker or "peer_agent"

        if self.llm_client is not None:
            payload: Dict[str, Any] = {
                "speaker_role": speaker_name,
                "listener_role": listener,
                "contingency": contingency,
                "task_goal": task_goal or "task execution",
                "conversation_history": (history or [])[-6:],
                "speaker_belief": speaker_belief or {},
            }
            if prior_speaker_ie:
                # Structured context from the prior speaker's IEPayload so this agent
                # can explicitly engage the claim being made.
                _prior_utterance = prior_speaker_ie.get("utterance", {})
                _prior_belief = prior_speaker_ie.get("belief", {})
                payload["prior_speaker_context"] = {
                    "concept_ids": _prior_utterance.get("concept_ids", []),
                    "posterior": _prior_belief.get("posterior", 0.5),
                    "prior": _prior_belief.get("prior", 0.5),
                    "inferred_intent": _prior_utterance.get("inferred_intent", ""),
                    "content": _prior_utterance.get("content", ""),
                }
            result = self.llm_client.complete_json("tom_agent_utterance", payload)
            utterance = str(result.get("utterance", "")).strip()
            if utterance:
                _rationale = str(result.get("rationale", "")).strip()
                _thought = str(result.get("thought_summary", "")).strip()
                if _rationale:
                    utterance += f" | {_rationale}"
                if _thought:
                    utterance += f" | {_thought}"
                return utterance, None

        if enable_derailment and speaker_belief is not None:
            confidence = float(speaker_belief.get("confidence", 0.5))
            safety_blindness = max(0.0, 0.48 - confidence)
            cost_overfit = max(0.0, confidence - 0.68)
            urgency_overfit = max(0.0, confidence - 0.78)
            trust_drop = max(0.0, 0.5 - confidence)
            follow_overfit = max(0.0, confidence - 0.78)
            derail_score = (
                safety_blindness + cost_overfit + urgency_overfit + trust_drop + follow_overfit
            )
            if derail_score > 0.15 or random.random() < derail_probability:
                cause = self._select_derailment_cause(
                    speaker=speaker_name,
                    contingency=contingency,
                    speaker_belief=speaker_belief,
                )
                utterance = self._derailed_utterance(
                    cause=cause,
                    speaker=speaker_name,
                    listener=listener,
                    contingency=contingency,
                    task_goal=task_goal,
                )
                return utterance, cause

        return self._normal_utterance(listener, contingency), None

    def adaptive_repair_utterance(
        self,
        listener: str,
        contingency: str,
        listener_belief: Dict[str, Any],
    ) -> str:
        repair_map = self._config.repair_utterances
        if contingency in repair_map:
            return repair_map[contingency].format(listener=listener)
        return self._config.repair_utterances.get(
            "default", f"{listener}, remain within task scope."
        ).format(listener=listener)

    def is_nonsense_utterance(self, utterance: str, derailment_cause: str | None) -> bool:
        if derailment_cause in self._config.nonsense_derailment_causes:
            return True
        text = utterance.lower()
        return any(marker in text for marker in self._config.nonsense_markers)


__all__ = ["IEEngineConfig", "IEEngine"]

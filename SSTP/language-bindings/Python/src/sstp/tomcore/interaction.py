from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from sstp.tomcore.types import Turn

LOGGER = logging.getLogger("ioc")


class InteractionEngine:
    def __init__(self) -> None:
        self.turn_target_ms = 200
        self.derailment_causes: Dict[str, str] = {
            "policy_tangent": (
                "{listener}, before continuing this quote, we should revisit discount approval policy "
                "ownership and internal escalation rules."
            ),
            "data_drift": (
                "{listener}, I will inspect unrelated telemetry trends first and delay the active "
                "customer offer update."
            ),
            "scope_creep": (
                "{listener}, let's redesign CRM handoff workflow now and postpone the customer's "
                "pricing and delivery decision."
            ),
            "persona_break": (
                "{listener}, I will switch into market-analyst mode and pause VIN, inventory, and offer "
                "execution details."
            ),
            "topic_shift": (
                "{listener}, let's pause this offer and discuss generic process metrics instead of the "
                "customer's current purchase path."
            ),
        }

    def _normal_agent_utterance(self, listener: str, contingency: str) -> str:
        if contingency == "repair_alignment":
            return f"{listener}, please restate your pricing rationale and expected margin boundaries."
        if contingency == "expedite_decision":
            return f"{listener}, align to a fast-delivery offer with minimal negotiation cycles."
        return f"{listener}, continue with a budget-aligned offer update and inventory check."

    def _select_derailment_cause(
        self,
        *,
        speaker: str,
        contingency: str,
        speaker_tom: Optional[Dict[str, float]],
    ) -> str:
        if len(self.derailment_causes) == 1:
            return next(iter(self.derailment_causes))

        available = set(self.derailment_causes)
        if not available:
            return "data_drift"

        if speaker_tom is None:
            fallback_chain = [
                "data_drift" if contingency == "repair_alignment" else "scope_creep",
                "policy_tangent",
                "topic_shift",
            ]
            for cause in fallback_chain:
                if cause in available:
                    return cause
            return next(iter(self.derailment_causes))

        price_pressure = max(0.0, speaker_tom.get("price_sensitivity", 0.0) - 0.55)
        urgency_pressure = max(0.0, speaker_tom.get("urgency", 0.0) - 0.7)
        trust_drop = max(0.0, 0.55 - speaker_tom.get("trust", 0.6))
        budget_uncertainty = max(0.0, 0.52 - speaker_tom.get("budget_confidence", 0.5))
        buyer_signal_drop = max(0.0, 0.45 - speaker_tom.get("buy_intent", 0.0))

        scores = {
            "policy_tangent": 0.15 + 0.85 * trust_drop,
            "data_drift": 0.15 + 0.65 * budget_uncertainty,
            "scope_creep": 0.1 + 0.75 * urgency_pressure,
            "persona_break": 0.08 + 0.7 * buyer_signal_drop,
            "topic_shift": 0.08 + 0.7 * price_pressure,
        }

        if contingency == "repair_alignment":
            scores["policy_tangent"] += 0.15
            scores["data_drift"] += 0.1
        elif contingency == "expedite_decision":
            scores["scope_creep"] += 0.15
            scores["topic_shift"] += 0.1

        if speaker in {"sfdc"}:
            scores["topic_shift"] += 0.1
        if speaker in {"orchestrator"}:
            scores["policy_tangent"] += 0.08
        if speaker in {"fmc"}:
            scores["data_drift"] += 0.08

        candidate_scores = [(cause, score) for cause, score in scores.items() if cause in available]
        if not candidate_scores:
            return next(iter(self.derailment_causes))
        candidate_scores.sort(key=lambda item: (item[1], item[0]), reverse=True)
        return candidate_scores[0][0]

    def _derailed_agent_utterance(
        self,
        *,
        cause: str,
        speaker: str,
        listener: str,
        contingency: str,
        task_goal: str | None,
    ) -> str:
        template = self.derailment_causes.get(cause)
        if template:
            return template.format(
                speaker=speaker,
                listener=listener,
                contingency=contingency,
                task_goal=task_goal or "current sales objective",
            )
        return (
            f"{listener}, I am pausing this customer flow to handle unrelated process work before we "
            "finalize the active offer."
        )

    def infer_intent(self, utterance: str) -> str:
        text = utterance.lower()
        if "?" in text or "can you" in text:
            return "information_request"
        if any(token in text for token in ["too expensive", "cheaper", "discount"]):
            return "price_challenge"
        if any(token in text for token in ["yes", "accept", "sounds good", "let's do it"]):
            return "acceptance_signal"
        return "proposal_or_context"

    def maybe_repair(self, utterance: str) -> bool:
        return len(utterance.strip()) < 3 or utterance.strip().lower() in {"what?", "huh?"}

    def process_turn(self, speaker: str, utterance: str) -> Turn:
        inferred = self.infer_intent(utterance)
        repaired = self.maybe_repair(utterance)
        LOGGER.debug(
            "interaction.turn speaker=%s intent=%s repaired=%s utterance=%r",
            speaker,
            inferred,
            repaired,
            utterance,
        )
        return Turn(
            speaker=speaker,
            utterance=utterance,
            inferred_intent=inferred,
            timestamp_ms=int(time.time() * 1000) + self.turn_target_ms,
            repaired=repaired,
        )

    def _is_out_of_bound(self, utterance: str) -> bool:
        tokens = (
            "price",
            "discount",
            "offer",
            "inventory",
            "budget",
            "delivery",
            "warranty",
            "financing",
            "eta",
            "vin",
        )
        text = utterance.lower()
        return not any(token in text for token in tokens)

    def adaptive_contingency(
        self,
        alignment_score: float,
        disagreement: float,
        urgency: float,
    ) -> str:
        if alignment_score < 0.55 or disagreement > 0.35:
            return "repair_alignment"
        if urgency > 0.7:
            return "expedite_decision"
        return "normal_alignment"

    def adaptive_agent_utterance(
        self,
        listener: str,
        contingency: str,
        allow_derail: bool,
        speaker: str | None = None,
        speaker_tom: Optional[Dict[str, float]] = None,
        task_goal: str | None = None,
    ) -> tuple[str, bool, str | None]:
        if allow_derail:
            speaker_name = speaker or "peer_agent"
            cause = self._select_derailment_cause(
                speaker=speaker_name,
                contingency=contingency,
                speaker_tom=speaker_tom,
            )
            utterance = self._derailed_agent_utterance(
                cause=cause,
                speaker=speaker_name,
                listener=listener,
                contingency=contingency,
                task_goal=task_goal,
            )
            return utterance, True, cause

        utterance = self._normal_agent_utterance(listener=listener, contingency=contingency)
        return utterance, self._is_out_of_bound(utterance), None

    def adaptive_repair_utterance(
        self,
        listener: str,
        contingency: str,
        listener_tom: Dict[str, float],
    ) -> str:
        if contingency == "repair_alignment":
            if listener_tom.get("price_sensitivity", 0.0) > 0.6:
                return f"{listener}, re-anchor on customer budget and discount limits before continuing."
            return f"{listener}, re-anchor on intent and delivery timeline before continuing."
        if contingency == "expedite_decision":
            return f"{listener}, constrain response to delivery ETA and final offer terms only."
        return f"{listener}, continue within sales scope and keep response bounded to current offer context."

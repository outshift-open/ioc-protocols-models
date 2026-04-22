from __future__ import annotations

import logging
import random
from typing import Any, Dict, List

from sstp.tomcore.types import Turn
from sstp.tomcore.cognition import TheoryOfMindEngine
from sstp.tomcore.interaction import InteractionEngine
from sstp.tomcore.tom_channel import TOMPairChannel
from sstp.ie.l9 import build_l9_header

LOGGER = logging.getLogger("ioc")


class Orchestrator:
    def __init__(self, interaction: InteractionEngine) -> None:
        self.interaction = interaction

    def execute_turns(self, customer_utterances: List[str]) -> tuple[List[Turn], List[str]]:
        turns: List[Turn] = []
        log: List[str] = []
        LOGGER.info("orchestrator.turns_start utterances=%d", len(customer_utterances))

        for utterance in customer_utterances:
            customer_turn = self.interaction.process_turn("customer", utterance)
            turns.append(customer_turn)
            log.append(f"customer_turn:{customer_turn.inferred_intent}")

            if customer_turn.repaired:
                repair_turn = self.interaction.process_turn("orchestrator", "Could you clarify that?")
                repair_turn.repaired = True
                turns.append(repair_turn)
                log.append("repair_sequence:clarification_requested")
                LOGGER.info("orchestrator.repair_triggered utterance=%r", utterance)

        LOGGER.info("orchestrator.turns_complete turns=%d log_events=%d", len(turns), len(log))
        return turns, log

    def execute_recursive_peer_dialogue(
        self,
        tom_engine: TheoryOfMindEngine,
        customer_tom: Dict[str, float],
        task_goal: str,
        depth: int = 3,
        derail_probability: float = 0.18,
        start_message_number: int = 1,
    ) -> tuple[List[Turn], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        peer_turns: List[Turn] = []
        peer_interactions: List[Dict[str, Any]] = []
        log: List[str] = []
        out_of_bound_events: List[Dict[str, Any]] = []
        peer_alignment_events: List[Dict[str, Any]] = []
        message_number = max(1, start_message_number)

        agent_tom: Dict[str, Dict[str, float]] = {
            "orchestrator": {**customer_tom, "trust": min(1.0, customer_tom.get("trust", 0.6) + 0.05)},
            "fmc": {**customer_tom, "urgency": min(1.0, customer_tom.get("urgency", 0.5) + 0.1)},
            "sfdc": {
                **customer_tom,
                "budget_confidence": min(1.0, customer_tom.get("budget_confidence", 0.5) + 0.1),
                "price_sensitivity": max(0.0, customer_tom.get("price_sensitivity", 0.5) - 0.05),
            },
        }

        pair_sequence = [("orchestrator", "fmc"), ("fmc", "sfdc"), ("sfdc", "orchestrator")]

        # One TOMPairChannel per pair — set enabled=False on any channel to
        # disable TOM for that pair while SSTP remains active for all agents.
        channels = {
            f"{a}<->{b}": TOMPairChannel(a, b, tom_engine, enabled=True)
            for a, b in pair_sequence
        }

        def _alignment_score(value: Dict[str, Any]) -> float | None:
            raw_value = value.get("alignment_score") if isinstance(value, dict) else None
            if isinstance(raw_value, (int, float)):
                return max(0.0, min(1.0, float(raw_value)))
            return None

        def _risk_score(score: float | None, out_of_bound: bool) -> float:
            if out_of_bound:
                return 1.0
            if score is None:
                return 0.5
            return max(0.0, min(1.0, round(1.0 - score, 4)))

        for turn_depth in range(depth):
            for speaker, listener in pair_sequence:
                listener_state = agent_tom[listener]
                channel = channels[f"{speaker}<->{listener}"]
                speaker_view = {k: agent_tom[speaker].get(k, 0.0) for k in tom_engine.dimensions}
                listener_view = {k: listener_state.get(k, 0.0) for k in tom_engine.dimensions}
                pair_metrics = channel.assess(speaker_view, listener_view, listener_state, task_goal)
                contingency = self.interaction.adaptive_contingency(
                    alignment_score=pair_metrics["alignment_score"],
                    disagreement=pair_metrics["disagreement_score"],
                    urgency=listener_state.get("urgency", 0.5),
                )

                allow_derail = random.random() < derail_probability and turn_depth > 0
                utterance, out_of_bound, derailment_cause = self.interaction.adaptive_agent_utterance(
                    listener=listener,
                    contingency=contingency,
                    allow_derail=allow_derail,
                    speaker=speaker,
                    speaker_tom=agent_tom[speaker],
                    task_goal=task_goal,
                )
                alignment = channel.assess_utterance(utterance, task_goal)
                alignment_score = _alignment_score(alignment)
                peer_alignment_events.append(
                    {
                        "depth": turn_depth,
                        "speaker": speaker,
                        "listener": listener,
                        "task_goal": task_goal,
                        "contingency": contingency,
                        "alignment": alignment,
                        "derailment_cause": derailment_cause,
                    }
                )
                peer_turn = self.interaction.process_turn(speaker, utterance)
                peer_turns.append(peer_turn)
                current_message_number = message_number
                log.append(f"peer_turn:{speaker}->{listener}:{contingency}")
                peer_l9_header = build_l9_header(
                    use_case="fmc",
                    tenant_id="ioc-demo-sales",
                    sensitivity="internal",
                    event_type="peer_turn",
                    sender=speaker,
                    receiver=listener,
                    timestamp_ms=peer_turn.timestamp_ms,
                    sequence_number=current_message_number,
                    turn_depth=turn_depth,
                    utterance=utterance,
                    confidence_score=alignment_score,
                    risk_score=_risk_score(alignment_score, out_of_bound),
                )
                peer_interactions.append(
                    {
                        "type": "peer_turn",
                        "event": "message",
                        "depth": turn_depth,
                        "speaker": speaker,
                        "listener": listener,
                        "message_number": current_message_number,
                        "task_goal": task_goal,
                        "contingency": contingency,
                        "utterance": utterance,
                        "out_of_bound": out_of_bound,
                        "repair_required": out_of_bound,
                        "derailment_cause": derailment_cause,
                        "alignment": alignment,
                        "l9_header": peer_l9_header,
                    }
                )
                message_number += 1

                if out_of_bound:
                    event = {
                        "depth": turn_depth,
                        "speaker": speaker,
                        "listener": listener,
                        "utterance": utterance,
                        "contingency": contingency,
                        "derailment_cause": derailment_cause,
                    }
                    out_of_bound_events.append(event)
                    if derailment_cause:
                        log.append(f"peer_derail:{speaker}->{listener}:{derailment_cause}")
                    else:
                        log.append(f"peer_derail:{speaker}->{listener}")
                    LOGGER.warning(
                        "peer_dialogue.derail depth=%d speaker=%s listener=%s cause=%s",
                        turn_depth,
                        speaker,
                        listener,
                        derailment_cause,
                    )
                    repair_required_l9_header = build_l9_header(
                        use_case="fmc",
                        tenant_id="ioc-demo-sales",
                        sensitivity="internal",
                        event_type="repair_required",
                        sender=speaker,
                        receiver=listener,
                        timestamp_ms=peer_turn.timestamp_ms,
                        sequence_number=current_message_number,
                        turn_depth=turn_depth,
                        utterance=utterance,
                        parent_ids=[peer_l9_header["message_id"]],
                        confidence_score=alignment_score,
                        risk_score=1.0,
                    )
                    peer_interactions.append(
                        {
                            "type": "repair_required",
                            "event": "repair_required",
                            "depth": turn_depth,
                            "speaker": speaker,
                            "listener": listener,
                            "trigger_message_number": current_message_number,
                            "trigger": {
                                "utterance": utterance,
                                "derailment_cause": derailment_cause,
                                "contingency": contingency,
                            },
                            "repair_required": True,
                            "repair_strategy": "re-anchor_to_budget_margin_timeline",
                            "l9_header": repair_required_l9_header,
                        }
                    )
                    repair = self.interaction.adaptive_repair_utterance(
                        listener=speaker,
                        contingency="repair_alignment",
                        listener_tom=agent_tom[speaker],
                    )
                    repair_turn = self.interaction.process_turn(listener, repair)
                    repair_turn.repaired = True
                    peer_turns.append(repair_turn)
                    repair_alignment = channel.assess_utterance(repair, task_goal)
                    repair_alignment_score = _alignment_score(repair_alignment)
                    log.append(f"peer_repair:{listener}->{speaker}")
                    peer_interactions.append(
                        {
                            "type": "peer_repair",
                            "event": "repair_applied",
                            "depth": turn_depth,
                            "speaker": listener,
                            "listener": speaker,
                            "message_number": message_number,
                            "task_goal": task_goal,
                            "contingency": "repair_alignment",
                            "utterance": repair,
                            "out_of_bound": False,
                            "repair_required": False,
                            "derailment_cause": derailment_cause,
                            "repair_strategy": "re-anchor_to_budget_margin_timeline",
                            "triggered_by": {
                                "message_number": current_message_number,
                                "speaker": speaker,
                                "listener": listener,
                                "utterance": utterance,
                                "derailment_cause": derailment_cause,
                            },
                            "alignment": repair_alignment,
                            "l9_header": build_l9_header(
                                use_case="fmc",
                                tenant_id="ioc-demo-sales",
                                sensitivity="internal",
                                event_type="repair_applied",
                                sender=listener,
                                receiver=speaker,
                                timestamp_ms=repair_turn.timestamp_ms,
                                sequence_number=message_number,
                                turn_depth=turn_depth,
                                utterance=repair,
                                parent_ids=[repair_required_l9_header["message_id"]],
                                confidence_score=repair_alignment_score,
                                risk_score=_risk_score(repair_alignment_score, False),
                            ),
                        }
                    )
                    message_number += 1

                actor_label = "peer_agent" if speaker != "customer" else "customer"
                channel.update(agent_tom[listener], utterance, task_goal, actor=actor_label)

        pairwise_summary = tom_engine.analyze_pairwise_agent_tom(
            agent_tom,
            task_goal=task_goal,
        )
        return peer_turns, peer_interactions, pairwise_summary, out_of_bound_events, peer_alignment_events, log

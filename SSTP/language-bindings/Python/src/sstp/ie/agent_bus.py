# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/ie/agent_bus.py — Domain-agnostic per-episode L9 message bus.

AgentBus is parameterised at construction with use_case and sensitivity
so any application can instantiate it without subclassing.

All interactions are peer-wise peer_turn events.  There is no privileged
coordinator role in IE.  Task delegation uses speech_act=task_handoff at
task_phase=transition; results use speech_act=belief_assertion at
task_phase=taskwork; errors use speech_act=help_request at
task_phase=interpersonal.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sstp.epistemic import SpeechAct, TaskPhase, BeliefStatus, make_epistemic_block
from sstp.epistemic.vocabulary import RepairReason
from sstp.ie.grounding import diagnose_repair_reason
from sstp.ie.l9 import build_l9_header


class AgentBus:
    """Per-episode L9 message bus shared by all agents in a session.

    Parameters
    ----------
    use_case:    domain label written into every L9 header (e.g. "healthcare")
    sensitivity: sensitivity label; defaults to "internal"
    """

    def __init__(
        self,
        run_id: str,
        conversation_id: str,
        use_case: str,
        sensitivity: str = "internal",
    ) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.use_case = use_case
        self.sensitivity = sensitivity
        self.messages: List[Dict[str, Any]] = []
        self._seq_counters: Dict[str, int] = {}

    def _next_sequence(self, actor_id: str) -> Dict[str, Any]:
        n = self._seq_counters.get(actor_id, 0)
        self._seq_counters[actor_id] = n + 1
        return {"counter": n, "actor_id": actor_id}

    def emit_peer_turn(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        speech_act: SpeechAct,
        task_phase: TaskPhase,
        parent_id: str | None = None,
        episode_id: str | None = None,
        turn_depth: int | None = None,
        kind_override: str | None = None,
        error: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """Emit a peer_turn with explicit epistemic annotation.

        All agent-to-agent interactions are peer_turns.  The speech_act and
        task_phase carry the role of this turn — delegation, result, error,
        or social repair — without privileging either party.
        """
        header = build_l9_header(
            use_case=self.use_case,
            event_type="peer_turn",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=utterance,
            parent_ids=[parent_id] if parent_id else None,
            episode_id=episode_id,
            turn_depth=turn_depth,
            kind_override=kind_override,
            epistemic=make_epistemic_block(
                speech_act=speech_act,
                task_phase=task_phase,
            ),
            state_sequence=self._next_sequence(sender),
        )
        envelope = self._wrap(header, "peer_turn", sender, receiver, utterance)
        if error is not None:
            envelope["error"] = error
        self.messages.append(envelope)
        return header

    def emit_request(self, *, sender: str, receiver: str, utterance: str,
                     episode_id: str | None = None, turn_depth: int | None = None,
                     epistemic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.TASK_HANDOFF, task_phase=TaskPhase.TRANSITION,
                                   episode_id=episode_id, turn_depth=turn_depth)

    def emit_response(self, *, sender: str, receiver: str, utterance: str,
                      parent_id: str | None = None, episode_id: str | None = None,
                      turn_depth: int | None = None,
                      epistemic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.BELIEF_ASSERTION, task_phase=TaskPhase.TASKWORK,
                                   parent_id=parent_id, episode_id=episode_id, turn_depth=turn_depth)

    def emit_error(self, *, sender: str, receiver: str, error_type: str, error_message: str,
                   traceback: str | None = None, parent_id: str | None = None,
                   epistemic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        error_record: Dict[str, Any] = {"type": error_type, "message": error_message}
        if traceback is not None:
            error_record["traceback"] = traceback
        return self.emit_peer_turn(sender=sender, receiver=receiver,
                                   utterance=f"error:{error_type}",
                                   speech_act=SpeechAct.HELP_REQUEST, task_phase=TaskPhase.INTERPERSONAL,
                                   parent_id=parent_id, error=error_record)

    def emit_semantic_repair(
        self,
        *,
        sender: str,
        receiver: str,
        target_message_id: str,
        repair_reason: RepairReason,
        target_epistemic: Optional[Dict[str, Any]] = None,
        episode_id: str | None = None,
        turn_depth: int | None = None,
    ) -> Dict[str, Any]:
        repair_scope = list(
            (target_epistemic or {}).get("scope", [])
            or (target_epistemic or {}).get("addresses_evidence", [])
        )
        header = build_l9_header(
            use_case=self.use_case,
            event_type="repair_required",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=f"repair_required:reason={repair_reason.value}:target={target_message_id}",
            parent_ids=[target_message_id],
            episode_id=episode_id,
            turn_depth=turn_depth,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.HELP_REQUEST,
                task_phase=TaskPhase.INTERPERSONAL,
                belief_status=BeliefStatus.CHALLENGED,
                scope=repair_scope or ["grounding"],
                repair_reason=repair_reason,
            ),
            state_sequence=self._next_sequence(sender),
        )
        envelope = self._wrap(
            header, "repair_required", sender, receiver,
            f"repair_required:reason={repair_reason.value}",
        )
        envelope["repair"] = {
            "target_message_id": target_message_id,
            "repair_reason": repair_reason.value,
        }
        self.messages.append(envelope)
        return header

    def check_and_repair(
        self,
        *,
        sender: str,
        prior_message_epistemic: Optional[Dict[str, Any]],
        response_epistemic: Optional[Dict[str, Any]],
        response_message_id: str,
        episode_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        reason = diagnose_repair_reason(prior_message_epistemic, response_epistemic)
        if reason is None:
            return None
        return self.emit_semantic_repair(
            sender=sender,
            receiver=response_message_id,
            target_message_id=response_message_id,
            repair_reason=reason,
            target_epistemic=prior_message_epistemic,
            episode_id=episode_id,
        )

    def emit_epistemic_clarification(
        self,
        *,
        sender: str,
        receiver: str,
        target_message_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        header = build_l9_header(
            use_case=self.use_case,
            event_type="epistemic_clarification",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=f"epistemic_clarification:{reason}",
            parent_ids=[target_message_id],
            state_sequence=self._next_sequence(sender),
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.HELP_REQUEST,
                task_phase=TaskPhase.INTERPERSONAL,
                belief_status=BeliefStatus.DEFERRED,
            ),
        )
        self.messages.append(self._wrap(
            header, "epistemic_clarification", sender, receiver,
            f"epistemic_clarification:{reason}",
        ))
        return header

    def _wrap(
        self,
        header: Dict[str, Any],
        event_type: str,
        sender: str,
        receiver: str,
        utterance: str,
    ) -> Dict[str, Any]:
        return {
            **header,
            "payload": {
                "run_id": self.run_id,
                "conversation_id": self.conversation_id,
                "phase": "peer_dialogue",
                "event_type": event_type,
                "sender": sender,
                "receiver": receiver,
                "message": {"utterance": utterance},
            },
        }


__all__ = ["AgentBus"]

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/examples/hcpanel/agent_bus.py — Per-episode L9 message bus for hcpanel.

MessageBus is the domain-agnostic base.  HCPanelAgentBus is the
healthcare-specialised subclass used by the hcpanel application.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple

from SSTP.subprotocol.siep.src.epistemic.stores import BeliefRevision, CommonGround
from SSTP.subprotocol.siep.src.epistemic.vocabulary import (
    SpeechAct, EpistemicState, BeliefStatus, make_epistemic_block, RepairReason,
)
from SSTP.subprotocol.cip.src.builder import build_l9_header
from SSTP.subprotocol.siep.src.panel import NetworkHandle


class ProtocolViolation(RuntimeError):
    """Raised when application code attempts to emit a lifecycle kind directly."""


def get_cip_repair(header: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the cip-repair payload content from an L9 header, or None."""
    for part in header.get("payload") or []:
        if part.get("type") == "cip-repair":
            return part.get("content")
    return None


def _is_lifecycle_kind(kind_override: str) -> bool:
    base = kind_override.split(":")[0]
    return base in ("intent", "commit")


class MessageBus(NetworkHandle):
    """Per-episode L9 message bus shared by all agents in a session."""

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
        self._current_phase: str = "taskwork"
        self._taskwork_store: Optional[Any] = None
        self._protocol_context: bool = False
        self._handlers: Dict[str, Any] = {}
        self._max_delivery_attempts: int = 3
        self._dead_letter: List[Dict[str, Any]] = []
        self.specialist_l9s: Dict[str, Any] = {}
        # Structured message identity counters (scoped to this session)
        self._session_id: str = run_id
        self._episode_seq: int = 0
        self._msg_seq: int = 0
        self._episode_registry: Dict[str, int] = {}

    @contextmanager
    def _lifecycle_emit(self) -> Generator[None, None, None]:
        prev = self._protocol_context
        self._protocol_context = True
        try:
            yield
        finally:
            self._protocol_context = prev

    def register_handler(self, agent_id: str, handler: Any) -> None:
        self._handlers[agent_id] = handler

    def get_handler(self, agent_id: str) -> Optional[Any]:
        return self._handlers.get(agent_id)

    def _deliver(self, header: Dict[str, Any]) -> None:
        import logging as _log
        ps = header.get("participants") or {}
        actors = ps.get("actors") or []
        if not actors:
            return
        sender_id = actors[0].get("id", "") if actors else ""
        msg_id = (header.get("message") or {}).get("id", "")
        episode_id = (header.get("message") or {}).get("episode")

        for actor in actors[1:]:
            recipient_id = actor.get("id", "")
            if not recipient_id or recipient_id == sender_id:
                continue
            handler = self._handlers.get(recipient_id)
            if handler is None:
                _log.getLogger(__name__).warning(
                    "message_bus.no_handler recipient=%s msg_id=%s", recipient_id, msg_id
                )
                self._dead_letter.append({
                    "message_id": msg_id, "recipient_id": recipient_id,
                    "reason": "no_handler",
                })
                try:
                    self.emit_semantic_repair(
                        sender=sender_id, receiver=recipient_id,
                        target_message_id=msg_id,
                        repair_reason=RepairReason.DELIVERY_FAILURE,
                        episode_id=episode_id,
                    )
                except Exception:
                    pass
                continue

            # Emit a WIRE received record so the trace shows each inbound message
            # from the recipient's perspective, immediately before handler dispatch.
            _recv_utt = f"received:{msg_id.split(':')[-1] if ':' in msg_id else msg_id}"
            _recv_header = build_l9_header(
                use_case=self.use_case,
                event_type="peer_turn",
                sender=recipient_id,
                receiver=sender_id,
                timestamp_ms=int(time.time() * 1000),
                sensitivity=self.sensitivity,
                utterance=_recv_utt,
                parent_ids=[msg_id] if msg_id else None,
                episode_id=episode_id,
                kind_override="exchange",
                payload_parts=[{
                    "type": "utterance", "location": "inline",
                    "content": _recv_utt,
                    "rationale": f"received from {sender_id}",
                }],
            )
            self.messages.append(_recv_header)

            delivered = False
            last_exc: "Optional[BaseException]" = None
            for attempt in range(1, self._max_delivery_attempts + 1):
                try:
                    handler(header)
                    delivered = True
                    break
                except Exception as exc:
                    _log.getLogger(__name__).warning(
                        "message_bus.deliver attempt=%d recipient=%s error=%s",
                        attempt, recipient_id, exc,
                    )
                    last_exc = exc

            if not delivered:
                self._dead_letter.append({
                    "message_id": msg_id, "recipient_id": recipient_id,
                    "reason": "handler_exhausted", "error": str(last_exc),
                })
                try:
                    self.emit_semantic_repair(
                        sender=sender_id, receiver=recipient_id,
                        target_message_id=msg_id,
                        repair_reason=RepairReason.DELIVERY_FAILURE,
                        episode_id=episode_id,
                    )
                except Exception:
                    pass

    @property
    def debate_trace(self) -> List[Dict[str, Any]]:
        return [m for m in self.messages if m.get("subprotocol") == "SIEP"]

    def emit_peer_turn(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        speech_act: SpeechAct,
        epistemic_state: EpistemicState,
        parent_id: "str | None" = None,
        episode_id: "str | None" = None,
        kind_override: "str | None" = None,
        error: "Optional[Dict[str, Any]]" = None,
        epistemic: "Optional[Dict[str, Any]]" = None,
        topic: "str | None" = None,
        ie_payload: "Any | None" = None,
        rationale: str = "",
        thought_summary: str = "",
        role: "str | None" = None,
        recipients: "List[str] | None" = None,
        **_: Any,
    ) -> Dict[str, Any]:
        if kind_override and _is_lifecycle_kind(kind_override) and not self._protocol_context:
            raise ProtocolViolation(
                f"kind_override={kind_override!r} is a lifecycle kind and may only be "
                f"set by the subprotocol layer."
            )
        _epistemic = epistemic or make_epistemic_block(
            speech_act=speech_act,
            epistemic_state=epistemic_state,
        )
        _utt_part: Dict[str, Any] = {"type": "utterance", "location": "inline", "content": utterance}
        if rationale:
            _utt_part["rationale"] = rationale
        if thought_summary:
            _utt_part["thought_summary"] = thought_summary
        _payload_parts: List[Dict[str, Any]] = [_utt_part]
        if ie_payload is not None:
            _payload_parts.append(
                {"type": "cip", "location": "inline", "content": ie_payload.to_dict()}
            )
        _recipients = recipients if recipients is not None else (
            [receiver] if receiver and receiver != sender else []
        )
        _eid = episode_id or ""
        _msg_id, _, _seq = self._next_msg_id(_eid)
        # Encode parents as intra-episode msg_seq integers
        _parent_ids: "List[Any] | None" = None
        if parent_id:
            if ":msg:" in parent_id:
                try:
                    _parent_ids = [int(parent_id.split(":msg:")[-1])]
                except ValueError:
                    _parent_ids = [parent_id]
            else:
                _parent_ids = [parent_id]
        header = build_l9_header(
            use_case=self.use_case,
            event_type="peer_turn",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=utterance,
            parent_ids=_parent_ids,
            episode_id=episode_id,
            kind_override=kind_override,
            epistemic=_epistemic,
            topic=topic,
            payload_parts=_payload_parts,
            role=role,
            recipients=_recipients,
            message_id=_msg_id,
        )
        if error is not None:
            header["error"] = error
        self.messages.append(header)
        self._deliver(header)
        return header

    def emit_request(self, *, sender: str, receiver: str, utterance: str,
                     episode_id: "str | None" = None,
                     epistemic: "Optional[Dict[str, Any]]" = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   episode_id=episode_id)

    def emit_response(self, *, sender: str, receiver: str, utterance: str,
                      parent_id: "str | None" = None, episode_id: "str | None" = None,
                      epistemic: "Optional[Dict[str, Any]]" = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   parent_id=parent_id, episode_id=episode_id)

    def emit_error(self, *, sender: str, receiver: str, error_type: str, error_message: str,
                   traceback: "str | None" = None, parent_id: "str | None" = None,
                   epistemic: "Optional[Dict[str, Any]]" = None) -> Dict[str, Any]:
        error_record: Dict[str, Any] = {"type": error_type, "message": error_message}
        if traceback is not None:
            error_record["traceback"] = traceback
        return self.emit_peer_turn(sender=sender, receiver=receiver,
                                   utterance=f"error:{error_type}",
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   parent_id=parent_id, error=error_record)

    def emit_semantic_repair(
        self,
        *,
        sender: str,
        receiver: str,
        target_message_id: str,
        repair_reason: "RepairReason | str",
        target_epistemic: "Optional[Dict[str, Any]]" = None,
        episode_id: "str | None" = None,
    ) -> Dict[str, Any]:
        from SSTP.subprotocol.cip.src.builder import get_topic
        _repair_topic = get_topic({"topic": None, "epistemic": target_epistemic}) if target_epistemic else None
        _reason_str = repair_reason.value if isinstance(repair_reason, RepairReason) else str(repair_reason)
        _utterance = f"repair_required:reason={_reason_str}:target={target_message_id}"
        header = build_l9_header(
            use_case=self.use_case,
            event_type="repair_required",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            parent_ids=[target_message_id],
            episode_id=episode_id,
            topic=_repair_topic,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                belief_status=BeliefStatus.CHALLENGED,
            ),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
            ],
        )
        header["payload"].append({
            "type": "cip-repair",
            "location": "inline",
            "content": {
                "target_message_id": target_message_id,
                "repair_reason": _reason_str,
            },
        })
        self.messages.append(header)
        self._deliver(header)
        return header

    def emit_epistemic_clarification(
        self,
        *,
        sender: str,
        receiver: str,
        target_message_id: str,
        reason: str,
        episode_id: "str | None" = None,
    ) -> Dict[str, Any]:
        _utterance = f"epistemic_clarification:{reason}"
        header = build_l9_header(
            use_case=self.use_case,
            event_type="epistemic_clarification",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            parent_ids=[target_message_id],
            episode_id=episode_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                belief_status=BeliefStatus.DEFERRED,
            ),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
            ],
        )
        self.messages.append(header)
        self._deliver(header)
        return header

    def _next_msg_id(self, episode_id: str) -> Tuple[str, str, int]:
        """Return (message_id_urn, episode_urn, msg_seq) for the next message in episode_id."""
        if episode_id not in self._episode_registry:
            self._episode_seq += 1
            self._episode_registry[episode_id] = self._episode_seq
        ep_seq = self._episode_registry[episode_id]
        phase = self._current_phase  # "team_process" | "taskwork" | "task"
        self._msg_seq += 1
        ep_urn = f"urn:session:{self._session_id}:phase:{phase}:episode:{ep_seq}"
        msg_urn = f"{ep_urn}:msg:{self._msg_seq}"
        return msg_urn, ep_urn, self._msg_seq

    def receive_peer_turn(
        self,
        envelope: Dict[str, Any],
        *,
        replica: "Optional[Any]" = None,
        belief_store: "Optional[Any]" = None,
        common_ground_store: "Optional[Any]" = None,
        use_case: str = "",
    ) -> "Optional[Dict[str, Any]]":
        from SSTP.subprotocol.cip.src.grounding import contingency_check, diagnose_repair_reason
        from SSTP.subprotocol.cip.src.message import get_part

        header = {k: v for k, v in envelope.items() if k != "payload"}
        ie_content = get_part(envelope, "cip")
        grounding = ie_content.get("grounding") or {}
        utterance = ie_content.get("utterance") or {}
        belief = ie_content.get("belief") or {}

        parents = (header.get("message") or {}).get("parents") or []
        prior_turn_mid = parents[0] if parents else None
        prior_epistemic: Optional[Dict[str, Any]] = None
        prior_ie_concept_ids: List[str] = []
        prior_ie_addresses_evidence: List[str] = []
        if prior_turn_mid and replica is not None:
            for e in getattr(replica, "_entries", []):
                if e.message_id == prior_turn_mid:
                    prior_epistemic = e.epistemic or {}
                    prior_ie_concept_ids = list(getattr(e, "ie_concept_ids", []))
                    prior_ie_addresses_evidence = list(getattr(e, "ie_addresses_evidence", []))
                    break

        current_ie_concept_ids = list(utterance.get("evidence") or utterance.get("concept_ids") or [])
        current_ie_addresses_evidence = list(utterance.get("addresses_evidence") or [])
        current_epistemic = header.get("epistemic") or {}

        verified, score = contingency_check(
            prior_epistemic, current_epistemic,
            a_ie_concept_ids=prior_ie_concept_ids,
            a_ie_addresses_evidence=prior_ie_addresses_evidence,
            b_ie_concept_ids=current_ie_concept_ids,
            b_ie_addresses_evidence=current_ie_addresses_evidence,
        )

        ie_content = dict(ie_content)
        ie_content["grounding"] = {**grounding, "contingency_verified": verified, "contingency_score": score}

        if replica is not None:
            replica.apply(header, payload=ie_content)

        if verified:
            from SSTP.subprotocol.cip.src.builder import get_topic
            ep_concept_id = get_topic(header) or ""
            if belief_store is not None and ep_concept_id:
                sender = ((header.get("participants") or {}).get("actors") or header.get("actors") or [{}])[0].get("id", "unknown")
                ep_id = (header.get("message") or {}).get("episode", "")
                revision = BeliefRevision(
                    cause=belief.get("revision_cause") or "grounded_argument",
                    confidence_before=float(belief.get("prior", 0.5)),
                    confidence_after=float(belief.get("posterior", 0.5)),
                    caused_by_agent=None,
                    argument_concept_ids=list(utterance.get("evidence") or utterance.get("concept_ids", [])),
                    episode_id=ep_id,
                )
                belief_store.record_revision(sender, ep_concept_id, use_case or self.use_case, ep_id,
                                             revision, new_status="asserted",
                                             new_public_confidence=float(belief.get("posterior", 0.5)))
            if common_ground_store is not None:
                sender = ((header.get("participants") or {}).get("actors") or header.get("actors") or [{}])[0].get("id", "unknown")
                ep = header.get("epistemic") or {}
                prior_sender = ""
                if prior_epistemic and prior_turn_mid and replica is not None:
                    for e in getattr(replica, "_entries", []):
                        if e.message_id == prior_turn_mid:
                            prior_sender = e.sender
                            break
                cg = CommonGround(
                    holder_id=prior_sender, confirmer_id=sender, concept_id=ep_concept_id,
                    use_case=use_case or self.use_case,
                    episode_id=(header.get("message") or {}).get("episode", ""),
                    grounding_confidence=score, holder_confidence=float(belief.get("prior", 0.5)),
                    confirmer_confidence=float(belief.get("posterior", 0.5)),
                    contingency_verified=True, speech_acts=[ep.get("message_act", "")],
                    grounding_message_ids=[prior_turn_mid or "", header["message"]["id"]],
                    formed_at_ms=int(time.time() * 1000),
                )
                common_ground_store.record(cg)
            return None
        else:
            repair_reason = diagnose_repair_reason(prior_epistemic, current_epistemic)
            if repair_reason is None:
                repair_reason = RepairReason.GROUNDING_FAILURE
            sender_id = self.run_id
            return self.emit_semantic_repair(
                sender=sender_id,
                receiver=((header.get("participants") or {}).get("actors") or header.get("actors") or [{}])[0].get("id", "unknown"),
                target_message_id=header["message"]["id"],
                repair_reason=repair_reason,
                target_epistemic=current_epistemic,
                episode_id=(header.get("message") or {}).get("episode"),
            )

    def emit_task_assignment(self, *, sender: str, receiver: str, utterance: str,
                              parent_id: "str | None" = None, episode_id: "str | None" = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
                                   parent_id=parent_id, episode_id=episode_id)

    def emit_taskwork_result(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        concept_id: "str | None" = None,
        posterior: "float | None" = None,
        parent_id: "str | None" = None,
        episode_id: "str | None" = None,
        rationale: str = "",
        thought_summary: str = "",
    ) -> Dict[str, Any]:
        _uncertainty = round(1.0 - posterior, 4) if posterior is not None else 0.5
        epistemic = make_epistemic_block(
            speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TASKWORK,
            belief_status=BeliefStatus.ASSERTED, uncertainty=_uncertainty,
        )
        return self.emit_peer_turn(
            sender=sender, receiver=receiver, utterance=utterance,
            speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TASKWORK,
            parent_id=parent_id, episode_id=episode_id, epistemic=epistemic,
            topic=concept_id, rationale=rationale, thought_summary=thought_summary,
        )

    def _emit_episode_open(self, *, coordinator: str, subject: str, episode_id: "str | None" = None,
                            rationale: str = "", thought_summary: str = "",
                            team_process: "Dict[str, Any] | None" = None,
                            recipients: "List[str] | None" = None) -> Dict[str, Any]:
        _utterance = f"session:open subject={subject}"
        _utt_part: Dict[str, Any] = {"type": "utterance", "location": "inline", "content": _utterance}
        if rationale:
            _utt_part["rationale"] = rationale
        if thought_summary:
            _utt_part["thought_summary"] = thought_summary
        _payload_parts: List[Dict[str, Any]] = [_utt_part]
        if team_process:
            _payload_parts.append({"type": "team_process", "location": "inline", "content": team_process})
        _epistemic = make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS)
        with self._lifecycle_emit():
            header = build_l9_header(
                use_case=self.use_case, event_type="peer_turn",
                sender=coordinator, receiver=coordinator, timestamp_ms=int(time.time() * 1000),
                sensitivity=self.sensitivity, utterance=_utterance,
                episode_id=episode_id, kind_override="intent",
                epistemic=_epistemic, payload_parts=_payload_parts,
                recipients=recipients or [],
            )
        self.messages.append(header)
        self._deliver(header)
        return header

    def _emit_episode_close(self, *, coordinator: str, subject: str, accepted: bool,
                             episode_id: "str | None" = None, rationale: str = "",
                             thought_summary: str = "",
                             summary: "Dict[str, Any] | None" = None,
                             recipients: "List[str] | None" = None) -> Dict[str, Any]:
        _outcome = "commit:converged" if accepted else "commit:rejected"
        _utterance = f"session:close subject={subject} accepted={accepted}"
        payload_parts: List[Dict[str, Any]] = [{"type": "utterance", "location": "inline", "content": _utterance}]
        if rationale:
            payload_parts[0]["rationale"] = rationale
        if thought_summary:
            payload_parts[0]["thought_summary"] = thought_summary
        if summary:
            payload_parts.append({"type": "team_process", "location": "inline", "content": summary})
        _epistemic = make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS)
        with self._lifecycle_emit():
            header = build_l9_header(
                use_case=self.use_case, event_type="peer_turn",
                sender=coordinator, receiver=coordinator, timestamp_ms=int(time.time() * 1000),
                sensitivity=self.sensitivity, utterance=_utterance,
                episode_id=episode_id, kind_override=_outcome,
                epistemic=_epistemic, payload_parts=payload_parts,
                recipients=recipients or [],
            )
        self.messages.append(header)
        self._deliver(header)
        return header

    def emit_grounding_phase_ready(self, *, sender: str, episode_id: "str | None" = None) -> Dict[str, Any]:
        _utterance = f"grounding:ready sender={sender}"
        epistemic = make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                         belief_status=BeliefStatus.ASSERTED, uncertainty=0.0)
        with self._lifecycle_emit():
            return self.emit_peer_turn(sender=sender, receiver=sender, utterance=_utterance,
                                       speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                       kind_override="commit:ready", episode_id=episode_id, epistemic=epistemic)

    def emit_grounding_phase_converged(self, *, coordinator: str, episode_id: "str | None" = None,
                                        coordination_summary: "Dict[str, Any] | None" = None,
                                        recipients: "List[str] | None" = None,
                                        rationale: str = "",
                                        thought_summary: str = "") -> Dict[str, Any]:
        _status = (coordination_summary or {}).get("coordination_status", "aligned")
        _utterance = f"grounding:converged status={_status}"
        _utt_part: Dict[str, Any] = {"type": "utterance", "location": "inline", "content": _utterance}
        if rationale:
            _utt_part["rationale"] = rationale
        if thought_summary:
            _utt_part["thought_summary"] = thought_summary
        payload_parts: List[Dict[str, Any]] = [_utt_part]
        if coordination_summary:
            payload_parts.append({"type": "team_process", "location": "inline", "content": coordination_summary})
        _epistemic = make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
                                          belief_status=BeliefStatus.ASSERTED, uncertainty=0.0)
        with self._lifecycle_emit():
            header = build_l9_header(
                use_case=self.use_case, event_type="peer_turn",
                sender=coordinator, receiver=coordinator, timestamp_ms=int(time.time() * 1000),
                sensitivity=self.sensitivity, utterance=_utterance,
                episode_id=episode_id, kind_override="commit:converged",
                epistemic=_epistemic, payload_parts=payload_parts,
                recipients=recipients or [],
            )
        self.messages.append(header)
        self._deliver(header)
        return header

    def emit_taskwork_phase_intent(self, *, coordinator: str, subject: str,
                                    episode_id: "str | None" = None,
                                    coordination_summary: "Dict[str, Any] | None" = None,
                                    role: "str | None" = None,
                                    recipients: "List[str] | None" = None,
                                    patient_complaint: "Dict[str, Any] | None" = None) -> Dict[str, Any]:
        _utterance = f"taskwork:open subject={subject}"
        payload_parts: List[Dict[str, Any]] = [{"type": "utterance", "location": "inline", "content": _utterance}]
        if patient_complaint:
            _complaint_text = "; ".join(patient_complaint.get("chat_history") or [])
            _symptoms = ", ".join(patient_complaint.get("symptoms") or [])
            _meds = ", ".join(patient_complaint.get("medications") or [])
            _complaint_utterance = (
                f"patient:{subject} symptoms=[{_symptoms}] medications=[{_meds}]"
                + (f" complaint: {_complaint_text}" if _complaint_text else "")
            )
            payload_parts.append({
                "type": "utterance",
                "location": "inline",
                "content": _complaint_utterance,
                "rationale": "Patient intake establishing the clinical question for this episode.",
                "thought_summary": f"Case {subject}: {_symptoms or 'see complaint'} on {_meds or 'current medications'}.",
            })
        if coordination_summary:
            payload_parts.append({"type": "team_process", "location": "inline", "content": coordination_summary})
        _epistemic = make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
                                          belief_status=BeliefStatus.ASSERTED, uncertainty=0.0)
        _recipients = recipients or []
        with self._lifecycle_emit():
            header = build_l9_header(
                use_case=self.use_case, event_type="peer_turn",
                sender=coordinator, receiver=coordinator, timestamp_ms=int(time.time() * 1000),
                sensitivity=self.sensitivity, utterance=_utterance,
                episode_id=episode_id, kind_override="intent",
                epistemic=_epistemic, payload_parts=payload_parts,
                role=role, recipients=_recipients,
            )
        self.messages.append(header)
        self._deliver(header)
        return header

    def emit_repair_resolved(self, *, sender: str, receiver: str, utterance: str,
                              parent_id: "str | None" = None, episode_id: "str | None" = None) -> Dict[str, Any]:
        with self._lifecycle_emit():
            return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                       speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                       parent_id=parent_id, episode_id=episode_id, kind_override="commit:resolved")

    def emit_knowledge_rule(self, *, coordinator: str, concept_id: str, posterior: float,
                             gar: float, scr: float, provenance_weight: float,
                             episode_id: "str | None" = None) -> Dict[str, Any]:
        _utterance = (f"rule_update:{concept_id}:posterior={posterior:.4f}"
                      f":gar={gar:.4f}:scr={scr:.4f}:provenance_weight={provenance_weight:.4f}")
        header = build_l9_header(
            use_case=self.use_case, event_type="rule_update",
            sender=coordinator, receiver=coordinator, timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity, utterance=_utterance, episode_id=episode_id, topic=concept_id,
            epistemic=make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                                           belief_status=BeliefStatus.ASSERTED),
            payload_parts=[{"type": "utterance", "location": "inline", "content": _utterance}],
        )
        self.messages.append(header)
        self._deliver(header)
        return header

    def emit_grounding_turn(
        self,
        *,
        speaker: str,
        listener: str,
        utterance: str,
        concept_id: "str | None" = None,
        prior: float = 0.5,
        posterior: float = 0.5,
        revision_cause: str = "grounded_argument",
        evidence: "List[str] | None" = None,
        addresses_evidence: "List[str] | None" = None,
        ring_round: int = 0,
        repair_depth: int = 0,
        parent_id: "str | None" = None,
        episode_id: "str | None" = None,
        rationale: str = "",
        thought_summary: str = "",
        role: "str | None" = None,
        recipients: "List[str] | None" = None,
    ) -> Dict[str, Any]:
        from SSTP.subprotocol.cip.src.message import IEPayload, IEUtteranceBlock, IEGroundingBlock, IEBeliefBlock
        ie_payload = IEPayload(
            utterance=IEUtteranceBlock(evidence=list(evidence or []), addresses_evidence=list(addresses_evidence or []), ring_round=ring_round, repair_depth=repair_depth),
            grounding=IEGroundingBlock(),
            belief=IEBeliefBlock(prior=prior, posterior=posterior, revision_cause=revision_cause),
        )
        epistemic = make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                         belief_status=BeliefStatus.ASSERTED, uncertainty=round(1.0 - posterior, 4))
        return self.emit_peer_turn(
            sender=speaker, receiver=listener, utterance=utterance,
            speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
            parent_id=parent_id, episode_id=episode_id, topic=concept_id,
            epistemic=epistemic, ie_payload=ie_payload,
            rationale=rationale, thought_summary=thought_summary, role=role, recipients=recipients,
        )

    def _emit_intent(self, *, sender: str, receiver: "str | None", subject: str,
                     episode_id: "str | None" = None, team_prior: "Dict[str, Any] | None" = None,
                     team_process: "Dict[str, Any] | None" = None, rationale: str = "",
                     thought_summary: str = "", role: "str | None" = None,
                     recipients: "List[str] | None" = None) -> Dict[str, Any]:
        _utterance = f"episode:open subject={subject}"
        _utt_part: Dict[str, Any] = {"type": "utterance", "location": "inline", "content": _utterance}
        if rationale:
            _utt_part["rationale"] = rationale
        if thought_summary:
            _utt_part["thought_summary"] = thought_summary
        payload_parts: List[Dict[str, Any]] = [_utt_part]
        if team_prior:
            payload_parts.append({"type": "team_prior", "location": "inline", "content": team_prior})
        if team_process:
            payload_parts.append({"type": "team_process", "location": "inline", "content": team_process})
        _receiver = receiver or sender
        _recipients = recipients if recipients is not None else ([_receiver] if _receiver != sender else [])
        with self._lifecycle_emit():
            header = build_l9_header(
                use_case=self.use_case, event_type="peer_turn",
                sender=sender, receiver=_receiver, timestamp_ms=int(time.time() * 1000),
                sensitivity=self.sensitivity, utterance=_utterance,
                episode_id=episode_id, kind_override="intent",
                epistemic=make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
                                               belief_status=BeliefStatus.ASSERTED),
                payload_parts=payload_parts, role=role, recipients=_recipients,
            )
        self.messages.append(header)
        self._deliver(header)
        return header

    def _emit_exchange_ready(self, *, speaker: str, listener: "str | None", utterance: str,
                              posterior: float, concept_id: "str | None" = None,
                              evidence: "List[str] | None" = None,
                              addresses_evidence: "List[str] | None" = None,
                              parent_id: "str | None" = None, episode_id: "str | None" = None,
                              rationale: str = "", thought_summary: str = "") -> Dict[str, Any]:
        epistemic = make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                         belief_status=BeliefStatus.ASSERTED, uncertainty=round(1.0 - posterior, 4))
        return self.emit_peer_turn(sender=speaker, receiver=listener or speaker, utterance=utterance,
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   parent_id=parent_id, episode_id=episode_id, kind_override="exchange:ready",
                                   topic=concept_id, epistemic=epistemic, rationale=rationale,
                                   thought_summary=thought_summary)

    def _emit_ready(self, *, sender: str, receiver: "str | None", posterior: float,
                    concept_id: "str | None" = None, parent_id: "str | None" = None,
                    episode_id: "str | None" = None) -> Dict[str, Any]:
        _utterance = f"ready posterior={posterior:.4f}"
        epistemic = make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                         belief_status=BeliefStatus.ASSERTED, uncertainty=round(1.0 - posterior, 4))
        with self._lifecycle_emit():
            return self.emit_peer_turn(sender=sender, receiver=receiver or sender, utterance=_utterance,
                                       speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                       parent_id=parent_id, episode_id=episode_id, kind_override="commit:ready",
                                       topic=concept_id, epistemic=epistemic)

    def _emit_knowledge_announcement(self, *, sender: str, concept_id: str, posterior: float,
                                      gar: float, scr: float, provenance_weight: float,
                                      commit_message_id: str = "",
                                      revision_cause: str = "converged_episode",
                                      episode_id: "str | None" = None) -> Dict[str, Any]:
        _utterance = (f"knowledge:{concept_id}:posterior={posterior:.4f}"
                      f":gar={gar:.4f}:scr={scr:.4f}:provenance_weight={provenance_weight:.4f}")
        _eid = episode_id or ""
        _msg_id, _, _ = self._next_msg_id(_eid)
        header = build_l9_header(
            use_case=self.use_case, event_type="peer_turn",
            sender=sender, receiver=sender, timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity, utterance=_utterance,
            parent_ids=[], episode_id=episode_id,
            kind_override="knowledge", topic=concept_id,
            message_id=_msg_id,
            epistemic=make_epistemic_block(speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                                           belief_status=BeliefStatus.ASSERTED, uncertainty=round(1.0 - posterior, 4)),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
                {"type": "knowledge", "location": "inline", "content": {
                    "concept_id": concept_id,
                    "source": commit_message_id,
                    "posterior": posterior,
                    "gar": gar, "scr": scr, "provenance_weight": provenance_weight,
                    "revision_cause": revision_cause,
                }},
            ],
        )
        self.messages.append(header)
        self._deliver(header)
        return header


# Backward-compat alias — existing `from agent_bus import AgentBus` imports still work
AgentBus = MessageBus


# ── HCPanelAgentBus ───────────────────────────────────────────────────────────


class HCPanelAgentBus(MessageBus):
    """Healthcare-specialised agent bus for the hcpanel application."""

    def __init__(self, run_id: str, conversation_id: str) -> None:
        super().__init__(
            run_id=run_id,
            conversation_id=conversation_id,
            use_case="healthcare",
            sensitivity="internal",
        )
        self.taskwork_episode_id: str = ""

    def emit_peer_turn(self, *, episode_id: "str | None" = None, **kwargs: Any) -> Dict[str, Any]:
        return super().emit_peer_turn(
            episode_id=episode_id or self.taskwork_episode_id or None,
            **kwargs,
        )


__all__ = ["MessageBus", "AgentBus", "HCPanelAgentBus", "ProtocolViolation", "get_cip_repair"]

class HealthcareAgentBus(MessageBus):
    def __init__(self, run_id: str, conversation_id: str) -> None:
        super().__init__(
            run_id=run_id,
            conversation_id=conversation_id,
            use_case="healthcare",
            sensitivity="internal",
        )
        # Set by MultiAgentHealthcareSystem.run_session() before graph.invoke() so that
        # domain agent bus calls (which do not carry episode_id) land on the correct
        # taskwork episode rather than falling back to the shared_dialogue state token.
        self.taskwork_episode_id: str = ""

    def emit_peer_turn(self, *, episode_id: str | None = None, **kwargs: Any) -> Dict[str, Any]:
        return super().emit_peer_turn(
            episode_id=episode_id or self.taskwork_episode_id or None,
            **kwargs,
        )

class HCPanelAgentBus(HealthcareAgentBus):
    """HCPanel bus — adds public lifecycle wrappers for the two-phase episode structure."""

    def emit_episode_open(self, *, coordinator: str, subject: str, episode_id: str,
                           recipients: "List[str] | None" = None) -> Dict[str, Any]:
        """kind=intent team_process — opens an episode (team-process or outer session)."""
        return self._emit_episode_open(coordinator=coordinator, subject=subject, episode_id=episode_id,
                                       recipients=recipients)

    def emit_episode_close(self, *, coordinator: str, subject: str, episode_id: str,
                            accepted: bool = True,
                            recipients: "List[str] | None" = None) -> Dict[str, Any]:
        """kind=commit:converged — closes an episode."""
        return self._emit_episode_close(coordinator=coordinator, subject=subject,
                                        episode_id=episode_id, accepted=accepted,
                                        recipients=recipients)

    def emit_taskwork_open(self, *, coordinator: str, subject: str, episode_id: str,
                            recipients: "List[str] | None" = None,
                            patient_complaint: "Dict[str, Any] | None" = None) -> Dict[str, Any]:
        """kind=intent taskwork — opens the taskwork assessment episode."""
        return self.emit_taskwork_phase_intent(coordinator=coordinator, subject=subject,
                                               episode_id=episode_id, recipients=recipients,
                                               patient_complaint=patient_complaint)

    def emit_team_process_close(self, *, coordinator: str, episode_id: str,
                                 role_count: int = 0,
                                 recipients: "List[str] | None" = None,
                                 rationale: str = "",
                                 thought_summary: str = "") -> Dict[str, Any]:
        """kind=commit:converged team_process — closes the team-process episode."""
        return self.emit_grounding_phase_converged(
            coordinator=coordinator, episode_id=episode_id,
            coordination_summary={"coordination_status": "aligned", "role_count": role_count},
            recipients=recipients,
            rationale=rationale,
            thought_summary=thought_summary,
        )


__all__ = ["HCPanelAgentBus"]

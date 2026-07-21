# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/base/emit.py — L9 wire-message construction as free functions.

All emit_* and _emit_* functions take a NetworkHandle as their first
positional argument (named ``net``) and end with ``net.send(header)``.
The episode layer calls these; the bus knows nothing about L9 vocabulary.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, TYPE_CHECKING

from SSTP.subprotocol.siep.src.epistemic.stores import CommonGround
from SSTP.subprotocol.siep.src.epistemic.vocabulary import (
    SpeechAct, EpistemicState, BeliefStatus, make_epistemic_block, RepairReason,
)
from SSTP.subprotocol.cip.src.builder import build_l9_header

if TYPE_CHECKING:
    from SSTP.subprotocol.siep.src.panel import NetworkHandle


class ProtocolViolation(RuntimeError):
    """Raised when application code attempts to emit a lifecycle kind directly."""


def _is_lifecycle_kind(kind_override: str) -> bool:
    base = kind_override.split(":")[0]
    return base in ("intent", "commit")


@contextmanager
def _lifecycle_emit(net: "NetworkHandle") -> Generator[None, None, None]:
    """Context manager that allows lifecycle kind emission on net."""
    prev = getattr(net, "_protocol_context", False)
    try:
        net._protocol_context = True  # type: ignore[attr-defined]
        yield
    finally:
        net._protocol_context = prev  # type: ignore[attr-defined]


# ── Core peer turn ────────────────────────────────────────────────────────────


def emit_peer_turn(
    net: "NetworkHandle",
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
    subprotocol: "str | None" = None,
    **_: Any,
) -> Dict[str, Any]:
    if kind_override and _is_lifecycle_kind(kind_override) and not getattr(net, "_protocol_context", False):
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
    # taskwork_episode_id fallback — set on MessageBus when opening a taskwork episode
    _eid = episode_id or getattr(net, "taskwork_episode_id", None) or ""
    _msg_id, _, _seq = net._next_msg_id(_eid)  # type: ignore[attr-defined]
    _parent_ids: "List[Any] | None" = None
    if parent_id:
        if ":msg:" in parent_id:
            try:
                _parent_ids = [int(parent_id.split(":msg:")[-1])]
            except ValueError:
                _parent_ids = [parent_id]
        else:
            _parent_ids = [parent_id]
    _build_kwargs: Dict[str, Any] = dict(
        use_case=net.use_case,  # type: ignore[attr-defined]
        event_type="peer_turn",
        sender=sender,
        receiver=receiver,
        timestamp_ms=int(time.time() * 1000),
        sensitivity=net.sensitivity,  # type: ignore[attr-defined]
        utterance=utterance,
        parent_ids=_parent_ids,
        episode_id=_eid or None,
        kind_override=kind_override,
        epistemic=_epistemic,
        topic=topic,
        payload_parts=_payload_parts,
        role=role,
        recipients=_recipients,
        message_id=_msg_id,
    )
    if subprotocol is not None:
        _build_kwargs["subprotocol"] = subprotocol
    header = build_l9_header(**_build_kwargs)
    if error is not None:
        header["error"] = error
    net.send(header)
    return header


# ── Convenience wrappers ──────────────────────────────────────────────────────


def emit_request(
    net: "NetworkHandle",
    *,
    sender: str,
    receiver: str,
    utterance: str,
    episode_id: "str | None" = None,
    epistemic: "Optional[Dict[str, Any]]" = None,
) -> Dict[str, Any]:
    return emit_peer_turn(
        net, sender=sender, receiver=receiver, utterance=utterance,
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        episode_id=episode_id,
    )


def emit_response(
    net: "NetworkHandle",
    *,
    sender: str,
    receiver: str,
    utterance: str,
    parent_id: "str | None" = None,
    episode_id: "str | None" = None,
    epistemic: "Optional[Dict[str, Any]]" = None,
) -> Dict[str, Any]:
    return emit_peer_turn(
        net, sender=sender, receiver=receiver, utterance=utterance,
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        parent_id=parent_id, episode_id=episode_id,
    )


def emit_error(
    net: "NetworkHandle",
    *,
    sender: str,
    receiver: str,
    error_type: str,
    error_message: str,
    traceback: "str | None" = None,
    parent_id: "str | None" = None,
    epistemic: "Optional[Dict[str, Any]]" = None,
) -> Dict[str, Any]:
    error_record: Dict[str, Any] = {"type": error_type, "message": error_message}
    if traceback is not None:
        error_record["traceback"] = traceback
    return emit_peer_turn(
        net, sender=sender, receiver=receiver,
        utterance=f"error:{error_type}",
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        parent_id=parent_id, error=error_record,
    )


def emit_semantic_repair(
    net: "NetworkHandle",
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
        use_case=net.use_case,  # type: ignore[attr-defined]
        event_type="repair_required",
        sender=sender,
        receiver=receiver,
        timestamp_ms=int(time.time() * 1000),
        sensitivity=net.sensitivity,  # type: ignore[attr-defined]
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
    net.send(header)
    return header


def emit_epistemic_clarification(
    net: "NetworkHandle",
    *,
    sender: str,
    receiver: str,
    target_message_id: str,
    reason: str,
    episode_id: "str | None" = None,
) -> Dict[str, Any]:
    _utterance = f"epistemic_clarification:{reason}"
    header = build_l9_header(
        use_case=net.use_case,  # type: ignore[attr-defined]
        event_type="epistemic_clarification",
        sender=sender,
        receiver=receiver,
        timestamp_ms=int(time.time() * 1000),
        sensitivity=net.sensitivity,  # type: ignore[attr-defined]
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
    net.send(header)
    return header


def emit_task_assignment(
    net: "NetworkHandle",
    *,
    sender: str,
    receiver: str,
    utterance: str,
    parent_id: "str | None" = None,
    episode_id: "str | None" = None,
) -> Dict[str, Any]:
    return emit_peer_turn(
        net, sender=sender, receiver=receiver, utterance=utterance,
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
        parent_id=parent_id, episode_id=episode_id,
    )


def emit_taskwork_result(
    net: "NetworkHandle",
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
    return emit_peer_turn(
        net, sender=sender, receiver=receiver, utterance=utterance,
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TASKWORK,
        parent_id=parent_id, episode_id=episode_id, epistemic=epistemic,
        topic=concept_id, rationale=rationale, thought_summary=thought_summary,
    )


def emit_grounding_phase_ready(
    net: "NetworkHandle",
    *,
    sender: str,
    episode_id: "str | None" = None,
) -> Dict[str, Any]:
    _utterance = f"grounding:ready sender={sender}"
    epistemic = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        belief_status=BeliefStatus.ASSERTED, uncertainty=0.0,
    )
    with _lifecycle_emit(net):
        return emit_peer_turn(
            net, sender=sender, receiver=sender, utterance=_utterance,
            speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
            kind_override="commit:ready", episode_id=episode_id, epistemic=epistemic,
        )


def emit_grounding_phase_converged(
    net: "NetworkHandle",
    *,
    coordinator: str,
    episode_id: "str | None" = None,
    coordination_summary: "Dict[str, Any] | None" = None,
    recipients: "List[str] | None" = None,
    rationale: str = "",
    thought_summary: str = "",
) -> Dict[str, Any]:
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
    _epistemic = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
        belief_status=BeliefStatus.ASSERTED, uncertainty=0.0,
    )
    with _lifecycle_emit(net):
        header = build_l9_header(
            use_case=net.use_case,  # type: ignore[attr-defined]
            event_type="peer_turn",
            sender=coordinator, receiver=coordinator,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=net.sensitivity,  # type: ignore[attr-defined]
            utterance=_utterance,
            episode_id=episode_id, kind_override="commit:converged",
            epistemic=_epistemic, payload_parts=payload_parts,
            recipients=recipients or [],
            subprotocol="SIEP",
        )
    net.send(header)
    return header


def emit_taskwork_phase_intent(
    net: "NetworkHandle",
    *,
    coordinator: str,
    subject: str,
    episode_id: "str | None" = None,
    coordination_summary: "Dict[str, Any] | None" = None,
    role: "str | None" = None,
    recipients: "List[str] | None" = None,
    patient_complaint: "Dict[str, Any] | None" = None,
) -> Dict[str, Any]:
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
    _epistemic = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
        belief_status=BeliefStatus.ASSERTED, uncertainty=0.0,
    )
    with _lifecycle_emit(net):
        header = build_l9_header(
            use_case=net.use_case,  # type: ignore[attr-defined]
            event_type="peer_turn",
            sender=coordinator, receiver=coordinator,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=net.sensitivity,  # type: ignore[attr-defined]
            utterance=_utterance,
            episode_id=episode_id, kind_override="intent",
            epistemic=_epistemic, payload_parts=payload_parts,
            role=role, recipients=recipients or [],
            subprotocol="SIEP",
        )
    net.send(header)
    return header


def emit_repair_resolved(
    net: "NetworkHandle",
    *,
    sender: str,
    receiver: str,
    utterance: str,
    parent_id: "str | None" = None,
    episode_id: "str | None" = None,
) -> Dict[str, Any]:
    with _lifecycle_emit(net):
        return emit_peer_turn(
            net, sender=sender, receiver=receiver, utterance=utterance,
            speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
            parent_id=parent_id, episode_id=episode_id, kind_override="commit:resolved",
        )


def emit_knowledge_rule(
    net: "NetworkHandle",
    *,
    coordinator: str,
    concept_id: str,
    posterior: float,
    gar: float,
    scr: float,
    provenance_weight: float,
    episode_id: "str | None" = None,
) -> Dict[str, Any]:
    _utterance = (
        f"rule_update:{concept_id}:posterior={posterior:.4f}"
        f":gar={gar:.4f}:scr={scr:.4f}:provenance_weight={provenance_weight:.4f}"
    )
    header = build_l9_header(
        use_case=net.use_case,  # type: ignore[attr-defined]
        event_type="rule_update",
        sender=coordinator, receiver=coordinator,
        timestamp_ms=int(time.time() * 1000),
        sensitivity=net.sensitivity,  # type: ignore[attr-defined]
        utterance=_utterance, episode_id=episode_id, topic=concept_id,
        subprotocol="SIEP",
        epistemic=make_epistemic_block(
            speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TASKWORK,
            belief_status=BeliefStatus.ASSERTED,
        ),
        payload_parts=[{"type": "utterance", "location": "inline", "content": _utterance}],
    )
    net.send(header)
    return header


def emit_grounding_turn(
    net: "NetworkHandle",
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
        utterance=IEUtteranceBlock(
            evidence=list(evidence or []),
            addresses_evidence=list(addresses_evidence or []),
            ring_round=ring_round,
            repair_depth=repair_depth,
        ),
        grounding=IEGroundingBlock(),
        belief=IEBeliefBlock(prior=prior, posterior=posterior, revision_cause=revision_cause),
    )
    epistemic = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        belief_status=BeliefStatus.ASSERTED, uncertainty=round(1.0 - posterior, 4),
    )
    return emit_peer_turn(
        net, sender=speaker, receiver=listener, utterance=utterance,
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        parent_id=parent_id, episode_id=episode_id, topic=concept_id,
        epistemic=epistemic, ie_payload=ie_payload,
        rationale=rationale, thought_summary=thought_summary,
        role=role, recipients=recipients,
    )


# ── Private lifecycle emitters ────────────────────────────────────────────────


def _emit_episode_open(
    net: "NetworkHandle",
    *,
    coordinator: str,
    subject: str,
    episode_id: "str | None" = None,
    rationale: str = "",
    thought_summary: str = "",
    team_process: "Dict[str, Any] | None" = None,
    recipients: "List[str] | None" = None,
) -> Dict[str, Any]:
    _utterance = f"session:open subject={subject}"
    _utt_part: Dict[str, Any] = {"type": "utterance", "location": "inline", "content": _utterance}
    if rationale:
        _utt_part["rationale"] = rationale
    if thought_summary:
        _utt_part["thought_summary"] = thought_summary
    _payload_parts: List[Dict[str, Any]] = [_utt_part]
    if team_process:
        _payload_parts.append({"type": "team_process", "location": "inline", "content": team_process})
    _epistemic = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
    )
    with _lifecycle_emit(net):
        header = build_l9_header(
            use_case=net.use_case,  # type: ignore[attr-defined]
            event_type="peer_turn",
            sender=coordinator, receiver=coordinator,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=net.sensitivity,  # type: ignore[attr-defined]
            utterance=_utterance,
            episode_id=episode_id, kind_override="intent",
            epistemic=_epistemic, payload_parts=_payload_parts,
            recipients=recipients or [],
            subprotocol="SIEP",
        )
    net.send(header)
    return header


def _emit_episode_close(
    net: "NetworkHandle",
    *,
    coordinator: str,
    subject: str,
    accepted: bool,
    episode_id: "str | None" = None,
    rationale: str = "",
    thought_summary: str = "",
    summary: "Dict[str, Any] | None" = None,
    recipients: "List[str] | None" = None,
    label: str = "episode:close",
) -> Dict[str, Any]:
    _outcome = "commit:converged" if accepted else "commit:rejected"
    _utterance = f"{label} subject={subject} accepted={accepted}"
    payload_parts: List[Dict[str, Any]] = [
        {"type": "utterance", "location": "inline", "content": _utterance}
    ]
    if rationale:
        payload_parts[0]["rationale"] = rationale
    if thought_summary:
        payload_parts[0]["thought_summary"] = thought_summary
    if summary:
        payload_parts.append({"type": "team_process", "location": "inline", "content": summary})
    _epistemic = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TEAM_PROCESS,
    )
    with _lifecycle_emit(net):
        header = build_l9_header(
            use_case=net.use_case,  # type: ignore[attr-defined]
            event_type="peer_turn",
            sender=coordinator, receiver=coordinator,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=net.sensitivity,  # type: ignore[attr-defined]
            utterance=_utterance,
            episode_id=episode_id, kind_override=_outcome,
            epistemic=_epistemic, payload_parts=payload_parts,
            recipients=recipients or [],
            subprotocol="SIEP",
        )
    net.send(header)
    return header


def _emit_intent(
    net: "NetworkHandle",
    *,
    sender: str,
    receiver: "str | None",
    subject: str,
    episode_id: "str | None" = None,
    team_prior: "Dict[str, Any] | None" = None,
    team_process: "Dict[str, Any] | None" = None,
    session_plan: "Dict[str, Any] | None" = None,
    rationale: str = "",
    thought_summary: str = "",
    role: "str | None" = None,
    recipients: "List[str] | None" = None,
    label: str = "episode:open",
) -> Dict[str, Any]:
    _utterance = f"{label} subject={subject}"
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
    if session_plan:
        payload_parts.append({"type": "session_plan", "location": "inline", "content": session_plan})
    _receiver = receiver or sender
    _recipients = recipients if recipients is not None else ([_receiver] if _receiver != sender else [])
    with _lifecycle_emit(net):
        header = build_l9_header(
            use_case=net.use_case,  # type: ignore[attr-defined]
            event_type="peer_turn",
            sender=sender, receiver=_receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=net.sensitivity,  # type: ignore[attr-defined]
            utterance=_utterance,
            episode_id=episode_id, kind_override="intent",
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TEAM_PROCESS,
                belief_status=BeliefStatus.ASSERTED,
            ),
            payload_parts=payload_parts, role=role, recipients=_recipients,
            subprotocol="SIEP",
        )
    net.send(header)
    return header


def _emit_exchange_ready(
    net: "NetworkHandle",
    *,
    speaker: str,
    listener: "str | None",
    utterance: str,
    posterior: float,
    concept_id: "str | None" = None,
    evidence: "List[str] | None" = None,
    addresses_evidence: "List[str] | None" = None,
    parent_id: "str | None" = None,
    episode_id: "str | None" = None,
    rationale: str = "",
    thought_summary: str = "",
) -> Dict[str, Any]:
    epistemic = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        belief_status=BeliefStatus.ASSERTED, uncertainty=round(1.0 - posterior, 4),
    )
    return emit_peer_turn(
        net, sender=speaker, receiver=listener or speaker, utterance=utterance,
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        parent_id=parent_id, episode_id=episode_id, kind_override="exchange:ready",
        topic=concept_id, epistemic=epistemic, rationale=rationale,
        thought_summary=thought_summary, subprotocol="SIEP",
    )


def _emit_ready(
    net: "NetworkHandle",
    *,
    sender: str,
    receiver: "str | None",
    posterior: float,
    concept_id: "str | None" = None,
    parent_id: "str | None" = None,
    episode_id: "str | None" = None,
) -> Dict[str, Any]:
    _utterance = f"ready posterior={posterior:.4f}"
    epistemic = make_epistemic_block(
        speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
        belief_status=BeliefStatus.ASSERTED, uncertainty=round(1.0 - posterior, 4),
    )
    with _lifecycle_emit(net):
        return emit_peer_turn(
            net, sender=sender, receiver=receiver or sender, utterance=_utterance,
            speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
            parent_id=parent_id, episode_id=episode_id, kind_override="commit:ready",
            topic=concept_id, epistemic=epistemic, subprotocol="SIEP",
        )


def _emit_knowledge_announcement(
    net: "NetworkHandle",
    *,
    sender: str,
    concept_id: str,
    posterior: float,
    gar: float,
    scr: float,
    provenance_weight: float,
    commit_message_id: str = "",
    revision_cause: str = "converged_episode",
    episode_id: "str | None" = None,
    value: str = "",
    value_detail: "Dict[str, Any] | None" = None,
) -> Dict[str, Any]:
    _utterance = (
        f"knowledge:{concept_id}:posterior={posterior:.4f}"
        f":gar={gar:.4f}:scr={scr:.4f}:provenance_weight={provenance_weight:.4f}"
    )
    _eid = episode_id or ""
    _msg_id, _, _ = net._next_msg_id(_eid)  # type: ignore[attr-defined]
    _knowledge_content: Dict[str, Any] = {
        "concept_id": concept_id,
        "value": value or concept_id.split(":")[-1],
        "value_detail": value_detail or {},
        "source": commit_message_id,
        "posterior": posterior,
        "gar": gar, "scr": scr, "provenance_weight": provenance_weight,
        "revision_cause": revision_cause,
    }
    header = build_l9_header(
        use_case=net.use_case,  # type: ignore[attr-defined]
        event_type="peer_turn",
        sender=sender, receiver=sender,
        timestamp_ms=int(time.time() * 1000),
        sensitivity=net.sensitivity,  # type: ignore[attr-defined]
        utterance=_utterance,
        parent_ids=[], episode_id=episode_id,
        kind_override="knowledge", topic=concept_id,
        message_id=_msg_id,
        subprotocol="SIEP",
        epistemic=make_epistemic_block(
            speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.TASKWORK,
            belief_status=BeliefStatus.ASSERTED, uncertainty=round(1.0 - posterior, 4),
        ),
        payload_parts=[
            {"type": "utterance", "location": "inline", "content": _utterance},
            {"type": "knowledge", "location": "inline", "content": _knowledge_content},
        ],
        recipients=["team-memory"],
    )
    net.send(header)
    return header


def emit_wire_received(
    net: "NetworkHandle",
    *,
    msg_id: str,
    recipient_id: str,
    sender_id: str,
    episode_id: "str | None" = None,
) -> Dict[str, Any]:
    """Emit an inbound 'wire received' trace record from the recipient's perspective."""
    _recv_utt = f"received:{msg_id.split(':')[-1] if ':' in msg_id else msg_id}"
    header = build_l9_header(
        use_case=net.use_case,  # type: ignore[attr-defined]
        event_type="peer_turn",
        sender=recipient_id,
        receiver=sender_id,
        timestamp_ms=int(time.time() * 1000),
        sensitivity=net.sensitivity,  # type: ignore[attr-defined]
        utterance=_recv_utt,
        parent_ids=[msg_id] if msg_id else None,
        episode_id=episode_id,
        kind_override="exchange",
        subprotocol="SIEP",
        payload_parts=[{
            "type": "utterance", "location": "inline",
            "content": _recv_utt,
            "rationale": f"received from {sender_id}",
        }],
    )
    net.messages.append(header)  # type: ignore[attr-defined]
    return header


__all__ = [
    "emit_peer_turn",
    "emit_request",
    "emit_response",
    "emit_error",
    "emit_semantic_repair",
    "emit_epistemic_clarification",
    "emit_task_assignment",
    "emit_taskwork_result",
    "emit_grounding_phase_ready",
    "emit_grounding_phase_converged",
    "emit_taskwork_phase_intent",
    "emit_repair_resolved",
    "emit_knowledge_rule",
    "emit_grounding_turn",
    "emit_wire_received",
    "_emit_episode_open",
    "_emit_episode_close",
    "_emit_intent",
    "_emit_exchange_ready",
    "_emit_ready",
    "_emit_knowledge_announcement",
    "_lifecycle_emit",
]

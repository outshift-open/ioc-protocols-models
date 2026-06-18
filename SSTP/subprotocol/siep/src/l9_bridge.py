# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Helpers for bridging L9 header dicts and lightweight SIEP message models."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from SSTP.l9_base import normalize_use_case
from SSTP.subprotocol.cip.src.l9 import build_l9_header
from SSTP.subprotocol.siep.src.negotiate import (
    NegotiationOperation,
    SNP_PROFILE,
    build_snp_l9_header,
    snp_event_type_for_operation,
)
from SSTP.subprotocol.siep.src.negotiate import (
    BaseSSTPMessage,
    LogicalClock,
    NegotiateSemanticContext,
    Origin,
    PolicyLabels,
    Provenance,
    SAONMI,
    SAOResponse,
    SAOState,
    SSTPNegotiateMessage,
    SemanticContext,
)


class GenericSSTPMessage(BaseSSTPMessage):
    semantic_context: SemanticContext = SemanticContext()


def _logical_clock_from_header(l9_header: Dict[str, Any]) -> LogicalClock | None:
    lc = l9_header.get("logical_clock")
    if isinstance(lc, str) and lc.startswith("lamport:"):
        try:
            return LogicalClock(value=int(lc.split(":", 1)[1]))
        except (ValueError, IndexError):
            return None
    return None


def _message_from_header(
    l9_header: Dict[str, Any],
    *,
    payload: Dict[str, Any] | None = None,
    kind_override: str | None = None,
    semantic_context: SemanticContext | None = None,
) -> BaseSSTPMessage:
    kind = kind_override or l9_header.get("kind", "exchange")
    message = l9_header.get("message") or {}
    actors = l9_header.get("actors") or []
    origin = actors[0] if actors else {}
    semantic = l9_header.get("semantic") or l9_header.get("semantic_context") or {}
    policy = l9_header.get("policy") or {}
    attributes = l9_header.get("attributes") or l9_header.get("provenance") or {}
    msg_dict: Dict[str, Any] = {
        "kind": kind,
        "version": l9_header.get("version", "1.0.0"),
        "message_id": message.get("id", ""),
        "dt_created": attributes.get("msg_created", ""),
        "origin": Origin(
            actor_id=origin.get("id", "unknown"),
            attestation=origin.get("attestation"),
        ),
        "semantic_context": semantic_context or SemanticContext(
            schema_id=semantic.get("schema_id", "")
        ),
        "policy_labels": PolicyLabels(
            sensitivity=policy.get("sensitivity", "internal"),
            propagation=policy.get("propagation", "restricted"),
            retention_policy=policy.get("retention_policy", "default"),
        ),
        "attributes": Provenance(
            msg_sources=list(attributes.get("msg_sources") or attributes.get("sources") or []),
            msg_transforms=list(attributes.get("msg_transforms") or []),
            msg_created=attributes.get("msg_created", ""),
            msg_expiry=attributes.get("msg_expiry"),
        ),
        "payload": payload or {},
        "parent_ids": list(message.get("parents") or []),
        "episode_id": message.get("episode") or None,
        "logical_clock": _logical_clock_from_header(l9_header),
        "ttl_seconds": attributes.get("msg_expiry"),
        "payload_refs": list(l9_header.get("payload_refs") or []),
    }
    model_cls = SSTPNegotiateMessage if kind == "negotiate" else GenericSSTPMessage
    return model_cls.model_validate(msg_dict)


def l9_header_to_pydantic(
    l9_header: Dict[str, Any],
    *,
    payload: Dict[str, Any] | None = None,
    kind_override: str | None = None,
) -> BaseSSTPMessage:
    return _message_from_header(l9_header, payload=payload, kind_override=kind_override)


def pydantic_to_l9_header(msg: BaseSSTPMessage) -> Dict[str, Any]:
    header: Dict[str, Any] = {
        "protocol": "SSTP",
        "version": msg.version,
        "kind": msg.kind,
        "subprotocol": None,
        "subkind": None,
        "actors": [{
            "id": msg.origin.actor_id,
            "attestation": msg.origin.attestation or "self_attested_local",
        }],
        "message": {
            "id": msg.message_id,
            "parents": list(msg.parent_ids),
            "episode": msg.episode_id or "",
        },
        "semantic": {
            "schema_id": msg.semantic_context.schema_id,
            "ontology_ref": None,
        },
        "policy": {
            "sensitivity": msg.policy_labels.sensitivity,
            "propagation": msg.policy_labels.propagation,
            "retention_policy": msg.policy_labels.retention_policy,
        },
        "attributes": {
            "msg_sources": list(msg.provenance.msg_sources),
            "msg_transforms": list(msg.provenance.msg_transforms),
            "msg_created": msg.dt_created,
            "msg_expiry": msg.ttl_seconds,
        },
        "payload_refs": list(msg.payload_refs),
        "epistemic": None,
        "logical_clock": (
            f"{msg.logical_clock.type}:{msg.logical_clock.value}"
            if msg.logical_clock is not None else None
        ),
    }
    header["semantic_context"] = dict(header["semantic"])
    return header


def build_negotiate_envelope(
    *,
    operation: str,
    use_case: str,
    sender: str,
    receiver: str | None,
    timestamp_ms: int,
    proposal_id: str,
    session_id: str,
    payload: Dict[str, Any],
    sao_state: SAOState | Dict[str, Any] | None = None,
    sao_response: SAOResponse | Dict[str, Any] | None = None,
    nmi: SAONMI | Dict[str, Any] | None = None,
    issues: list[str] | None = None,
    options_per_issue: dict[str, list[str]] | None = None,
    turn_depth: int | None = None,
    parent_ids: Iterable[str] | None = None,
    message_id: str | None = None,
) -> SSTPNegotiateMessage:
    l9_header = build_snp_l9_header(
        operation=operation,
        use_case=use_case,
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        proposal_id=proposal_id,
        turn_depth=turn_depth,
        parent_ids=parent_ids,
        message_id=message_id,
    )
    semantic_context = NegotiateSemanticContext(
        schema_id=(l9_header.get("semantic_context") or {}).get(
            "schema_id", "urn:ioc:schema:negotiate:negmas-sao:v1"
        ),
        session_id=session_id,
        issues=list(issues or []),
        options_per_issue=dict(options_per_issue or {}),
        sao_state=SAOState.model_validate(sao_state) if isinstance(sao_state, dict) else sao_state,
        sao_response=(
            SAOResponse.model_validate(sao_response)
            if isinstance(sao_response, dict) else sao_response
        ),
        nmi=SAONMI.model_validate(nmi) if isinstance(nmi, dict) else nmi,
    )
    return SSTPNegotiateMessage.model_validate(
        _message_from_header(
            l9_header,
            payload=payload,
            kind_override="negotiate",
            semantic_context=semantic_context,
        ).model_dump()
    )


def build_repair_required(
    *,
    use_case: str,
    sender: str,
    receiver: str | None,
    timestamp_ms: int,
    payload: Dict[str, Any],
    turn_depth: int | None = None,
    parent_ids: Iterable[str] | None = None,
    message_id: str | None = None,
) -> GenericSSTPMessage:
    return l9_header_to_pydantic(
        build_l9_header(
            use_case=use_case,
            event_type="repair_required",
            sender=sender,
            receiver=receiver,
            timestamp_ms=timestamp_ms,
            turn_depth=turn_depth,
            parent_ids=parent_ids,
            message_id=message_id,
        ),
        payload=payload,
        kind_override="contingency",
    )


def build_repair_applied(
    *,
    use_case: str,
    sender: str,
    receiver: str | None,
    timestamp_ms: int,
    payload: Dict[str, Any],
    turn_depth: int | None = None,
    parent_ids: Iterable[str] | None = None,
    message_id: str | None = None,
) -> GenericSSTPMessage:
    return l9_header_to_pydantic(
        build_l9_header(
            use_case=use_case,
            event_type="repair_applied",
            sender=sender,
            receiver=receiver,
            timestamp_ms=timestamp_ms,
            turn_depth=turn_depth,
            parent_ids=parent_ids,
            message_id=message_id,
        ),
        payload=payload,
        kind_override="commit",
    )


__all__ = [
    "GenericSSTPMessage",
    "SNP_PROFILE",
    "build_negotiate_envelope",
    "build_repair_applied",
    "build_repair_required",
    "l9_header_to_pydantic",
    "normalize_use_case",
    "pydantic_to_l9_header",
    "snp_event_type_for_operation",
    "NegotiationOperation",
]

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
l9_bridge.py — Conversion between L9 header dicts and Pydantic SSTP models.

This module connects two representations of the same SSTP envelope:

- **L9 primitives** (``protocol.snp.l9``): functional header builder that
  returns plain dicts, handles event-type normalisation, kind classification,
  deterministic message-ID generation, use-case-aware policies, and SNP
  operation mapping.

- **Pydantic models** (``protocol.snp``): typed envelope models providing
  validation, discriminated-union deserialisation, and NegMAS SAO state.

Public API
----------
``l9_header_to_pydantic``
    Convert an L9 header dict into a Pydantic ``_STBaseMessage`` subclass.

``pydantic_to_l9_header``
    Extract an L9-compatible header dict from a Pydantic message.

``build_negotiate_envelope``
    End-to-end: build an ``SSTPNegotiateMessage`` whose L9 metadata is
    derived from the SNP operation mapping, with the NegMAS SAO state
    carried in the ``NegotiateSemanticContext``.

``build_repair_required``
    Build a ``ContingencyMessage`` (kind=contingency) for a repair_required event.

``build_repair_applied``
    Build a ``CommitMessage`` (kind=commit) for a repair_applied event.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable

from sstp.l9_base import normalize_use_case
from sstp.ie.l9 import build_l9_header
from .l9 import (
    build_snp_l9_header,
    snp_event_type_for_operation,
    NegotiationOperation,
    SNP_PROFILE,
)

from ._base import (
    LogicalClock,
    Origin,
    PayloadRef,
    PolicyLabels,
    Provenance,
    SemanticContext,
    _STBaseMessage,
)
from .commit import NegotiateCommitSemanticContext, SSTPCommitMessage
from .contingency import ContingencyMessage
from .convergence import ConvergenceMessage
from .delegation import DelegationMessage
from .exchange import ExchangeMessage
from .intent import IntentMessage
from .knowledge import KnowledgeMessage
from .memory_delta import MemoryDeltaMessage
from .negotiate import NegotiateSemanticContext, SSTPNegotiateMessage
from .negmas_sao import SAOState, SAOResponse, SAONMI
from .query import QueryMessage

# ── Kind → Pydantic model mapping ─────────────────────────────────────────────

_KIND_MODEL_MAP: Dict[str, type[_STBaseMessage]] = {
    # New 5-value session-flow vocabulary
    "intent":       IntentMessage,
    "exchange":     ExchangeMessage,
    "contingency":  ContingencyMessage,
    "commit":       SSTPCommitMessage,
    "convergence":  ConvergenceMessage,
    # Legacy kinds (backward compat during transition)
    "delegation":   DelegationMessage,
    "knowledge":    KnowledgeMessage,
    "query":        QueryMessage,
    "memory_delta": MemoryDeltaMessage,
    # NegMAS SAO (intentionally kept; NegMAS-specific extension)
    "negotiate":    SSTPNegotiateMessage,
}


def _payload_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# ── L9 dict → Pydantic ────────────────────────────────────────────────────────


def l9_header_to_pydantic(
    l9_header: Dict[str, Any],
    *,
    payload: Dict[str, Any] | None = None,
    kind_override: str | None = None,
) -> _STBaseMessage:
    """Convert an L9 header dict (from ``build_l9_header``) into a Pydantic model.

    Parameters
    ----------
    l9_header:
        Dict returned by ``protocol.snp.l9.build_l9_header``
        or ``build_snp_l9_header``.
    payload:
        The message payload dict. Defaults to empty dict.
    kind_override:
        Force a specific kind instead of using ``l9_header["kind"]``.

    Returns
    -------
    A concrete ``_STBaseMessage`` subclass chosen by the ``kind`` discriminator.
    """
    kind = kind_override or l9_header.get("kind", "knowledge")
    payload = payload or {}

    origin = l9_header.get("origin", {})
    sem_ctx = l9_header.get("semantic_context", {})
    policy = l9_header.get("policy_labels", {})
    prov = l9_header.get("provenance", {})

    lc = l9_header.get("logical_clock")
    logical_clock = None
    if isinstance(lc, str) and lc.startswith("lamport:"):
        try:
            logical_clock = {"type": "lamport", "value": int(lc.split(":", 1)[1])}
        except (ValueError, IndexError):
            pass

    payload_refs = l9_header.get("payload_refs", [])

    msg_dict: Dict[str, Any] = {
        "kind": kind,
        "version": l9_header.get("version", "0"),
        "message_id": l9_header.get("message_id", ""),
        "dt_created": l9_header.get("dt_created", ""),
        "origin": {
            "actor_id": origin.get("actor_id", "unknown"),
            "tenant_id": origin.get("tenant_id", "unknown"),
            "attestation": origin.get("attestation"),
        },
        "semantic_context": {
            "schema_id": sem_ctx.get("schema_id", ""),
            "schema_version": sem_ctx.get("schema_version", "0.1"),
            "encoding": sem_ctx.get("encoding", "json"),
        },
        "payload_hash": _payload_hash(payload),
        "policy_labels": {
            "sensitivity": policy.get("sensitivity", "internal"),
            "propagation": policy.get("propagation", "restricted"),
            "retention_policy": policy.get("retention_policy", "default"),
        },
        "provenance": {
            "sources": prov.get("sources", []),
            "transforms": prov.get("transforms", []),
        },
        "payload": payload,
    }

    # Optional fields
    if l9_header.get("state_object_id"):
        msg_dict["state_object_id"] = l9_header["state_object_id"]
    if l9_header.get("parent_ids"):
        msg_dict["parent_ids"] = l9_header["parent_ids"]
    if logical_clock:
        msg_dict["logical_clock"] = logical_clock
    if payload_refs:
        msg_dict["payload_refs"] = [
            {"type": ref.get("type", "inline"), "ref": ref.get("ref", "")}
            for ref in payload_refs
        ]
    if l9_header.get("confidence_score") is not None:
        msg_dict["confidence_score"] = l9_header["confidence_score"]
    if l9_header.get("ttl_seconds") is not None:
        msg_dict["ttl_seconds"] = l9_header["ttl_seconds"]
    if l9_header.get("merge_strategy"):
        msg_dict["merge_strategy"] = l9_header["merge_strategy"]
    if l9_header.get("risk_score") is not None:
        msg_dict["risk_score"] = l9_header["risk_score"]

    model_cls = _KIND_MODEL_MAP.get(kind)
    if model_cls is None:
        raise ValueError(f"Unknown SSTP kind: {kind!r}")

    return model_cls.model_validate(msg_dict)


# ── Pydantic → L9 dict ────────────────────────────────────────────────────────


def pydantic_to_l9_header(msg: _STBaseMessage) -> Dict[str, Any]:
    """Extract an L9-compatible header dict from a Pydantic SSTP message.

    Returns a dict in the same shape as ``build_l9_header`` output, suitable
    for embedding as an ``l9_header`` field in interaction engine events.
    """
    origin = msg.origin
    sem_ctx = msg.semantic_context
    policy = msg.policy_labels
    prov = msg.provenance

    lc_str = None
    if msg.logical_clock is not None:
        if msg.logical_clock.type == "lamport":
            lc_str = f"lamport:{msg.logical_clock.value}"

    header: Dict[str, Any] = {
        "protocol": "SSTP",
        "version": msg.version,
        "kind": msg.kind,
        "message_id": msg.message_id,
        "dt_created": msg.dt_created,
        "origin": {
            "actor_id": origin.actor_id,
            "tenant_id": origin.tenant_id,
            "attestation": origin.attestation or "self_attested_local",
        },
        "semantic_context": {
            "schema_id": sem_ctx.schema_id,
            "schema_version": sem_ctx.schema_version,
            "encoding": sem_ctx.encoding,
        },
        "policy_labels": {
            "sensitivity": policy.sensitivity,
            "propagation": policy.propagation,
            "retention_policy": policy.retention_policy,
        },
        "provenance": {
            "sources": list(prov.sources),
            "transforms": list(prov.transforms),
        },
        "state_object_id": msg.state_object_id,
        "parent_ids": list(msg.parent_ids),
        "logical_clock": lc_str,
        "confidence_score": msg.confidence_score,
        "risk_score": msg.risk_score,
        "ttl_seconds": msg.ttl_seconds,
        "merge_strategy": msg.merge_strategy,
        "payload_refs": [
            {"type": ref.type, "ref": ref.ref} for ref in msg.payload_refs
        ],
    }
    return header


# ── End-to-end negotiate envelope builder ──────────────────────────────────────


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
    confidence_score: float | None = None,
    risk_score: float | None = None,
    message_id: str | None = None,
) -> SSTPNegotiateMessage:
    """Build an ``SSTPNegotiateMessage`` using the base layer's SNP mapping.

    The SSTP event_type is derived from *operation* via the base layer
    (``snp_event_type_for_operation``), and the L9 header is constructed by
    ``build_snp_l9_header``.  The NegMAS SAO state is carried in the
    session layer's ``NegotiateSemanticContext``.

    This is the primary entry point for producing negotiation messages that
    are grounded in the interaction-repair base layer.
    """
    # Build the L9 header via the base layer
    l9_hdr = build_snp_l9_header(
        operation=operation,
        use_case=use_case,
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        proposal_id=proposal_id,
        turn_depth=turn_depth,
        parent_ids=parent_ids,
        confidence_score=confidence_score,
        risk_score=risk_score,
        message_id=message_id,
    )

    # Coerce SAO types to Pydantic models if given as dicts
    _sao_state = (
        SAOState.model_validate(sao_state)
        if isinstance(sao_state, dict) else sao_state
    )
    _sao_response = (
        SAOResponse.model_validate(sao_response)
        if isinstance(sao_response, dict) else sao_response
    )
    _nmi = (
        SAONMI.model_validate(nmi)
        if isinstance(nmi, dict) else nmi
    )

    sem_ctx = l9_hdr.get("semantic_context", {})

    msg_dict: Dict[str, Any] = {
        "kind": "negotiate",
        "version": l9_hdr.get("version", "0"),
        "message_id": l9_hdr.get("message_id", ""),
        "dt_created": l9_hdr.get("dt_created", ""),
        "origin": l9_hdr.get("origin", {}),
        "semantic_context": {
            "schema_id": sem_ctx.get("schema_id", "urn:ioc:schema:negotiate:negmas-sao:v1"),
            "schema_version": sem_ctx.get("schema_version", "1.0"),
            "encoding": "json",
            "session_id": session_id,
            "issues": issues or [],
            "options_per_issue": options_per_issue or {},
            "sao_state": _sao_state.model_dump() if _sao_state else None,
            "sao_response": _sao_response.model_dump() if _sao_response else None,
            "nmi": _nmi.model_dump() if _nmi else None,
        },
        "payload_hash": _payload_hash(payload),
        "policy_labels": l9_hdr.get("policy_labels", {
            "sensitivity": "internal",
            "propagation": "restricted",
            "retention_policy": "default",
        }),
        "provenance": l9_hdr.get("provenance", {"sources": [], "transforms": []}),
        "payload": payload,
        "parent_ids": l9_hdr.get("parent_ids", []),
        "payload_refs": l9_hdr.get("payload_refs", []),
    }

    if l9_hdr.get("state_object_id"):
        msg_dict["state_object_id"] = l9_hdr["state_object_id"]
    if l9_hdr.get("confidence_score") is not None:
        msg_dict["confidence_score"] = l9_hdr["confidence_score"]
    if l9_hdr.get("ttl_seconds") is not None:
        msg_dict["ttl_seconds"] = l9_hdr["ttl_seconds"]
    if l9_hdr.get("merge_strategy"):
        msg_dict["merge_strategy"] = l9_hdr["merge_strategy"]
    if l9_hdr.get("risk_score") is not None:
        msg_dict["risk_score"] = l9_hdr["risk_score"]

    lc = l9_hdr.get("logical_clock")
    if isinstance(lc, str) and lc.startswith("lamport:"):
        try:
            msg_dict["logical_clock"] = {"type": "lamport", "value": int(lc.split(":", 1)[1])}
        except (ValueError, IndexError):
            pass

    return SSTPNegotiateMessage.model_validate(msg_dict)


# ── Interaction-repair event builders ──────────────────────────────────────────


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
) -> ContingencyMessage:
    """Build a ``repair_required`` event as a ``ContingencyMessage`` (kind=contingency).

    Opens a contingency branch. The parent session is held until repair_applied.
    """
    l9_hdr = build_l9_header(
        use_case=use_case,
        event_type="repair_required",
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        turn_depth=turn_depth,
        parent_ids=parent_ids,
        message_id=message_id,
    )
    return l9_header_to_pydantic(l9_hdr, payload=payload, kind_override="contingency")  # type: ignore[return-value]


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
) -> SSTPCommitMessage:
    """Build a ``repair_applied`` event as a ``CommitMessage`` (kind=commit).

    Closes the contingency branch opened by repair_required. Parent session resumes.
    """
    l9_hdr = build_l9_header(
        use_case=use_case,
        event_type="repair_applied",
        sender=sender,
        receiver=receiver,
        timestamp_ms=timestamp_ms,
        turn_depth=turn_depth,
        parent_ids=parent_ids,
        message_id=message_id,
    )
    return l9_header_to_pydantic(l9_hdr, payload=payload, kind_override="commit")  # type: ignore[return-value]


__all__ = [
    "l9_header_to_pydantic",
    "pydantic_to_l9_header",
    "build_negotiate_envelope",
    "build_repair_required",
    "build_repair_applied",
]

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
    "commit:converged": SSTPCommitMessage,
    "commit:abort":     SSTPCommitMessage,
    "convergence":      ConvergenceMessage,
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

    # New wire format field names
    actors = l9_header.get("actors") or []
    origin_id = actors[0].get("id", "unknown") if actors else "unknown"
    origin_attest = actors[0].get("attestation") if actors else None
    sem_ctx = l9_header.get("semantic") or l9_header.get("semantic_context", {})
    policy = l9_header.get("policy") or l9_header.get("policy_labels", {})
    prov = l9_header.get("provenance", {})
    msg_block = l9_header.get("message", {})

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
        "message_id": msg_block.get("id", ""),
        "dt_created": prov.get("created", ""),
        "origin": {
            "actor_id": origin_id,
            "attestation": origin_attest,
        },
        "semantic_context": {
            "schema_id": sem_ctx.get("schema_id", ""),
        },
        "payload_hash": _payload_hash(payload),
        "policy_labels": {
            "sensitivity": policy.get("sensitivity", "internal"),
            "propagation": policy.get("propagation", "restricted"),
            "retention_policy": policy.get("retention_policy", "default"),
        },
        "provenance": {
            "sources": prov.get("sources", []),
        },
        "payload": payload,
    }

    # Optional fields
    episode = msg_block.get("episode")
    if episode:
        msg_dict["episode_id"] = episode
    parents = msg_block.get("parents")
    if parents:
        msg_dict["parent_ids"] = parents
    if logical_clock:
        msg_dict["logical_clock"] = logical_clock
    expiry = prov.get("expiry")
    if expiry:
        msg_dict["ttl_seconds"] = expiry
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
        "subkind": None,
        "group":   [origin.actor_id],
        "actors":  [{"id": origin.actor_id, "attestation": origin.attestation or "self_attested_local"}],
        "message": {
            "id":      msg.message_id,
            "parents": list(msg.parent_ids),
            "episode": msg.episode_id or "",
        },
        "semantic": {
            "schema_id":    sem_ctx.schema_id,
            "ontology_ref": None,
            "sub_protocol": None,
        },
        "policy": {
            "sensitivity":      policy.sensitivity,
            "propagation":      policy.propagation,
            "retention_policy": policy.retention_policy,
        },
        "provenance": {
            "sources":    list(prov.sources),
            "transforms": [],
            "created":    msg.dt_created,
            "expiry":     None,
        },
        "epistemic":     None,
        "logical_clock": lc_str,
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

    _msg_block = l9_hdr.get("message", {})
    _actors = l9_hdr.get("actors") or []
    _prov2 = l9_hdr.get("provenance", {})
    msg_dict: Dict[str, Any] = {
        "kind": "negotiate",
        "version": l9_hdr.get("version", "0"),
        "message_id": _msg_block.get("id", ""),
        "dt_created": _prov2.get("created", ""),
        "origin": {
            "actor_id": _actors[0].get("id", "unknown") if _actors else "unknown",
            "attestation": _actors[0].get("attestation") if _actors else None,
        },
        "semantic_context": {
            "schema_id": sem_ctx.get("schema_id", "urn:ioc:schema:negotiate:negmas-sao:v1"),
            "session_id": session_id,
            "issues": issues or [],
            "options_per_issue": options_per_issue or {},
            "sao_state": _sao_state.model_dump() if _sao_state else None,
            "sao_response": _sao_response.model_dump() if _sao_response else None,
            "nmi": _nmi.model_dump() if _nmi else None,
        },
        "payload_hash": _payload_hash(payload),
        "policy_labels": l9_hdr.get("policy") or l9_hdr.get("policy_labels", {
            "sensitivity": "internal",
            "propagation": "restricted",
            "retention_policy": "default",
        }),
        "provenance": _prov2,
        "payload": payload,
        "parent_ids": _msg_block.get("parents", []),
        "payload_refs": [],
    }

    if _msg_block.get("episode"):
        msg_dict["episode_id"] = _msg_block["episode"]
    expiry2 = _prov2.get("expiry")
    if expiry2 is not None:
        msg_dict["ttl_seconds"] = expiry2

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

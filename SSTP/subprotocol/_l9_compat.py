# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the legacy flat L9 header adapter APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

L9_PROTOCOL: str = "SSTP"
L9_VERSION: str = "0.0.5"

_CERTIFIED_KINDS: frozenset[str] = frozenset({"commit"})


def normalize_use_case(use_case: str) -> str:
    return str(use_case).strip().lower().replace("-", "_").replace(" ", "_")


def schema_trust_level_for_kind(kind: str) -> str:
    return "certified" if kind in _CERTIFIED_KINDS else "draft"


def schema_version_for_trust_level(trust_level: str) -> str:
    if trust_level == "certified":
        return "1.0"
    if trust_level == "inline":
        return "0.0"
    return "0.1"


def schema_version_for_kind(kind: str) -> str:
    return schema_version_for_trust_level(schema_trust_level_for_kind(kind))


def iso8601_from_timestamp_ms(timestamp_ms: int) -> str:
    return (
        datetime.fromtimestamp(max(0, timestamp_ms) / 1000.0, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def split_kind_subkind(kind_value: str | None) -> tuple[str | None, str | None]:
    if kind_value is None:
        return None, None
    base, sep, subkind = str(kind_value).partition(":")
    return base, ((subkind or None) if sep else None)


def legacy_participants(
    *,
    sender: str,
    receiver: str | None,
    role: str | None,
    recipients: List[str] | None,
) -> Dict[str, Any]:
    sender_id = str(sender or "unknown")
    sender_role = role or sender_id
    recipient_ids = list(recipients) if recipients is not None else (
        [str(receiver)] if receiver and str(receiver) != sender_id else []
    )
    actors = [
        {
            "id": sender_id,
            "role": sender_role,
            "participant_type": "sender",
            "attestation": "self_attested_local",
        }
    ]
    actors.extend(
        {
            "id": recipient_id,
            "role": recipient_id,
            "participant_type": "recipient",
            "attestation": None,
        }
        for recipient_id in recipient_ids
        if recipient_id != sender_id
    )
    return {"actors": actors, "groups": None}


def legacy_episode_id(use_case: str, episode_id: str | None) -> str:
    return episode_id or f"urn:ioc:{normalize_use_case(use_case)}:state:shared_dialogue"


def legacy_parent_ids(parent_ids: Iterable[str] | None) -> List[str]:
    return [str(parent_id) for parent_id in (parent_ids or []) if parent_id]


def legacy_sources(provenance_sources: Iterable[str] | None) -> List[str]:
    return [str(source) for source in (provenance_sources or []) if source]


def flatten_legacy_header(
    *,
    builder_header: Dict[str, Any],
    sender: str,
    receiver: str | None,
    role: str | None,
    recipients: List[str] | None,
    use_case: str,
    timestamp_ms: int,
    message_id: str | None,
    episode_id: str | None,
    topic: str | None,
    epistemic: Dict[str, Any] | None,
    schema_id: str,
    ontology_ref: str | None,
    subprotocol: str | None,
    payload_parts: List[Dict[str, Any]] | None,
    sensitivity: str,
    propagation: str,
    provenance_sources: Iterable[str] | None,
    provenance_expiry: str | None = None,
) -> Dict[str, Any]:
    normalized_use_case = normalize_use_case(use_case)
    message = dict(builder_header.get("message") or {})
    if message_id is not None:
        message["id"] = message_id
    message["parents"] = legacy_parent_ids(message.get("parents"))
    message["episode"] = legacy_episode_id(use_case, episode_id)
    return {
        "protocol": L9_PROTOCOL,
        "version": L9_VERSION,
        "kind": builder_header.get("kind"),
        "subprotocol": subprotocol if subprotocol is not None else builder_header.get("subprotocol"),
        "subkind": builder_header.get("subkind"),
        "participants": legacy_participants(
            sender=sender,
            receiver=receiver,
            role=role,
            recipients=recipients,
        ),
        "message": message,
        "context": {
            "topic": topic or None,
            "epistemic": dict(epistemic) if epistemic is not None else None,
            "semantic": {
                "schema_id": schema_id,
                "ontology_ref": ontology_ref,
            },
        },
        "policy": {
            "sensitivity": sensitivity,
            "propagation": propagation,
            "retention_policy": f"policy.{normalized_use_case}.default",
        },
        "attributes": {
            "msg_sources": legacy_sources(provenance_sources),
            "msg_transforms": [],
            "msg_created": iso8601_from_timestamp_ms(timestamp_ms),
            "msg_expiry": provenance_expiry,
        },
        "payload": list(payload_parts) if payload_parts is not None else [],
    }


__all__ = [
    "L9_PROTOCOL",
    "L9_VERSION",
    "flatten_legacy_header",
    "iso8601_from_timestamp_ms",
    "legacy_episode_id",
    "legacy_parent_ids",
    "legacy_participants",
    "legacy_sources",
    "normalize_use_case",
    "schema_trust_level_for_kind",
    "schema_version_for_kind",
    "schema_version_for_trust_level",
    "split_kind_subkind",
]

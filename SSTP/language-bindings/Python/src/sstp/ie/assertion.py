# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""UtteranceAssertion — per-utterance identity, integrity, and chain types."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import List


@dataclass
class AgentIdentity:
    agent_id: str
    role: str
    session_id: str
    signing_key: bytes  # HMAC-SHA256 key, derived per agent per session


@dataclass
class UtteranceAssertion:
    utterance_id: str
    agent_id: str
    session_id: str
    task_goal: str
    content: str
    content_hash: str        # SHA-256(content)
    timestamp_ms: int
    prev_utterance_hash: str  # SHA-256 of previous assertion content from this agent; "" for first
    parent_ids: List[str]     # utterance_ids being responded to
    signature: str            # HMAC-SHA256(signing_key, canonical_payload)
    event_type: str = "utterance"  # declaration | utterance | clarification_request | clarification_response | repair


class AssertionVerificationError(Exception):
    def __init__(self, utterance_id: str, agent_id: str, reason: str) -> None:
        super().__init__(f"Assertion verification failed for {agent_id}/{utterance_id}: {reason}")
        self.utterance_id = utterance_id
        self.agent_id = agent_id
        self.reason = reason


def _canonical(assertion: UtteranceAssertion) -> str:
    return json.dumps({
        "utterance_id": assertion.utterance_id,
        "agent_id": assertion.agent_id,
        "session_id": assertion.session_id,
        "content_hash": assertion.content_hash,
        "timestamp_ms": assertion.timestamp_ms,
        "prev_utterance_hash": assertion.prev_utterance_hash,
    }, sort_keys=True)


def build_assertion(
    identity: AgentIdentity,
    content: str,
    task_goal: str,
    prev_utterance_hash: str = "",
    parent_ids: List[str] | None = None,
    event_type: str = "utterance",
) -> UtteranceAssertion:
    utterance_id = str(uuid.uuid4())
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    timestamp_ms = int(time.time() * 1000)
    assertion = UtteranceAssertion(
        utterance_id=utterance_id,
        agent_id=identity.agent_id,
        session_id=identity.session_id,
        task_goal=task_goal,
        content=content,
        content_hash=content_hash,
        timestamp_ms=timestamp_ms,
        prev_utterance_hash=prev_utterance_hash,
        parent_ids=parent_ids or [],
        signature="",
        event_type=event_type,
    )
    sig = hmac.new(identity.signing_key, _canonical(assertion).encode(), hashlib.sha256).hexdigest()
    assertion.signature = sig
    return assertion


def verify_assertion(
    assertion: UtteranceAssertion,
    signing_key: bytes,
    prev_assertion: UtteranceAssertion | None = None,
) -> None:
    expected_hash = hashlib.sha256(assertion.content.encode()).hexdigest()
    if assertion.content_hash != expected_hash:
        raise AssertionVerificationError(assertion.utterance_id, assertion.agent_id, "content_hash_mismatch")
    expected_sig = hmac.new(signing_key, _canonical(assertion).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assertion.signature, expected_sig):
        raise AssertionVerificationError(assertion.utterance_id, assertion.agent_id, "signature_invalid")
    if prev_assertion is not None:
        prev_hash = hashlib.sha256(prev_assertion.content.encode()).hexdigest()
        if assertion.prev_utterance_hash != prev_hash:
            raise AssertionVerificationError(assertion.utterance_id, assertion.agent_id, "chain_broken")


__all__ = ["AgentIdentity", "UtteranceAssertion", "AssertionVerificationError", "build_assertion", "verify_assertion"]

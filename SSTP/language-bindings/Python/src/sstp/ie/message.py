# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""IE message schema — typed message envelopes for the Interaction Engine subprotocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sstp.ie.assertion import UtteranceAssertion


@dataclass
class IEMessage:
    message_id: str
    agent_id: str
    session_id: str
    task_goal: str
    event_type: str  # declaration | utterance | clarification_request | clarification_response | repair
    assertion: UtteranceAssertion
    timestamp_ms: int


@dataclass
class IEDeclaration(IEMessage):
    """Sent once per agent at session start; roots the agent's assertion chain."""
    role: str = ""
    objective: str = ""


@dataclass
class IEUtterance(IEMessage):
    content: str = ""
    contingency: str = "normal_alignment"


@dataclass
class IEClarificationRequest(IEMessage):
    content: str = ""
    ambiguous_spans: List[str] = field(default_factory=list)
    plausible_interpretations: List[str] = field(default_factory=list)
    pending_utterance_id: str = ""


@dataclass
class IEClarificationResponse(IEMessage):
    content: str = ""
    resolves_utterance_id: str = ""


@dataclass
class IERepair(IEMessage):
    content: str = ""
    repair_strategy: str = ""
    triggered_by_utterance_id: str = ""


__all__ = [
    "IEMessage",
    "IEDeclaration",
    "IEUtterance",
    "IEClarificationRequest",
    "IEClarificationResponse",
    "IERepair",
]

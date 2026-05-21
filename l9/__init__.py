"""
L9 Protocol — SSTP (Semantic Structured Transfer Protocol)
Agentic Workflow Lifecycle: Phases 1–5

Usage:
    from l9 import L9Protocol
    from l9.teamwork import AgentHiringKind
    from l9.goal_intent import ConsensusCommitPayload
    from l9.communication import QueryRequest
    from l9.shared import Knowledge, EvidenceBundle
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from l9.shared import EvidenceBundle, Knowledge
from l9.teamwork import AgentHiringKind
from l9.goal_intent import GoalIntentKind
from l9.planning import PlanningKind
from l9.communication import CommunicationKind
from l9.validation import ValidationKind
from l9.message import L9, L9Header, L9Payload, L9Phase, L9Kind, L9MessageType


class L9Protocol(BaseModel):
    """L9 / SSTP — Agentic Workflow Lifecycle (Phases 1–5)."""

    agent_hiring:  AgentHiringKind   = Field(default_factory=AgentHiringKind)
    goal_intent:   GoalIntentKind    = Field(default_factory=GoalIntentKind)
    planning:      PlanningKind      = Field(default_factory=PlanningKind)
    communication: CommunicationKind = Field(default_factory=CommunicationKind)
    validation:    ValidationKind    = Field(default_factory=ValidationKind)

    @property
    def kinds(self) -> List[BaseModel]:
        return [
            self.agent_hiring,
            self.goal_intent,
            self.planning,
            self.communication,
            self.validation,
        ]

    @property
    def knowledge_store(self) -> List[Knowledge]:
        """Aggregated view of all knowledge across agents and learning outcomes."""
        store: List[Knowledge] = []
        for domains in self.agent_hiring.state.knowledge_domains.values():
            store.extend(domains)
        for outcome in self.validation.state.learning_outcomes:
            store.extend(outcome.updated_knowledge)
        return store


__all__ = [
    "L9Protocol",
    # message envelope
    "L9",
    "L9Header",
    "L9Payload",
    "L9Phase",
    "L9Kind",
    "L9MessageType",
    # shared
    "Knowledge",
    "EvidenceBundle",
    # kind classes
    "AgentHiringKind",
    "GoalIntentKind",
    "PlanningKind",
    "CommunicationKind",
    "ValidationKind",
]

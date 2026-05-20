"""
Phase 1 — AgentHiring
Hire a set of agents based on their skills / capabilities (teamwork).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field

from l9.shared import Knowledge


class AgentHiringSubKind(str, Enum):
    SKILL_MATCH           = "skill_match"
    CAPABILITY_ASSESSMENT = "capability_assessment"
    TEAM_FORMATION        = "team_formation"
    KNOWLEDGE_DOMAIN      = "knowledge_domain"   # agents carry domain knowledge


class AgentHiringAction(str, Enum):
    ADVERTISE_ROLE     = "advertise_role"
    EVALUATE_CANDIDATE = "evaluate_candidate"
    ASSIGN_AGENT       = "assign_agent"
    FORM_TEAM          = "form_team"
    REGISTER_KNOWLEDGE = "register_knowledge"    # record an agent's knowledge domains


class AgentHiringEvent(str, Enum):
    ROLE_ADVERTISED      = "role_advertised"
    CANDIDATE_EVALUATED  = "candidate_evaluated"
    AGENT_ASSIGNED       = "agent_assigned"
    TEAM_FORMED          = "team_formed"
    KNOWLEDGE_REGISTERED = "knowledge_registered"


class AgentHiringState(BaseModel):
    available_agents:  List[str]                  = Field(default_factory=list)
    assigned_agents:   Dict[str, str]             = Field(default_factory=dict)  # role -> agent_id
    team:              List[str]                  = Field(default_factory=list)
    knowledge_domains: Dict[str, List[Knowledge]] = Field(default_factory=dict)  # agent_id -> Knowledge[]


class AgentHiringKind(BaseModel):
    phase:     int                      = 1
    name:      str                      = "AgentHiring"
    sub_kinds: List[AgentHiringSubKind] = Field(default_factory=lambda: list(AgentHiringSubKind))
    actions:   List[AgentHiringAction]  = Field(default_factory=lambda: list(AgentHiringAction))
    events:    List[AgentHiringEvent]   = Field(default_factory=lambda: list(AgentHiringEvent))
    state:     AgentHiringState         = Field(default_factory=AgentHiringState)

    def register_knowledge(self, agent_id: str, knowledge: Knowledge) -> None:
        """Record a knowledge domain for an agent (KNOWLEDGE_REGISTERED event)."""
        self.state.knowledge_domains.setdefault(agent_id, []).append(knowledge)

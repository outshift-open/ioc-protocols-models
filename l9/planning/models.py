"""
Phase 3 — Planning
Decompose the goal into tasks and allocate resources (taskwork).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field


class PlanningSubKind(str, Enum):
    TASK_DECOMPOSITION    = "task_decomposition"
    RESOURCE_ALLOCATION   = "resource_allocation"
    DEPENDENCY_RESOLUTION = "dependency_resolution"


class PlanningAction(str, Enum):
    DECOMPOSE_GOAL       = "decompose_goal"
    ALLOCATE_RESOURCES   = "allocate_resources"
    RESOLVE_DEPENDENCIES = "resolve_dependencies"
    COMMIT_PLAN          = "commit_plan"


class PlanningEvent(str, Enum):
    PLAN_INITIATED      = "plan_initiated"
    TASKS_DECOMPOSED    = "tasks_decomposed"
    RESOURCES_ALLOCATED = "resources_allocated"
    PLAN_COMMITTED      = "plan_committed"


class PlanningState(BaseModel):
    tasks:          List[str]            = Field(default_factory=list)
    resource_map:   Dict[str, str]       = Field(default_factory=dict)
    dependencies:   Dict[str, List[str]] = Field(default_factory=dict)
    plan_committed: bool                 = False


class PlanningKind(BaseModel):
    phase:     int                   = 3
    name:      str                   = "Planning"
    sub_kinds: List[PlanningSubKind] = Field(default_factory=lambda: list(PlanningSubKind))
    actions:   List[PlanningAction]  = Field(default_factory=lambda: list(PlanningAction))
    events:    List[PlanningEvent]   = Field(default_factory=lambda: list(PlanningEvent))
    state:     PlanningState         = Field(default_factory=PlanningState)

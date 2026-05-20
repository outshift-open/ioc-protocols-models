"""
Phase 5 — Validation
Online, offline-triggered, offline-manual, offline-periodic, pre-commit eval.
learn — derive updated Knowledge from validation outcomes.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from l9.shared import Knowledge


class ValidationSubKind(str, Enum):
    ONLINE            = "online"
    OFFLINE_TRIGGERED = "offline_triggered"
    OFFLINE_MANUAL    = "offline_manual"
    OFFLINE_PERIODIC  = "offline_periodic"
    PRE_COMMIT_EVAL   = "pre_commit_eval"


class ValidationAction(str, Enum):
    VALIDATE_ONLINE = "validate_online"
    TRIGGER_OFFLINE = "trigger_offline"
    RUN_MANUAL      = "run_manual"
    RUN_PERIODIC    = "run_periodic"
    RUN_PRE_COMMIT  = "run_pre_commit"
    LEARN           = "learn"   # derive updated Knowledge from validation outcomes


class ValidationEvent(str, Enum):
    VALIDATION_STARTED = "validation_started"
    VALIDATION_PASSED  = "validation_passed"
    VALIDATION_FAILED  = "validation_failed"
    EVAL_TRIGGERED     = "eval_triggered"
    KNOWLEDGE_UPDATED  = "knowledge_updated"   # emitted after a LEARN action


class LearningOutcome(BaseModel):
    """Knowledge delta produced by a LEARN action after validation."""
    source_validation_id: str             = ""
    updated_knowledge:    List[Knowledge] = Field(default_factory=list)
    insights:             List[str]       = Field(default_factory=list)


class ValidationState(BaseModel):
    validation_mode:   Optional[ValidationSubKind] = None
    results:           List[Dict[str, Any]]         = Field(default_factory=list)
    passed:            Optional[bool]               = None
    learning_outcomes: List[LearningOutcome]        = Field(default_factory=list)


class ValidationKind(BaseModel):
    phase:     int                     = 5
    name:      str                     = "Validation"
    sub_kinds: List[ValidationSubKind] = Field(default_factory=lambda: list(ValidationSubKind))
    actions:   List[ValidationAction]  = Field(default_factory=lambda: list(ValidationAction))
    events:    List[ValidationEvent]   = Field(default_factory=lambda: list(ValidationEvent))
    state:     ValidationState         = Field(default_factory=ValidationState)

    def learn(self, outcome: LearningOutcome) -> None:
        """Record a LearningOutcome and emit KNOWLEDGE_UPDATED."""
        self.state.learning_outcomes.append(outcome)

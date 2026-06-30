# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Drift Detection — source-of-truth output models.

These hand-authored Pydantic models describe the payload the Drift
Detection Cognition Engine emits. Consumers (CIP router, other CEs,
analytics) parse incoming L9 messages where the Drift Detection
verdict has been placed at the dotted path the caller specified in
``header.attributes['drift']``.

Formerly Semantic Alignment Validation / SAV (renamed 2026-06-30).
"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    """Discrete severity bucket for a detected failure mode."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProcessFailureMode(str, Enum):
    """PM-* — process-level failure modes detected from the interaction history.

    PM_0 (Unclassified) is emitted when the issue does not cleanly fit
    one of PM_1 to PM_7.
    """

    UNCLASSIFIED = "Unclassified"
    PERSISTENT_DIVERGENCE = "Persistent Divergence"
    DOMINANT_NARRATIVE = "Dominant Narrative"
    REPETITION = "Repetition"
    REASONING_BREAKDOWN = "Reasoning Breakdown"
    TASK_DEVIATION = "Task Deviation"
    CONSTRAINT_VIOLATION = "Constraint Violation"
    AMBIGUITY = "Ambiguity"


class Severity(BaseModel):
    """Severity verdict for one failure mode.

    ``type`` is the bucket the engine assigned. ``high`` and ``medium``
    are the score thresholds the engine used: score ≤ high → HIGH,
    score ≤ medium → MEDIUM, otherwise LOW. Thresholds are returned so
    callers can re-bucket under their own policy.
    """

    type: SeverityLevel = Field(..., description="Assigned severity bucket")
    high: float = Field(..., ge=0.0, le=1.0, description="Score ≤ this → HIGH")
    medium: float = Field(..., ge=0.0, le=1.0, description="Score ≤ this → MEDIUM")


class FailureMode(BaseModel):
    """A single detected process failure mode."""

    type: ProcessFailureMode = Field(..., description="Detected failure-mode category")
    score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Confidence score in [0,1]; lower = stronger evidence of drift",
    )
    severity: Severity
    description: str = Field(
        ..., description="Static taxonomy description for ``type``",
    )
    reasoning: str = Field(
        ..., description="Engine's per-instance justification for flagging this mode",
    )


class DriftDetectionOutput(BaseModel):
    """Top-level Drift Detection output (formerly SAVOutput).

    Placed in the L9 response message at the dotted path the caller
    specified in ``header.attributes['drift']``. Empty
    ``failure_modes`` list means no drift was detected.
    """

    failure_modes: List[FailureMode] = Field(
        default_factory=list,
        description="Detected process failure modes; empty list = no drift detected",
    )

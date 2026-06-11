# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Shared domain-primitive types used across all interaction engine apps."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Turn:
    speaker: str
    utterance: str
    inferred_intent: str
    timestamp_ms: int
    message_number: int = 0
    repaired: bool = False
    assertion: object = None  # UtteranceAssertion | None — typed as object to avoid circular import
    pending_clarification: bool = False


__all__ = ["Turn"]

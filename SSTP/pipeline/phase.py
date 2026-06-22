# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Phase and Kind enumerations for the SSTP pipeline."""

from enum import Enum


class Phase(str, Enum):
    """Ordered pipeline phases. All subprotocols operate within this fixed set."""
    SHARED_KNOWLEDGE = "shared-knowledge"
    PLANNING         = "planning"
    TEAM_FORMED      = "team-formed"
    GOAL_ALIGNMENT   = "goal-alignment"
    EXECUTION        = "execution"
    STATE_MANAGEMENT = "state-management"


# Canonical pipeline order (sequential by default; concurrency declared per-subprotocol).
PHASE_ORDER: list[Phase] = [
    Phase.SHARED_KNOWLEDGE,
    Phase.PLANNING,
    Phase.TEAM_FORMED,
    Phase.GOAL_ALIGNMENT,
    Phase.EXECUTION,
    Phase.STATE_MANAGEMENT,
]


class Kind(str, Enum):
    """
    Fixed set of L9 message kinds. No new kinds may be added by subprotocol
    developers — use subkind to specialise behaviour within a kind.
    """
    intent      = "intent"
    exchange    = "exchange"
    commit      = "commit"
    contingency = "contingency"
    knowledge   = "knowledge"


class PhaseRejectedError(Exception):
    """
    Raised when a message arrives for a phase that the receiving subprotocol
    does not operate in, or when the current episode phase does not permit the
    message kind.
    """
    def __init__(self, kind: str, current_phase: Phase, subprotocol: str = ""):
        sp = f" [{subprotocol}]" if subprotocol else ""
        super().__init__(
            f"kind={kind!r} rejected{sp}: not allowed in phase={current_phase.value!r}"
        )
        self.kind = kind
        self.current_phase = current_phase
        self.subprotocol = subprotocol


__all__ = ["Phase", "PHASE_ORDER", "Kind", "PhaseRejectedError"]

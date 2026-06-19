# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp.process — Team process and taskwork adaptation layer.

Sits between application code and the Episode/AgentBus APIs.  Application agents
call TeamCoordinator and TaskSession; the layer translates to L9.open(),
Episode.say(), emit_peer_turn(), and PanelBus.

Usage::

    from sstp.process import (
        AgentCapability,
        Phase,
        ReentryTrigger,
        TeamProcessStore,
        TeamProcessState,
        PhaseGate,
        TeamCoordinator,
        TaskSession,
        ConvergenceResult,
    )

    store = TeamProcessStore()
    gate  = PhaseGate(store)
    coord = TeamCoordinator(l9, panel_bus_factory, store, gate)
    sess  = TaskSession(bus, gate, coord, store)

    # TP-1
    coord.form_team("discharge_recommendation", capabilities)
    # TP-2
    coord.align_mental_model(priors)
    # TW-1
    sess.assess("pharmacologist", "concept:drug_interaction", 0.85, utterance, scope=[...])
    # TW-2
    result = sess.negotiate("concept:drug_interaction", participants, panel_bus)
"""

from sstp.process.store import (
    Phase,
    ReentryTrigger,
    AgentCapability,
    AgentTeamBelief,
    TeamProcessState,
    TeamProcessStore,
)
from sstp.process.gate import PhaseGate
from sstp.process.coordinator import (
    TeamCoordinator,
    TeamFormationError,
    MentalModelError,
    CONCEPT_ROLE_ASSIGNMENT,
    CONCEPT_TEAM_GOAL,
    CONCEPT_SHARED_MENTAL_MODEL,
    CONCEPT_CURRENT_PHASE,
)
from sstp.process.session import TaskSession, ConvergenceResult

__all__ = [
    "Phase",
    "ReentryTrigger",
    "AgentCapability",
    "AgentTeamBelief",
    "TeamProcessState",
    "TeamProcessStore",
    "PhaseGate",
    "TeamCoordinator",
    "TeamFormationError",
    "MentalModelError",
    "CONCEPT_ROLE_ASSIGNMENT",
    "CONCEPT_TEAM_GOAL",
    "CONCEPT_SHARED_MENTAL_MODEL",
    "CONCEPT_CURRENT_PHASE",
    "TaskSession",
    "ConvergenceResult",
]

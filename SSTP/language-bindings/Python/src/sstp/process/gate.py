# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
gate.py — Phase gate enforcement.

PhaseGate is the enforcement boundary between team process and taskwork.
It is called by TaskSession before every IE or SNP turn and silently
suppresses turns that violate the current team process state.

Rules
-----
TRANSITION phase
    Only coordination turns (coordination=True) are permitted.
    All taskwork turns are suppressed.

ACTION phase
    Taskwork turns are permitted only for the agent's assigned concept_id.
    Coordination turns are suppressed (use TeamCoordinator for those).
    An agent asserting on a concept it does not own is suppressed.

The app never sees suppression — TaskSession returns None on a suppressed
turn, and the caller proceeds without emitting a message.  This is
intentional: the caller does not need to know whether suppression occurred.
"""

from __future__ import annotations

import logging
from typing import Optional

from sstp.process.store import Phase, TeamProcessStore

LOGGER = logging.getLogger("sstp.process.gate")


class PhaseGate:
    """Enforces team process constraints on every taskwork turn.

    Injected into TaskSession.  Application code does not call it directly.
    """

    def __init__(self, store: TeamProcessStore) -> None:
        self._store = store

    def check(
        self,
        agent_id: str,
        concept_id: str,
        *,
        coordination: bool = False,
    ) -> bool:
        """Return True if this turn is permitted under the current team process state.

        Parameters
        ----------
        agent_id:
            The agent attempting the turn.
        concept_id:
            The clinical (or coordination) concept the turn addresses.
        coordination:
            True when the caller declares this is a team-process coordination turn.
            Set by TeamCoordinator internally; never set by app code.
        """
        phase = self._store.phase()

        if phase == Phase.TRANSITION:
            # Only coordination turns pass in TRANSITION.
            if not coordination:
                LOGGER.debug(
                    "gate.suppressed agent=%s concept=%s reason=transition_phase_blocks_taskwork",
                    agent_id, concept_id,
                )
            return coordination

        # ACTION phase —————————————————————————————————————————————————
        if coordination:
            # Coordination turns are suppressed in ACTION; use reenter() instead.
            LOGGER.debug(
                "gate.suppressed agent=%s concept=%s reason=action_phase_blocks_coordination",
                agent_id, concept_id,
            )
            return False

        role = self._store.role_for(agent_id)
        if role is not None:
            # Assigned agent: must match its own concept or a sub-concept URI.
            permitted = concept_id == role or concept_id.startswith(role)
            if not permitted:
                LOGGER.debug(
                    "gate.suppressed agent=%s concept=%s assigned_role=%s reason=role_mismatch",
                    agent_id, concept_id, role,
                )
            return permitted

        # Unassigned agent_id (e.g. ephemeral panel sub-agent like "dr-001").
        # Permit if the concept is owned by (or is a sub-concept of) any assigned role.
        # Sub-concept URIs use the pattern urn:concept:<use-case>:<role-leaf>:<specific>
        # where the role-leaf segment appears in the sub-concept URI.
        state = self._store.current()
        if state is not None:
            for assigned_concept in state.role_assignments.values():
                # Direct match or sub-concept via startswith (same-prefix URIs)
                if concept_id == assigned_concept or concept_id.startswith(assigned_concept):
                    return True
                # Sub-concept URI: extract leaf segment (after last ':') and check containment
                leaf = assigned_concept.rsplit(":", 1)[-1]
                if leaf and leaf in concept_id:
                    return True

        LOGGER.debug(
            "gate.suppressed agent=%s concept=%s reason=no_role_assignment",
            agent_id, concept_id,
        )
        return False

    def check_coordination(self, agent_id: str, concept_id: str) -> bool:
        """Convenience wrapper for coordination turns (always sets coordination=True)."""
        return self.check(agent_id, concept_id, coordination=True)


__all__ = ["PhaseGate"]

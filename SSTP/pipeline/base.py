# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SubprotocolBase — abstract base class for all SSTP subprotocol implementations.

Generated subprotocol base classes (e.g. SIEPBase) extend this.
Concrete implementations extend the generated base and fill in the abstract hooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ioc_l9.src import L9
from SSTP.pipeline.phase import Phase, PhaseRejectedError


class SubprotocolBase(ABC):
    """
    Base class for all SSTP subprotocol implementations.

    Subclasses (typically generated from a .ioc DSL spec) declare:
      - name            : protocol identifier string
      - version         : semver string
      - active_phases   : phases this subprotocol participates in
      - allowed_kinds   : per-phase set of permitted L9 kinds
      - concurrent_phases: phases that may run in parallel with others
      - _gate_methods   : mapping of Phase → gate-predicate method name

    Concrete implementations override the abstract gate predicates and handle().
    """

    # --- class-level declarations (set by generated subclass) ---
    name: str = ""
    version: str = ""
    active_phases: List[Phase] = []
    allowed_kinds: Dict[Phase, List[str]] = {}
    concurrent_phases: List[Phase] = []

    def __init__(self) -> None:
        # Phase pointer: index into active_phases
        self._phase_index: int = 0
        # Per-subprotocol private state (opaque dict — concrete impl may use any type)
        self._state: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Phase tracking
    # ------------------------------------------------------------------

    @property
    def current_phase(self) -> Phase:
        if not self.active_phases:
            raise RuntimeError(f"{self.__class__.__name__} has no active_phases declared.")
        return self.active_phases[self._phase_index]

    def accepts(self, msg: L9) -> bool:
        """Return True if this subprotocol handles msg in its current phase."""
        phase = self.current_phase
        return msg.header.kind in self.allowed_kinds.get(phase, [])

    def route(self, msg: L9) -> List[L9]:
        """
        Dispatch msg through the subprotocol after phase-validity check.
        Raises PhaseRejectedError if the kind is not allowed in the current phase.
        """
        if not self.accepts(msg):
            raise PhaseRejectedError(msg.header.kind, self.current_phase, self.name)
        responses = self.handle(msg)
        self._maybe_advance(msg)
        return responses

    def check_phase_advance(self) -> bool:
        """
        Evaluate the gate predicate for the current phase.
        If satisfied, advance to the next phase. Returns True if advanced.
        """
        gate = self._gate_for(self.current_phase)
        if gate is not None and gate(self._state):
            return self._advance_phase()
        return False

    def _maybe_advance(self, msg: L9) -> None:  # noqa: ARG002
        """Called after handle() — advances through all immediately-satisfied gates."""
        while self.check_phase_advance():
            pass

    def _advance_phase(self) -> bool:
        if self._phase_index < len(self.active_phases) - 1:
            self._phase_index += 1
            return True
        return False

    def _gate_for(self, phase: Phase):
        """Return the gate callable for a given phase, or None."""
        gate_name = getattr(self, "_gate_methods", {}).get(phase)
        if gate_name:
            return getattr(self, gate_name, None)
        return None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    def handle(self, msg: L9) -> List[L9]:
        """
        Default dispatcher — overridden by generated subclass handle().
        Subclasses with no handlers return empty list.
        """
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def phase_summary(self) -> Dict[str, Any]:
        return {
            "subprotocol": self.name,
            "version": self.version,
            "current_phase": self.current_phase.value,
            "phase_index": self._phase_index,
            "total_phases": len(self.active_phases),
        }

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} name={self.name!r} "
            f"phase={self.current_phase.value!r}>"
        )


__all__ = ["SubprotocolBase"]

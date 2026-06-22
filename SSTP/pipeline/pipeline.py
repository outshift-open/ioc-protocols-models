# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTPipeline — orchestrates message routing across registered subprotocols.
BaseEpisode — centralized phase + per-subprotocol state container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ioc_l9.src import L9
from SSTP.pipeline.base import SubprotocolBase
from SSTP.pipeline.phase import Phase, PhaseRejectedError


@dataclass
class SubprotocolSlice:
    """Per-subprotocol state slice stored inside BaseEpisode."""
    name: str
    current_phase: Phase
    private_state: Dict[str, Any] = field(default_factory=dict)


class BaseEpisode:
    """
    Centralized episode state. Tracks:
      - The overall pipeline phase (derived from subprotocol states)
      - A private state slice for each registered subprotocol

    The phase itself is NOT in the L9 wire format — it is managed here.
    """

    def __init__(self, subprotocols: List[SubprotocolBase]) -> None:
        self._subprotocols: Dict[str, SubprotocolBase] = {
            sp.name: sp for sp in subprotocols
        }
        self._slices: Dict[str, SubprotocolSlice] = {
            sp.name: SubprotocolSlice(name=sp.name, current_phase=sp.current_phase)
            for sp in subprotocols
        }

    def sync(self) -> None:
        """Sync slice snapshots from subprotocol live state."""
        for name, sp in self._subprotocols.items():
            self._slices[name].current_phase = sp.current_phase
            self._slices[name].private_state = sp._state.copy()

    def summary(self) -> Dict[str, Any]:
        self.sync()
        return {
            name: {
                "current_phase": s.current_phase.value,
                "private_state": s.private_state,
            }
            for name, s in self._slices.items()
        }

    def get_slice(self, name: str) -> Optional[SubprotocolSlice]:
        return self._slices.get(name)


class SSTPipeline:
    """
    Routes incoming L9 messages to the appropriate registered subprotocol(s).

    Routing rules:
      - A message is delivered to every subprotocol that accepts it
        (i.e. its kind is allowed in that subprotocol's current phase).
      - If NO subprotocol accepts the message, PhaseRejectedError is raised.
      - After handling, each subprotocol checks whether its phase gate is satisfied
        and advances automatically.
    """

    def __init__(self, subprotocols: List[SubprotocolBase]) -> None:
        self._subprotocols = subprotocols
        self.episode = BaseEpisode(subprotocols)

    def process(self, msg: L9) -> List[L9]:
        """Route msg, collect responses, advance phases. Returns all responses."""
        accepted = [sp for sp in self._subprotocols if sp.accepts(msg)]
        if not accepted:
            # Build a helpful error listing which phases are active
            phases = {sp.name: sp.current_phase.value for sp in self._subprotocols}
            raise PhaseRejectedError(
                kind=msg.header.kind,
                current_phase=list(self._subprotocols[0].active_phases)[0]
                if self._subprotocols else Phase.PLANNING,
                subprotocol=f"any — active phases: {phases}",
            )

        responses: List[L9] = []
        for sp in accepted:
            responses.extend(sp.route(msg))

        self.episode.sync()
        return responses

    def phase_summary(self) -> Dict[str, Any]:
        return self.episode.summary()

    def __repr__(self) -> str:
        sps = ", ".join(sp.name for sp in self._subprotocols)
        return f"<SSTPipeline subprotocols=[{sps}]>"


__all__ = ["BaseEpisode", "SubprotocolSlice", "SSTPipeline"]

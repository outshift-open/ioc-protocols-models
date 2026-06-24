# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""SIEP-specific data models that extend the L9 wheel primitives.

This module provides:
  - ``Actors``        — alias for the wheel's ``ParticipantSet``
  - ``Message``       — alias for the wheel's ``Message``
  - ``SIEPEpistemic`` — SIEP epistemic block stored in header.attributes["epistemic"]
  - ``siep_parents``  — decode parents list from a received L9 message
  - ``siep_epistemic``— decode SIEPEpistemic from a received L9 message
"""

from __future__ import annotations

import json
from typing import List, Optional

from pydantic import BaseModel

from ai.outshift.data_model import L9, Message, ParticipantSet


# ── SIEPEpistemic ─────────────────────────────────────────────────────────────

class SIEPEpistemic(BaseModel):
    """Epistemic metadata stored in ``header.attributes["epistemic"]``.

    The base L9 ``Epistemic`` model is intentionally empty; SIEP stores its
    richer epistemic state here so it survives round-trips without modifying the
    shared wheel.
    """

    message_act: Optional[str] = None
    state: Optional[str] = None
    belief_status: Optional[str] = None
    concept_id: Optional[str] = None
    uncertainty: float = 0.0
    epistemic_kind: str = "siep"


# ── Helpers ───────────────────────────────────────────────────────────────────

def siep_parents(msg: L9) -> List[str]:
    """Return the parents list from a received L9 message (decodes JSON string)."""
    raw = msg.header.message.parents if msg.header.message else None
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def siep_epistemic(msg: L9) -> Optional[SIEPEpistemic]:
    """Return the SIEPEpistemic block from ``header.attributes``, or None."""
    attrs = msg.header.attributes
    if not attrs or "epistemic" not in attrs:
        return None
    data = attrs["epistemic"]
    if not isinstance(data, dict):
        return None
    return SIEPEpistemic(**data)


__all__ = [
    "ParticipantSet",
    "Message",
    "SIEPEpistemic",
    "siep_parents",
    "siep_epistemic",
]

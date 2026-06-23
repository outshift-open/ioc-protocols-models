# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

<<<<<<< HEAD:ioc_l9/src/epistemic.py
"""Epistemic state carried in an L9 message header."""

from typing import Optional
=======
"""
Epistemic state — represents a participant's belief, knowledge, and uncertainty
about the world or about a specific message/task at a point in time.

Included as an optional field in L9Header so participants can signal confidence
levels, known unknowns, or prior beliefs to downstream message handlers.
Fields are TBD and will expand as the epistemic protocol matures.
"""
>>>>>>> main:src/epistemic.py

from pydantic import BaseModel, ConfigDict


class Epistemic(BaseModel):
<<<<<<< HEAD:ioc_l9/src/epistemic.py
    """Agent epistemic state at send time. Extensible via model_config extra='allow'."""

    model_config = ConfigDict(extra="allow")

    message_act: Optional[str] = None
    state: Optional[str] = None
    belief_status: Optional[str] = None
    concept_id: Optional[str] = None
    uncertainty: float = 0.0
    epistemic_kind: str = "siep"
=======
    """
    Participant epistemic (belief/knowledge) state at the time the message was sent.
    Currently a placeholder — fields will be added as the model is defined.
    """
    # TODO: add fields — e.g. confidence: float, known_unknowns: list[str], belief_state: dict
>>>>>>> main:src/epistemic.py

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
Epistemic state — represents a participant's belief, knowledge, and uncertainty
about the world or about a specific message/task at a point in time.

Included as an optional field in L9Header so participants can signal confidence
levels, known unknowns, or prior beliefs to downstream message handlers.
Fields are TBD and will expand as the epistemic protocol matures.
"""

from pydantic import BaseModel


class Epistemic(BaseModel):
    """
    Participant epistemic (belief/knowledge) state at the time the message was sent.
    Currently a placeholder — fields will be added as the model is defined.
    """
    # TODO: add fields — e.g. confidence: float, known_unknowns: list[str], belief_state: dict

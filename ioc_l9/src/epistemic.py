# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Epistemic state carried in an L9 message header."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class Epistemic(BaseModel):
    """Agent epistemic state at send time. Extensible via model_config extra='allow'."""

    model_config = ConfigDict(extra="allow")

    message_act: Optional[str] = None
    state: Optional[str] = None
    belief_status: Optional[str] = None
    concept_id: Optional[str] = None
    uncertainty: float = 0.0
    epistemic_kind: str = "siep"

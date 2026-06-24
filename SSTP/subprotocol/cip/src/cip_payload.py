# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""CIP-specific Pydantic payload model — the CIP portion of L9.payload."""

from __future__ import annotations

import enum
from typing import List, Optional

from pydantic import BaseModel

CIP_SCHEMA_URN = "urn:ioc:cip:payload:v1"
CIP_ONTOLOGY_REF = "protocol/ontology/cip_ontology.ttl"


class RepairReason(str, enum.Enum):
    """Canonical repair reason vocabulary — upper-case names, lower-case wire values."""
    GROUNDING_FAILURE = "grounding_failure"
    SCOPE_MISMATCH = "scope_mismatch"
    UNGROUNDABLE_NOVELTY = "ungroundable_novelty"
    DELIVERY_FAILURE = "delivery_failure"
    # lower-case aliases for backwards compat with old builder usage
    grounding_failure = "grounding_failure"
    scope_mismatch = "scope_mismatch"
    ungroundable_novelty = "ungroundable_novelty"
    delivery_failure = "delivery_failure"


class CIPUtteranceBlock(BaseModel):
    text: Optional[str] = None
    evidence: List[str] = []
    addresses_evidence: List[str] = []
    ring_round: int = 0    # pass through the agent ring (0 = first pass)
    repair_depth: int = 0  # recursion depth within a repair branch (0 = not in repair)


class CIPGroundingBlock(BaseModel):
    contingency_verified: Optional[bool] = None
    contingency_score: Optional[float] = None
    repair_reason: Optional[str] = None
    challenges: List[str] = []


class CIPBeliefBlock(BaseModel):
    prior: float = 0.5
    posterior: float = 0.5
    revision_cause: Optional[str] = None


class CIPMessagePayload(BaseModel):
    """CIP protocol payload — goes under L9Payload.data when type='cip'."""

    utterance: CIPUtteranceBlock = CIPUtteranceBlock()
    grounding: CIPGroundingBlock = CIPGroundingBlock()
    belief: CIPBeliefBlock = CIPBeliefBlock()


__all__ = [
    "CIP_SCHEMA_URN",
    "CIP_ONTOLOGY_REF",
    "CIPMessagePayload",
    "CIPUtteranceBlock",
    "CIPGroundingBlock",
    "CIPBeliefBlock",
]

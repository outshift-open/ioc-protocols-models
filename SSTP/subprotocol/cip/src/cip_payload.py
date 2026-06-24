# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""CIP-specific Pydantic payload model — the CIP portion of L9.payload."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

CIP_SCHEMA_URN = "urn:ioc:cip:payload:v1"
CIP_ONTOLOGY_REF = "protocol/ontology/cip_ontology.ttl"


class CIPUtteranceBlock(BaseModel):
    text: Optional[str] = None
    evidence: List[str] = []
    addresses_evidence: List[str] = []
    turn_depth: int = 0


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

# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0
"""SIEP-specific Pydantic payload model — the SIEP portion of L9.payload."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from SSTP.subprotocol.common.data_models.drift_dectection import DriftDetectionOutput

SIEP_SCHEMA_URN = "urn:ioc:siep:payload:v1"
SIEP_ONTOLOGY_REF = "protocol/ontology/siep_ontology.ttl"


class SIEPUtteranceBlock(BaseModel):
    text: Optional[str] = None
    evidence: List[str] = []
    addresses_evidence: List[str] = []
    ring_round: int = 0    # pass through the agent ring (0 = first pass)
    repair_depth: int = 0  # recursion depth within a repair branch (0 = not in repair)


class SIEPGroundingBlock(BaseModel):
    contingency_verified: Optional[bool] = None
    contingency_score: Optional[float] = None
    repair_reason: Optional[str] = None
    challenges: List[str] = []


class SIEPBeliefBlock(BaseModel):
    prior: float = 0.5
    posterior: float = 0.5
    revision_cause: Optional[str] = None


class SIEPMessagePayload(BaseModel):
    """SIEP protocol payload — goes under L9Payload.data when type='siep'."""

    utterance: SIEPUtteranceBlock = SIEPUtteranceBlock()
    grounding: SIEPGroundingBlock = SIEPGroundingBlock()
    belief: SIEPBeliefBlock = SIEPBeliefBlock()
    drift_detection: Optional[DriftDetectionOutput] = None  # optional drift detection output


__all__ = [
    "SIEP_SCHEMA_URN",
    "SIEP_ONTOLOGY_REF",
    "SIEPMessagePayload",
    "SIEPUtteranceBlock",
    "SIEPGroundingBlock",
    "SIEPBeliefBlock",
]

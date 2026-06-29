# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Contingency Interaction Protocol (CIP) Python implementation."""

from .engine import CIPEngine, CIPEngineConfig, IEEngine, IEEngineConfig
from .grounding import contingency_check, diagnose_repair_reason
from .message import (
    CIPPayload,
    CIPUtteranceBlock,
    CIPGroundingBlock,
    CIPBeliefBlock,
    IEPayload,
    IEUtteranceBlock,
    IEGroundingBlock,
    IEBeliefBlock,
    ProcessPayload,
    get_part,
)
from .tom import TheoryOfMindEngineBase, normalize_alignment, normalize_tom_snapshot
from .cip_payload import CIPMessagePayload, RepairReason

# CIPMessageBuilder and CIPProcessor depend on the ai.outshift.data_model pydantic
# wheel from SSTP/language_bindings/python.  Guard so the rest of the package
# imports cleanly without the wheel on sys.path.
try:
    from .builder import CIPMessageBuilder
    from .processor import CIPProcessor
    _BUILDER_AVAILABLE = True
except ImportError:
    _BUILDER_AVAILABLE = False

__all__ = [
    "TheoryOfMindEngineBase",
    "normalize_alignment",
    "normalize_tom_snapshot",
    "CIPPayload",
    "CIPUtteranceBlock",
    "CIPGroundingBlock",
    "CIPBeliefBlock",
    "IEPayload",
    "IEUtteranceBlock",
    "IEGroundingBlock",
    "IEBeliefBlock",
    "ProcessPayload",
    "get_part",
    "CIPEngine",
    "CIPEngineConfig",
    "IEEngine",
    "IEEngineConfig",
    "contingency_check",
    "diagnose_repair_reason",
    "CIPMessagePayload",
    "RepairReason",
    "CIPMessageBuilder",
    "CIPProcessor",
]

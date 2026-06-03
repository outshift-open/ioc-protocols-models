# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
protocol.ie — Interaction Engine protocol specialisation.

Provides the IE-specific L9 header builder and the episode adapter that
converts IE runtime episodes into ``interaction_engine_protocol`` events.

Wire envelope schema: ``protocol/ie/interaction_engine_protocol.schema.json``
"""

from .l9 import (
    INTERACTION_ENGINE_PROTOCOL,
    INTERACTION_ENGINE_PROTOCOL_VERSION,
    IEL9HeaderBuilder,
    build_l9_header,
    canonical_event_type,
    kind_for_event_type,
    schema_id_for,
)
from .adapter import InteractionProtocolAdapter
from .tom import (
    TheoryOfMindEngineBase,
    normalize_alignment,
    normalize_tom_snapshot,
)
from .assertion import (
    AgentIdentity,
    AssertionVerificationError,
    UtteranceAssertion,
    build_assertion,
    verify_assertion,
)
from .message import (
    IEPayload,
    IEUtteranceBlock,
    IEGroundingBlock,
    IEBeliefBlock,
)
from .agent_bus import AgentBus
from .epistemic_store import EpistemicStore
from .ie_engine import IEEngine, IEEngineConfig

__all__ = [
    "INTERACTION_ENGINE_PROTOCOL",
    "INTERACTION_ENGINE_PROTOCOL_VERSION",
    "IEL9HeaderBuilder",
    "build_l9_header",
    "canonical_event_type",
    "kind_for_event_type",
    "schema_id_for",
    "InteractionProtocolAdapter",
    # ToM normalization utilities and interfaces
    "normalize_tom_snapshot",
    "normalize_alignment",
    "TheoryOfMindEngineBase",
    # Assertion types
    "AgentIdentity",
    "UtteranceAssertion",
    "AssertionVerificationError",
    "build_assertion",
    "verify_assertion",
    # IE payload envelopes
    "IEPayload",
    "IEUtteranceBlock",
    "IEGroundingBlock",
    "IEBeliefBlock",
    # SDK: domain-agnostic bus, store, and engine
    "AgentBus",
    "EpistemicStore",
    "IEEngine",
    "IEEngineConfig",
]

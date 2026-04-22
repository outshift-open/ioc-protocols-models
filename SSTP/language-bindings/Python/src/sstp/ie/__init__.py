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
    AgentResponsibility,
    DiscourseEntry,
    GraphEdge,
    GraphNode,
    KnowledgeGraphNode,
    KnowledgeGraphVisualization,
    SocialState,
    TheoryOfMindEngineBase,
    TheoryOfMindState,
    TOMPairChannelBase,
    normalize_alignment,
    normalize_tom_snapshot,
)

__all__ = [
    "INTERACTION_ENGINE_PROTOCOL",
    "INTERACTION_ENGINE_PROTOCOL_VERSION",
    "IEL9HeaderBuilder",
    "build_l9_header",
    "canonical_event_type",
    "kind_for_event_type",
    "schema_id_for",
    "InteractionProtocolAdapter",
    # ToM types and interfaces
    "TheoryOfMindState",
    "SocialState",
    "KnowledgeGraphNode",
    "AgentResponsibility",
    "DiscourseEntry",
    "GraphEdge",
    "GraphNode",
    "KnowledgeGraphVisualization",
    "normalize_tom_snapshot",
    "normalize_alignment",
    "TheoryOfMindEngineBase",
    "TOMPairChannelBase",
]

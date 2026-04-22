# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
tom.py — Domain-independent Theory-of-Mind data types and abstract interfaces
for the Interaction Engine protocol layer.

These types capture the protocol-level abstractions that all ToM
implementations share across use cases (healthcare, travel, sales).
Domain-specific subclasses or extensions can build on these.

Abstract base classes (``TheoryOfMindEngineBase``, ``TOMPairChannelBase``)
define the contract every concrete ToM engine must satisfy.  Implementations
live in ``app/shared/core/`` and depend on an LLM backend; this module has
zero runtime dependencies beyond the standard library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Core ToM State ─────────────────────────────────────────────────────────────


@dataclass
class TheoryOfMindState:
    """Scalar belief model of a subject using application-defined dimensions.

    Dimensions are keyed by application-specific names (e.g. "trust",
    "urgency", "follow_through", "buy_intent").  No field names are
    prescribed at the protocol level; applications supply their own
    dimension vocabulary when constructing the engine.
    """

    dimensions: Dict[str, float] = field(default_factory=dict)

    def get(self, key: str, default: float = 0.0) -> float:
        return self.dimensions.get(key, default)

    def to_dict(self) -> Dict[str, float]:
        return dict(self.dimensions)


@dataclass
class SocialState(TheoryOfMindState):
    """Extended ToM state with multi-agent alignment tracking and repair signals.

    Adds engine-level coordination signals on top of the base dimension model.
    """

    agent_alignment: Dict[str, float] = field(default_factory=dict)
    derailment_detected: bool = False
    repair_depth: int = 0


# ── Knowledge Graph Types ──────────────────────────────────────────────────────


@dataclass
class KnowledgeGraphNode:
    """A fact, requirement, responsibility, constraint, or utterance in the
    social knowledge graph maintained by the interaction engine."""

    node_id: str
    node_type: str  # "requirement" | "responsibility" | "constraint" | "fact" | "utterance"
    agent_id: str
    description: str
    task_goal: str
    confidence: float = 0.8
    source: str = "prompt"  # "prompt" | "discourse" | "inference"
    created_at: int = 0
    last_updated: int = 0


@dataclass
class AgentResponsibility:
    """What a specific agent is responsible for doing."""

    agent_id: str
    responsibility_task: str
    requirements: List[str]
    constraints: List[str]
    derived_from: str = "prompt"  # "prompt" | "discourse"


@dataclass
class DiscourseEntry:
    """A peer-wise interaction record for knowledge graph updates."""

    source_agent: str
    target_agent: str
    utterance: str
    inferred_intent: str
    timestamp_ms: int
    alignment_with_graph: float = 0.5
    requires_repair: bool = False
    repair_recursion_depth: int = 0


# ── Graph Visualization Types ──────────────────────────────────────────────────


@dataclass
class GraphEdge:
    """Directed edge in the knowledge graph."""

    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str  # "responsibility" | "constraint" | "inference" | "discourse" | "alignment"
    label: str
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphNode:
    """Visualization-ready representation of a knowledge graph node."""

    node_id: str
    label: str
    node_type: str
    agent_id: str
    description: str
    confidence: float = 0.8
    x: float = 0.0
    y: float = 0.0
    color: str = "#3498db"
    size: float = 30.0
    icon: str = "node"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeGraphVisualization:
    """Complete visualization-ready export of the knowledge graph."""

    graph_id: str
    timestamp_ms: int
    episode_id: str
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    agent_groups: Dict[str, List[str]] = field(default_factory=dict)
    graph_metrics: Dict[str, Any] = field(default_factory=dict)


# ── Protocol Normalization ─────────────────────────────────────────────────────


def normalize_tom_snapshot(value: Any) -> Dict[str, Any]:
    """Normalize a ToM snapshot dict to a canonical float-valued dimension map.

    All keys whose values are numeric are preserved; non-numeric values are
    dropped.  No dimension names are prescribed — the caller supplies whatever
    vocabulary their application uses.
    """
    source = value if isinstance(value, dict) else {}

    def _as_float(v: Any) -> float | None:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return None
        return None

    return {k: f for k, v in source.items() if (f := _as_float(v)) is not None}


def normalize_alignment(value: Any, fallback_task_goal: str | None = None) -> Dict[str, Any]:
    """Normalize an alignment assessment dict to the canonical fields."""

    def _as_float(v: Any) -> float | None:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return None
        return None

    if not isinstance(value, dict):
        return {
            "task_goal": fallback_task_goal,
            "aligned": None,
            "alignment_score": None,
            "disagreement_score": None,
            "rationale": None,
        }

    aligned = value.get("aligned")
    if not isinstance(aligned, bool):
        aligned = None

    alignment_score = _as_float(value.get("alignment_score"))
    if alignment_score is not None:
        alignment_score = max(0.0, min(1.0, alignment_score))

    disagreement_score = _as_float(value.get("disagreement_score"))
    if disagreement_score is not None:
        disagreement_score = max(0.0, min(1.0, disagreement_score))

    rationale = value.get("rationale")
    if rationale is not None:
        rationale = str(rationale)

    task_goal = value.get("task_goal", fallback_task_goal)
    if task_goal is not None:
        task_goal = str(task_goal)

    return {
        "task_goal": task_goal,
        "aligned": aligned,
        "alignment_score": alignment_score,
        "disagreement_score": disagreement_score,
        "rationale": rationale,
    }


# ── Abstract Engine Interfaces ─────────────────────────────────────────────────


class TheoryOfMindEngineBase(ABC):
    """Contract every concrete ToM engine must satisfy.

    Concrete implementations live in ``app/shared/core/cognition.py`` and
    depend on an LLM backend.  This interface lives here so protocol-layer
    code can type-annotate against it without importing any runtime
    dependencies.
    """

    @abstractmethod
    def assess_task_alignment(
        self, actor: str, task_goal: str, utterance: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return alignment assessment dict for a single utterance."""

    @abstractmethod
    def analyze_inter_agent_tom(
        self,
        subject_view: Dict[str, float],
        left_view: Dict[str, float],
        right_view: Dict[str, float],
        task_goal: str,
    ) -> Dict[str, Any]:
        """Return pairwise dimension agreements between two agent views."""

    @abstractmethod
    def analyze_pairwise_agent_tom(
        self, agent_views: Dict[str, Dict[str, float]], task_goal: str
    ) -> Dict[str, Any]:
        """Return all-pairs alignment analysis across a set of agents."""

    @abstractmethod
    def update(
        self,
        view: Dict[str, float],
        utterance: str,
        task_goal: str,
        actor: str = "agent",
    ) -> Dict[str, float]:
        """Update the belief state given a new utterance; return updated view."""


class TOMPairChannelBase(ABC):
    """Contract for a ToM alignment/repair channel scoped to one agent pair.

    Implementations may disable ToM per-pair while keeping the protocol
    envelope active; in that case every method must return a deterministic
    neutral result so callers need no ``if channel.enabled:`` guards.
    """

    @abstractmethod
    def assess(
        self,
        speaker_view: Dict[str, float],
        listener_view: Dict[str, float],
        subject_view: Dict[str, float],
        task_goal: str,
    ) -> Dict[str, Any]:
        """Return inter-agent ToM metrics, or a neutral stub if disabled."""

    @abstractmethod
    def assess_utterance(
        self, utterance: str, task_goal: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return task-alignment assessment for a single utterance."""

    @abstractmethod
    def update(
        self,
        view: Dict[str, float],
        utterance: str,
        task_goal: str,
        actor: str = "peer_agent",
    ) -> Dict[str, float]:
        """Update the ToM belief for the listener side; returns updated view. No-op if disabled."""


__all__ = [
    # Core state types
    "TheoryOfMindState",
    "SocialState",
    # Knowledge graph types
    "KnowledgeGraphNode",
    "AgentResponsibility",
    "DiscourseEntry",
    # Graph visualization types
    "GraphEdge",
    "GraphNode",
    "KnowledgeGraphVisualization",
    # Protocol normalization
    "normalize_tom_snapshot",
    "normalize_alignment",
    # Abstract interfaces
    "TheoryOfMindEngineBase",
    "TOMPairChannelBase",
]

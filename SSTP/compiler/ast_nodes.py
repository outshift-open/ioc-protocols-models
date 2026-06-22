# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
AST node dataclasses produced by the .ioc parser.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GateNode:
    """A gate predicate call: (predicate-name?)"""
    predicate: str        # e.g. "repairs-resolved?"


@dataclass
class PhaseNode:
    """A (phase :name ...) declaration."""
    name: str             # e.g. "execution"
    kinds: List[str]      # e.g. ["exchange", "contingency"]
    subkinds: List[str]   # e.g. ["query"]  (may be empty)
    concurrent: bool      # whether this phase may run in parallel
    gate: GateNode


@dataclass
class SequentialNode:
    """(sequential phase-or-group ...)"""
    children: List[PhaseNode | "ParallelNode"]


@dataclass
class ParallelNode:
    """(parallel phase-or-group ...)"""
    children: List[PhaseNode | SequentialNode]


@dataclass
class PipelineNode:
    """(pipeline sequential-or-parallel)"""
    root: SequentialNode | ParallelNode


@dataclass
class ProtocolNode:
    """Top-level (defprotocol NAME ...) node."""
    name: str
    version: str
    description: str
    pipeline: PipelineNode


__all__ = [
    "GateNode", "PhaseNode", "SequentialNode", "ParallelNode",
    "PipelineNode", "ProtocolNode",
]

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
class HandlerNode:
    """A (handler :kind ...) declaration within a phase."""
    kind: str               # message kind handled e.g. "exchange"
    fn: str                 # function name in snake_case e.g. "on_exchange"
    reads: List[str]        # L9 field paths consumed
    returns: List[str]      # L9 kinds emitted
    pre: Optional[str]      # precondition predicate name (or None)
    post: Optional[str]     # postcondition predicate name (or None)
    mutates: List[str]      # internal state keys written
    raises: List[str]       # declared failure/error modes
    idempotent: bool        # safe to call multiple times?
    max_retries: int        # 0 = no retry
    doc: str                # docstring


@dataclass
class GateNode:
    """A gate predicate call: (predicate-name?)"""
    predicate: str        # e.g. "repairs-resolved?"


@dataclass
class PhaseNode:
    """A (phase :name ...) declaration."""
    name: str                   # e.g. "execution"
    kinds: List[str]            # e.g. ["exchange", "contingency"]
    subkinds: List[str]         # e.g. ["query"]  (may be empty)
    concurrent: bool            # whether this phase may run in parallel
    gate: GateNode
    handlers: List[HandlerNode] = field(default_factory=list)


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
    "HandlerNode", "GateNode", "PhaseNode", "SequentialNode", "ParallelNode",
    "PipelineNode", "ProtocolNode",
]

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
Python code generator — walks a ProtocolNode AST and emits a Python module
containing a generated abstract base class for the subprotocol.
"""

from __future__ import annotations

from typing import List

from SSTP.compiler.ast_nodes import (
    GateNode, PhaseNode, SequentialNode, ParallelNode, PipelineNode, ProtocolNode,
)


def _snake(name: str) -> str:
    """Convert kebab-case / hyphenated names to snake_case."""
    return name.replace("-", "_").replace("?", "")


def _phase_const(name: str) -> str:
    """e.g. 'state-management' → 'Phase.STATE_MANAGEMENT'"""
    return f"Phase.{name.replace('-', '_').upper()}"


def _collect_phases(node) -> List[PhaseNode]:
    """Flatten all PhaseNodes from the pipeline tree."""
    phases = []
    if isinstance(node, PhaseNode):
        phases.append(node)
    elif isinstance(node, (SequentialNode, ParallelNode)):
        for child in node.children:
            phases.extend(_collect_phases(child))
    elif isinstance(node, PipelineNode):
        phases.extend(_collect_phases(node.root))
    return phases


def _concurrent_phases(node) -> List[str]:
    """Return names of phases marked :concurrent true."""
    return [p.name for p in _collect_phases(node) if p.concurrent]


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


def generate_python(proto: ProtocolNode) -> str:
    """Return the full source of the generated Python base class module."""
    phases = _collect_phases(proto.pipeline)
    class_name = f"{proto.name}Base"
    concurrent = _concurrent_phases(proto.pipeline)

    # active_phases
    active_phases_items = ",\n        ".join(_phase_const(p.name) for p in phases)

    # allowed_kinds
    allowed_lines = []
    for p in phases:
        kinds_str = ", ".join(f'"{k}"' for k in p.kinds)
        allowed_lines.append(f"        {_phase_const(p.name)}: [{kinds_str}],")
    allowed_kinds_block = "\n".join(allowed_lines)

    # concurrent_phases
    concurrent_str = ", ".join(_phase_const(n) for n in concurrent)

    # _gate_methods
    gate_map_lines = []
    for p in phases:
        method = _snake(p.gate.predicate)
        gate_map_lines.append(f"        {_phase_const(p.name)}: \"{method}\",")
    gate_map_block = "\n".join(gate_map_lines)

    # abstract gate methods
    gate_methods = []
    for p in phases:
        method = _snake(p.gate.predicate)
        doc = f"Gate condition for phase: {p.name}. Return True to advance to the next phase."
        gate_methods.append(
            f"    @abstractmethod\n"
            f"    def {method}(self, state: Dict[str, Any]) -> bool:\n"
            f"        \"\"\"{doc}\"\"\"\n"
            f"        ..."
        )
    gate_methods_block = "\n\n".join(gate_methods)

    # phase table for docstring
    phase_table = ""
    for p in phases:
        concurrent_mark = " [concurrent]" if p.concurrent else ""
        phase_table += f"      {p.name:<20} kinds={p.kinds}  gate={p.gate.predicate}{concurrent_mark}\n"

    return (
        f"# Copyright 2026 Cisco Systems, Inc. and its affiliates\n"
        f"#\n"
        f"# SPDX-License-Identifier: Apache-2.0\n"
        f"#\n"
        f"# !! AUTO-GENERATED — do not edit by hand !!\n"
        f"# Generated from: SSTP/spec/{proto.name.lower()}.ioc\n"
        f"# Run:  python scripts/compile_spec.py SSTP/spec/{proto.name.lower()}.ioc\n"
        f"#\n"
        f"# {proto.description}\n"
        f"\n"
        f"from __future__ import annotations\n"
        f"\n"
        f"from abc import abstractmethod\n"
        f"from typing import Any, Dict, List\n"
        f"\n"
        f"from ioc_l9.src import L9\n"
        f"from SSTP.pipeline.base import SubprotocolBase\n"
        f"from SSTP.pipeline.phase import Phase\n"
        f"\n"
        f"\n"
        f"class {class_name}(SubprotocolBase):\n"
        f"    \"\"\"\n"
        f"    Generated base class for the {proto.name} subprotocol (v{proto.version}).\n"
        f"\n"
        f"    Concrete implementations must extend this class and:\n"
        f"      1. Override each abstract gate predicate (see below).\n"
        f"      2. Implement handle(msg) to process accepted messages.\n"
        f"\n"
        f"    Phase pipeline:\n"
        f"{phase_table}"
        f"    \"\"\"\n"
        f"\n"
        f"    name    = \"{proto.name}\"\n"
        f"    version = \"{proto.version}\"\n"
        f"\n"
        f"    active_phases: List[Phase] = [\n"
        f"        {active_phases_items},\n"
        f"    ]\n"
        f"\n"
        f"    allowed_kinds: Dict[Phase, List[str]] = {{\n"
        f"{allowed_kinds_block}\n"
        f"    }}\n"
        f"\n"
        f"    concurrent_phases: List[Phase] = [{concurrent_str}]\n"
        f"\n"
        f"    _gate_methods: Dict[Phase, str] = {{\n"
        f"{gate_map_block}\n"
        f"    }}\n"
        f"\n"
        f"    # ------------------------------------------------------------------\n"
        f"    # Abstract gate predicates — implement in your concrete subclass\n"
        f"    # ------------------------------------------------------------------\n"
        f"\n"
        f"{gate_methods_block}\n"
        f"\n"
        f"    # ------------------------------------------------------------------\n"
        f"    # Abstract message handler\n"
        f"    # ------------------------------------------------------------------\n"
        f"\n"
        f"    @abstractmethod\n"
        f"    def handle(self, msg: L9) -> List[L9]:\n"
        f"        \"\"\"Process an accepted message. Called after phase validation.\"\"\"\n"
        f"        ...\n"
        f"\n"
        f"\n"
        f"__all__ = [\"{class_name}\"]\n"
    )


__all__ = ["generate_python"]

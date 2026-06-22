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
    HandlerNode, GateNode, PhaseNode, SequentialNode, ParallelNode, PipelineNode, ProtocolNode,
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


def _handler_method(h: HandlerNode) -> str:
    """Generate a single abstract handler method with full metadata docstring."""
    lines = [h.doc]
    lines.append("")
    if h.reads:
        lines.append(f"Reads:       {', '.join(h.reads)}")
    if h.returns:
        lines.append(f"Returns:     kinds={h.returns}")
    if h.pre:
        lines.append(f"Pre:         {h.pre}")
    if h.post:
        lines.append(f"Post:        {h.post}")
    if h.mutates:
        lines.append(f"Mutates:     {', '.join(h.mutates)}")
    if h.raises:
        lines.append(f"Raises:      {', '.join(h.raises)}")
    lines.append(f"Idempotent:  {h.idempotent}")
    if h.max_retries:
        lines.append(f"Max-retries: {h.max_retries}")
    docstring = "\n        ".join(lines)
    return (
        f"    @abstractmethod\n"
        f"    def {h.fn}(self, msg: L9, state: Dict[str, Any]) -> List[L9]:\n"
        f"        \"\"\"\n"
        f"        {docstring}\n"
        f"        \"\"\"\n"
        f"        ..."
    )


def _dispatcher(phases: List[PhaseNode]) -> str:
    """Generate the handle() dispatcher that routes to per-kind abstract methods."""
    # Collect all handlers across all phases, deduplicated by kind
    dispatch_entries = []
    seen = set()
    for p in phases:
        for h in p.handlers:
            key = (p.name, h.kind)
            if key not in seen:
                seen.add(key)
                dispatch_entries.append(
                    f"            ({_phase_const(p.name)}, \"{h.kind}\"): self.{h.fn},"
                )
    if not dispatch_entries:
        return (
            "    def handle(self, msg: L9) -> List[L9]:\n"
            "        \"\"\"Route message to the appropriate per-kind handler.\"\"\"\n"
            "        return []\n"
        )
    entries = "\n".join(dispatch_entries)
    return (
        "    def handle(self, msg: L9) -> List[L9]:\n"
        "        \"\"\"Route message to the appropriate per-kind handler (auto-generated).\"\"\"\n"
        "        dispatch = {\n"
        f"{entries}\n"
        "        }\n"
        "        fn = dispatch.get((self.current_phase, msg.header.kind))\n"
        "        return fn(msg, self._state) if fn else []\n"
    )


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

    # abstract handler methods (per kind, per phase)
    handler_methods = []
    for p in phases:
        for h in p.handlers:
            handler_methods.append(_handler_method(h))
    handler_methods_block = "\n\n".join(handler_methods)

    # generated dispatcher
    dispatcher_block = _dispatcher(phases)

    # phase table for docstring
    phase_table = ""
    for p in phases:
        concurrent_mark = " [concurrent]" if p.concurrent else ""
        handler_names = ", ".join(h.fn for h in p.handlers) or "—"
        phase_table += (
            f"      {p.name:<20} kinds={p.kinds}  "
            f"gate={p.gate.predicate}  handlers=[{handler_names}]{concurrent_mark}\n"
        )

    # concrete implementations note
    impl_note = (
        "      2. Implement each abstract handler method (see below).\n"
        "         handle() is auto-generated and dispatches by (phase, kind)."
    )

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
        f"{impl_note}\n"
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
        f"    # Abstract handler methods — implement in your concrete subclass\n"
        f"    # ------------------------------------------------------------------\n"
        f"\n"
        f"{handler_methods_block}\n"
        f"\n"
        f"    # ------------------------------------------------------------------\n"
        f"    # Auto-generated dispatcher — do not override\n"
        f"    # ------------------------------------------------------------------\n"
        f"\n"
        f"{dispatcher_block}\n"
        f"\n"
        f"__all__ = [\"{class_name}\"]\n"
    )


__all__ = ["generate_python"]

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
.ioc DSL parser — tokenises LISP-like source and builds an AST.

Grammar (informal):
  file         ::= comment* defprotocol
  defprotocol  ::= '(' 'defprotocol' SYMBOL kv* pipeline ')'
  pipeline     ::= '(' 'pipeline' group ')'
  group        ::= sequential | parallel
  sequential   ::= '(' 'sequential' (phase | group)* ')'
  parallel     ::= '(' 'parallel'   (phase | group)* ')'
  phase        ::= '(' 'phase' keyword kv* ')'
  kv           ::= keyword value
  value        ::= string | bool | vector | sexpr
  vector       ::= '[' keyword* ']'
  sexpr        ::= '(' SYMBOL* ')'
  keyword      ::= ':' SYMBOL
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Tuple

from SSTP.compiler.ast_nodes import (
    GateNode, PhaseNode, SequentialNode, ParallelNode, PipelineNode, ProtocolNode,
)

# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    ;[^\n]*           |   # line comment (skip)
    "(?:[^"\\]|\\.)*" |   # quoted string
    \[                |   # vec open
    \]                |   # vec close
    \(                |   # list open
    \)                |   # list close
    [^\s\(\)\[\]"]+       # atom (keyword, symbol, bool, etc.)
    """,
    re.VERBOSE,
)


def _tokenise(src: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall(src) if not t.startswith(";")]


# ---------------------------------------------------------------------------
# Reader (tokens → nested Python lists)
# ---------------------------------------------------------------------------

def _read(tokens: List[str], pos: int) -> Tuple[Any, int]:
    """Read one form starting at pos. Returns (form, new_pos)."""
    tok = tokens[pos]

    if tok == "(":
        items: List[Any] = []
        pos += 1
        while tokens[pos] != ")":
            item, pos = _read(tokens, pos)
            items.append(item)
        return items, pos + 1  # consume ')'

    if tok == "[":
        items = []
        pos += 1
        while tokens[pos] != "]":
            item, pos = _read(tokens, pos)
            items.append(item)
        return items, pos + 1  # consume ']'

    pos += 1
    if tok.startswith('"') and tok.endswith('"'):
        return tok[1:-1], pos   # strip quotes
    if tok == "true":
        return True, pos
    if tok == "false":
        return False, pos
    return tok, pos             # symbol / keyword atom


def _read_all(tokens: List[str]) -> Any:
    _, pos = _read(tokens, 0)
    return _


# ---------------------------------------------------------------------------
# AST builder (nested lists → ProtocolNode)
# ---------------------------------------------------------------------------

def _expect(form: list, index: int, value: str) -> None:
    if form[index] != value:
        raise SyntaxError(f"Expected {value!r} at position {index}, got {form[index]!r}")


def _kv_pairs(form: list, start: int) -> dict:
    """Extract :key value pairs from a flat list starting at *start*."""
    kvs: dict = {}
    i = start
    while i < len(form):
        tok = form[i]
        if isinstance(tok, str) and tok.startswith(":"):
            key = tok[1:]   # strip leading ':'
            val = form[i + 1]
            kvs[key] = val
            i += 2
        else:
            break
    return kvs, i


def _parse_gate(form: list) -> GateNode:
    """(predicate-name?)  → GateNode"""
    if not isinstance(form, list) or len(form) < 1:
        raise SyntaxError(f"Invalid gate form: {form!r}")
    return GateNode(predicate=form[0])


def _parse_phase(form: list) -> PhaseNode:
    """(phase :name :kinds [...] :subkinds [...] :concurrent bool :gate (...))"""
    _expect(form, 0, "phase")
    name_kw = form[1]
    if not name_kw.startswith(":"):
        raise SyntaxError(f"phase name must be a keyword, got {name_kw!r}")
    name = name_kw[1:]

    kvs, _ = _kv_pairs(form, 2)
    raw_kinds = kvs.get("kinds", [])
    kinds = [k[1:] if k.startswith(":") else k for k in raw_kinds]
    raw_subkinds = kvs.get("subkinds", [])
    subkinds = [k[1:] if k.startswith(":") else k for k in raw_subkinds]
    concurrent = kvs.get("concurrent", False)
    gate_form = kvs.get("gate")
    if gate_form is None:
        raise SyntaxError(f"phase {name!r} is missing :gate")
    gate = _parse_gate(gate_form if isinstance(gate_form, list) else [gate_form])

    return PhaseNode(
        name=name,
        kinds=kinds,
        subkinds=subkinds,
        concurrent=concurrent,
        gate=gate,
    )


def _parse_group(form: list):
    """(sequential ...) | (parallel ...) | (phase ...)"""
    head = form[0]
    if head == "sequential":
        children = [_parse_group(child) for child in form[1:] if isinstance(child, list)]
        return SequentialNode(children=children)
    if head == "parallel":
        children = [_parse_group(child) for child in form[1:] if isinstance(child, list)]
        return ParallelNode(children=children)
    if head == "phase":
        return _parse_phase(form)
    raise SyntaxError(f"Unknown group head: {head!r}")


def _parse_pipeline(form: list) -> PipelineNode:
    """(pipeline group)"""
    _expect(form, 0, "pipeline")
    group_form = form[1]
    return PipelineNode(root=_parse_group(group_form))


def _parse_defprotocol(form: list) -> ProtocolNode:
    """(defprotocol NAME :version ... :description ... (pipeline ...))"""
    _expect(form, 0, "defprotocol")
    name = form[1]
    kvs, next_i = _kv_pairs(form, 2)
    version = kvs.get("version", "0.0.1")
    description = kvs.get("description", "")
    # Find pipeline form
    pipeline_form = None
    for item in form[next_i:]:
        if isinstance(item, list) and item and item[0] == "pipeline":
            pipeline_form = item
            break
    if pipeline_form is None:
        raise SyntaxError("defprotocol missing (pipeline ...) form")
    return ProtocolNode(
        name=name,
        version=version,
        description=description,
        pipeline=_parse_pipeline(pipeline_form),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_ioc_string(src: str) -> ProtocolNode:
    tokens = _tokenise(src)
    form, _ = _read(tokens, 0)
    return _parse_defprotocol(form)


def parse_ioc_file(path: str | Path) -> ProtocolNode:
    src = Path(path).read_text(encoding="utf-8")
    return parse_ioc_string(src)


__all__ = ["parse_ioc_string", "parse_ioc_file"]

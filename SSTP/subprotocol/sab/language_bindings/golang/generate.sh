#!/usr/bin/env bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Generate Go types for the SAB JSON Schema.
#
# USAGE:
#   From project root: ./SSTP/subprotocol/sab/language_bindings/golang/generate.sh
#   From this directory: ./generate.sh
#
# PREREQUISITES:
#   go install github.com/atombender/go-jsonschema@latest
#   Both sab_schema.json and l9_schema.json must be present.
#
# OUTPUT:
#   SSTP/subprotocol/sab/language_bindings/golang/data_model.go
#
# The script runs in two steps:
#   1. go-jsonschema produces a self-contained file (L9 types inlined).
#   2. A post-processing pass removes duplicated L9 types and replaces them
#      with references to the l9 package, then fixes SABHeader / SABPayload
#      to use l9.* types for shared fields.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

SCHEMA_FILE="$PROJECT_ROOT/SSTP/subprotocol/sab/spec/sab_schema.json"
OUT_FILE="$SCRIPT_DIR/data_model.go"
PACKAGE="sab"
L9_MODULE="github.com/outshift-open/ioc-protocols-models/SSTP/language_bindings/golang"

echo "Generating Go SAB bindings..."
echo "  schema : $SCHEMA_FILE"
echo "  output : $OUT_FILE"

if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Error: schema not found at $SCHEMA_FILE"
    exit 1
fi

if ! command -v go-jsonschema &>/dev/null; then
    echo "  installing go-jsonschema..."
    go install github.com/atombender/go-jsonschema@latest
fi

# ---------------------------------------------------------------------------
# Step 1: auto-generate (produces self-contained file with L9 types inlined)
# ---------------------------------------------------------------------------
$(go env GOPATH)/bin/go-jsonschema \
    --capitalization ID \
    --capitalization URL \
    --package "$PACKAGE" \
    --output "$OUT_FILE" \
    "$SCHEMA_FILE"

echo "  auto-generation complete, post-processing..."

# ---------------------------------------------------------------------------
# Step 2: post-process
#   - keep only SAB-specific declarations (drop all L9 types)
#   - replace the single L9 type reference ([]Actor → []l9.Actor)
#   - append hand-crafted SABHeader, SABPayload, SAB using l9 package types
#   - rebuild import block
# ---------------------------------------------------------------------------
python3 - "$OUT_FILE" "$L9_MODULE" << 'PYEOF'
import re, sys

out_file  = sys.argv[1]
l9_module = sys.argv[2]

# Type-name prefixes that belong to the SAB package (not L9).
# Any top-level declaration whose name starts with one of these is kept.
KEEP_PREFIXES = (
    "SAB", "SAO", "Negotiate", "SemanticContext",
    "ResponseType", "ThreadState",
)

with open(out_file) as f:
    src = f.read()

lines = src.splitlines(keepends=True)

def split_declarations(src):
    """Yield (start, end) line-index ranges of each top-level declaration."""
    lines = src.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.startswith("package "):
            i += 1
            continue
        start = i
        # Consume leading comment lines.
        while i < len(lines) and lines[i].startswith("//"):
            i += 1
        if i >= len(lines):
            yield (start, i)
            break
        # Read declaration body using brace-depth tracking.
        depth = 0
        in_decl = False
        while i < len(lines):
            l = lines[i]
            depth += l.count("{") - l.count("}")
            if not in_decl and any(
                l.startswith(kw) for kw in
                ("type ", "func ", "var ", "const ", "import ")
            ):
                in_decl = True
            i += 1
            if in_decl and depth <= 0:
                break
        yield (start, i)

def decl_name(chunk):
    """Return the primary identifier of a top-level declaration, or None."""
    for l in chunk:
        l = l.strip()
        m = re.match(r'^type\s+(\w+)\b', l)
        if m:
            return m.group(1)
        # func (j *Foo) Bar → receiver type Foo
        m = re.match(r'^func\s+\(\w+\s+\*?(\w+)\)', l)
        if m:
            return m.group(1)
        # var enumValues_Foo = ...
        m = re.match(r'^var\s+(\w+)\b', l)
        if m:
            return m.group(1)
        # const FooBar FooType = "value"
        m = re.match(r'^const\s+(\w+)\b', l)
        if m:
            return m.group(1)
    return None

def is_sab_type(name):
    if not name:
        return False
    # var enumValues_NegotiateXxx → check the type suffix
    if name.startswith("enumValues_"):
        return any(name[len("enumValues_"):].startswith(p) for p in KEEP_PREFIXES)
    return any(name.startswith(p) for p in KEEP_PREFIXES)

kept = []
header_lines = []
in_header = True

for start, end in split_declarations(src):
    chunk = lines[start:end]
    text = "".join(chunk)

    if any(l.startswith("package ") or l.startswith("import ") for l in chunk):
        if in_header:
            header_lines.extend(chunk)
        continue

    name = decl_name(chunk)
    if not is_sab_type(name):
        continue

    in_header = False
    kept.append(text)

body = "\n".join(kept)

# The only L9 type referenced in SAB types is Actor (in SABActors.Actors []Actor).
# Replace []Actor with []l9.Actor (type-position only: preceded by []).
body = re.sub(r'(?<=\[\])Actor\b', 'l9.Actor', body)

# Collapse 3+ blank lines.
body = re.sub(r'\n{3,}', '\n\n', body)

# ---- Hand-crafted SABHeader, SABPayload, SAB ----
# go-jsonschema does not generate these as distinct types (it merges SAB
# constraints into the inlined L9Header/L9Payload). We define them manually
# so callers have a concrete SAB-aware envelope type.
sab_types = f'''
// SABHeader is the L9 header specialised for the SAB subprotocol.
type SABHeader struct {{
\tProtocol    string                `json:"protocol"                      yaml:"protocol"                      mapstructure:"protocol"`
\tSubprotocol string                `json:"subprotocol"                   yaml:"subprotocol"                   mapstructure:"subprotocol"`
\tKind        string                `json:"kind"                          yaml:"kind"                          mapstructure:"kind"`
\tSubkind     string                `json:"subkind"                       yaml:"subkind"                       mapstructure:"subkind"`
\tVersion     string                `json:"version"                       yaml:"version"                       mapstructure:"version"`
\tActors      SABActors             `json:"actors"                        yaml:"actors"                        mapstructure:"actors"`
\tAttributes  *SABAttributes        `json:"attributes,omitempty,omitzero" yaml:"attributes,omitempty"           mapstructure:"attributes,omitempty"`
\tContext     *l9.L9HeaderContext   `json:"context,omitempty,omitzero"    yaml:"context,omitempty"             mapstructure:"context,omitempty"`
\tMessage     *l9.L9HeaderMessage   `json:"message,omitempty,omitzero"    yaml:"message,omitempty"             mapstructure:"message,omitempty"`
\tPolicy      *l9.L9HeaderPolicy    `json:"policy,omitempty,omitzero"     yaml:"policy,omitempty"              mapstructure:"policy,omitempty"`
}}

// SABPayload is the L9 payload specialised for the SAB subprotocol.
type SABPayload struct {{
\tType string      `json:"type"                          yaml:"type"                          mapstructure:"type"`
\tData interface{{}} `json:"data,omitempty,omitzero"       yaml:"data,omitempty"                mapstructure:"data,omitempty"`
}}

// SAB is the root SAB message envelope (header + payload).
type SAB struct {{
\tHeader  SABHeader  `json:"header"  yaml:"header"  mapstructure:"header"`
\tPayload SABPayload `json:"payload" yaml:"payload" mapstructure:"payload"`
}}
'''

# ---- Rebuild file ----
import_block = (
    'import (\n'
    '\t"encoding/json"\n'
    '\t"errors"\n'
    '\t"fmt"\n'
    '\t"reflect"\n\n'
    f'\tl9 "{l9_module}"\n'
    ')\n'
)

package_line = next(
    (l for l in header_lines if l.startswith("package ")), "package sab\n"
)
preamble = (
    "// Code generated by github.com/atombender/go-jsonschema; "
    "post-processed to import l9 package.\n\n"
)

result = (
    preamble
    + package_line + "\n"
    + import_block + "\n"
    + body.lstrip("\n")
    + sab_types
)

with open(out_file, "w") as f:
    f.write(result)

print(f"  post-processing complete: {out_file}")
PYEOF

echo "  running gofmt..."
gofmt -w "$OUT_FILE"

echo "Done: $OUT_FILE"

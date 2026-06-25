#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Generate Python Pydantic models from the SAB JSON Schema.
#
# USAGE:
#   From project root: ./SSTP/subprotocol/sab/language_bindings/python/generate.sh
#   From this directory: ./generate.sh
#
# PREREQUISITES:
#   pip install datamodel-code-generator
#   Both sab_schema.json and l9_schema.json must be present.
#
# OUTPUT:
#   SSTP/subprotocol/sab/language_bindings/python/data_model.py
#
# The script runs in two steps:
#   1. datamodel-codegen produces a self-contained file (L9 types inlined).
#   2. A post-processing pass removes duplicated L9 types and replaces them
#      with imports from the L9 language binding, then fixes SABHeader /
#      SABPayload to extend their L9 base classes.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

SCHEMA_FILE="$PROJECT_ROOT/SSTP/subprotocol/sab/spec/sab_schema.json"
OUTPUT_FILE="$SCRIPT_DIR/data_model.py"

echo "Generating Python SAB bindings..."
echo "  schema : $SCHEMA_FILE"
echo "  output : $OUTPUT_FILE"

if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Error: schema not found at $SCHEMA_FILE"
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 1: auto-generate (produces self-contained file with L9 types inlined)
# ---------------------------------------------------------------------------
datamodel-codegen \
    --input "$SCHEMA_FILE" \
    --input-file-type jsonschema \
    --output "$OUTPUT_FILE" \
    --output-model-type pydantic_v2.BaseModel \
    --field-constraints \
    --collapse-root-models \
    --use-standard-collections \
    --use-union-operator \
    --target-python-version 3.10 \
    --wrap-string-literal \
    --use-title-as-name \
    --strict-nullable \
    --disable-timestamp

echo "  auto-generation complete, post-processing..."

# ---------------------------------------------------------------------------
# Step 2: post-process
#   - remove L9 type definitions (Actor, Context, L9Header, L9Payload, …)
#   - add import from the SSTP L9 language binding
#   - fix SABHeader → extends L9Header
#   - fix SABL9Payload → SABPayload, extends L9Payload
#   - rename root class SAB_L9 → SAB
# ---------------------------------------------------------------------------
python3 - "$OUTPUT_FILE" << 'PYEOF'
import re, sys

output_file = sys.argv[1]
with open(output_file) as f:
    content = f.read()

# L9 classes to strip (defined in the SSTP L9 language binding).
L9_CLASSES = [
    "Actor", "Actors", "Context", "Epistemic",
    "L9", "L9Header", "L9Payload",
    "Message", "PolicyLabel", "Provenance", "Semantic",
]

for cls in L9_CLASSES:
    # Match 'class Foo(...):\n    <indented body>\n' including trailing blank lines.
    pattern = rf"(?m)^class {cls}\b[^\n]*\n(?:(?:    [^\n]*)?\n)*"
    content = re.sub(pattern, "", content)

# Add L9 import (just before the pydantic import line).
l9_import = (
    "\nfrom src import L9Header, L9Payload\n"
    "from src.primitives import Actor, Context\n"
)
content = content.replace("from pydantic import", l9_import + "from pydantic import", 1)

# Fix inheritance and rename root types.
content = content.replace("class SABHeader(BaseModel):", "class SABHeader(L9Header):")
content = content.replace("class SABL9Payload(BaseModel):", "class SABPayload(L9Payload):")
content = content.replace("class SAB_L9(BaseModel):", "class SAB(BaseModel):")
content = content.replace("SABL9Payload", "SABPayload")
content = content.replace("SAB_L9", "SAB")

# datamodel-codegen names the allOf-constrained header/payload by their
# property key ("Header", "Payload") and roots from the $ref class ("SAB(L9)").
# Rename to SAB-prefixed names and drop the L9 base (SAB has its own typed fields).
content = content.replace("class Header(L9Header):", "class SABHeader(L9Header):")
content = content.replace("class Payload(L9Payload):", "class SABPayload(L9Payload):")
content = re.sub(r"class SAB\(L9[^)]*\):", "class SAB(BaseModel):", content)
content = re.sub(r"\bheader:\s+Header\b", "header: SABHeader", content)
content = re.sub(r"\bpayload:\s+Payload\b", "payload: SABPayload", content)

# Collapse 3+ consecutive blank lines to 2.
content = re.sub(r"\n{3,}", "\n\n", content)

COPYRIGHT = (
    "# Copyright 2026 Cisco Systems, Inc. and its affiliates\n"
    "#\n"
    "# SPDX-License-Identifier: Apache-2.0\n"
    "\n"
)
if not content.startswith("# Copyright"):
    content = COPYRIGHT + content

with open(output_file, "w") as f:
    f.write(content.strip() + "\n")

print(f"  post-processing complete: {output_file}")
PYEOF

if command -v black &>/dev/null; then
    echo "  formatting with black..."
    black "$OUTPUT_FILE" || echo "  warning: black formatting failed"
fi

echo "Done: $OUTPUT_FILE"

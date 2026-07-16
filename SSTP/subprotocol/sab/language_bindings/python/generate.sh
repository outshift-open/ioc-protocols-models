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
#
# OUTPUT:
#   SSTP/subprotocol/sab/language_bindings/python/ai/outshift/sab/data_model.py
#
# sab_schema.json is payload-only (it describes L9Payload.data — SAB does not
# redeclare the L9 header). So this is a single-step generation: no L9 types are
# inlined and there is no SAB envelope to rewrite. The L9 envelope is the
# canonical L9 core binding (ai.outshift.data_model); SABMessageBuilder in
# ../../src/builder.py assembles it.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

SCHEMA_FILE="$PROJECT_ROOT/SSTP/subprotocol/sab/spec/sab_schema.json"
OUTPUT_FILE="$SCRIPT_DIR/ai/outshift/sab/data_model.py"

echo "Generating Python SAB bindings..."
echo "  schema : $SCHEMA_FILE"
echo "  output : $OUTPUT_FILE"

if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Error: schema not found at $SCHEMA_FILE"
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"

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

echo "  generation complete, adding license header..."

# Prepend the SPDX license header (datamodel-codegen does not emit one).
python3 - "$OUTPUT_FILE" << 'PYEOF'
import sys

output_file = sys.argv[1]
with open(output_file) as f:
    content = f.read()

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

print(f"  license header applied: {output_file}")
PYEOF

if command -v black &>/dev/null; then
    echo "  formatting with black..."
    black "$OUTPUT_FILE" || echo "  warning: black formatting failed"
fi

echo "Done: $OUTPUT_FILE"

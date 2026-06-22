#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Generate Python Pydantic models from SAB JSON Schema.
# Uses datamodel-codegen to convert the SAB_l9 JSON schema
# to equivalent Pydantic v2 models with built-in validations.
#
# USAGE:
#   From project root: ./SSTP/subprotocol/sab/language_bindings/python/generate.sh
#   From this directory: ./generate.sh
#
# PREREQUISITES:
#   1. Install dependencies: poetry install
#   2. Ensure schema exists at: SSTP/subprotocol/sab/spec/sab_schema.json
#
# OUTPUT:
#   SSTP/subprotocol/sab/language_bindings/python/generated_models.py

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

SCHEMA_FILE="$PROJECT_ROOT/SSTP/subprotocol/sab/spec/sab_schema.json"
OUTPUT_FILE="$SCRIPT_DIR/generated_models.py"

echo "Generating Python bindings from SAB JSON Schema..."
echo "Schema file: $SCHEMA_FILE"
echo "Output file: $OUTPUT_FILE"

if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Error: Schema file not found at $SCHEMA_FILE"
    exit 1
fi

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

echo "Generated Python bindings successfully!"
echo "Output written to: $OUTPUT_FILE"

if command -v black &> /dev/null; then
    echo "Formatting generated code with black..."
    black "$OUTPUT_FILE" || echo "Warning: Failed to format with black"
fi

echo "Generation complete!"

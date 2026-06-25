#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Generate Python Pydantic models from JSON Schema
# This script uses datamodel-codegen to convert the IOC L9 JSON schema
# to equivalent Pydantic models with built-in validations
#
# USAGE:
#   From project root: ./SSTP/language_bindings/python/generate.sh
#   From this directory: ./generate.sh
#
# PREREQUISITES:
#   1. Install dependencies: poetry install
#   2. Ensure JSON schema exists at: SSTP/spec/l9_schema.json
#
# OUTPUT:
#   Generated models will be written to: ai/outshift/data_model.py

set -e

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Define paths
SCHEMA_FILE="$PROJECT_ROOT/SSTP/spec/l9_schema.json"
OUTPUT_FILE="$SCRIPT_DIR/ai/outshift/data_model.py"

mkdir -p "$(dirname "$OUTPUT_FILE")"

echo "Generating Python bindings from JSON Schema..."
echo "Schema file: $SCHEMA_FILE"
echo "Output file: $OUTPUT_FILE"

# Check if schema file exists
if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Error: Schema file not found at $SCHEMA_FILE"
    exit 1
fi

# Generate Python models using datamodel-codegen
poetry run datamodel-codegen \
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

# Prepend license header
LICENSE_HEADER="# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"
echo "${LICENSE_HEADER}$(cat "$OUTPUT_FILE")" > "$OUTPUT_FILE"

# Optional: Format the generated code
if command -v black &> /dev/null; then
    echo "Formatting generated code with black..."
    poetry run black "$OUTPUT_FILE" || echo "Warning: Failed to format with black"
fi

echo "Python bindings generated: $OUTPUT_FILE"

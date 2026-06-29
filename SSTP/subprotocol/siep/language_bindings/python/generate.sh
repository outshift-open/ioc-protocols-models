#!/bin/bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Generate Python Pydantic models from the SIEP JSON Schema.
# This script uses datamodel-codegen to convert the SIEP JSON schema
# (spec/siep_schema.json) into equivalent Pydantic models, mirroring
# the TFP binding generator.
#
# USAGE:
#   From project root: ./SSTP/subprotocol/siep/language_bindings/python/generate.sh
#   From this directory: ./generate.sh
#
# PREREQUISITES:
#   1. Install dependencies: poetry install
#   2. Ensure JSON schema exists at: <siep-root>/spec/siep_schema.json
#
# OUTPUT:
#   Generated models will be written to the namespaced wheel package:
#   ai/outshift/siep/data_model.py

set -e

# Resolve directories. This script lives in language_bindings/python/ under the
# SIEP root, mirroring the TFP generate.sh layout.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIEP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Define paths. The binding ships as the namespace-packaged wheel
# `ai-outshift-siep-data-model`, so models live under ai/outshift/siep/.
SCHEMA_FILE="$SIEP_ROOT/spec/siep_schema.json"
OUTPUT_FILE="$SCRIPT_DIR/ai/outshift/siep/data_model.py"

echo "Generating Python SIEP bindings from JSON Schema..."
echo "Schema file: $SCHEMA_FILE"
echo "Output file: $OUTPUT_FILE"

# Check if schema file exists
if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Error: Schema file not found at $SCHEMA_FILE"
    exit 1
fi

# Ensure the namespace package directory exists.
mkdir -p "$(dirname "$OUTPUT_FILE")"

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
    --use-subclass-enum \
    --capitalise-enum-members \
    --strict-nullable \
    --disable-timestamp

echo "Generated Python SIEP bindings successfully!"
echo "Output written to: $OUTPUT_FILE"

# Prepend copyright header
LICENSE_HEADER="# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"
echo "${LICENSE_HEADER}$(cat "$OUTPUT_FILE")" > "$OUTPUT_FILE"

# Optional: Format the generated code
if poetry run black --version &> /dev/null; then
    echo "Formatting generated code with black..."
    poetry run black "$OUTPUT_FILE" || echo "Warning: Failed to format with black"
fi

echo "Generation complete!"

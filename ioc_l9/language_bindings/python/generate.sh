#!/bin/bash

# Generate Python Pydantic models from JSON Schema
# This script uses datamodel-codegen to convert the IOC L9 JSON schema 
# to equivalent Pydantic models with built-in validations
#
# USAGE:
#   From project root: ./ioc_l9/language_bindings/python/generate.sh
#   From this directory: ./generate.sh
#
# PREREQUISITES:
#   1. Install dependencies: poetry install
#   2. Ensure JSON schema exists at: ioc_l9/spec/json_schema/l9.json
#
# OUTPUT:
#   Generated models will be written to: generated_models.py

set -e

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Define paths
SCHEMA_FILE="$PROJECT_ROOT/ioc_l9/spec/json_schema/l9.json"
OUTPUT_FILE="$SCRIPT_DIR/generated_models.py"

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

echo "Generated Python bindings successfully!"
echo "Output written to: $OUTPUT_FILE"

# Optional: Format the generated code
if command -v black &> /dev/null; then
    echo "Formatting generated code with black..."
    poetry run black "$OUTPUT_FILE" || echo "Warning: Failed to format with black"
fi

echo "Generation complete!"

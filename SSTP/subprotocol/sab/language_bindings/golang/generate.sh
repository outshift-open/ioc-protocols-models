#!/usr/bin/env bash

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Generate Go types for the SAB JSON Schema.
# Uses go-jsonschema to produce typed Go structs from the SAB schema.
#
# USAGE:
#   From project root: ./SSTP/subprotocol/sab/language_bindings/golang/generate.sh
#   From this directory: ./generate.sh
#
# PREREQUISITES:
#   go install github.com/atombender/go-jsonschema@latest
#   Ensure schema exists at: SSTP/subprotocol/sab/spec/sab_schema.json
#      (run SSTP/subprotocol/sab/spec/generate_sab_schema.py first if missing)
#
# OUTPUT:
#   SSTP/subprotocol/sab/language_bindings/golang/generated_models.go

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

SCHEMA_FILE="$PROJECT_ROOT/SSTP/subprotocol/sab/spec/sab_schema.json"
OUT_DIR="$SCRIPT_DIR"
PACKAGE="sab"

echo "Generating Go bindings from SAB JSON Schema..."
echo "Schema file: $SCHEMA_FILE"
echo "Output directory: $OUT_DIR"

if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Error: Schema file not found at $SCHEMA_FILE"
    echo "Run: python3 SSTP/subprotocol/sab/spec/generate_sab_schema.py"
    exit 1
fi

if ! command -v go-jsonschema &>/dev/null; then
    echo "Installing go-jsonschema..."
    go install github.com/atombender/go-jsonschema@latest
fi

echo "Generating Go types from: $SCHEMA_FILE"
$(go env GOPATH)/bin/go-jsonschema \
    --capitalization ID \
    --capitalization URL \
    --package "$PACKAGE" \
    --output "$OUT_DIR/generated_models.go" \
    "$SCHEMA_FILE"

echo "Running gofmt..."
gofmt -w "$OUT_DIR/generated_models.go"

echo "Go bindings generated successfully!"
echo "Generated: $OUT_DIR/generated_models.go"

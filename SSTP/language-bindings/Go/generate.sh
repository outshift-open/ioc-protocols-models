#!/usr/bin/env bash
# generate.sh — Generate Go types for the SSTP L9 schema.
#
# Uses go-jsonschema (github.com/atombender/go-jsonschema) to produce
# typed Go structs from the canonical SSTP JSON schema.
#
# Usage:
#   ./generate.sh
#   ./generate.sh --schema ../../JSON\ schema/sstp-schema.json
#
# Requirements:
#   go install github.com/atombender/go-jsonschema/cmd/go-jsonschema@latest

set -euo pipefail

SCHEMA="${1:-../../JSON schema/sstp-schema.json}"
OUT_DIR="sstp"
PACKAGE="sstp"

if ! command -v go-jsonschema &>/dev/null; then
  echo "Installing go-jsonschema..."
  go install github.com/atombender/go-jsonschema/cmd/go-jsonschema@latest
fi

echo "Generating Go types from: $SCHEMA"
go-jsonschema \
  --capitalization ID \
  --capitalization URL \
  --package "$PACKAGE" \
  --output "$OUT_DIR/l9_types.go" \
  "$SCHEMA"

echo "Running gofmt..."
gofmt -w "$OUT_DIR/l9_types.go"

echo "Done. Generated: $OUT_DIR/l9_types.go"

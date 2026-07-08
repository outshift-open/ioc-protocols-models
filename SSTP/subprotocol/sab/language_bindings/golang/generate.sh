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
#
# OUTPUT:
#   SSTP/subprotocol/sab/language_bindings/golang/data_model.go
#
# sab_schema.json is payload-only (it describes L9Payload.data — SAB does not
# redeclare the L9 header). So this is a single-step generation: no L9 types are
# inlined and there is no SAB envelope to hand-craft. The L9 envelope is the
# canonical L9 core Go binding (SSTP/language_bindings/golang).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

SCHEMA_FILE="$PROJECT_ROOT/SSTP/subprotocol/sab/spec/sab_schema.json"
OUT_FILE="$SCRIPT_DIR/data_model.go"
PACKAGE="sab"

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
GOJSONSCHEMA="$(command -v go-jsonschema || echo "$(go env GOPATH)/bin/go-jsonschema")"

"$GOJSONSCHEMA" \
    --capitalization ID \
    --capitalization URL \
    --package "$PACKAGE" \
    --output "$OUT_FILE" \
    "$SCHEMA_FILE"

echo "  generation complete, adding license header..."

# Prepend the SPDX license header if go-jsonschema did not emit one.
python3 - "$OUT_FILE" << 'PYEOF'
import sys

out_file = sys.argv[1]
with open(out_file) as f:
    content = f.read()

COPYRIGHT = (
    "// Copyright 2026 Cisco Systems, Inc. and its affiliates\n"
    "//\n"
    "// SPDX-License-Identifier: Apache-2.0\n"
    "\n"
)
if not content.startswith("// Copyright"):
    content = COPYRIGHT + content

with open(out_file, "w") as f:
    f.write(content)
print(f"  license header applied: {out_file}")
PYEOF

echo "  running gofmt..."
gofmt -w "$OUT_FILE"

echo "Done: $OUT_FILE"

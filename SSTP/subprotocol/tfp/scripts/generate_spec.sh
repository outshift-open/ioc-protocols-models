#!/bin/bash

# Generate the TFP JSON Schema from the source-of-truth Pydantic models.
# This script dumps the JSON Schema of src/tfp_models.py:TFPPayload and applies
# a small normalization pass so the schema (and the downstream language
# bindings generated from it) stay clean:
#   * nullable scalars become {"type": ["<t>", "null"]} instead of anyOf
#     wrappers (avoids RootModel generation in datamodel-codegen)
#   * array fields get an explicit "default": []
#   * the (otherwise unreferenced) TFPSubkind enum is added to $defs
#
# Pipeline:
#   src/tfp_models.py  --(this script)-->  spec/tfp_schema.json
#   spec/tfp_schema.json  --(language_bindings/python/generate.sh)-->  generated_models.py
#
# USAGE:
#   From project root: ./SSTP/subprotocol/tfp/scripts/generate_spec.sh
#   From this directory: ./generate_spec.sh
#
# PREREQUISITES:
#   Install dependencies: poetry install
#
# OUTPUT:
#   Generated schema is written to: <tfp-root>/spec/tfp_schema.json

set -e

# Resolve directories. This script lives in scripts/ under the TFP root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TFP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SRC_DIR="$TFP_ROOT/src"
OUTPUT_FILE="$TFP_ROOT/spec/tfp_schema.json"
SCHEMA_VERSION="${TFP_SCHEMA_VERSION:-0.0.1}"

echo "Generating JSON Schema from source Pydantic models..."
echo "Source dir:  $SRC_DIR"
echo "Output file: $OUTPUT_FILE"

TFP_SRC_DIR="$SRC_DIR" TFP_OUTPUT_FILE="$OUTPUT_FILE" TFP_SCHEMA_VERSION="$SCHEMA_VERSION" \
poetry run python - <<'PY'
import json
import os
import sys

SRC_DIR = os.environ["TFP_SRC_DIR"]
OUTPUT_FILE = os.environ["TFP_OUTPUT_FILE"]
SCHEMA_VERSION = os.environ["TFP_SCHEMA_VERSION"]

sys.path.insert(0, SRC_DIR)
import tfp_models as m  # noqa: E402


def normalize(obj: dict) -> None:
    """Normalize one object schema's properties in place."""
    props = obj.get("properties")
    if not props:
        return
    for name in list(props):
        p = props[name]
        any_of = p.get("anyOf")
        # Collapse anyOf[<scalar>, null] -> {"type": ["<scalar>", "null"], ...}.
        # Leave anyOf[<$ref>, null] alone so codegen emits `Model | None`.
        if any_of and len(any_of) == 2 and {"type": "null"} in any_of:
            other = next(s for s in any_of if s != {"type": "null"})
            if "$ref" not in other:
                t = other.get("type")
                merged = {"type": [t, "null"]} if t is not None else {}
                for k, v in other.items():
                    if k != "type":
                        merged[k] = v
                for k in ("default", "title"):
                    if k in p:
                        merged[k] = p[k]
                props[name] = merged
                continue
        # Give every array an explicit empty-list default.
        if p.get("type") == "array" and "default" not in p:
            p["default"] = []


schema = m.TFPPayload.model_json_schema()

normalize(schema)
for definition in schema.get("$defs", {}).values():
    normalize(definition)

# TFPSubkind is not referenced by the payload, so add it explicitly.
schema.setdefault("$defs", {})["TFPSubkind"] = {
    "title": "TFPSubkind",
    "description": " ".join((m.TFPSubkind.__doc__ or "").split()),
    "enum": [e.value for e in m.TFPSubkind],
    "type": "string",
}

schema["version"] = SCHEMA_VERSION

with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
    json.dump(schema, fh, indent=2)
    fh.write("\n")

print(f"Wrote {OUTPUT_FILE}")
PY

echo "JSON Schema generated successfully!"

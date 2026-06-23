#!/usr/bin/env python3

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
generate_schemas.py
-------------------
Generates JSON Schema for every Pydantic model in the ioc_l9 package.

Default output: SSTP/spec/l9_schema.json  (single combined file)
Alt output:     ioc_l9/spec/json_schema/  (one file per model, --split)

Usage:  python scripts/generate_schemas.py
        python scripts/generate_schemas.py --split
        python scripts/generate_schemas.py --model L9
        python scripts/generate_schemas.py --out path/to/output.json
"""

# ── Schema version — increment manually on breaking/significant changes ───────
SCHEMA_VERSION = "0.0.3"

import argparse
import inspect
import json
import sys
from pathlib import Path

from pydantic import BaseModel

# ── make sure the repo root is on the path ───────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# ── import every module that contains models ──────────────────────────────────
import src.primitives as primitives_module
import src.epistemic  as epistemic_module
import src.state_mgmt as state_mgmt_module
import src             as src_module

# Map each module to the subdirectory name it should produce
MODULES = [
    (primitives_module, "primitives"),
    (epistemic_module,  "epistemic"),
    (state_mgmt_module, "state_mgmt"),
    (src_module,        "src"),
]

# ── collect all BaseModel subclasses, keyed by source subdir ─────────────────
def collect_models(modules, filter_name: str | None = None):
    seen = set()
    models = []  # list of (subdir, name, class)
    for module, subdir in modules:
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseModel)
                and obj is not BaseModel
                and obj not in seen
                and obj.__module__.startswith("src")
                and (filter_name is None or name == filter_name)
            ):
                seen.add(obj)
                models.append((subdir, name, obj))
    return models

# ── write schemas — combined single file ─────────────────────────────────────
def generate_combined(out_path: Path, filter_name: str | None = None, version: str = SCHEMA_VERSION) -> None:
    models = collect_models(MODULES, filter_name)
    if not models:
        print(f"No model named '{filter_name}' found.")
        sys.exit(1)

    combined = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:ioc:l9:schema:v1",
        "version": version,
        "title": "L9",
        "description": "Combined JSON Schema for all ioc_l9 Pydantic models.",
        "$defs": {},
    }
    for _, name, model in sorted(models, key=lambda x: (x[0], x[1])):
        schema = model.model_json_schema()
        schema.pop("title", None)
        # Promote nested $defs to top-level so that absolute $ref paths like
        # "#/$defs/Kind" resolve correctly when tools (e.g. go-jsonschema)
        # process the combined schema.
        for def_name, def_schema in schema.pop("$defs", {}).items():
            combined["$defs"].setdefault(def_name, def_schema)
        combined["$defs"][name] = schema

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(combined, indent=2))
    print(f"Schema version: {version}")
    print(f"Found {len(models)} models — written to {out_path.relative_to(REPO_ROOT)}")
    print(f"\nDone. {len(models)} model{'s' if len(models) != 1 else ''} combined.")


# ── write schemas — one file per model ───────────────────────────────────────
def generate(base_output_dir: Path, filter_name: str | None = None, version: str = SCHEMA_VERSION) -> None:
    models = collect_models(MODULES, filter_name)
    if not models:
        print(f"No model named '{filter_name}' found.")
        sys.exit(1)
    label = f"model '{filter_name}'" if filter_name else f"{len(models)} models"
    print(f"Schema version: {version}")
    print(f"Found {label} — writing to {base_output_dir}/\n")

    for subdir, name, model in sorted(models, key=lambda x: (x[0], x[1])):
        output_dir = base_output_dir if subdir in ("root", "src") else base_output_dir / subdir
        output_dir.mkdir(parents=True, exist_ok=True)
        schema = model.model_json_schema()
        schema["version"] = version
        out_path = output_dir / f"{name.lower()}.json"
        out_path.write_text(json.dumps(schema, indent=2))
        print(f"  ✓ {subdir}/{name:25s} → {out_path.relative_to(REPO_ROOT)}")

    written = len(models)
    print(f"\nDone. {written} schema{'s' if written != 1 else ''} written.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate JSON schemas for ioc_l9 models.")
    parser.add_argument("--model",   metavar="NAME",    help="Generate schema for a single model by class name (e.g. L9)")
    parser.add_argument("--version", metavar="VERSION", default=SCHEMA_VERSION, help=f"Schema version to embed (default: {SCHEMA_VERSION})")
    parser.add_argument("--split",   action="store_true", help="Write one file per model into ioc_l9/spec/json_schema/ instead of a single combined file")
    parser.add_argument("--out",     metavar="PATH",    help="Output path (default: SSTP/spec/l9_schema.json for combined, ioc_l9/spec/json_schema/ for --split)")
    args = parser.parse_args()

    if args.split:
        base_output_dir = Path(args.out) if args.out else REPO_ROOT / "ioc_l9" / "spec" / "json_schema"
        generate(base_output_dir, filter_name=args.model, version=args.version)
    else:
        out_path = Path(args.out) if args.out else REPO_ROOT / "SSTP" / "spec" / "l9_schema.json"
        generate_combined(out_path, filter_name=args.model, version=args.version)

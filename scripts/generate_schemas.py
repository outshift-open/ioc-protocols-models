#!/usr/bin/env python3

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
generate_schemas.py
-------------------
Generates JSON Schema files for every Pydantic model in the ioc_l9 package.

Output: schemas/ioc_l9/<source_module>/<ModelName>.json
        e.g. schemas/ioc_l9/primitives/Actor.json
             schemas/ioc_l9/state_mgmt/Team.json

Usage:  python scripts/generate_schemas.py
        python scripts/generate_schemas.py --model L9
"""

# ── Schema version — increment manually on breaking/significant changes ───────
SCHEMA_VERSION = "1.0.0"

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
import ioc_l9.src.primitives as primitives_module
import ioc_l9.src.epistemic  as epistemic_module
import ioc_l9.src.state_mgmt as state_mgmt_module
import ioc_l9.src             as src_module

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
                and obj.__module__.startswith("ioc_l9")
                and (filter_name is None or name == filter_name)
            ):
                seen.add(obj)
                models.append((subdir, name, obj))
    return models

# ── write schemas ─────────────────────────────────────────────────────────────
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
    parser.add_argument("--model", metavar="NAME", help="Generate schema for a single model by class name (e.g. L9)")
    parser.add_argument("--version", metavar="VERSION", default=SCHEMA_VERSION, help=f"Schema version to embed (default: {SCHEMA_VERSION})")
    args = parser.parse_args()

    base_output_dir = REPO_ROOT / "ioc_l9" / "spec" / "json_schema"
    generate(base_output_dir, filter_name=args.model, version=args.version)

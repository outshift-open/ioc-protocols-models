#!/usr/bin/env python3
"""
generate_schemas.py
-------------------
Generates JSON Schema files for every Pydantic model in the ioc_l9 package.

Output: schemas/ioc_l9/<source_module>/<ModelName>.json
        e.g. schemas/ioc_l9/primitives/Actor.json
             schemas/ioc_l9/state_mgmt/Team.json

Usage:  python scripts/generate_schemas.py
"""

import inspect
import json
import sys
from pathlib import Path

from pydantic import BaseModel

# ── make sure the repo root is on the path ───────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# ── import every module that contains models ──────────────────────────────────
import ioc_l9.primitives as primitives_module
import ioc_l9.epistemic  as epistemic_module
import ioc_l9.state_mgmt as state_mgmt_module
import ioc_l9             as root_module

# Map each module to the subdirectory name it should produce
MODULES = [
    (primitives_module, "primitives"),
    (epistemic_module,  "epistemic"),
    (state_mgmt_module, "state_mgmt"),
    (root_module,       "root"),
]

# ── collect all BaseModel subclasses, keyed by source subdir ─────────────────
def collect_models(modules):
    seen = set()
    models = []  # list of (subdir, name, class)
    for module, subdir in modules:
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseModel)
                and obj is not BaseModel
                and obj not in seen
                and obj.__module__.startswith("ioc_l9")
            ):
                seen.add(obj)
                models.append((subdir, name, obj))
    return models

# ── write schemas ─────────────────────────────────────────────────────────────
def generate(base_output_dir: Path) -> None:
    models = collect_models(MODULES)
    print(f"Found {len(models)} models — writing to {base_output_dir}/\n")

    for subdir, name, model in sorted(models, key=lambda x: (x[0], x[1])):
        output_dir = base_output_dir / subdir
        output_dir.mkdir(parents=True, exist_ok=True)
        schema = model.model_json_schema()
        out_path = output_dir / f"{name}.json"
        out_path.write_text(json.dumps(schema, indent=2))
        print(f"  ✓ {subdir}/{name:25s} → {out_path.relative_to(REPO_ROOT)}")

    print(f"\nDone. {len(models)} schemas written.")


if __name__ == "__main__":
    base_output_dir = REPO_ROOT / "schemas" / "ioc_l9"
    generate(base_output_dir)

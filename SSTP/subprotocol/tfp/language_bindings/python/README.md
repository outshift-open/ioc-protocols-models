# TFP — Python Language Binding

Pydantic models for the **Team Formation via Polling** subprotocol payload,
packaged as the **`ai-outshift-tfp-data-model`** wheel.

## Contents

- `ai/outshift/tfp/data_model.py` — **generated** from
  [`../../spec/tfp_schema.json`](../../spec/tfp_schema.json) via
  [`generate.sh`](generate.sh). Defines `TFPPayload` and its sub-structures
  (`SkillRequirement`, `SkillClaim`, `CandidateOffer`, `TeamSelection`,
  `RoleAssignment`, `TaskSpec`), plus the `TFPOperation` enum.
  Do not edit by hand.
- `ai/outshift/tfp/__init__.py` — re-exports the public models so they can be
  imported from either `ai.outshift.tfp` or `ai.outshift.tfp.data_model`.
- `pyproject.toml` — wheel metadata for `ai-outshift-tfp-data-model`.
- `ai_outshift_tfp_data_model-<version>-py3-none-any.whl` — the built wheel
  (produced by `make build_tfp_wheel`).
- `generate.sh` — regenerates `ai/outshift/tfp/data_model.py` from the JSON Schema.
- `test_tfp.py` — model + end-to-end episode tests.

The package is namespaced under `ai.outshift`, the same namespace as the L9
`ai-outshift-data-model` wheel, so the two coexist when both are installed.

The JSON Schema itself is **generated** from the source-of-truth Pydantic models
in [`../../src/`](../../src/) via [`../../scripts/generate_spec.sh`](../../scripts/generate_spec.sh).
The full pipeline is:

```
src/tfp_models.py  →  spec/tfp_schema.json  →  language_bindings/python/ai/outshift/tfp/data_model.py
```

To change the models, edit `src/tfp_models.py`, then re-run `scripts/generate_spec.sh`
followed by `generate.sh`.

These models describe the TFP-specific `payload` only. They are carried inside an
L9 envelope (`ai.outshift.data_model.L9`) with `header.subprotocol == "TFP"` and
`payload.type == "json-schema"`. See [`../../documentation/TFP.md`](../../documentation/TFP.md) for the
protocol spec and [`../../examples/team_formation_example.py`](../../examples/team_formation_example.py)
for a runnable walkthrough.

## Build the wheel

```bash
# from the repo root
make build_tfp_wheel
```

The version is auto-stamped from the `version` field of `spec/tfp_schema.json`.

## Usage

```python
from ai.outshift.tfp.data_model import (
    TFPPayload, TFPOperation, SkillRequirement, TaskSpec,
)

payload = TFPPayload(
    operation=TFPOperation.POLL_OPEN,
    poll_id="urn:ioc:tfp:poll:abc123",
    task=TaskSpec(task_id="incident-4471", description="Triage suspicious login"),
    required_skills=[SkillRequirement(skill="skill:log_triage", min_proficiency=0.7)],
)
```

## Test

```bash
# from the repo root
poetry run pytest SSTP/subprotocol/tfp/language_bindings/python/test_tfp.py -v
```

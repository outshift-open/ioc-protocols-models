# TFP — Python Language Binding

Pydantic models for the **Team Formation via Polling** subprotocol payload.

## Contents

- `data_model.py` — **generated** from [`../../spec/tfp_schema.json`](../../spec/tfp_schema.json)
  via [`generate.sh`](generate.sh). Defines `TFPPayload` and its sub-structures
  (`SkillRequirement`, `SkillClaim`, `CandidateOffer`, `TeamSelection`,
  `RoleAssignment`, `TaskSpec`), plus the `TFPOperation` enum.
  Do not edit by hand.
- `generate.sh` — regenerates `data_model.py` from the JSON Schema.
- `test_tfp.py` — model + end-to-end episode tests.

The JSON Schema itself is **generated** from the source-of-truth Pydantic models
in [`../../src/`](../../src/) via [`../../scripts/generate_spec.sh`](../../scripts/generate_spec.sh).
The full pipeline is:

```
src/tfp_models.py  →  spec/tfp_schema.json  →  language_bindings/python/data_model.py
```

To change the models, edit `src/tfp_models.py`, then re-run `scripts/generate_spec.sh`
followed by `generate.sh`.

These models describe the TFP-specific `payload` only. They are carried inside an
L9 envelope (`src.L9`) with `header.subprotocol == "TFP"` and
`payload.type == "json-schema"`. See [`../../documentation/TFP.md`](../../documentation/TFP.md) for the
protocol spec and [`../../examples/team_formation_example.py`](../../examples/team_formation_example.py)
for a runnable walkthrough.

## Usage

```python
from data_model import TFPPayload, TFPOperation, SkillRequirement, TaskSpec

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

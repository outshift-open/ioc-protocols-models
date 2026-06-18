# TFP — Python Language Binding

Pydantic models for the **Team Formation via Polling** subprotocol payload.

## Contents

- `tfp_models.py` — `TFPPayload` and its sub-structures (`SkillRequirement`,
  `SkillClaim`, `CandidateOffer`, `TeamSelection`, `RoleAssignment`, `TaskSpec`),
  plus the `TFPOperation` and `TFPSubkind` enums.
- `test_tfp.py` — model + end-to-end episode tests.

These models describe the TFP-specific `payload` only. They are carried inside an
L9 envelope (`ioc_l9.src.L9`) with `header.subprotocol == "TFP"` and
`payload.type == "json-schema"`. See [`../../docs/TFP.md`](../../docs/TFP.md) for the
protocol spec and [`../../examples/team_formation_example.py`](../../examples/team_formation_example.py)
for a runnable walkthrough.

## Usage

```python
from tfp_models import TFPPayload, TFPOperation, SkillRequirement, TaskSpec

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

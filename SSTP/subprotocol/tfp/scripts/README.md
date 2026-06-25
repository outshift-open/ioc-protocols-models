# TFP — Scripts

- `generate_spec.sh` — generates the JSON Schema [`../spec/tfp_schema.json`](../spec/tfp_schema.json)
  from the source-of-truth Pydantic models in [`../src/`](../src/). It dumps
  `src/tfp_models.py:TFPPayload`'s JSON Schema and normalizes it (nullable
  scalars as `type: ["<t>", "null"]`, explicit `default: []` on arrays) so the
  downstream bindings stay clean.

## Generation pipeline

```
src/tfp_models.py          (edit here — source of truth)
    │  scripts/generate_spec.sh
    ▼
spec/tfp_schema.json       (generated)
    │  language_bindings/python/generate.sh
    ▼
language_bindings/python/ai/outshift/tfp/data_model.py   (generated)
```

```bash
# from the repo root (or this directory)
./SSTP/subprotocol/tfp/scripts/generate_spec.sh
```

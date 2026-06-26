---
name: l9-message-gen
description: Generates a complete L9 message (header + payload) as valid JSON.
---

# L9 Message Generator

## Context / Trigger Requirements

Use this skill when you need to produce a complete L9 message (header + payload) as valid JSON on stdout.

## Schema Reference

Fetch the raw content from these URLs before generating output:

- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — see `$defs.L9`, `$defs.L9Header`, `$defs.L9Payload`, `$defs.ParticipantSet`, `$defs.Actor`, `$defs.Kind`
- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/language_bindings/python/ai/outshift/data_model.py — see classes `L9`, `L9Header`, `L9Payload`, `ParticipantSet`, `Actor`, `Kind`

You can `curl` or `fetch` the data from those URLs. Do not rely on cached or memorized schema content.

## Input Parameters

The user must provide:

- `kind` — one of the `Kind` enum values from the schema (e.g. `intent`, `contingency`, `exchange`, `commit`, `knowledge`)
- `subprotocol` — the subprotocol identifier (e.g. `SIEP`, `CIP`, `TFP`, `SAB`)
- `payload_type` — string describing the payload format (e.g. `text`, `task_proposal`)
- `payload_data` — object containing the payload content

Auto-generate `sender_id` as a UUID (v4). Derive all other fields and their types from the fetched schema (`$defs.L9`, `$defs.L9Header`, `$defs.L9Payload`).

## Instructions

1. **Fetch** the schema and model files from the URLs above.
2. **Parse** the fetched content to extract field requirements, types, and enum values.
3. **Generate** an `L9` envelope conforming to the schema.
4. **Output** ONLY valid JSON. No explanation, no markdown fences.

## Constraints

- `L9Header.protocol` is always `"SSTP"`.
- All validation rules MUST come from the fetched schema/model files, not hardcoded assumptions.
- You MUST fetch the remote files every time — do not assume schema content from memory.
- Output valid JSON only.

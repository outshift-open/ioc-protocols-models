---
name: l9-transform
description: Converts plain-text input into a valid L9 exchange message.
---

# L9 Transform

## Context / Trigger Requirements

Use this skill when the input is a human-readable message that needs to be converted into a valid L9 message. Input pattern: `<sender_name>: <message>`.

If no sender name is provided (no colon separator), default sender to "User".

## Schema Reference

Fetch the raw content from these URLs before generating output:

- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — see `$defs.L9`, `$defs.L9Header`, `$defs.L9Payload`, `$defs.ParticipantSet`, `$defs.Actor`, `$defs.Kind`
- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/language_bindings/python/ai/outshift/data_model.py — see classes `L9`, `L9Header`, `L9Payload`, `ParticipantSet`, `Actor`, `Kind`

You can `curl` or `fetch` the data from those URLs. Do not rely on cached or memorized schema content.

## Input Parameters

Derive all structural fields from the fetched schema. The only user input is the plain-text message.

## Instructions

1. **Fetch** the schema and model files from the URLs above.
2. **Parse** input to extract `sender_name` and `message`. No colon → sender is `"User"`.
3. Derive sender actor `id`: lowercase, replace spaces with dashes.
4. **Generate** an `L9` envelope conforming to the fetched schema with `kind` = `"exchange"`.
5. **Output** ONLY valid JSON. No explanation, no markdown fences.

## Constraints

- `L9Header.protocol` is always `"SSTP"`.
- `L9Header.subprotocol` must be one of: `SIEP`, `CIP`, `TFP`, `SAB`.
- All structural rules MUST come from the fetched schema/model files, not hardcoded assumptions.
- You MUST fetch the remote files every time — do not assume schema content from memory.
- Output valid JSON only.

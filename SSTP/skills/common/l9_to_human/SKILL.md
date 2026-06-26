---
name: l9-to-human
description: Converts an L9 JSON message into a simple human-readable string.
---

# L9 to Human

## Context / Trigger Requirements

Use this skill when you receive a valid L9 JSON message and need to produce a simple, human-readable plain-text representation on stdout.

## Schema Reference

Fetch the raw content from these URLs before processing:

- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — see `$defs.L9`, `$defs.L9Header`, `$defs.L9Payload`, `$defs.ParticipantSet`, `$defs.Actor`, `$defs.Kind`
- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/language_bindings/python/ai/outshift/data_model.py — see classes `L9`, `L9Header`, `L9Payload`, `ParticipantSet`, `Actor`, `Kind`

You can `curl` or `fetch` the data from those URLs. Do not rely on cached or memorized schema content.

## Input Parameters

The only input is a valid L9 JSON message. Derive field structure from the fetched schema.

## Instructions

1. **Fetch** the schema and model files from the URLs above.
2. **Parse** the input as a valid L9 JSON message per `$defs.L9`.
3. **Extract** the sender (first actor with role `"sender"` from `header.participants.actors`), the kind, and the payload content.
4. **Format** as plain text: `[<protocol>/<subprotocol>/<kind>] <sender_id>: <payload summary>`
5. **Output** ONLY the plain-text string. No JSON, no markdown fences, no explanation.

## Constraints

- `L9Header.protocol` is always `"SSTP"`.
- All structural rules MUST come from the fetched schema/model files, not hardcoded assumptions.
- You MUST fetch the remote files every time — do not assume schema content from memory.
- Output plain text only — no JSON wrapping, no markdown.
- If the payload cannot be summarized as a single line, produce a concise multi-line representation.

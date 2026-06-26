---
name: l9-header-gen
description: Generates a valid L9 header JSON from kind and sender.
---

# L9 Header Generator

## Context / Trigger Requirements

Use this skill when you need to produce a standalone L9 header as valid JSON on stdout.

## Schema Reference

Fetch the raw content from these URLs before generating output:

- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — see `$defs.L9Header`, `$defs.ParticipantSet`, `$defs.Actor`, `$defs.Kind`
- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/language_bindings/python/ai/outshift/data_model.py — see class `L9Header`, `ParticipantSet`, `Actor`, `Kind`

You can `curl` or `fetch` the data from those URLs. Do not rely on cached or memorized schema content.

## Input Parameters

Derive all input parameters from the fetched schema (`$defs.L9Header` required fields).

## Instructions

1. **Fetch** the schema and model files from the URLs above.
2. **Parse** the fetched content to extract field requirements, types, and enum values.
3. **Generate** an `L9Header` conforming to the schema.
4. **Output** ONLY valid JSON. No explanation, no markdown fences.

## Constraints

- All validation rules MUST come from the fetched schema/model files, not hardcoded assumptions.
- You MUST fetch the remote files every time — do not assume schema content from memory.
- Output valid JSON only.

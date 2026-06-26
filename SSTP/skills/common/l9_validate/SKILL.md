---
name: l9-validate
description: Validates an L9 JSON message against the schema. Reports PASS or FAIL.
---

# L9 Validator

## Context / Trigger Requirements

Use this skill when you receive an L9 JSON message and need to verify it conforms to the schema. Input is the JSON to validate. Output is a validation report on stdout.

## Schema Reference

Fetch the raw content from these URLs before validating:

- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — walk `$defs.L9` → `$defs.L9Header` → `$defs.L9Payload` and all referenced types.
- https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/language_bindings/python/ai/outshift/data_model.py — mirrors the schema as Pydantic classes.

You can `curl` or `fetch` the data from those URLs. Do not rely on cached or memorized schema content.

## Input Parameters

The only input is the L9 JSON message to validate. Derive all validation rules from the fetched schema.

## Instructions

1. **Fetch** the schema and model files from the URLs above.
2. **Parse** the input as JSON — reject if invalid.
3. **Validate** the input against the fetched schema, checking every required field, enum constraint, and type rule.
4. **Report** ALL errors found, not just the first.
5. **Output** the validation report as JSON only. No prose, no markdown fences.

## Constraints

- `L9Header.protocol` is always `"SSTP"`.
- ALL validation rules MUST be derived from the fetched schema/model files, not hardcoded assumptions.
- You MUST fetch the remote files every time — do not assume schema content from memory.
- Report ALL errors found, not just the first.
- Do not modify the input — this is read-only validation.
- Output valid JSON only.

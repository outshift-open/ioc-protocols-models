---
name: tfp-message-validation
description: Validates that a single TFP (Team Formation Protocol) L9 message follows the TFP format, using the authoritative raw GitHub L9 + TFP JSON schemas as the source of truth. Infers structure from the schemas; checks one message only (no cross-message/episode checks). Precise, not pedantic — reports real problems with locations.
---

# TFP L9 Message Validator

Given **one** TFP L9 message, decide whether it follows the TFP format and report the problems
with their locations. Single-message only — this does **not** verify anything across messages
(episode ordering, cumulative roster growth, `parents` pointing at the real `poll_open`, poll
finality, etc.). Counterpart to `tfp-message-generation`.

**Precise, not pedantic.** Hard-fail only on things that genuinely break the protocol. Don't
reject a message over optional or stylistic fields, and don't invent rules the schema doesn't
back. When unsure, let the schema decide and, if it still looks off, record a non-failing
`note` rather than a `problem`.

## Source of truth — fetch these raw and infer from them

The schemas are authoritative. **Fetch them fresh, derive the structure (fields, types, required
keys, enums, per-operation shapes) from them, and let them decide.** Anything written in this
file is a short hint that may lag the repo — when the schema disagrees, the schema wins.

- L9 envelope: `https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json`
- TFP payload: `https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/tfp/spec/tfp_schema.json`

If a fetch fails, say so and mark the report `"source": "cached-rules"`.

## How to validate

1. **Structure** — validate the whole message against the L9 schema, and `payload.data` against
   the TFP schema (Draft 2020-12). Every schema error is a real `problem` (JSON-pointer `path`).

2. **Must hold** (hard-fail — these define the operation, and the schema alone can't enforce
   them since it only requires `operation` + `poll_id`):
   - `operation` matches `header.kind` / `header.subkind`:
     `poll_open` → `intent`/`team-formation`; `form_converged` → `commit`/`converged`;
     `form_failed` → `commit`/`abort`; all other ops → `exchange`/`team-formation`.
   - The operation carries the data that gives it meaning:
     `poll_open` → `task`; `bid` → `offer`; `select` → `selection`;
     `form_converged` → `selection` with `coverage == 1.0` and empty `unmet_skills`;
     `form_failed` → `selection` with `coverage < 1.0` and non-empty `unmet_skills`.
   - `poll_open` has `message.parents == []`; any other op has a non-empty `parents`.

3. **Conventions** (record as a `note`, don't fail unless clearly broken):
   - `participants.groups == null`; actors are agents (not a `topic:` channel) with roles
     `sender` / `receiver` / `participant`, one `sender` first; broadcasts (`poll_open`,
     `form_converged`, `form_failed`) usually have no `receiver`.
   - `required_skills` is populated on `poll_open` and typically empty elsewhere.
   - `accept` / `reject` / `decline` usually carry a `reason`; `poll_open` / `bid` / the closes
     usually carry a `reasoning_summary` (all optional in the schema).
   - Ids follow the house style: `poll_id` = `urn:ioc:tfp:poll:<hex>`, `message.id` /
     `message.episode` are UUID v4; `context.topic` is set; `context.epistemic` /
     `context.semantic` / `policy` are `null`; `payload.type == "json-schema"`.

Anything else (exact required fields, enum values, numeric ranges) — **infer from the fetched
schema**; don't hardcode it here.

## Output

Compact JSON, no prose or fences:

```json
{
  "valid": false,
  "source": "raw-git | cached-rules",
  "message_id": "<header.message.id or null>",
  "operation": "poll_open | bid | select | accept | reject | decline | clarify | re_poll | form_converged | form_failed | unknown",
  "problems": [ { "path": "/payload/data/selection/unmet_skills", "detail": "form_failed needs a non-empty unmet_skills" } ],
  "notes": [ { "detail": "reasoning_summary is empty (optional, but usually set on poll_open)" } ]
}
```

`valid` is `true` when `problems` is empty — `notes` never make a message invalid.

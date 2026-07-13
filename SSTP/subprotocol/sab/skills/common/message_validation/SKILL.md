---
name: sab-message-validation
description: Validates that a single SAB (Semantic Alignment via Bargaining) L9 message follows the SAB format, using the authoritative raw GitHub L9 + SAB JSON schemas as the source of truth. Infers structure from the schemas; checks one message only (no cross-message/session checks). Reports pass/fail with precise locations.
---

# SAB L9 Message Validator

Given **one** SAB L9 message, decide whether it follows the SAB format and report every problem
with its location. Single-message only — this does **not** verify anything across messages
(session ordering, step sequence, alternation, etc.). Counterpart to `sab-message-generation`.

## Source of truth — fetch these raw and infer from them

The schemas are authoritative. **Fetch them fresh, derive the structure (fields, types, required
keys, enums, per-phase shapes) from them, and let them decide.** Anything written in this file is
a short hint that may lag the repo — when the schema disagrees, the schema wins.

- L9 envelope: `https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json`
- SAB payload: `https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/sab/spec/sab_schema.json`

If a fetch fails, say so and mark the report `"source": "cached-rules"`.

## How to validate

1. **Structure** — validate the whole message against the L9 schema, and `payload.data` against
   the SAB schema (Draft 2020-12). Report each error as a JSON-pointer `path` + message.
2. **SAB conventions the schema can't express** — the SAB payload root is a *permissive union*
   (variants discriminated by the shape of `semantic_context`, with open `additionalProperties`),
   so structural pass alone does **not** prove validity. Also enforce, within this one message:
   - Fixed cast: exactly the two negotiators (`role: participant`) + facilitator
     `"negotiation_server"` (`role: facilitator`); `participants.groups == null`.
   - `origin.actor_id` is a negotiator — **never** the facilitator.
   - `message.parents == []` (SAB doesn't thread).
   - `payload.data.message_id == header.message.id`.
   - `sao_response.response` (when present) is a `ResponseType` **name** (`ACCEPT_OFFER`,
     `REJECT_OFFER`, …); the schema types it as an int, but the wire form in `examples/` is the
     name — accept the name (and a bare int), reject anything else.
   - Phase = `header.kind`/`header.subkind`. The mapping is **not 1:1 by name**: a timed-out run
     closes `commit`/`disagreement`; a broken run closes `commit`/`timeout`. Infer the required
     `semantic_context` shape for that phase from the schema and check the pair is a valid combo.
   - **Session-initiating negotiate messages**: the first negotiate-phase message
     (`kind='contingency'`, `subkind='negotiation'`) may use the plain `SemanticContext`
     (only `schema_version` + `encoding`, no `session_id`) because the session has not yet been
     assigned by the facilitator. Accept either `NegotiateSemanticContext` (with `session_id`)
     or plain `SemanticContext` on negotiate-phase messages. Only flag a missing `session_id`
     when other negotiate-specific fields (`sao_state`, `sao_response`, `nmi`) are present —
     those imply an in-progress session where `session_id` is mandatory.
   - Acceptance (`response == ACCEPT_OFFER`) keeps `current_proposer` as the proposer of the
     accepted offer (not the accepter); `running=false`, `agreement` set.

Everything else (which fields are required, allowed enum values, id/URN formats, per-phase
`semantic_context` keys) — **infer from the fetched schema** rather than hardcoding it here.

## Output

Compact JSON, no prose or fences:

```json
{
  "valid": false,
  "source": "raw-git | cached-rules",
  "message_id": "<header.message.id or null>",
  "phase": "intent | negotiate | commit | unknown",
  "problems": [ { "path": "/payload/data/semantic_context/session_id", "detail": "missing on a negotiate round" } ]
}
```

`valid` is `true` only when `problems` is empty.

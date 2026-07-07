---
name: tfp-message-generation
description: Generates a complete TFP L9 message (header + TFP payload) as valid JSON.
---

# TFP L9 Message Generator

Produce a complete TFP (Team Formation Protocol) L9 message — header + payload — as valid JSON on stdout.

## Behavior — interactive prompt

When invoked, do NOT generate a message immediately. Instead:

1. **Ask** which operation the user wants: `poll_open | bid | decline | clarify | select | accept | reject | re_poll | form_converged | form_failed`
2. **Show a pre-filled sample input** for that operation (from the "Example input" and per-operation table below) and ask: _"Use this as-is, or tell me what to change?"_
3. **Collect** the user's edits (or confirmation), then generate the full L9 JSON.

## Source of truth (fetch raw content every time)

Fetch these raw files and derive all field names, types, required fields, and enum values from them. Do not rely on memory.

- L9 envelope: https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — `$defs.L9`, `L9Header`, `L9Payload`, `ParticipantSet`, `Actor`, `Kind`
- TFP payload: https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/tfp/spec/tfp_schema.json — `$defs.TFPPayload` (`required: [operation, poll_id]`), `TFPOperation`, `TaskSpec`, `SkillRequirement`, `SkillClaim`, `CandidateOffer`, `TeamSelection`, `RoleAssignment`

(These JSON schemas are authoritative; the Python bindings are generated from them.)

## Inputs — what YOU provide

Provide exactly this small object. Everything else (UUIDs, `poll_id`, and all the
"Fixed values" below) is filled in for you — do not provide them.

```json
{
  "kind": "intent | exchange | commit",
  "operation": "poll_open | bid | decline | clarify | select | accept | reject | re_poll | form_converged | form_failed",
  "sender": "who is sending this turn, e.g. recruiter",
  "receivers": ["who it goes to, e.g. topic:tfp/polls or an agent id"],
  "payload_data": { "...fields for the chosen operation (see table below)..." }
}
```

Field guide:
- `kind` — the L9 turn type. Rule of thumb: `poll_open` → `intent`; every bid/decline/select/accept/reject/re_poll → `exchange`; `form_converged`/`form_failed` → `commit`.
- `operation` — the TFP action (one of the 10 `TFPOperation` values above).
- `sender` — the agent id sending this turn.
- `receivers` — list of recipients; use `topic:tfp/polls` for a broadcast (poll_open / commit), or an agent id for a direct turn (bid, select, accept…).
- `payload_data` — only the fields that operation needs (see the per-operation table under the golden example).

### Example input (produces the golden example below)

```json
{
  "kind": "intent",
  "operation": "poll_open",
  "sender": "recruiter",
  "receivers": ["topic:tfp/polls"],
  "payload_data": {
    "task": {
      "task_id": "incident-4471",
      "description": "Triage a suspicious-login security incident across SIEM + endpoint data",
      "objective": "Confirm or dismiss compromise within 30 minutes"
    },
    "required_skills": [
      { "skill": "skill:log_triage",    "min_proficiency": 0.7, "weight": 2.0, "mandatory": true },
      { "skill": "skill:threat_intel",  "min_proficiency": 0.6, "weight": 1.5, "mandatory": true },
      { "skill": "skill:host_forensics","min_proficiency": 0.6, "weight": 1.0, "mandatory": false }
    ],
    "reasoning_summary": "Need log triage + threat intel; host forensics is a nice-to-have."
  }
}
```

## Fixed values

- `header.protocol` = `"SSTP"`, `header.subprotocol` = `"TFP"`, `header.version` = `"0"`
- `header.subkind` = `"team-formation"`, except the terminal `commit` → `"converged"` (`form_converged`) or `"abort"` (`form_failed`)
- `payload.type` = `"json-schema"`
- `payload.data.operation` + `payload.data.poll_id` are always required; `header.participants.groups` is required (use `null`)
- build `participants.actors` from the input: `sender` (role `sender`) then each `receivers` entry (role `receiver`); drop any `topic:*` receiver (a channel is not an actor — a broadcast then has only the sender)
- **IDs: generate every id as a fresh UUID v4.** Keep the `urn:` scheme prefix when the example uses one (`poll_id` → `urn:ioc:tfp:poll:<uuid>`); use the bare UUID when the example does (`message.id`, `episode`). Reuse the same `episode` and `poll_id` across a poll; the root turn has `parents: []` and later turns list the id(s) they reply to.

## Golden example (canonical L9 TFP `poll_open`, from the reference dumps)

> Use this for **structure only**. Do NOT copy its literal values: generate fresh
> UUID v4s for `message.id`, `episode`, and the `poll_id` (keep its `urn:ioc:tfp:poll:`
> prefix), and take the actors, `task`, `required_skills`, and scenario/`topic` from
> the user's inputs.

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "TFP",
    "version": "0",
    "kind": "intent",
    "subkind": "team-formation",
    "participants": { "actors": [ { "id": "recruiter", "role": "sender", "attestation": null } ], "groups": null },
    "message": { "id": "018b65ea-8d39-4fde-a9b5-76b9915b1e32", "parents": [], "episode": "6356e69f-5692-4203-b084-120c91a3172d" },
    "policy": null,
    "context": { "topic": "Forming a team to Triage a suspicious-login security incident across SIEM + endpoint data", "epistemic": null, "semantic": null }
  },
  "payload": {
    "type": "json-schema",
    "data": {
      "operation": "poll_open",
      "poll_id": "urn:ioc:tfp:poll:2f9c1a7b-4d3e-4c88-9a12-5b6e7f081234",
      "task": { "task_id": "incident-4471", "description": "Triage a suspicious-login security incident across SIEM + endpoint data", "objective": "Confirm or dismiss compromise within 30 minutes" },
      "required_skills": [
        { "skill": "skill:log_triage",   "min_proficiency": 0.7, "weight": 2.0, "mandatory": true },
        { "skill": "skill:threat_intel", "min_proficiency": 0.6, "weight": 1.5, "mandatory": true },
        { "skill": "skill:host_forensics","min_proficiency": 0.6, "weight": 1.0, "mandatory": false }
      ],
      "reasoning_summary": "Need log triage + threat intel; host forensics is a nice-to-have."
    }
  }
}
```

Per-operation `payload.data` (same envelope, swap `kind`/`subkind`/`data`):
- `bid` (exchange) → `offer` (`CandidateOffer`) + `reasoning_summary`
- `decline` / `reject` (exchange) → `reason`
- `select` (exchange) → `selection` (`TeamSelection`)
- `accept` (exchange) → `reason`
- `re_poll` (exchange) → `required_skills` (the uncovered ones)
- `form_converged` (commit, subkind `converged`) / `form_failed` (commit, subkind `abort`) → `selection`

## Output

Output ONLY valid JSON — no explanation, no markdown fences.

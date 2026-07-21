---
name: tfp-message-generation
description: Generates a complete TFP L9 message (header + TFP payload) as valid JSON.
---

# TFP L9 Message Generator

Produce one complete TFP (Team Formation Protocol) L9 message — header + payload — as
valid JSON on stdout.

To keep things simple this skill uses a **fixed cast of three agents** and covers only
the two end-to-end outcomes:

- **`recruiter`** — opens the poll, selects, and commits.
- **`agent-a`**, **`agent-b`** — two candidates that bid and accept.

Two flows:

- **Success** → `poll_open` → `agent-a` `bid` → `agent-b` `bid` → `select` (both) →
  `agent-a` `accept` → `agent-b` `accept` → `form_converged`
- **Failure** → `poll_open` → `agent-a` `bid` → `agent-b` `bid` → `select` (both,
  but a mandatory skill is uncovered) → `form_failed`

Note: `form_converged` is only valid after all selected members have accepted.
`form_failed` follows `select` directly (skipping `accept`) when coverage < 1.0
because a mandatory skill remains unmet.

(TFP has more operations — decline, reject, clarify, re_poll — but they are out of
scope here.)

## Examples are structure only — never copy their content

Every JSON block below uses **angle-bracket placeholders** (e.g. `<task description>`,
`skill:<skill-1>`) wherever a value depends on the use case. They exist only to show the
message *shape*. Fill every placeholder from the user's inputs — a `<...>` token must never
appear in your output, and nothing from these examples should carry over unchanged.

- **Keep (fixed structure):** `protocol` / `subprotocol` / `version`, the `kind` / `subkind`
  mapping, `payload.type`, participant roles, the `parents` rule, and `context.epistemic` /
  `context.semantic` / `policy` = `null`.
- **Replace from the user's use case (fill every placeholder):** `context.topic`, `task.*`,
  `required_skills[*]`, `offer.*`, everything in `selection` (`members`, `roles`,
  `coverage`, `unmet_skills`, `aggregate_fit`), `reason`, `reasoning_summary`, and all ids
  (`message.id`, `episode`, `poll_id`).

The numbers in the examples (`min_proficiency`, `weight`, `fit_score`, `aggregate_fit`) are
placeholder magnitudes — recompute them for the real task. Only the outcome-defining values
are fixed by the operation: `form_converged` requires `coverage: 1.0` with
`unmet_skills: []`; `form_failed` requires `coverage < 1.0` with a non-empty `unmet_skills`.

## Defaults — use only if the user doesn't supply a value

Always prefer the user's real values. If the user is vague or skips a field, fall back to
these — the incident-triage sample taken verbatim from the reference dumps
(`examples/dumps/team_formation_*.json`):

| placeholder | default value (from the dumps) |
|-------------|--------------------------------|
| `<task-id>` | `incident-4471` |
| `<task description>` | `Triage a suspicious-login security incident across SIEM + endpoint data` |
| `<measurable objective>` | `Confirm or dismiss compromise within 30 minutes` |
| `skill:<skill-1>` | `skill:log_triage` (`min_proficiency` 0.7, `weight` 2.0, `mandatory` true) |
| `skill:<skill-2>` | `skill:threat_intel` (`min_proficiency` 0.6, `weight` 1.5, `mandatory` true) |
| `skill:<uncovered-mandatory-skill>` | `skill:quantum_forensics` |
| `<why these skills are needed>` | `Need log triage + threat intel; host forensics is a nice-to-have.` |
| `aggregate_fit` (converged / failed) | `0.3245` / `0.2655` |
| `<why the team converged; ...>` | `coverage=1.0 aggregate_fit=0.3245` |
| `<why forming failed; ...>` | `coverage=0.6667 aggregate_fit=0.2655` |
| ids (`<uuid-v4>`, `<poll_open message.id>`, `urn:ioc:tfp:poll:<hex>`) | **never default — always generate fresh / reuse the poll's** |

## Behavior — interactive prompt

When invoked, do NOT emit a message immediately:

1. **Ask which turn to build**: `poll_open | bid | select | accept | form_converged | form_failed`.
   - Only offer `form_converged` after all selected members have accepted.
   - Only offer `form_failed` directly after `select` when coverage < 1.0 (mandatory skill unmet).
2. **Ask only that turn's fields** (see the table), then show a pre-filled sample using
   the fixed cast and ask _"Use this as-is, or tell me what to change?"_
3. **Confirm or collect edits**, then emit the full L9 JSON for that single turn,
   reusing the poll's `episode` and `poll_id`.
4. **Repeat from step 1.** The session is not over until the user completes a
   `form_converged` or `form_failed` turn. Keep prompting for the next turn.

## Source of truth (fetch raw content every time)

Fetch these raw files and derive all field names, types, required fields, and enum values from them. Do not rely on memory.

- L9 envelope: https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — `$defs.L9`, `L9Header`, `L9Payload`, `ParticipantSet`, `Actor`, `Context`, `Kind`
- TFP payload: https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/tfp/spec/tfp_schema.json — `$defs.TFPPayload` (`required: [operation, poll_id]`), `TFPOperation`, `TaskSpec`, `SkillRequirement`, `SkillClaim`, `CandidateOffer`, `TeamSelection`, `RoleAssignment`

(These JSON schemas are authoritative; the Python bindings are generated from them.)

## Inputs — what YOU provide

```json
{
  "operation": "poll_open | bid | select | accept | form_converged | form_failed",
  "sender": "recruiter | agent-a | agent-b",
  "task_description": "short task description (used for context.topic and poll_open task.description)",
  "payload_data": { "...only the fields this operation needs (see table)..." },

  "episode": "OPTIONAL: reuse the poll's episode UUID (omit on poll_open to mint a fresh one)",
  "poll_id": "OPTIONAL: reuse the poll's poll_id (omit on poll_open to mint a fresh one)",
  "poll_open_id": "OPTIONAL: the poll_open message.id — set as parents on every non-poll_open turn"
}
```

`operation` fully determines `kind`/`subkind` and the receiver (see Fixed values) — you
don't supply those.

## Fixed values

- `header.protocol` = `"SSTP"`, `header.subprotocol` = `"TFP"`, `header.version` = `"0"`
- `header.kind` / `header.subkind` from `operation`:
  - `poll_open` → `intent` / `team-formation`
  - `bid` `select` `accept` → `exchange` / `team-formation`
  - `form_converged` → `commit` / `converged`
  - `form_failed` → `commit` / `abort`
- `header.participants.groups` = `null`. `header.participants.actors` is a **cumulative,
  insertion-ordered roster of every agent seen so far in the episode**, rebuilt on each turn
  (it keeps growing as agents join and eventually lists everyone who took part):
  - `actors[0]` = this turn's `sender`, role `"sender"`
  - then this turn's addressed receiver(s), role `"receiver"`: `bid` and `accept` (from a
    candidate) add `recruiter`; `select` (from the recruiter) adds the target candidate
  - then **every other agent that already appeared earlier in the episode**, role
    `"participant"` (carried forward — an agent joins the roster the first time it sends or is
    addressed, and persists as `"participant"` on all later turns)
  - a new agent "joins" the list the first time it participates, so the roster only grows,
    never shrinks or reorders past entries
  - broadcast turns have **no receiver**: `poll_open`'s roster is just `[recruiter]`;
    `form_converged` / `form_failed` carry the full accumulated roster (`recruiter` as
    `sender`, everyone else as `participant`)
  - only **agents** are actors — never add a broadcast channel / `topic:` as an actor
  - the roster is stamped by the sequencer that has seen the whole episode. If you build a
    single turn in isolation, include exactly the agents you've been told already
    participated — don't invent participants you have no evidence for.
- `header.message.parents`: `poll_open` → `[]`; every other turn → `[<poll_open message.id>]`
- `header.context.topic` = `"Forming a team to <task_description>"`; `header.context.epistemic` = `null`; `header.context.semantic` = `null`; `header.policy` = `null`
- `payload.type` = `"json-schema"`; `payload.data.operation` and `payload.data.poll_id` are always present; `payload.data.required_skills` is populated on `poll_open`, otherwise `[]`
- **IDs:** `message.id` and `episode` are fresh UUID v4 (bare); `poll_id` is `urn:ioc:tfp:poll:<hex>`. Mint `episode` + `poll_id` once on `poll_open` and reuse them on every later turn.

## Golden example (canonical L9 TFP `poll_open`, from the reference dumps)

> **Structure only** (see "Examples are structure only" above). Generate a fresh
> `message.id` + `episode` (UUID v4) and a fresh `poll_id` (`urn:ioc:tfp:poll:<hex>`), and
> fill every `<...>` placeholder from the user's inputs. The ids shown are illustrative
> format samples, not values to reuse.

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "TFP",
    "version": "0",
    "kind": "intent",
    "subkind": "team-formation",
    "participants": { "actors": [ { "id": "recruiter", "role": "sender", "attestation": null } ], "groups": null },
    "message": { "id": "<uuid-v4>", "parents": [], "episode": "<uuid-v4>" },
    "policy": null,
    "context": { "topic": "Forming a team to <task description>", "epistemic": null, "semantic": null }
  },
  "payload": {
    "type": "json-schema",
    "data": {
      "operation": "poll_open",
      "poll_id": "urn:ioc:tfp:poll:<hex>",
      "task": { "task_id": "<task-id>", "description": "<task description>", "objective": "<measurable objective>" },
      "required_skills": [
        { "skill": "skill:<skill-1>", "min_proficiency": 0.7, "weight": 2.0, "mandatory": true },
        { "skill": "skill:<skill-2>", "min_proficiency": 0.6, "weight": 1.5, "mandatory": true }
      ],
      "reasoning_summary": "<why these skills are needed>"
    }
  }
}
```

## Per-operation `payload.data`

Same envelope every turn — only `kind`/`subkind` and `payload.data` change.
`operation`, `poll_id`, and `required_skills` (`[]` unless `poll_open`) are always present.

| operation | sender → receiver | payload.data (besides `operation`, `poll_id`, `required_skills`) |
|-----------|-------------------|------------------------------------------------------------------|
| `poll_open` | recruiter → (broadcast) | `task`, `required_skills` (populated), `reasoning_summary` |
| `bid` | agent-a / agent-b → recruiter | `offer` (`{ "skills": [{skill, proficiency}], "fit_score": <0..1> }`), `reasoning_summary` |
| `select` | recruiter → candidate | `selection` (`{ "members": [...], "roles": [{agent_id, role, responsible_for}], "coverage": <0..1>, "unmet_skills": [], "aggregate_fit": <0..1> }`) |
| `accept` | agent-a / agent-b → recruiter | `reason` |
| `form_converged` | recruiter → (broadcast) | `selection` (coverage `1.0`, `unmet_skills: []`), `reasoning_summary` |
| `form_failed` | recruiter → (broadcast) | `selection` (coverage `< 1.0`, non-empty `unmet_skills`), `reasoning_summary` |

Both closes below are **full L9 messages** and are the two alternative endings of the
**same poll** as the golden `poll_open` above. Note the ids are in sync: `episode` and
`poll_id` match the `poll_open`, `parents` is the `poll_open` `message.id`
(`<poll_open message.id>`), and only `message.id` (a fresh UUID) and the payload differ.

The `skill:<...>` names and the role assignments are placeholders — fill `selection` and
`reasoning_summary` with the real team decision for the user's task.

### Success close — `form_converged` (full message)

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "TFP",
    "version": "0",
    "kind": "commit",
    "subkind": "converged",
    "participants": { "actors": [ { "id": "recruiter", "role": "sender", "attestation": null }, { "id": "agent-a", "role": "participant", "attestation": null }, { "id": "agent-b", "role": "participant", "attestation": null } ], "groups": null },
    "message": { "id": "<uuid-v4>", "parents": [ "<poll_open message.id>" ], "episode": "<same episode as poll_open>" },
    "policy": null,
    "context": { "topic": "Forming a team to <task description>", "epistemic": null, "semantic": null }
  },
  "payload": {
    "type": "json-schema",
    "data": {
      "operation": "form_converged",
      "poll_id": "<same poll_id as poll_open>",
      "required_skills": [],
      "selection": {
        "members": [ "agent-a", "agent-b" ],
        "roles": [
          { "agent_id": "agent-a", "role": "contributor", "responsible_for": [ "skill:<skill-1>" ] },
          { "agent_id": "agent-b", "role": "contributor", "responsible_for": [ "skill:<skill-2>" ] }
        ],
        "coverage": 1.0,
        "unmet_skills": [],
        "aggregate_fit": 0.3245
      },
      "reasoning_summary": "<why the team converged; e.g. all mandatory skills covered>"
    }
  }
}
```

### Failure close — `form_failed` (full message)

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "TFP",
    "version": "0",
    "kind": "commit",
    "subkind": "abort",
    "participants": { "actors": [ { "id": "recruiter", "role": "sender", "attestation": null }, { "id": "agent-a", "role": "participant", "attestation": null }, { "id": "agent-b", "role": "participant", "attestation": null } ], "groups": null },
    "message": { "id": "<uuid-v4>", "parents": [ "<poll_open message.id>" ], "episode": "<same episode as poll_open>" },
    "policy": null,
    "context": { "topic": "Forming a team to <task description>", "epistemic": null, "semantic": null }
  },
  "payload": {
    "type": "json-schema",
    "data": {
      "operation": "form_failed",
      "poll_id": "<same poll_id as poll_open>",
      "required_skills": [],
      "selection": {
        "members": [ "agent-a", "agent-b" ],
        "roles": [
          { "agent_id": "agent-a", "role": "contributor", "responsible_for": [ "skill:<skill-1>" ] },
          { "agent_id": "agent-b", "role": "contributor", "responsible_for": [ "skill:<skill-2>" ] }
        ],
        "coverage": 0.6667,
        "unmet_skills": [ "skill:<uncovered-mandatory-skill>" ],
        "aggregate_fit": 0.2655
      },
      "reasoning_summary": "<why forming failed; e.g. mandatory skill <uncovered-mandatory-skill> uncovered>"
    }
  }
}
```

## Session finality

Once a `form_converged` or `form_failed` message is emitted, the poll is **terminal**. Do
NOT offer or generate any further turns for that `episode`/`poll_id`. If the user wants to
form another team, start a fresh poll (new `poll_open` with new ids).

## Output

Output ONLY valid JSON — no explanation, no markdown fences. Before emitting, confirm no
`<...>` placeholder remains and that every domain value (task, skills, roles, numbers,
ids) comes from the user's request rather than the examples.

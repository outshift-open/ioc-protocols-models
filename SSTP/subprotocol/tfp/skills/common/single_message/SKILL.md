---
name: tfp-single-message
description: Builds ONE correctly-formatted TFP (Team Formation Protocol) L9 message from explicit inputs (operation, sender, receiver, payload). Non-interactive and cast-agnostic. Use tfp-message-generation instead for the guided fixed-cast flow.
---

# TFP Single-Message Builder

Given an `operation`, a `sender`, an optional `receiver`, and the operation's data, emit **one**
TFP L9 message (header + payload) as valid JSON. No prompting, no fixed cast.

## Source of truth (fetch raw every time)

Derive all fields, types, required keys, and enums from these — the schema wins over anything here.

- L9: `https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json`
- TFP: `https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/tfp/spec/tfp_schema.json`

## Inputs

```json
{
  "operation": "poll_open | bid | decline | clarify | select | accept | reject | re_poll | form_converged | form_failed",
  "sender": "<agent id>",
  "receiver": "<agent id, or null for broadcasts: poll_open, re_poll, form_converged, form_failed>",
  "participants": ["<other agent ids already in the episode>"],
  "task_description": "<short task text>",
  "payload_data": { "...only the fields this operation needs..." },
  "episode": "reuse the poll's UUID (omit on poll_open to mint fresh)",
  "poll_id": "reuse the poll's urn:ioc:tfp:poll:<hex> (omit on poll_open to mint fresh)",
  "poll_open_id": "the poll_open message.id — set as parents on every non-poll_open turn"
}
```

Only `operation` + `sender` are required.

## Assembly

- `protocol`=`"SSTP"`, `subprotocol`=`"TFP"`, `version`=`"0"`.
- `kind`/`subkind` from `operation`: `poll_open`→`intent`/`team-formation`;
  `form_converged`→`commit`/`converged`; `form_failed`→`commit`/`abort`; all others→`exchange`/`team-formation`.
- `participants.groups`=`null`; `actors` = `sender` (role `sender`), then `receiver` (role
  `receiver`, omitted for broadcasts), then each `participants` id (role `participant`). Agents only.
- `message.id` = fresh UUID v4; `episode` = input (or fresh UUID v4 on `poll_open`);
  `parents` = `[]` on `poll_open`, else `[poll_open_id]`.
- `context.topic` = `"Forming a team to <task_description>"`; `epistemic`/`semantic`/`policy` = `null`.
- `payload.type`=`"json-schema"`; `data.operation` + `data.poll_id` always present;
  `data.required_skills` populated on `poll_open` (all needed skills) and `re_poll` (the still-uncovered
  ones), `[]` otherwise. Add the operation's fields:

| operation | receiver | extra `payload.data` |
|-----------|----------|----------------------|
| `poll_open` | broadcast | `task`, `required_skills`, `reasoning_summary` |
| `bid` | recruiter | `offer` (`skills:[{skill,proficiency}]`, `fit_score`), `reasoning_summary` |
| `decline`/`accept`/`reject`/`clarify` | recruiter | `reason` |
| `select` | candidate | `selection` (`members`, `roles:[{agent_id,role,responsible_for}]`, `coverage`, `unmet_skills`, `aggregate_fit`) |
| `re_poll` | broadcast | `required_skills` (uncovered), `reasoning_summary` |
| `form_converged` | broadcast | `selection` (`coverage:1.0`, `unmet_skills:[]`), `reasoning_summary` |
| `form_failed` | broadcast | `selection` (`coverage<1.0`, non-empty `unmet_skills`), `reasoning_summary` |

## Output

Output ONLY the single L9 JSON message — no prose, no fences. Optionally check it with
`tfp-message-validation`.

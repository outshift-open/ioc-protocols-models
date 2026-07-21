---
name: sab-message-generation
description: Generates a complete SAB L9 message (header + SAB payload) as valid JSON.
---

# SAB L9 Message Generator

Produce one complete SAB (Semantic Alignment via Bargaining) L9 message — header +
payload — as valid JSON on stdout. SAB runs NegMAS Stacked Alternating Offers: agents
exchange offers and converge on one option per issue.

To keep things simple this skill uses a **fixed cast of three actors** and covers only the
two end-to-end outcomes:

- **`agent-buyer`**, **`agent-seller`** — the two negotiators that make and answer offers.
- **`negotiation_server`** — the facilitator that runs the session (present on every
  message, never proposes).

Two flows (mirroring `examples/demo_agreement.json` and `examples/demo_disagreement.json`):

- **Agreement** → `open` → `agent-buyer` offer (`NO_RESPONSE`) → `agent-seller` counter
  (`REJECT_OFFER`) → `agent-buyer` counter (`REJECT_OFFER`) → `agent-seller` accept
  (`ACCEPT_OFFER`) → `close` `resolved`
- **Disagreement** → `open` → the same alternating counters until the step budget is
  exhausted (the last round has `timedout: true`) → `close` `unresolved`

## SAB is special

- **SAB does not define its own header.** A SAB message *is* a canonical L9 message: a standard `L9Header` (`protocol: "SSTP"`, `subprotocol: "SAB"`) plus `L9Payload` (`type: "json-schema"`, `data` = the SAB payload). The `sab_schema.json` models **only `payload.data`**.
- Only two `kind`s: `contingency` (the open and every offer round, `subkind: "negotiation"`) and `commit` (the close, `subkind: "resolved" | "unresolved" | "timeout"`). SAB never uses `intent`/`exchange`/`knowledge` as the L9 `kind`.
- `payload.data` has three shapes, chosen by **phase**: `open` → `SABIntentPayloadData`, `round` → `SABNegotiatePayloadData`, `close` → `SABCommitPayloadData`.
- The negotiation space (mission, `issues`, `options_per_issue`) is **not** in `payload.data` — it is encoded into `header.context.topic`, and `header.context.semantic.schema_id = "urn:ioc:schema:sab-l9:v1"` identifies the envelope. `msg_created_at` lives in `header.attributes`.

## Examples are structure only — never copy their content

Every JSON block below uses **angle-bracket placeholders** (e.g. `<mission>`, `<issue-1>`,
`<chosen option>`) wherever a value depends on the use case. They exist only to show the
message *shape*. Fill every placeholder from the user's inputs — a `<...>` token must never
appear in your output, and nothing from these examples should carry over unchanged.

- **Keep (fixed structure):** `protocol` / `subprotocol` / `version`, the `kind` / `subkind`
  mapping, `payload.type`, the three-actor cast and their roles (`participant` /
  `facilitator`), `parents: []`, `context.semantic` (`schema_id` / `ontology_ref`),
  `context.epistemic` / `policy` = `null`, `version: "0"`, and the `sao_state` / `sao_response`
  / `nmi` field scaffolding and flags.
- **Replace from the user's use case (fill every placeholder):** `context.topic` (the
  `<mission>` plus `issues` / `options_per_issue`), `origin.actor_id` (which agent is acting),
  every `current_offer` / `sao_response.outcome` / `agreement`, `final_agreement`,
  `content_text`, the timings (`dt_created`, `msg_created_at`, `time`, `relative_time`,
  `step`), and all ids (`message.id`, `episode`, `session_id`, `payload_hash`).

The numbers in the examples (`time`, `relative_time`, `step`, the `nmi` limits) are
placeholder magnitudes — set them for the real session. Only the outcome-defining values are
fixed by the phase: an acceptance sets `n_acceptances: 1`, `running: false`, and `sao_state.agreement`;
`close` `resolved` needs `outcome: "agreement"` with a non-null `final_agreement`, while
`close` `unresolved`/`timeout` needs `final_agreement: null`.

## Defaults — use only if the user doesn't supply a value

Always prefer the user's real values. If the user is vague or skips a field, fall back to
these — the "Quick Deal" sample taken verbatim from the reference dumps
(`examples/demo_agreement.json`, `examples/demo_disagreement.json`):

| placeholder | default value (from the dumps) |
|-------------|--------------------------------|
| `<mission>` | `Two parties need to agree on price and delivery speed for an urgent supply order.` |
| `<issue-1>` / `<issue-2>` | `price` / `delivery_speed` |
| options for `price` | `["low", "medium", "high"]` |
| options for `delivery_speed` | `["express", "standard", "deferred"]` |
| opening offer (step 0, `agent-buyer`) | `{ "price": "high", "delivery_speed": "express" }` |
| agreed offer (resolved) | `{ "price": "medium", "delivery_speed": "standard" }` |
| `episode` (agreement / disagreement) | `urn:ioc:episode:supply-order-urgent-2026-001` / `...-002` |
| `session_id` (agreement / disagreement) | `urn:ioc:sab:session:qd-2026-06-22-001` / `...-002` |
| ids (`message.id`, `payload_hash`) | **never default — always generate fresh** |

## Behavior — interactive prompt

When invoked, do NOT emit a message immediately:

1. **Ask which step to build**: `open | round | close`.
   - `open` — start the session; the mission, `issues`, and `options_per_issue` go into `header.context.topic`.
   - `round` — one alternating-offers turn: an **opening offer** (`NO_RESPONSE`), a **counter** (`REJECT_OFFER`), or an **acceptance** (`ACCEPT_OFFER`).
   - `close` — commit the outcome: `resolved` (agreement) or `unresolved` (no deal).
2. **Ask only that step's fields** (see the table), then show a pre-filled sample using the
   fixed cast (defaulting from the table above) and ask _"Use this as-is, or tell me what to change?"_
3. **Confirm or collect edits**, then emit the full L9 JSON for that single step, reusing
   the session's `episode` and `session_id`.
4. **Repeat from step 1.** The session is not over until the user completes a
   `close` turn (`resolved` or `unresolved`). Keep prompting for the next step.

## Source of truth (fetch raw content every time)

Fetch these raw files and derive all field names, types, required fields, and enum values from them. Do not rely on memory.

- L9 envelope (the whole header + payload wrapper): https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — `$defs.L9`, `L9Header`, `L9Payload`, `ParticipantSet`, `Actor`, `Context`, `Kind`
- SAB `payload.data` only: https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/sab/spec/sab_schema.json — `$defs.SABPayloadData` (root union), `SABIntentPayloadData`, `SABNegotiatePayloadData`, `SABCommitPayloadData`, `SemanticContext`, `NegotiateSemanticContext`, `NegotiateCommitSemanticContext`, `SAOState`, `SAOResponse`, `SAONMI`, `SABOrigin`, `ResponseType`

(These JSON schemas are authoritative; the Python bindings are generated from them.)

## Inputs — what YOU provide

Provide exactly this small object. Everything else (UUIDs, `payload_hash`, and all the "Fixed values" below) is filled in for you — do not provide them.

```json
{
  "phase": "open | round | close",
  "sender": "the agent acting this turn → payload.data.origin.actor_id (agent-buyer | agent-seller)",
  "mission": "one-line description of what is being negotiated",
  "issues": ["price", "delivery_speed"],
  "options_per_issue": { "price": ["low","medium","high"], "delivery_speed": ["express","standard","deferred"] },
  "episode": "OPTIONAL: reuse the session's episode urn (omit on open to mint one)",
  "session_id": "OPTIONAL: reuse the session's session_id urn (omit on open to mint one)",
  "payload_data": { "...phase-specific fields (see table)..." }
}
```

There is **no `receivers`/broadcast** field: every message carries the same
`participants` (both negotiators as role `participant` plus the `negotiation_server`
facilitator), and the acting agent is named only in `payload.data.origin.actor_id`.

Field guide by `phase`:
- `open` → `contingency:negotiation`, `parents: []`. `payload_data` is just the intent envelope (`semantic_context` with `schema_version`/`encoding`).
- `round` → `contingency:negotiation`, `parents: []`. `payload_data`: the `current_offer` (one option per issue), `current_proposer`, `step`, and `sao_response.response` — one of `"NO_RESPONSE"` (opening offer), `"REJECT_OFFER"` (counter), `"ACCEPT_OFFER"` (acceptance).
- `close` → `commit`, `parents: []`. `payload_data`: `outcome` (`agreement`|`disagreement`), `final_agreement` (list of `{issue_id, chosen_option}` or `null`), and set `subkind` `resolved` (agreement) / `unresolved`.

## Fixed values

- `header.protocol` = `"SSTP"`, `header.subprotocol` = `"SAB"`, `header.version` = `"0"`
- `header.kind`/`subkind`: `open`/`round` → `contingency`/`negotiation`; `close` → `commit`/(`resolved`|`unresolved`|`timeout`)
- `header.attributes` = `{ "msg_created_at": "<ISO-8601>" }` (a plain dict); `header.participants.groups` = `null`
- `header.context.topic` = `"<mission> | issues: <issues> | options_per_issue: <options_per_issue>"`; `header.context.epistemic` = `null`; `header.context.semantic` = `{ "schema_id": "urn:ioc:schema:sab-l9:v1", "ontology_ref": "urn:ioc:ontology:sab:v1", "provenance": null }`
- `header.participants.actors` is the **same on every message**: `agent-buyer` and `agent-seller` as `{ "id": <agent>, "role": "participant", "attestation": null }`, followed by `{ "id": "negotiation_server", "role": "facilitator", "attestation": null }`
- `header.message.parents` = `[]` on **every** message (SAB does not thread via `parents`; the round/close messages are tied to the session by the shared `episode` + `session_id`)
- `payload.type` = `"json-schema"`; `payload.data.message_id` = the header `message.id`; `payload.data.version` = `"0"`; `payload.data.origin` = `{ "actor_id": <sender>, "attestation": null }`
- **IDs:** `message.id` (and the matching `payload.data.message_id`) is a fresh UUID v4. `episode` and `session_id` are stable `urn:` identifiers for the whole negotiation — the reference dumps use descriptive slugs (`urn:ioc:episode:<slug>`, `urn:ioc:sab:session:<slug>`); mint them once on `open` and reuse across every message in the session. `payload_hash` is a 64-hex SHA-256 digest.
- `sao_response.response` is the `ResponseType` **name string** (as serialized on the wire): `"ACCEPT_OFFER"` (0), `"REJECT_OFFER"` (1), `"END_NEGOTIATION"` (2), `"NO_RESPONSE"` (3), `"WAIT"` (4), `"LEAVE"` (5). Opening offer uses `"NO_RESPONSE"`; a counter uses `"REJECT_OFFER"`; acceptance uses `"ACCEPT_OFFER"`.

## Golden example (canonical SAB `open` = `contingency:negotiation`)

> **Structure only** (see "Examples are structure only" above). Generate a fresh UUID v4 for
> `message.id`, mint your own `episode` / `session_id` (`urn:ioc:episode:<slug>` /
> `urn:ioc:sab:session:<slug>`) and a fresh `payload_hash`, and fill every `<...>`
> placeholder from the user's inputs.

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "SAB",
    "version": "0",
    "kind": "contingency",
    "subkind": "negotiation",
    "participants": { "actors": [ { "id": "agent-buyer", "role": "participant", "attestation": null }, { "id": "agent-seller", "role": "participant", "attestation": null }, { "id": "negotiation_server", "role": "facilitator", "attestation": null } ], "groups": null },
    "message": { "id": "<uuid-v4>", "parents": [], "episode": "urn:ioc:episode:<slug>" },
    "policy": null,
    "attributes": { "msg_created_at": "<ISO-8601>" },
    "context": {
      "topic": "<mission> | issues: [\"<issue-1>\", \"<issue-2>\"] | options_per_issue: {\"<issue-1>\": [\"<opt>\", \"<opt>\", \"<opt>\"], \"<issue-2>\": [\"<opt>\", \"<opt>\", \"<opt>\"]}",
      "epistemic": null,
      "semantic": { "schema_id": "urn:ioc:schema:sab-l9:v1", "ontology_ref": "urn:ioc:ontology:sab:v1", "provenance": null }
    }
  },
  "payload": {
    "type": "json-schema",
    "data": {
      "message_id": "<uuid-v4>",
      "version": "0",
      "dt_created": "<ISO-8601>",
      "origin": { "actor_id": "agent-buyer", "attestation": null },
      "payload_hash": "<64-hex sha-256>",
      "semantic_context": { "schema_version": "1.0", "encoding": "json" }
    }
  }
}
```

## `round` — `payload.data`

Same L9 envelope as `open` (`kind:contingency` / `subkind:negotiation`, same `participants`,
`parents: []`); only `payload.data` changes. The `<...>` offers are use-case content — fill
them from the user's `options_per_issue`.

```json
{
  "message_id": "<uuid-v4>",
  "version": "0",
  "dt_created": "<ISO-8601>",
  "origin": { "actor_id": "agent-buyer", "attestation": null },
  "payload_hash": "<64-hex sha-256>",
  "semantic_context": {
    "schema_version": "1.0", "encoding": "json", "session_id": "urn:ioc:sab:session:<slug>",
    "sao_state": {
      "running": true, "waiting": false, "started": true, "step": 0, "time": 2.1, "relative_time": 0.035,
      "broken": false, "timedout": false, "agreement": null, "results": null, "n_negotiators": 2,
      "has_error": false, "error_details": "", "erred_negotiator": "", "erred_agent": "", "threads": {},
      "last_thread": "", "left_negotiators": [],
      "current_offer": { "<issue-1>": "<chosen option>", "<issue-2>": "<chosen option>" },
      "current_proposer": "agent-buyer", "current_proposer_agent": "agent-buyer",
      "n_acceptances": 0, "new_offers": [], "new_offerer_agents": [], "last_negotiator": null,
      "current_data": null, "new_data": [], "n_participating": 2
    },
    "sao_response": { "response": "NO_RESPONSE", "outcome": { "<issue-1>": "<chosen option>", "<issue-2>": "<chosen option>" }, "data": null },
    "nmi": { "id": "urn:ioc:sab:session:<slug>", "n_outcomes": 9, "shared_time_limit": 60.0, "shared_n_steps": 40, "private_time_limit": 30.0, "private_n_steps": null, "pend": 0.0, "pend_per_second": 0.0, "step_time_limit": 10.0, "negotiator_time_limit": 5.0, "dynamic_entry": false, "max_n_negotiators": null, "annotation": {}, "end_on_no_response": true, "one_offer_per_step": false, "offering_is_accepting": true, "allow_none_with_data": true, "allow_negotiators_to_leave": true },
    "offer_validation_failure": null
  }
}
```

- `nmi` is populated on the **first** round and is `null` thereafter.
- Opening offer → `sao_response.response = "NO_RESPONSE"`; a counter → `"REJECT_OFFER"`. Each
  offer/counter flips `origin.actor_id` / `current_proposer` / `current_proposer_agent`
  between `agent-buyer` and `agent-seller`, sets `current_offer` = `sao_response.outcome` (the
  offer just made), and `last_negotiator` = the previous proposer (`null` on the opening
  offer, `step` counting up from 0).
- **Acceptance:** `origin.actor_id` is the *accepting* agent, but `current_offer` /
  `current_proposer` / `current_proposer_agent` stay the **standing offer being accepted**
  (proposed by the *other* agent), and `last_negotiator` is that proposer — they do **not**
  flip to the accepter. Set `sao_response.response = "ACCEPT_OFFER"` with `outcome` = that
  offer, `n_acceptances = 1`, `running = false`, and `sao_state.agreement` = the agreed offer
  (because `offering_is_accepting = true`).
- **Timed-out final round (disagreement path):** the last `round` keeps `response = "REJECT_OFFER"` but sets `sao_state.timedout = true` and `running = false` once the step budget is exhausted.

## Success close — `resolved` (full message)

`kind:commit` / `subkind:resolved`, same three-actor cast, `parents: []`, `outcome: "agreement"`
with a non-null `final_agreement`.

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "SAB",
    "version": "0",
    "kind": "commit",
    "subkind": "resolved",
    "participants": { "actors": [ { "id": "agent-buyer", "role": "participant", "attestation": null }, { "id": "agent-seller", "role": "participant", "attestation": null }, { "id": "negotiation_server", "role": "facilitator", "attestation": null } ], "groups": null },
    "message": { "id": "<uuid-v4>", "parents": [], "episode": "<same episode as open>" },
    "policy": null,
    "attributes": { "msg_created_at": "<ISO-8601>" },
    "context": {
      "topic": "<mission> | issues: [\"<issue-1>\", \"<issue-2>\"] | options_per_issue: {\"<issue-1>\": [\"<opt>\", \"<opt>\", \"<opt>\"], \"<issue-2>\": [\"<opt>\", \"<opt>\", \"<opt>\"]}",
      "epistemic": null,
      "semantic": { "schema_id": "urn:ioc:schema:sab-l9:v1", "ontology_ref": "urn:ioc:ontology:sab:v1", "provenance": null }
    }
  },
  "payload": {
    "type": "json-schema",
    "data": {
      "message_id": "<uuid-v4>",
      "version": "0",
      "dt_created": "<ISO-8601>",
      "origin": { "actor_id": "agent-buyer", "attestation": null },
      "payload_hash": "<64-hex sha-256>",
      "semantic_context": {
        "schema_version": "1.0", "encoding": "json", "session_id": "<same session_id as open>",
        "outcome": "agreement", "error_message": null,
        "content_text": "<mission>",
        "agents_negotiating": [ "agent-buyer", "agent-seller" ],
        "final_agreement": [ { "issue_id": "<issue-1>", "chosen_option": "<chosen option>" }, { "issue_id": "<issue-2>", "chosen_option": "<chosen option>" } ]
      }
    }
  }
}
```

## Failure close — `unresolved` (full message)

Identical envelope except `subkind: "unresolved"`, `outcome: "disagreement"`,
`final_agreement: null` (`unresolved` is the no-deal / step-budget-exhausted close; use
`subkind: "timeout"` instead only if a participant broke off or returned an invalid offer).
The `outcome` field must always be set: `"agreement"` for `resolved`, `"disagreement"` for
`unresolved` or `timeout`.

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "SAB",
    "version": "0",
    "kind": "commit",
    "subkind": "unresolved",
    "participants": { "actors": [ { "id": "agent-buyer", "role": "participant", "attestation": null }, { "id": "agent-seller", "role": "participant", "attestation": null }, { "id": "negotiation_server", "role": "facilitator", "attestation": null } ], "groups": null },
    "message": { "id": "<uuid-v4>", "parents": [], "episode": "<same episode as open>" },
    "policy": null,
    "attributes": { "msg_created_at": "<ISO-8601>" },
    "context": {
      "topic": "<mission> | issues: [\"<issue-1>\", \"<issue-2>\"] | options_per_issue: {\"<issue-1>\": [\"<opt>\", \"<opt>\", \"<opt>\"], \"<issue-2>\": [\"<opt>\", \"<opt>\", \"<opt>\"]}",
      "epistemic": null,
      "semantic": { "schema_id": "urn:ioc:schema:sab-l9:v1", "ontology_ref": "urn:ioc:ontology:sab:v1", "provenance": null }
    }
  },
  "payload": {
    "type": "json-schema",
    "data": {
      "message_id": "<uuid-v4>",
      "version": "0",
      "dt_created": "<ISO-8601>",
      "origin": { "actor_id": "agent-buyer", "attestation": null },
      "payload_hash": "<64-hex sha-256>",
      "semantic_context": {
        "schema_version": "1.0", "encoding": "json", "session_id": "<same session_id as open>",
        "outcome": "disagreement", "error_message": null,
        "content_text": "<mission>",
        "agents_negotiating": [ "agent-buyer", "agent-seller" ],
        "final_agreement": null
      }
    }
  }
}
```

## Session finality

Once a `close` message is emitted (`resolved`, `unresolved`, or `timeout`), the session
is **terminal**. Do NOT offer or generate any further steps for that `episode`/`session_id`.
If the user wants to continue negotiating, start a fresh session (new `open` with new ids).

## Output

Output ONLY valid JSON — no explanation, no markdown fences. Before emitting, confirm no
`<...>` placeholder remains and that every domain value (mission, issues, options, offers,
ids) comes from the user's request rather than the examples.

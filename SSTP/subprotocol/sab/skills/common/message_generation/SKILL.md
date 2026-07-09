---
name: sab-message-generation
description: Generates a complete SAB L9 message (header + SAB payload) as valid JSON.
---

# SAB L9 Message Generator

Produce a complete SAB (Semantic Alignment via Bargaining) message — header + payload — as valid JSON on stdout. SAB runs NegMAS Stacked Alternating Offers: agents exchange offers and converge on one option per issue.

## Behavior — interactive prompt

When invoked, do NOT emit a message immediately. Walk the user through one step of a
Stacked Alternating Offers (SAO) negotiation, using SAB's own vocabulary:

1. **Ask which negotiation step to build** (these map to the three SAB payload shapes):
   - `open` — open a new bargaining session; the mission, the `issues`, and the
     `options_per_issue` on the table are encoded into `header.context.topic`
   - `round` — make an **offer**, **counter-offer**, or **acceptance** in the
     alternating-offers loop (one option per issue)
   - `close` — **commit** the final outcome: `converged` (agreement), `disagreement`,
     or `timeout`
2. **Ask the step-specific bargaining details**, then show a pre-filled sample and ask
   _"Use this as-is, or tell me what to change?"_:
   - `open` → who initiates (the `origin` agent), the mission text, and each issue's options
   - `round` → the current `offer` (one option per issue), the `proposer`, the `step`
     number, and whether this is an **opening offer** (`sao_response.response =
     "NO_RESPONSE"`), a **counter** (`"REJECT_OFFER"`), or an **acceptance**
     (`"ACCEPT_OFFER"`, re-proposing the same offer with `n_acceptances = 1` and
     `sao_state.agreement` set)
   - `close` → the `outcome` (agreement / disagreement / broken / error) and the
     `final_agreement` (one chosen option per issue, or `null` if no deal)
3. **Confirm or collect edits**, then emit the full L9 JSON for that single step,
   reusing the session's `episode` and `session_id`.

## Source of truth (fetch raw content every time)

Fetch these raw files and derive all field names, types, required fields, and enum values from them. Do not rely on memory.

- L9 envelope (the whole header + payload wrapper): https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — `$defs.L9`, `L9Header`, `L9Payload`, `ParticipantSet`, `Actor`, `Context`, `Kind`
- SAB `payload.data` only: https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/sab/spec/sab_schema.json — `$defs.SABPayloadData` (root union), `SABIntentPayloadData`, `SABNegotiatePayloadData`, `SABCommitPayloadData`, `SemanticContext`, `NegotiateSemanticContext`, `NegotiateCommitSemanticContext`, `SAOState`, `SAOResponse`, `SAONMI`, `SABOrigin`, `ResponseType`

(These JSON schemas are authoritative; the Python bindings are generated from them.)

## SAB is special

- **SAB does not define its own header.** A SAB message *is* a canonical L9 message: a standard `L9Header` (with `protocol: "SSTP"`, `subprotocol: "SAB"`) plus `L9Payload` (`type: "json-schema"`, `data` = the SAB payload). The `sab_schema.json` models **only `payload.data`**.
- Only two `kind`s: `contingency` (the open and every offer round, `subkind: "negotiation"`) and `commit` (the close, `subkind: "converged" | "disagreement" | "timeout"`). SAB never uses `intent`/`exchange`/`knowledge` as the L9 `kind`.
- `payload.data` has three shapes, chosen by **phase**: `open` → `SABIntentPayloadData`, `round` → `SABNegotiatePayloadData`, `close` → `SABCommitPayloadData`.
- The negotiation space (mission, `issues`, `options_per_issue`) is **not** in `payload.data` — it is encoded into `header.context.topic`, and `header.context.semantic.schema_id = "urn:ioc:schema:sab-l9:v1"` identifies the envelope. `msg_created_at` lives in `header.attributes`.

## Inputs — what YOU provide

Provide exactly this small object. Everything else (UUIDs, `payload_hash`, and all the "Fixed values" below) is filled in for you — do not provide them.

```json
{
  "phase": "open | round | close",
  "sender": "the agent acting this turn → payload.data.origin.actor_id, e.g. agent-buyer",
  "agents": ["agent-buyer", "agent-seller"],
  "mission": "one-line description of what is being negotiated",
  "issues": ["price", "delivery_speed"],
  "options_per_issue": { "price": ["low","medium","high"], "delivery_speed": ["express","standard","deferred"] },
  "session_id": "urn:ioc:sab:session:<slug>",
  "payload_data": { "...phase-specific fields (see table)..." }
}
```

There is **no `receivers`/broadcast** field: every message carries the same
`participants` (all `agents` as role `participant` plus a `negotiation_server`
facilitator), and the acting agent is named only in `payload.data.origin.actor_id`.

Field guide by `phase`:
- `open` → `contingency:negotiation`, `parents: []`. `payload_data` is empty (just the intent envelope: `SemanticContext` with `schema_version`/`encoding`).
- `round` → `contingency:negotiation`, `parents: []`. `payload_data`: the `offer` (one option per issue), `proposer`, `step`, and `response` — one of `"NO_RESPONSE"` (opening offer), `"REJECT_OFFER"` (counter), `"ACCEPT_OFFER"` (acceptance).
- `close` → `commit`, `parents: []`. `payload_data`: `outcome` (`agreement`|`disagreement`|`broken`|`error`), `final_agreement` (list of `{issue_id, chosen_option}` or `null`), and set `subkind` `converged` (agreement) / `disagreement` / `timeout`.

## Fixed values

- `header.protocol` = `"SSTP"`, `header.subprotocol` = `"SAB"`, `header.version` = `"0"`
- `header.kind`/`subkind`: `open`/`round` → `contingency`/`negotiation`; `close` → `commit`/(`converged`|`disagreement`|`timeout`)
- `header.attributes` = `{ "msg_created_at": "<ISO-8601>" }` (a plain dict); `header.participants.groups` = `null`
- `header.context.topic` = `"<mission> | issues: <issues> | options_per_issue: <options_per_issue>"`; `header.context.epistemic` = `null`; `header.context.semantic` = `{ "schema_id": "urn:ioc:schema:sab-l9:v1", "ontology_ref": "urn:ioc:ontology:sab:v1", "provenance": null }`
- `header.participants.actors` is the **same on every message**: each `agents` entry as `{ "id": <agent>, "role": "participant", "attestation": null }`, followed by `{ "id": "negotiation_server", "role": "facilitator", "attestation": null }`
- `header.message.parents` = `[]` on **every** message (SAB does not thread via `parents`; the round/close messages are tied to the session by the shared `episode` + `session_id`)
- `payload.type` = `"json-schema"`; `payload.data.message_id` = the header `message.id`; `payload.data.version` = `"0"`; `payload.data.origin` = `{ "actor_id": <sender>, "attestation": null }`
- **IDs:** `message.id` (and the matching `payload.data.message_id`) is a fresh UUID v4. `episode` and `session_id` are stable `urn:` identifiers for the whole negotiation — the reference dumps use descriptive slugs (`urn:ioc:episode:<slug>`, e.g. `urn:ioc:episode:supply-order-urgent-2026-001`; `urn:ioc:sab:session:<slug>`, e.g. `urn:ioc:sab:session:qd-2026-06-22-001`); mint them once and reuse across every message in the session. `payload_hash` is a 64-hex SHA-256 digest.
- `sao_response.response` is the `ResponseType` **name string** (as serialized on the wire): `"ACCEPT_OFFER"` (0), `"REJECT_OFFER"` (1), `"END_NEGOTIATION"` (2), `"NO_RESPONSE"` (3), `"WAIT"` (4), `"LEAVE"` (5). Opening offer uses `"NO_RESPONSE"`; a counter uses `"REJECT_OFFER"`; acceptance uses `"ACCEPT_OFFER"`.

## Golden example (canonical SAB `open` = `contingency:negotiation`, from the reference dumps)

> Use this for **structure only**. Do NOT copy its literal values: generate a fresh
> UUID v4 for `message.id`, mint your own `episode` / `session_id`
> (`urn:ioc:episode:<slug>` / `urn:ioc:sab:session:<slug>`) and a fresh `payload_hash`,
> and take the `agents`, `mission`, `issues`, and `options_per_issue` from the user's inputs.

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "SAB",
    "version": "0",
    "kind": "contingency",
    "subkind": "negotiation",
    "participants": { "actors": [ { "id": "agent-buyer", "role": "participant", "attestation": null }, { "id": "agent-seller", "role": "participant", "attestation": null }, { "id": "negotiation_server", "role": "facilitator", "attestation": null } ], "groups": null },
    "message": { "id": "f1a2b3c4-d5e6-f780-9abc-def012345678", "parents": [], "episode": "urn:ioc:episode:supply-order-urgent-2026-001" },
    "policy": null,
    "attributes": { "msg_created_at": "2026-06-22T09:58:00Z" },
    "context": {
      "topic": "Two parties need to agree on price and delivery speed for an urgent supply order. | issues: [\"price\", \"delivery_speed\"] | options_per_issue: {\"price\": [\"low\", \"medium\", \"high\"], \"delivery_speed\": [\"express\", \"standard\", \"deferred\"]}",
      "epistemic": null,
      "semantic": { "schema_id": "urn:ioc:schema:sab-l9:v1", "ontology_ref": "urn:ioc:ontology:sab:v1", "provenance": null }
    }
  },
  "payload": {
    "type": "json-schema",
    "data": {
      "message_id": "f1a2b3c4-d5e6-f780-9abc-def012345678",
      "version": "0",
      "dt_created": "2026-06-22T10:00:00Z",
      "origin": { "actor_id": "agent-buyer", "attestation": null },
      "payload_hash": "a3f8e2d1c9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1",
      "semantic_context": { "schema_version": "1.0", "encoding": "json" }
    }
  }
}
```

### `round` — `payload.data` (same L9 envelope as `open`: `kind:contingency` / `subkind:negotiation`, same `participants`)

```json
{
  "message_id": "<this message.id>",
  "version": "0",
  "dt_created": "2026-06-22T10:00:02Z",
  "origin": { "actor_id": "agent-buyer", "attestation": null },
  "payload_hash": "<64-hex>",
  "semantic_context": {
    "schema_version": "1.0", "encoding": "json", "session_id": "urn:ioc:sab:session:qd-2026-06-22-001",
    "sao_state": {
      "running": true, "waiting": false, "started": true, "step": 0, "time": 2.1, "relative_time": 0.035,
      "broken": false, "timedout": false, "agreement": null, "results": null, "n_negotiators": 2,
      "has_error": false, "error_details": "", "erred_negotiator": "", "erred_agent": "", "threads": {},
      "last_thread": "", "left_negotiators": [],
      "current_offer": { "price": "high", "delivery_speed": "express" },
      "current_proposer": "agent-buyer", "current_proposer_agent": "agent-buyer",
      "n_acceptances": 0, "new_offers": [], "new_offerer_agents": [], "last_negotiator": null,
      "current_data": null, "new_data": [], "n_participating": 2
    },
    "sao_response": { "response": "NO_RESPONSE", "outcome": { "price": "high", "delivery_speed": "express" }, "data": null },
    "nmi": { "id": "urn:ioc:sab:session:qd-2026-06-22-001", "n_outcomes": 9, "shared_time_limit": 60.0, "shared_n_steps": 40, "private_time_limit": 30.0, "private_n_steps": null, "pend": 0.0, "pend_per_second": 0.0, "step_time_limit": 10.0, "negotiator_time_limit": 5.0, "dynamic_entry": false, "max_n_negotiators": null, "annotation": {}, "end_on_no_response": true, "one_offer_per_step": false, "offering_is_accepting": true, "allow_none_with_data": true, "allow_negotiators_to_leave": true },
    "offer_validation_failure": null
  }
}
```

- `nmi` is populated on the first round and is `null` thereafter.
- Opening offer → `sao_response.response = "NO_RESPONSE"`; a counter → `"REJECT_OFFER"`.
- Acceptance: re-propose the same `current_offer` with `sao_response.response = "ACCEPT_OFFER"`, `n_acceptances = 1`, `running = false`, and `sao_state.agreement` set to the agreed offer (because `offering_is_accepting = true`).

### `close` — `payload.data` (`kind:commit`, `subkind:converged`)

```json
{
  "message_id": "<this message.id>",
  "version": "0",
  "dt_created": "2026-06-22T10:00:25Z",
  "origin": { "actor_id": "agent-buyer", "attestation": null },
  "payload_hash": "<64-hex>",
  "semantic_context": {
    "schema_version": "1.0", "encoding": "json", "session_id": "urn:ioc:sab:session:qd-2026-06-22-001",
    "outcome": "agreement", "error_message": null,
    "content_text": "Two parties need to agree on price and delivery speed for an urgent supply order.",
    "agents_negotiating": [ "agent-buyer", "agent-seller" ],
    "final_agreement": [ { "issue_id": "price", "chosen_option": "medium" }, { "issue_id": "delivery_speed", "chosen_option": "standard" } ]
  }
}
```

- No deal: `subkind: "disagreement"` (or `"timeout"`), `outcome: "disagreement"`, `final_agreement: null`.

## Output

Output ONLY valid JSON — no explanation, no markdown fences.

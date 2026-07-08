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
   - `open` — announce a new bargaining session to `topic:sab/sessions`; declares the
     mission, the `issues`, and the `options_per_issue` that are on the table
   - `round` — make an **offer**, **counter-offer**, or **acceptance** in the
     alternating-offers loop (one option per issue)
   - `close` — **commit** the final outcome: `converged` (agreement), `disagreement`,
     or `timeout`
2. **Ask the step-specific bargaining details**, then show a pre-filled sample and ask
   _"Use this as-is, or tell me what to change?"_:
   - `open` → who initiates, the mission text, and each issue's options
   - `round` → the current `offer` (one option per issue), the `proposer`, the `step`
     number, and whether this is an **opening offer** (`NO_RESPONSE`, response `3`), a
     **counter** (`REJECT_OFFER`, response `1`), or an **acceptance** (`ACCEPT_OFFER`,
     response `0`, re-proposing the same offer with `n_acceptances = 1`)
   - `close` → the `outcome` (agreement / disagreement / timeout) and the
     `final_agreement` (one chosen option per issue, or `null` if no deal)
3. **Confirm or collect edits**, then emit the full L9 JSON for that single step,
   reusing the session's `episode` and `session_id`.

## Source of truth (fetch raw content every time)

Fetch these raw files and derive all field names, types, required fields, and enum values from them. Do not rely on memory.

- L9 envelope: https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json — `$defs.L9Header`, `ParticipantSet`, `Actor`, `Context`
- SAB payload: https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/sab/spec/sab_schema.json — `$defs.SAB`, `SABHeader`, `SABPayload`, `SABIntentPayloadData`, `SABNegotiatePayloadData`, `SABCommitPayloadData`, `SAOState`, `SAOResponse`, `SAONMI`, `SABActors`, `SABOrigin`, `SABAttributes`, `Kind`, `Subkind`, `Outcome`, `ResponseType`

(These JSON schemas are authoritative; the Python bindings are generated from them.)

## SAB is special

- Only two `kind`s: `contingency` (the open and every offer round, `subkind: "negotiate"`) and `commit` (the close, `subkind: "converged" | "disagreement" | "timeout"`). SAB never uses `intent`/`exchange`/`knowledge`.
- The message body is `SABPayload` (`type: "json-schema"`) with `data` in one of three shapes, chosen by **phase**: `open` → `SABIntentPayloadData`, `round` → `SABNegotiatePayloadData`, `close` → `SABCommitPayloadData`.

## Inputs — what YOU provide

Provide exactly this small object. Everything else (UUIDs, `payload_hash`, and all the "Fixed values" below) is filled in for you — do not provide them.

```json
{
  "phase": "open | round | close",
  "sender": "who is sending, e.g. agent-buyer",
  "receivers": ["topic:sab/sessions (open/close) or the other agent id (round)"],
  "mission": "one-line description of what is being negotiated",
  "issues": ["price", "delivery_speed"],
  "options_per_issue": { "price": ["low","medium","high"], "delivery_speed": ["express","standard","deferred"] },
  "session_id": "urn:ioc:sab:session:<uuid>",
  "payload_data": { "...phase-specific fields (see table)..." }
}
```

Field guide by `phase`:
- `open` → `contingency:negotiate`, broadcast to `topic:sab/sessions`, `parents: []`. `payload_data` is empty (just the intent envelope).
- `round` → `contingency:negotiate`, sender→other agent, `parents: [open.id]`. `payload_data`: `offer` (one option per issue), `proposer`, `step`, `response` (`ACCEPT_OFFER`|`REJECT_OFFER`|`NO_RESPONSE`).
- `close` → `commit`, broadcast to `topic:sab/sessions`, `parents: [open.id]`. `payload_data`: `outcome` (`agreement`|`disagreement`), `final_agreement` (list of `{issue_id, chosen_option}` or `null`), and set `subkind` `converged` (agreement) / `disagreement` / `timeout`.

## Fixed values

- `header.protocol` = `"SSTP"`, `header.subprotocol` = `"SAB"`, `header.version` = `"0"`
- `header.kind`/`subkind`: `open`/`round` → `contingency`/`negotiate`; `close` → `commit`/(`converged`|`disagreement`|`timeout`)
- `header.attributes.msg_created_at` = ISO-8601 timestamp; `header.participants.groups` = `null`
- `header.context.topic` = `"<mission> | issues: <issues> | options_per_issue: <options_per_issue>"`; `header.context.semantic` = `{ "schema_id": "urn:ioc:schema:sab-l9:v1", "ontology_ref": "urn:ioc:ontology:sab:v1", "provenance": null }`
- build `participants.actors` from `sender` (role `sender`) + `receivers` (role `receiver`); a `topic:*` receiver stays as the actor for broadcasts
- `payload.type` = `"json-schema"`; `payload.data.message_id` = the header `message.id`; `payload.data.version` = `"0"`; `payload.data.origin` = `{ "actor_id": <sender>, "attestation": null }`
- **IDs: generate every id as a fresh UUID v4.** Keep the `urn:` scheme prefix when the example uses one (`episode` → `urn:ioc:episode:<uuid>`, `session_id` → `urn:ioc:sab:session:<uuid>`); `message.id` is a bare UUID. `payload_hash` is a 64-hex SHA-256 digest (not an id). Reuse the same `episode` and `session_id` for the whole negotiation.
- `sao_response.response` uses `ResponseType` ints: `0`=ACCEPT_OFFER, `1`=REJECT_OFFER, `2`=END_NEGOTIATION, `3`=NO_RESPONSE, `4`=WAIT, `5`=LEAVE (opening offer uses `3`; a counter uses `1`; acceptance uses `0`)

## Golden example (canonical SAB `open` = `contingency:negotiate`, from the reference dumps)

> Use this for **structure only**. Do NOT copy its literal values: generate fresh
> UUID v4s for `message.id`, `episode` (keep the `urn:ioc:episode:` prefix), and
> `session_id` (keep the `urn:ioc:sab:session:` prefix), a fresh `payload_hash`, and
> take the actors, `mission`, `issues`, and `options_per_issue` from the user's inputs.

```json
{
  "header": {
    "protocol": "SSTP",
    "subprotocol": "SAB",
    "version": "0",
    "kind": "contingency",
    "subkind": "negotiate",
    "participants": { "actors": [ { "id": "agent-buyer", "role": "sender", "attestation": null }, { "id": "topic:sab/sessions", "role": "receiver", "attestation": null } ], "groups": null },
    "message": { "id": "f1a2b3c4-d5e6-f780-9abc-def012345678", "parents": [], "episode": "urn:ioc:episode:7f3d9c22-4e18-4a55-b6a1-2c9e0d4f8a10" },
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

### `round` — `payload.data` (same envelope, `kind:contingency` / `subkind:negotiate`, receiver = other agent)

```json
{
  "message_id": "<this message.id>",
  "version": "0",
  "dt_created": "2026-06-22T10:00:02Z",
  "origin": { "actor_id": "agent-buyer", "attestation": null },
  "payload_hash": "<64-hex>",
  "semantic_context": {
    "schema_version": "1.0", "encoding": "json", "session_id": "urn:ioc:sab:session:3a1f8e64-9c07-4b2d-8f51-6e2a0c9d4b73",
    "sao_state": {
      "running": true, "waiting": false, "started": true, "step": 0, "time": 2.1, "relative_time": 0.035,
      "broken": false, "timedout": false, "agreement": null, "results": null, "n_negotiators": 2,
      "has_error": false, "error_details": "", "erred_negotiator": "", "erred_agent": "", "threads": null,
      "last_thread": "", "left_negotiators": null,
      "current_offer": { "price": "high", "delivery_speed": "express" },
      "current_proposer": "agent-buyer", "current_proposer_agent": "agent-buyer",
      "n_acceptances": 0, "new_offers": null, "new_offerer_agents": null, "last_negotiator": null,
      "current_data": null, "new_data": null
    },
    "sao_response": { "response": 3, "outcome": { "price": "high", "delivery_speed": "express" }, "data": null },
    "nmi": { "id": "urn:ioc:sab:session:3a1f8e64-9c07-4b2d-8f51-6e2a0c9d4b73", "n_outcomes": 9, "shared_time_limit": 60.0, "shared_n_steps": 40, "private_time_limit": 30.0, "step_time_limit": 10.0, "negotiator_time_limit": 5.0, "offering_is_accepting": true },
    "offer_validation_failure": null
  }
}
```

- `nmi` is populated on the first round and may be `null` thereafter.
- Acceptance: re-propose the same `current_offer` with `sao_response.response = 0` and `n_acceptances = 1` (because `offering_is_accepting = true`).

### `close` — `payload.data` (`kind:commit`, `subkind:converged`)

```json
{
  "message_id": "<this message.id>",
  "version": "0",
  "dt_created": "2026-06-22T10:00:25Z",
  "origin": { "actor_id": "agent-buyer", "attestation": null },
  "payload_hash": "<64-hex>",
  "semantic_context": {
    "schema_version": "1.0", "encoding": "json", "session_id": "urn:ioc:sab:session:3a1f8e64-9c07-4b2d-8f51-6e2a0c9d4b73",
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

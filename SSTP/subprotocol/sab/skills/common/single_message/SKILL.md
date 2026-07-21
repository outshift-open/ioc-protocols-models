---
name: sab-single-message
description: Builds ONE correctly-formatted SAB (Semantic Alignment via Bargaining) L9 message from explicit inputs (phase, sender/origin, offer or outcome). Non-interactive. Use sab-message-generation instead for the guided prompt flow.
---

# SAB Single-Message Builder

Given a `phase` (`open` | `round` | `close`), the acting `sender`, and the phase's data, emit
**one** SAB L9 message as valid JSON. No prompting. SAB is fixed-cast: every message carries the
same three actors and `parents: []`; the acting agent is named only in `payload.data.origin.actor_id`
(no receiver/broadcast).

## Source of truth (fetch raw every time)

Derive all fields, types, required keys, enums, and the full `sao_state` / `nmi` scaffolding from
these — the schema wins over anything here.

- L9: `https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/spec/l9_schema.json`
- SAB (`payload.data` only): `https://raw.githubusercontent.com/outshift-open/ioc-protocols-models/main/SSTP/subprotocol/sab/spec/sab_schema.json`

## Inputs

```json
{
  "phase": "open | round | close",
  "sender": "agent-buyer | agent-seller  (→ payload.data.origin.actor_id)",
  "mission": "<one-line negotiation description>",
  "issues": ["price", "delivery_speed"],
  "options_per_issue": { "price": ["low","medium","high"], "delivery_speed": ["express","standard","deferred"] },
  "payload_data": { "...phase-specific fields..." },
  "episode": "reuse urn:ioc:episode:<slug> (omit on open to mint)",
  "session_id": "reuse urn:ioc:sab:session:<slug> (omit on open to mint)"
}
```

Only `phase` + `sender` are required.

## Header (same every message)

- `protocol`=`"SSTP"`, `subprotocol`=`"SAB"`, `version`=`"0"`.
- `kind`/`subkind`: `open`/`round` → `contingency`/`negotiation`; `close` → `commit`/(`resolved` | `unresolved` | `timeout`).
- `participants.groups`=`null`; `actors` are always `agent-buyer` (`participant`), `agent-seller`
  (`participant`), `negotiation_server` (`facilitator`).
- `message`: `id` = fresh UUID v4, `parents` = `[]`, `episode` (mint `urn:ioc:episode:<slug>` on `open`, else reuse).
- `attributes` = `{ "msg_created_at": "<ISO-8601>" }`; `policy`=`null`.
- `context`: `topic` = `"<mission> | issues: <issues> | options_per_issue: <options_per_issue>"`;
  `epistemic`=`null`; `semantic` = `{ "schema_id": "urn:ioc:schema:sab-l9:v1", "ontology_ref": "urn:ioc:ontology:sab:v1", "provenance": null }`.

## Payload

`payload.type`=`"json-schema"`. `payload.data` always has `message_id` (= `message.id`),
`version`=`"0"`, `dt_created` (ISO-8601), `origin` = `{ "actor_id": <sender>, "attestation": null }`,
`payload_hash` (64-hex SHA-256), and `semantic_context`:

| phase | `semantic_context` |
|-------|--------------------|
| `open` | `schema_version`=`"1.0"`, `encoding`=`"json"` (no `session_id`) |
| `round` | + `session_id`, `sao_state`, `sao_response`, `nmi` (first round only, else `null`), `offer_validation_failure` |
| `close` | + `session_id`, `outcome`, `error_message`, `content_text`, `agents_negotiating`, `final_agreement` |

**Round** — `sao_response.response` is the ResponseType **name**: opening offer `"NO_RESPONSE"`,
counter `"REJECT_OFFER"`, accept `"ACCEPT_OFFER"`. `step` counts from 0. Each offer/counter flips
`origin` / `current_proposer` / `current_proposer_agent` between the two agents, sets
`current_offer` = `sao_response.outcome`, `last_negotiator` = previous proposer (`null` on the
opener). On **accept**, `origin` is the accepter but `current_offer`/`current_proposer` stay the
standing offer (don't flip); set `n_acceptances: 1`, `running: false`, `sao_state.agreement` = that
offer. A timed-out final round keeps `"REJECT_OFFER"` with `timedout: true`, `running: false`.

**Close** — `resolved` → `outcome: "agreement"` + non-null `final_agreement` (list of
`{issue_id, chosen_option}`); `unresolved`/`timeout` → `outcome: "disagreement"` +
`final_agreement: null`. Reuse the `open` `episode`/`session_id`.

## Output

Output ONLY the single L9 JSON message — no prose, no fences. Optionally check it with
`sab-message-validation`.

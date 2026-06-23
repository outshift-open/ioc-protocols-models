---
name: l9-transform
description: Converts a human-readable message into a valid L9 protocol JSON message with kind=exchange. Use when transforming plain-text chat input into structured L9 exchange payloads.
---

# L9 Transform

## Context / Trigger Requirements

Use this skill when the input is a human-readable message that needs to be converted into a valid L9 protocol JSON message. The input follows the pattern: `<sender_name>: <message>`.

If no sender name is provided (no colon separator), default the sender name to "User".

Examples:
- `MathAgent: Add 2 and 3` → sender is "MathAgent", message is "Add 2 and 3"
- `Calculate the sum of 10 and 25` → sender is "User", message is "Calculate the sum of 10 and 25"

## Schema Reference

The authoritative schema is `SSTP/spec/l9_schema.json`. The top-level L9 message has two required fields:

- **`header`** (`L9Header`) — routing and metadata envelope.
  - Required: `protocol`, `subprotocol`, `version`, `kind`, `subkind`, `actors`
  - Optional (default `null`): `message`, `policy`, `attributes`, `context`
- **`payload`** (`L9Payload`) — the content being carried.
  - Required: `type`, `data`

### Key Sub-Schemas

- **Actor** — `{ id, role }` (required), `attestation` (optional, default `null`)
- **Actors** — `{ actors: Actor[], groups: string[] }` (both required)
- **Message** — `{ id, parents, episode }` (all required strings)
- **Context** — `{ topic }` (required), `epistemic` and `semantic` (optional, default `null`)
- **Semantic** — `{ schema_id, ontology_ref }` (required), `provenance` (optional, default `null`)
- **PolicyLabel** — `{ sensitivity, propagation, retention_policy }` (all required strings)
- **Provenance** — empty object (fields TBD)
- **Epistemic** — empty object (fields TBD)

## Step-by-Step Instructions

1. Parse the input to extract `sender_name` and `message`. If no colon separator is present, set `sender_name` to "User" and use the entire input as `message`.
2. Derive the sender actor `id` from `sender_name`: lowercase the name and replace spaces with dashes.
3. Produce the following L9 JSON structure using the extracted values:

```json
{
  "header": {
    "protocol": "L9",
    "subprotocol": "SSTP",
    "version": "0.0.2",
    "kind": "exchange",
    "subkind": "chat",
    "actors": {
      "actors": [
        {
          "id": "<sender_name lowercase, spaces replaced with dashes>",
          "role": "sender",
          "attestation": null
        },
        {
          "id": "cfn-agent-001",
          "role": "receiver",
          "attestation": null
        }
      ],
      "groups": ["exchange-session-001"]
    },
    "message": null,
    "policy": null,
    "attributes": null,
    "context": {
      "topic": "chat",
      "epistemic": null,
      "semantic": {
        "schema_id": "l9_v1",
        "ontology_ref": "standard",
        "provenance": null
      }
    }
  },
  "payload": {
    "type": "text",
    "data": {
      "content": "<message>"
    }
  }
}
```

4. Output ONLY the JSON. No explanation, no markdown code fences, no surrounding text.

## Guardrails & Constraints

- The output must conform to `SSTP/spec/l9_schema.json`.
- All required fields in `L9Header` (`protocol`, `subprotocol`, `version`, `kind`, `subkind`, `actors`) must be present.
- All required fields in each `Actor` (`id`, `role`) must be present.
- The `actors` field is an `Actors` object containing an `actors` array and a `groups` array — not a bare array of actors.
- Always include exactly two actors: the human sender and the default CFN Agent receiver.
- `kind` must always be `"exchange"`.
- Optional header fields (`message`, `policy`, `attributes`, `context`) should be set to `null` unless explicitly provided.
- When `context` is provided, `topic` is required. `epistemic` and `semantic` within context default to `null`.
- `payload.type` and `payload.data` are both required. `payload.data.content` must contain the exact message text.
- Output valid JSON only — no trailing commas, no comments.

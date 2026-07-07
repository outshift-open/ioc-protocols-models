# SAB — Skills

Skills for generating **SAB (Semantic Alignment via Bargaining)** L9 messages,
mirroring the top-level `SSTP/skills` layout: one real, agent-agnostic skill under
`common/` plus thin per-agent wrappers.

SAB runs NegMAS Stacked Alternating Offers (SAO): agents exchange offers over a set
of issues and converge on one option per issue, then commit the outcome.

## Layout

```
skills/
  common/
    message_generation/SKILL.md   # real skill (builds a full SAB L9 message)
  codex/skills/SKILL.md           # placeholder wrapper
  openclaw/skills/SKILL.md        # placeholder wrapper
  claude/skills/SKILL.md          # placeholder wrapper
```

## Skills

| Skill | Description |
|-------|-------------|
| `common/message_generation` | Generates a complete SAB L9 message (header + SAB payload) as valid JSON |

## message_generation

Produces a complete SAB L9 message (header + `SABPayload`) as valid JSON. You
provide a small object (`phase`, `sender`, `receivers`, `mission`, `issues`,
`options_per_issue`, `session_id`, `payload_data`); the skill fills the fixed
envelope values and auto-generates all ids.

### Phases & payload shapes

SAB uses only two `kind`s — `contingency` (open + every offer round) and `commit`
(the close). The `payload.data` shape is chosen by phase:

| phase | kind / subkind | payload.data | receivers | parents |
|-------|----------------|--------------|-----------|---------|
| open | `contingency` / `negotiate` | `SABIntentPayloadData` | `topic:sab/sessions` (broadcast) | `[]` |
| round | `contingency` / `negotiate` | `SABNegotiatePayloadData` (`sao_state` / `sao_response` / `nmi`) | the other agent | `[open.id]` |
| close | `commit` / `converged`\|`disagreement`\|`timeout` | `SABCommitPayloadData` (`outcome` / `final_agreement`) | `topic:sab/sessions` (broadcast) | `[open.id]` |

`ResponseType` ints in `sao_response.response`: `0` ACCEPT_OFFER, `1` REJECT_OFFER,
`2` END_NEGOTIATION, `3` NO_RESPONSE, `4` WAIT, `5` LEAVE. Opening offer uses `3`, a
counter uses `1`, an acceptance uses `0`.

### IDs

Every id is a fresh UUID v4. Keep the `urn:` prefix where the examples use one
(`episode` → `urn:ioc:episode:<uuid>`, `session_id` → `urn:ioc:sab:session:<uuid>`);
`message.id` is a bare UUID. `payload_hash` is a 64-hex SHA-256 digest (not an id).
Reuse the same `episode` and `session_id` for the whole negotiation.

## Source of truth

- L9 envelope: `SSTP/spec/l9_schema.json`
- SAB payload: `SSTP/subprotocol/sab/spec/sab_schema.json`

The JSON schemas are authoritative; the Python bindings under
`language_bindings/python/ai/outshift/sab/data_model.py` are generated from them.
The golden examples in the skill are validated against those models.

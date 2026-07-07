# TFP — Skills

Skills for generating **TFP (Team Formation Protocol)** L9 messages, mirroring the
top-level `SSTP/skills` layout: one real, agent-agnostic skill under `common/` plus
thin per-agent wrappers.

TFP is the open-world team-discovery subprotocol: a recruiter broadcasts a poll,
candidate agents bid with their skills, the recruiter selects a team, members
accept/reject, and the episode commits (converged) or aborts (failed).

## Layout

```
skills/
  common/
    message_generation/SKILL.md   # real skill (builds a full TFP L9 message)
  codex/SKILLS.md                 # placeholder wrapper
  openclaw/SKILLS.md              # placeholder wrapper
  claude/SKILLS.md                # placeholder wrapper
```

## Skills

| Skill | Description |
|-------|-------------|
| `common/message_generation` | Generates a complete TFP L9 message (header + TFP payload) as valid JSON |

## message_generation

Produces a complete TFP L9 message (header + `TFPPayload`) as valid JSON. You
provide a small object (`kind`, `operation`, `sender`, `receivers`, `payload_data`);
the skill fills the fixed envelope values and auto-generates all ids.

### Operations & turn types

| operation | kind | subkind | payload.data |
|-----------|------|---------|--------------|
| `poll_open` | `intent` | `team-formation` | `task`, `required_skills`, `reasoning_summary` |
| `bid` | `exchange` | `team-formation` | `offer` (`CandidateOffer`), `reasoning_summary` |
| `decline` | `exchange` | `team-formation` | `reason` |
| `clarify` | `exchange` | `team-formation` | question / clarification fields |
| `select` | `exchange` | `team-formation` | `selection` (`TeamSelection`) |
| `accept` | `exchange` | `team-formation` | `reason` |
| `reject` | `exchange` | `team-formation` | `reason` |
| `re_poll` | `exchange` | `team-formation` | `required_skills` (uncovered ones) |
| `form_converged` | `commit` | `converged` | `selection` |
| `form_failed` | `commit` | `abort` | `selection` |

### IDs

Every id is a fresh UUID v4. Keep the `urn:` prefix where the examples use one
(`poll_id` → `urn:ioc:tfp:poll:<uuid>`); `message.id` and `episode` are bare UUIDs.
Reuse the same `episode` and `poll_id` across a poll.

### Typical flow

`poll_open` (broadcast) → `bid` × N (candidates) → `select` (recruiter) →
`accept` / `reject` (members) → `form_converged` **or** `form_failed` /
`re_poll` if skills remain uncovered.

## Source of truth

- L9 envelope: `SSTP/spec/l9_schema.json`
- TFP payload: `SSTP/subprotocol/tfp/spec/tfp_schema.json`

The JSON schemas are authoritative; the Python bindings under
`language_bindings/python/ai/outshift/tfp/data_model.py` are generated from them.

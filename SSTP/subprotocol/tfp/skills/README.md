# TFP — Skills

Skills for generating **TFP (Team Formation Protocol)** L9 messages.

TFP is the open-world team-discovery subprotocol: a recruiter broadcasts a poll,
candidate agents bid with their skills, the recruiter selects a team, members
accept/reject, and the episode commits (converged) or aborts (failed).

## Layout

```
skills/
  common/
    message_generation/SKILL.md   # real skill (guided, fixed-cast TFP flow)
    single_message/SKILL.md       # real skill (one message from explicit sender/receiver inputs)
    message_validation/SKILL.md   # real skill (validates a single TFP L9 message)
  codex/SKILLS.md                 # placeholder wrapper
  openclaw/SKILLS.md              # placeholder wrapper
  claude/SKILLS.md                # placeholder wrapper
```

## Skills

| Skill | Description |
|-------|-------------|
| `common/message_generation` | Guided, fixed-cast (recruiter + 2 candidates) generator covering the success/failure flows |
| `common/single_message` | Builds one TFP L9 message from explicit inputs (operation, sender, receiver, payload) — non-interactive, cast-agnostic |
| `common/message_validation` | Validates that a single TFP L9 message follows the TFP format against the raw GitHub L9 + TFP schemas, plus TFP cross-field rules |

## Tested With

| Agent | Haiku 4.5 | Opus 4.6 |
|-------|-----------|----------|
| Claude | ✓ | ✓ |
| OpenClaw | ✓ | ✓ |

## Source of truth

- L9 envelope: `SSTP/spec/l9_schema.json`
- TFP payload: `SSTP/subprotocol/tfp/spec/tfp_schema.json`
- Full skill spec: `common/message_generation/SKILL.md`
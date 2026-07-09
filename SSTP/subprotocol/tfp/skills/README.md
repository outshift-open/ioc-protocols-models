# TFP — Skills

Skills for generating **TFP (Team Formation Protocol)** L9 messages.

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

## Source of truth

- L9 envelope: `SSTP/spec/l9_schema.json`
- TFP payload: `SSTP/subprotocol/tfp/spec/tfp_schema.json`
- Full skill spec: `common/message_generation/SKILL.md`
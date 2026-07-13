# SAB — Skills

Skills for generating **SAB (Semantic Alignment via Bargaining)** L9 messages.

SAB runs NegMAS Stacked Alternating Offers (SAO): agents exchange offers over a set
of issues and converge on one option per issue, then commit the outcome.

## Layout

```
skills/
  common/
    message_generation/SKILL.md   # real skill (builds a full SAB L9 message)
    message_validation/SKILL.md   # real skill (validates a SAB L9 message / session)
  codex/skills/SKILL.md           # placeholder wrapper
  openclaw/skills/SKILL.md        # placeholder wrapper
  claude/skills/SKILL.md          # placeholder wrapper
```

## Skills

| Skill | Description |
|-------|-------------|
| `common/message_generation` | Generates a complete SAB L9 message (header + SAB payload) as valid JSON |
| `common/message_validation` | Validates that a single SAB L9 message follows the SAB format against the raw GitHub L9 + SAB schemas, plus SAB cross-field rules |

## Source of truth

- L9 envelope: `SSTP/spec/l9_schema.json`
- SAB payload: `SSTP/subprotocol/sab/spec/sab_schema.json`
- Full skill spec: `common/message_generation/SKILL.md`
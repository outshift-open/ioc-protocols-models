# SAB — Skills

Skills for generating **SAB (Semantic Alignment via Bargaining)** L9 messages.

SAB runs NegMAS Stacked Alternating Offers (SAO): agents exchange offers over a set
of issues and converge on one option per issue, then commit the outcome.

## Layout

```
skills/
  common/
    message_generation/SKILL.md   # real skill (guided SAB flow)
    single_message/SKILL.md       # real skill (one message from explicit phase/sender inputs)
    message_validation/SKILL.md   # real skill (validates a single SAB L9 message)
  codex/skills/SKILL.md           # placeholder wrapper
  openclaw/skills/SKILL.md        # placeholder wrapper
  claude/skills/SKILL.md          # placeholder wrapper
```

## Skills

| Skill | Description |
|-------|-------------|
| `common/message_generation` | Guided generator for the agreement/disagreement flows (fixed 3-actor cast) |
| `common/single_message` | Builds one SAB L9 message from explicit inputs (phase, sender, offer/outcome) — non-interactive |
| `common/message_validation` | Validates that a single SAB L9 message follows the SAB format against the raw GitHub L9 + SAB schemas, plus SAB cross-field rules |

## Source of truth

- L9 envelope: `SSTP/spec/l9_schema.json`
- SAB payload: `SSTP/subprotocol/sab/spec/sab_schema.json`
- Full skill spec: `common/message_generation/SKILL.md`
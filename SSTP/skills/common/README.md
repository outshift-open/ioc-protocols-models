# SSTP Common Skills

Reusable skills for working with L9 protocol messages under the SSTP protocol. These common skills work with both Claude and OpenClaw agents.

## Skills

| Skill | Description |
|-------|-------------|
| `header_generation` | Generates a standalone L9 header as valid JSON for a given kind and subprotocol |
| `message_generation` | Generates a complete L9 message (header + payload) as valid JSON |
| `message_to_text` | Converts an L9 JSON message into a human-readable plain-text string |
| `text_to_message` | Converts plain-text human input into a valid L9 exchange message |
| `message_validation` | Validates an L9 JSON message against the schema and reports PASS/FAIL with details |
| `generate_and_validate` | Chains message_generation → message_validation to generate and immediately validate |

## Supported Subprotocols

- SIEP
- CIP
- TFP
- SAB

## Tested With

| Agent | Haiku 4.5 | Opus 4.6 |
|-------|-----------|----------|
| Claude | ✓ | ✓ |
| OpenClaw | ✓ | ✓ |
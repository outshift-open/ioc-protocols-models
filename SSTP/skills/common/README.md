# SSTP Common Skills

Reusable skills for working with L9 protocol messages under the SSTP protocol.

## Skills

| Skill | Description |
|-------|-------------|
| `l9_header_gen` | Generates a standalone L9 header as valid JSON for a given kind and subprotocol |
| `l9_message_gen` | Generates a complete L9 message (header + payload) as valid JSON |
| `l9_to_human` | Converts an L9 JSON message into a human-readable plain-text string |
| `l9_transform` | Converts plain-text human input into a valid L9 exchange message |
| `l9_validate` | Validates an L9 JSON message against the schema and reports PASS/FAIL with details |

## Supported Subprotocols

- SIEP
- CIP
- TFP
- SAB

## Tested With

- Claude (Anthropic)
- OpenClaw
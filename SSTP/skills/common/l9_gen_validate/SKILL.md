---
name: l9-gen-validate
description: Generates an L9 message then validates it against the schema. Reports message + PASS/FAIL.
---

# L9 Generate → Validate Chain

## Flow

```
User Input → [Parse] → [l9_message_gen] → [l9_validate] → Output
```

## How to Invoke

```
/l9_gen_validate kind: exchange, subprotocol: SIEP, payload_type: text, payload_data: {"content": "hello"}
```

## Instructions

1. **Parse** user input to extract: `kind`, `subprotocol`, `payload_type`, `payload_data`.
   - Log: `[PARSE] Extracted — kind: <kind>, subprotocol: <subprotocol>, payload_type: <payload_type>, payload_data: <payload_data>`

2. **Generate** — Invoke the Skill tool with `skill: "l9_message_gen"` passing the extracted parameters as args. Collect the generated L9 message JSON.
   - Log before: `[GENERATE] Invoking l9_message_gen with args: kind=<kind>, subprotocol=<subprotocol>, payload_type=<payload_type>, payload_data=<payload_data>`
   - Log after success: `[GENERATE] ✓ Message generated successfully (<byte_size> bytes)`
   - Log after failure: `[GENERATE] ✗ Generation failed: <error_message>`

3. **Validate** — Invoke the Skill tool with `skill: "l9_validate"` passing the generated message JSON as args. Collect the validation report.
   - Log before: `[VALIDATE] Invoking l9_validate with generated message`
   - Log after success: `[VALIDATE] ✓ Validation complete — status: <PASS|FAIL>`
   - Log after failure: `[VALIDATE] ✗ Validation invocation failed: <error_message>`

4. **Output** in this format:

```
## Execution Log
<all log lines from steps 1-3, one per line>

## Generated L9 Message
<message JSON>

## Validation Result
<JSON with status PASS/FAIL and errors array>
```

## CRITICAL — Single-Turn Execution

- After l9_message_gen returns, you MUST immediately invoke l9_validate in the SAME response.
- Do NOT output the generated message to the user and wait.
- Do NOT stop between generation and validation.
- Both skill invocations MUST happen in a single assistant turn — no pausing, no intermediate output to the user.
- Only produce the final formatted output AFTER both skills have completed.

## Constraints

- You MUST use the Skill tool to invoke `l9_message_gen` — do not inline its logic.
- You MUST use the Skill tool to invoke `l9_validate` — do not inline its logic.
- Sequential: generation must complete before validation begins.
- If generation fails, report the error and skip validation.

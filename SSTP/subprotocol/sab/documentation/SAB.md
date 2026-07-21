# Semantic Alignment via Bargaining (SAB)

SAB is a subprotocol of **SSTP** (Layer 9) that lets agents reach semantic
alignment through a bargaining process, implemented with NegMAS **Stacked
Alternating Offers (SAO)**. Agents exchange offers over a shared negotiation
space until they converge on an agreement, exhaust the step budget, or break.

## Overview

Like SIEP, CIP, and TFP, **SAB does not define an L9 header**. A SAB message
*is* a canonical [`L9`](../../../spec/l9_schema.json) message:

```
L9
├── header   : L9Header      # the standard L9 header (protocol="SSTP", subprotocol="SAB", …)
└── payload   : L9Payload     # { type: "json-schema", data: <SAB payload> }
```

The SAB source of truth (`src/sab_models.py`) models **only `payload.data`**.
The envelope is built by [`SABMessageBuilder`](../src/builder.py), which fills
the canonical `L9Header` and puts SAB metadata into the standard
`header.attributes` dict. In particular:

- **`msg_created_at`** lives in **`header.attributes["msg_created_at"]`**.
- The **negotiation space** (mission text, `issues`, `options_per_issue`) is
  encoded into **`header.context.topic`**; `header.context.semantic.schema_id =
  "urn:ioc:schema:sab-l9:v1"` identifies the envelope.
- **Participants** use the standard `ParticipantSet` (`header.participants`).

## Building a SAB message

```python
from SSTP.subprotocol.sab.src import (
    SABMessageBuilder, SABNegotiatePayloadData, NegotiateSemanticContext,
    SABOrigin, SAOState, SAOResponse,
)

data = SABNegotiatePayloadData(
    message_id="n1", dt_created="2026-06-22T10:00:02Z",
    origin=SABOrigin(actor_id="agent-buyer"), payload_hash="…",
    semantic_context=NegotiateSemanticContext(
        session_id="sess-1",
        sao_state=SAOState(step=0, n_negotiators=2, current_offer={"price": "high"}),
        sao_response=SAOResponse(response=3, outcome={"price": "high"}),
    ),
)

l9 = (
    SABMessageBuilder("sess-1")
    .participants(["agent-buyer", "agent-seller"])
    .message("n1", parents=[])
    .topic("Agree price and delivery speed",
           issues=["price", "delivery_speed"],
           options_per_issue={"price": ["low", "high"]})
    .created_at("2026-06-22T10:00:02Z")   # → header.attributes["msg_created_at"]
    .negotiate(data)
    .build()
)
```

`build()` returns a canonical `L9`. The variant helpers set `header.kind` /
`header.subkind`: `intent()` / `negotiate()` → `contingency/negotiation`;
`resolved()`, `unresolved()`, `timeout()` → `commit/<subkind>`. Use
`status(<ce-status>, data)` to map a CE status string directly.

## Message flow

| Step | payload.data variant       | L9 kind       | L9 subkind      | Meaning |
|------|----------------------------|---------------|-----------------|---------|
| open | `SABIntentPayloadData`     | `contingency` | `negotiation`   | Initiator opens the session with the mission/issues. |
| round| `SABNegotiatePayloadData`  | `contingency` | `negotiation`   | An agent's SAO offer/response for the round (`sao_state` snapshot). |
| close| `SABCommitPayloadData`     | `commit`      | `resolved`      | Agreement reached (`final_agreement`). |
| close| `SABCommitPayloadData`     | `commit`      | `unresolved`    | Step budget exhausted, no agreement. |
| close| `SABCommitPayloadData`     | `commit`      | `timeout`       | A participant broke off or returned an invalid offer. |

The CE status → kind/subkind map is `STATUS_KIND` in `src/builder.py` and is
kept wire-compatible with the runtime adapter in
`ioc-cfn-cognitive-agents/protocol/sab/l9_adapter.py`.

## payload.data

Every variant extends `SABPayloadBase` (`message_id`, `version`, `dt_created`,
`origin`, `payload_hash`) and carries a `semantic_context`:

- **`SemanticContext`** (intent) — `schema_version`, `encoding`.
- **`NegotiateSemanticContext`** — adds `session_id`, the negotiation space
  (`issues`, `options_per_issue`, `options_memory_blob`), and the NegMAS SAO
  snapshot (`sao_state`, `sao_response`, `nmi`, `offer_validation_failure`).
- **`NegotiateCommitSemanticContext`** — adds `session_id`, `outcome`
  (`agreement` | `disagreement` | `broken` | `error`), `content_text`,
  `agents_negotiating`, `issues`, `options_per_issue`, `final_agreement`.

`SABNegotiatePayloadData` additionally carries **`round_messages`** — the pending
per-round SAB L9 envelopes the recipient dispatches to the participant agents this
round (each item a full SAB `contingency/negotiation` message; empty when there is
nothing to dispatch). Named distinctly from the header's own `message` field.

`header.context.topic` carries the human mission summary only; the negotiation
space (`issues`, `options_per_issue`) is the canonical `semantic_context`, not the
topic string. The envelope is identified by `header.context.semantic.schema_id`.

## Schema & bindings pipeline

```
src/sab_models.py            (source of truth — edit here)
    │  spec/generate_sab_schema.py
    ▼
spec/sab_schema.json         (JSON Schema for payload.data)
    │  language_bindings/{python,golang}/generate.sh
    ▼
ai/outshift/sab/data_model.py   +   data_model.go   (generated bindings)
```

Do **not** hand-edit `sab_schema.json` or the generated `data_model.*`. Change
`src/sab_models.py` and re-run the generators. The SAO snapshot models mirror
NegMAS 0.15.1 (`negmas.sao.common` / `negmas.gb.common`).

## Schema reference

- Payload schema: [`spec/sab_schema.json`](../spec/sab_schema.json)
- L9 envelope schema: [`SSTP/spec/l9_schema.json`](../../../spec/l9_schema.json)
- Examples: [`examples/demo_agreement.json`](../examples/demo_agreement.json),
  [`examples/demo_disagreement.json`](../examples/demo_disagreement.json)
  (regenerate with `examples/run_demo.py`).

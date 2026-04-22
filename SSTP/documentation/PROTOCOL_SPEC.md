# Protocol Specification

## Overview

This directory defines the **L9 protocol stack** used by IoC CFN Cognitive Agents.

L9 is a generic semantic envelope format.  Any protocol that needs to carry
identity, provenance, policy, schema, and sequencing metadata between agents
can specialise L9 by subclassing `L9HeaderBuilder`.

Two protocols are currently defined:

| Protocol | Package | Purpose |
|---|---|---|
| **SNP** (Semantic Negotiation Protocol) | `protocol/snp/` | Always-active SSTP envelope for all agent messages |
| **IE** (Interaction Engine) | `protocol/ie/` | Conversational event labelling for TOM-based interaction sessions |

---

## Transport Modalities (`L9Transport`)

The `protocol` field of every L9 envelope identifies the transport modality.
Three values are defined in `L9Transport` (`protocol/l9_base.py`):

| Value | Class constant | Payload type | Typical use |
|---|---|---|---|
| `"SSTP"` | `L9Transport.SSTP` | Structured (JSON / dict) semantic state | Reasoning, negotiation, commits, conversational traces.  All current sub-protocols (SNP, IE) run over SSTP. |
| `"CSTP"` | `L9Transport.CSTP` | Embedding / vector | Similarity search, semantic clustering, dense-retrieval coordination between agents and Cognition Engines. |
| `"LSTP"` | `L9Transport.LSTP` | Latent / tensor | High-fidelity cognitive coordination where full distributional representations must be propagated (e.g. cross-model knowledge distillation). |

`L9Transport` is a `str` subclass (`str, enum.Enum`), so instances compare and
serialise identically to their string values:

```python
L9Transport.SSTP == "SSTP"    # True
json.dumps(L9Transport.SSTP)  # '"SSTP"'
```

Sub-protocols declare their transport by setting the `PROTOCOL` class attribute
on their `L9HeaderBuilder` subclass:

```python
from protocol.l9_base import L9HeaderBuilder, L9Transport

class MyCSTensorBuilder(L9HeaderBuilder):
    PROTOCOL = L9Transport.CSTP   # wire field: "CSTP"

    def kind_for_event_type(self, event_type: str) -> str: ...
    def schema_id_for(self, use_case, event_type, kind, trust_level) -> str: ...
```

The `L9_PROTOCOL` module constant remains `L9Transport.SSTP` and serves as
the default for all existing builders.

---

## L9 Header Structure

Every L9 header is a dict with the following fields.  The `build()` method of
`L9HeaderBuilder` (`protocol/l9_base.py`) assembles this structure.

```
{
  "protocol":       string   — L9 wire protocol ID (e.g. "SSTP")
  "version":        string   — envelope version ("0")
  "kind":           string   — semantic kind (see Kind Taxonomy below)
  "message_id":     string   — deterministic UUIDv5 or supplied ID
  "dt_created":     string   — ISO 8601 UTC timestamp
  "origin": {
    "actor_id":     string   — producing agent / engine ID
    "tenant_id":    string   — tenant / organisation
    "attestation":  string   — credential or signature
  }
  "semantic_context": {
    "schema_id":              string  — canonical schema URN
    "schema_version":         string  — schema version
    "encoding":               string  — "json" | "structured_text" | "hybrid"
    "schema_trust_level":     string  — "draft" | "certified"
    "ontology_ref":           string? — optional ontology reference URI
    "cognition_profile_id":   string? — cognition interaction profile type
                                        ("semantic_alignment:v1", "adaptive_communication:v1",
                                         or null for generic SSTP messages)
    "cognition_protocol":     string? — specific sub-protocol identifier ("SNP", "IE", or null)
  }
  "policy_labels": {
    "sensitivity":        string  — "public" | "internal" | "restricted" | "confidential"
    "propagation":        string  — "forward" | "restricted" | "no_forward"
    "retention_policy":   string  — policy ID reference
  }
  "provenance": {
    "sources":     [string]  — upstream URNs / message IDs
    "transforms":  [string]  — processing steps applied
  }
  "state_object_id":    string?  — target state object URN
  "parent_ids":         [string] — IDs of messages this one is derived from
  "logical_clock":      string?  — "lamport:<n>" or null
  "confidence_score":   float?   — 0.0–1.0
  "risk_score":         float?   — 0.0–1.0
  "ttl_seconds":        int      — expiry in seconds
  "merge_strategy":     string   — "add" | "replace" | "merge" | "crdt"
  "payload_refs":       [{type, ref}]  — inline or external payload references
}
```

### Kind Taxonomy

All current L9 protocols share this SSTP kind vocabulary:

| Kind | Semantics |
|---|---|
| `intent` | Initial goal or request |
| `delegation` | Task or authority handoff |
| `knowledge` | Factual or contextual information |
| `query` | Request for information or repair |
| `commit` | Final decision or commitment |
| `memory_delta` | Persistent memory update |
| `evidence_bundle` | Supporting evidence package |
| `negotiate` | SNP panel negotiation message |

`commit` and `memory_delta` are **certified** kinds (schema trust level = "certified",
schema version = "1.0").  All others are "draft" / "0.1".

---

## SNP — Semantic Negotiation Protocol

**Package:** `protocol/snp/`
**Spec:** `protocol/snp/SEMANTIC_NEGOTIATION_PROTOCOL.md`
**Formal model:** `protocol/snp/SSTP_FORMAL_MODEL.md`

SNP uses the SSTP envelope (`protocol="SSTP"`) and maps its own operation
vocabulary (§1.1 of `SEMANTIC_NEGOTIATION_PROTOCOL.md`) to SSTP kinds via a
two-step pipeline.  All SNP headers carry `cognition_profile_id = "semantic_alignment:v1"`
and `cognition_protocol = "SNP"` in `semantic_context`.

```
SNP operation  →  SSTP event_type  →  L9 kind
─────────────────────────────────────────────
propose / counter_proposal / …  →  peer_turn        →  delegation
accept / reject                 →  decision_emitted →  commit
```

**Key classes / functions:**

| Symbol | Location | Purpose |
|---|---|---|
| `SNPL9HeaderBuilder` | `protocol/snp/l9.py` | SNP specialisation of `L9HeaderBuilder` |
| `build_snp_l9_header()` | `protocol/snp/l9.py` | Build an SNP L9 header from an operation |
| `build_snp_payload()` | `protocol/snp/l9.py` | Build the SNP NegotiationPayload dict |
| `NegotiationOperation` | `protocol/snp/l9.py` | Operation vocabulary constants |
| `NegotiationStatus` | `protocol/snp/l9.py` | Status vocabulary constants |
| `build_negotiate_envelope()` | `protocol/snp/l9_bridge.py` | End-to-end: SNP operation → `SSTPNegotiateMessage` |
| `STPMessage` | `protocol/snp/__init__.py` | Discriminated union of all SSTP Pydantic kinds |

---

## IE — Interaction Engine Protocol

**Package:** `protocol/ie/`
**Wire envelope schema:** `protocol/ie/interaction_engine_protocol.schema.json`

The IE protocol labels conversational events produced by the Interaction Engine
runtime.  Each IE event carries an SSTP L9 header (built by `IEL9HeaderBuilder`)
at the top level, with IE-specific fields nested under a `payload` key.  All IE
headers carry `cognition_profile_id = "adaptive_communication:v1"` and
`cognition_protocol = "IE"` in `semantic_context`.

IE event_type → L9 kind mapping:

```
turn_ingested           →  intent
peer_turn               →  delegation
repair_required         →  query
repair_applied          →  delegation
decision_emitted        →  commit
episode_persisted       →  memory_delta
conversation_terminated →  knowledge
agent_request           →  delegation
agent_response          →  commit
agent_error / agent_shutdown / agent_shutdown_ack  →  knowledge
```

**Key classes / functions:**

| Symbol | Location | Purpose |
|---|---|---|
| `IEL9HeaderBuilder` | `protocol/ie/l9.py` | IE specialisation of `L9HeaderBuilder` |
| `build_l9_header()` | `protocol/ie/l9.py` | Build an IE L9 header from an event_type |
| `canonical_event_type()` | `protocol/ie/l9.py` | Resolve IE event_type aliases |
| `InteractionProtocolAdapter` | `protocol/ie/adapter.py` | Convert IE episodes to IE protocol events |

---

## Base classes

**`L9HeaderBuilder`** (`protocol/l9_base.py`)

Abstract base class for all L9 header builders.  Provides:
- Common envelope assembly (`build()`)
- Deterministic `message_id` generation (UUIDv5)
- Policy, provenance, and TTL defaults

Subclass it to add a new protocol:

```python
from protocol.l9_base import L9HeaderBuilder

class MyProtocolBuilder(L9HeaderBuilder):
    def kind_for_event_type(self, event_type: str) -> str:
        return {"my_event": "intent", "my_commit": "commit"}.get(event_type, "knowledge")

    def schema_id_for(self, use_case, event_type, kind, trust_level):
        return f"urn:my-org:{use_case}:{kind}:v1"

header = MyProtocolBuilder().build(
    use_case="my_use_case",
    event_type="my_event",
    sender="agent-1",
    receiver=None,
    timestamp_ms=0,
)
```

Shared utilities re-exported from `protocol.l9_base`:

| Symbol | Purpose |
|---|---|
| `L9Transport` | Enum of valid transport modalities: `SSTP`, `CSTP`, `LSTP` |
| `L9_PROTOCOL` | Default transport — `L9Transport.SSTP` |
| `L9_VERSION` | `"0"` current envelope version |
| `normalize_use_case()` | Normalise use-case label to snake_case |
| `schema_trust_level_for_kind()` | "certified" / "draft" for a kind |
| `schema_version_for_kind()` | "1.0" / "0.1" for a kind |

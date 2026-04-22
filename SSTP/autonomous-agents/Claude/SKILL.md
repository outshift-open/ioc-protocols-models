# SSTP Skill — Claude

This skill teaches Claude how to build, validate, and reason about **SSTP L9 headers** when working on IoC CFN cognitive agent implementations.

## Trigger conditions

Use this skill when:
- The user asks to build or inspect an L9 header
- The user is implementing a new sub-protocol on top of SSTP
- The user is debugging a `message_id`, `kind`, or `schema_id` mismatch
- The user asks about `L9Transport`, `L9HeaderBuilder`, or `build_l9_header()`

## Background

SSTP (Structured Semantic Transport Protocol) is the L9 semantic envelope carried by all IoC CFN agent messages.  Every SSTP message contains:

1. A **kind** — the semantic intent of the message (`intent`, `delegation`, `commit`, `query`, `knowledge`, `memory_delta`, `evidence_bundle`, `negotiate`)
2. A **transport modality** — always `"SSTP"` for structured messages; `"CSTP"` for embeddings; `"LSTP"` for latent tensors
3. A **schema URN** — identifies the payload schema (`urn:ioc:<use_case>:<area>:<topic>:v<version>`)
4. A **cognition profile** — `"semantic_alignment:v1"` (SNP) or `"adaptive_communication:v1"` (IE)

## Key files

| File | Purpose |
|---|---|
| `language-bindings/Python/src/sstp/l9_base.py` | `L9HeaderBuilder`, `L9Transport` — always read this first |
| `language-bindings/Python/src/sstp/ie/l9.py` | IE specialisation — `build_l9_header()` |
| `language-bindings/Python/src/sstp/snp/l9.py` | SNP specialisation — `build_snp_l9_header()` |
| `spec/SSTP_FORMAL_MODEL.md` | Normative field definitions |
| `spec/SEMANTIC_NEGOTIATION_PROTOCOL.md` | SNP operation vocabulary |
| `JSON schema/sstp-schema.json` | Machine-readable schema |

## How to build a new sub-protocol

```python
from sstp.l9_base import L9HeaderBuilder, L9Transport

class MyProtocolBuilder(L9HeaderBuilder):
    PROTOCOL = L9Transport.SSTP

    def kind_for_event_type(self, event_type: str) -> str:
        return {"my_start": "intent", "my_done": "commit"}.get(event_type, "knowledge")

    def schema_id_for(self, use_case, event_type, kind, trust_level) -> str:
        v = "1.0" if kind in ("commit", "memory_delta") else "0.1"
        trust = "certified" if trust_level == "certified" else "draft"
        prefix = "urn:ioc" if trust == "certified" else "urn:ioc:draft"
        return f"{prefix}:{use_case}:coordination:{kind}:v{v}"
```

## Kind → trust level rules

- `commit`, `memory_delta` → `schema_trust_level = "certified"`, version `"1.0"`
- All others → `schema_trust_level = "draft"`, version `"0.1"`

## Common mistakes to catch

- Using a kind not in the taxonomy — only the 8 kinds above are valid
- Setting `cognition_protocol` without the matching `cognition_profile_id`
- Generating non-deterministic `message_id` values — use UUIDv5 over `sender + timestamp_ms`
- TTL for `peer_turn` / `repair_required` / `repair_applied` is 1 day (86400 s), not the default 7 days

## See also

- [SSTP Formal Model](../../spec/SSTP_FORMAL_MODEL.md)
- [SNP spec](../../spec/SEMANTIC_NEGOTIATION_PROTOCOL.md)
- [Go bindings README](../../../SSTP/language-bindings/Go/README.md)

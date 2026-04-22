# SSTP Skill — Codex

This skill enables Codex to generate correct SSTP L9 header code when working on IoC CFN protocol implementations.

## Task types this skill covers

- Generating a `build_l9_header()` call for a new event type
- Adding a new sub-protocol by subclassing `L9HeaderBuilder`
- Writing Go struct initialisers for `sstp.Header`
- Fixing `schema_id` URN format errors
- Reviewing a header dict for missing required fields

## Required fields checklist

Every L9 header must contain:

```
protocol       ✓  "SSTP" | "CSTP" | "LSTP"
version        ✓  "0"
kind           ✓  one of: intent delegation knowledge query commit memory_delta evidence_bundle negotiate
message_id     ✓  deterministic UUIDv5 — do NOT use random UUID
dt_created     ✓  ISO 8601 UTC
origin.actor_id ✓ non-empty string
semantic_context.schema_id ✓ URN format: urn:ioc[:<draft>]:<use_case>:<area>:<topic>:v<version>
policy_labels.sensitivity  ✓ public | internal | restricted | confidential
policy_labels.propagation  ✓ forward | restricted | no_forward
ttl_seconds    ✓  86400 (peer_turn / repair_*) or 604800 (all others)
merge_strategy ✓  add | replace | merge | crdt  (default: "merge")
```

## Schema URN format

```
urn:ioc:<use_case>:<area>:<topic>:v<version>          ← certified (commit / memory_delta)
urn:ioc:draft:<use_case>:<area>:<topic>:v<version>    ← all other kinds
```

Examples:
```
urn:ioc:healthcare:coordination:decision:v1.0        (commit — certified)
urn:ioc:draft:healthcare:intake:turn:v0.1            (intent — draft)
```

## Python pattern

```python
from sstp.l9_base import L9HeaderBuilder, L9Transport

class AnalyticsProtocolBuilder(L9HeaderBuilder):
    PROTOCOL = L9Transport.SSTP

    def kind_for_event_type(self, event_type: str) -> str:
        return {
            "observation_start": "intent",
            "metric_emit":       "knowledge",
            "analysis_commit":   "commit",
        }.get(event_type, "knowledge")

    def schema_id_for(self, use_case, event_type, kind, trust_level) -> str:
        from sstp.l9_base import schema_trust_level_for_kind, schema_version_for_kind
        version = schema_version_for_kind(kind)
        trust = schema_trust_level_for_kind(kind)
        prefix = "urn:ioc" if trust == "certified" else "urn:ioc:draft"
        return f"{prefix}:{use_case}:analytics:{kind}:v{version}"
```

## Go pattern

```go
header := sstp.Header{
    Protocol:  sstp.TransportSSTP,
    Version:   sstp.Version,
    Kind:      sstp.KindIntent,
    MessageID: sstp.MessageID("agent-1", timestampMs),
    // ...
}
```

## References

- [SSTP Formal Model](../../spec/SSTP_FORMAL_MODEL.md)
- [Python bindings README](../../language-bindings/Python/README.md)
- [Go bindings README](../../language-bindings/Go/README.md)
- [JSON schema](../../JSON%20schema/sstp-schema.json)

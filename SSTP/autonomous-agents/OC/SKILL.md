# SSTP Skill — OpenCognition (OC)

This skill provides OC agents with the context needed to produce and consume SSTP L9 headers in IoC CFN multi-agent systems.

## Overview

SSTP is the semantic envelope layer (L9) for all structured agent-to-agent messages.  An OC agent that participates in an IoC CFN system must:

1. Stamp every outbound message with an L9 header.
2. Read the `kind`, `schema_id`, and `cognition_protocol` fields from inbound headers to route and interpret messages.
3. Respect policy labels (`sensitivity`, `propagation`) when forwarding.

## Header fields OC agents must set

| Field | Rule |
|---|---|
| `protocol` | Always `"SSTP"` for structured messages |
| `kind` | Derived from the operation — see kind table below |
| `sender` | The agent's canonical ID |
| `timestamp_ms` | Unix epoch in milliseconds |
| `cognition_protocol` | `"SNP"` or `"IE"` depending on the sub-protocol in use |

## Kind table

| OC operation | SSTP kind |
|---|---|
| Initial goal submission | `intent` |
| Delegating a task to a peer | `delegation` |
| Publishing a fact or result | `knowledge` |
| Asking for information | `query` |
| Final binding decision | `commit` |
| Persistent memory write | `memory_delta` |
| SNP negotiation message | `negotiate` |

## Python usage

```python
from sstp.ie.l9 import build_l9_header
import time

header = build_l9_header(
    use_case="my_use_case",
    event_type="turn_ingested",   # maps to kind="intent"
    sender="oc-agent-1",
    receiver="oc-agent-2",
    timestamp_ms=int(time.time() * 1000),
    sensitivity="internal",
    propagation="restricted",
)
```

## Policy enforcement

OC agents must not forward messages with `propagation="no_forward"`.  Messages with `sensitivity="confidential"` must be logged but not surfaced to end-users.

## References

- [SSTP Formal Model](../../spec/SSTP_FORMAL_MODEL.md)
- [Protocol spec](../../documentation/PROTOCOL_SPEC.md)
- [Python bindings](../../language-bindings/Python/README.md)

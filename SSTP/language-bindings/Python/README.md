# SSTP Python Bindings

Python package (`sstp`) providing the L9 header builder and sub-protocol implementations for the **Structured Semantic Transport Protocol (SSTP)**.

## Package layout

```
src/sstp/
  l9_base.py          # L9HeaderBuilder, L9Transport, shared utilities
  ie/                 # Interaction Engine sub-protocol
    l9.py             # IEL9HeaderBuilder, build_l9_header()
    adapter.py        # InteractionProtocolAdapter
    tom.py            # ToM data types and abstract interfaces
  snp/                # Semantic Negotiation Protocol sub-protocol
    l9.py             # SNPL9HeaderBuilder, build_snp_l9_header()
    l9_bridge.py      # build_negotiate_envelope()
    negotiate.py      # NegotiationSession
    intent.py / commit.py / delegation.py / ...
    ontology/
      snp_ontology.ttl
```

## Install

```bash
pip install -e ".[dev]"
```

## Regenerate from source

The canonical source lives in `ioc-cfn-cognitive-agents/protocol/`.  To sync:

```bash
make generate
```

Or point at a custom checkout:

```bash
COGNITIVE_AGENTS_ROOT=/path/to/repo make generate
```

## Run tests

```bash
make test
```

## Quick start

```python
from sstp.l9_base import L9HeaderBuilder, L9Transport
from sstp.ie.l9 import build_l9_header
import time

header = build_l9_header(
    use_case="healthcare",
    event_type="turn_ingested",
    sender="agent-1",
    receiver="agent-2",
    timestamp_ms=int(time.time() * 1000),
)
print(header["kind"])          # "intent"
print(header["protocol"])      # "SSTP"
```

## Sub-protocols

| Sub-protocol | Module | Cognition profile |
|---|---|---|
| SNP — Semantic Negotiation | `sstp.snp` | `semantic_alignment:v1` |
| IE — Interaction Engine | `sstp.ie` | `adaptive_communication:v1` |

See `../../spec/SSTP_FORMAL_MODEL.md` and `../../spec/SEMANTIC_NEGOTIATION_PROTOCOL.md` for the normative specifications.

# IOC L9 Protocol Models

[![PyPI](https://img.shields.io/pypi/v/ioc-l9-all-models)](https://pypi.org/project/ioc-l9-all-models/)
[![Python](https://img.shields.io/pypi/pyversions/ioc-l9-all-models)](https://pypi.org/project/ioc-l9-all-models/)

Pydantic models and protocol definitions for the Internet of Cognition (IoC) Layer 9 protocol stack.

## Installation

```bash
pip install ioc-l9-all-models
```

## Quick Start

```python
# import L9 protocol models
from ai.outshift.data_model import L9, L9Header, L9Payload, Message, Actor, ParticipantSet, Kind

# import SAB subprotocol models
# from ai.outshift.sab.data_model import SAB, SABActors, SABHeader, SABPayload, SABIntentPayloadData

# Create an L9 message
msg = L9(
    header=L9Header(
        protocol="L9",
        subprotocol="SSTP",
        version="1.0",
        kind=Kind.intent,
        subkind="chat",
        participants=ParticipantSet(
            actors=[Actor(id="actor-1", role="analyst")],
            groups={"team_alpha": ["actor-1"]},
        ),
    ),
    payload=L9Payload(
        type="text",
        data={"content": "Hello from L9!"},
    ),
)

print(msg.model_dump_json(indent=2))
```

## What's Included

- **L9/SSTP** — Core protocol Pydantic models (L9, L9Header, L9Payload, Actor, Message, etc.)
- **SIEP** — Semantic Interoperability and Epistemic Protocol
- **CIP** — Cognition and Interoperability Protocol
- **SAB** — Semantic Alignment Broadcast
- **TFP** — Team Formation via Polling

## Requirements

- Python >= 3.10, < 3.14
- pydantic >= 2.0

## Links

- [Source Code](https://github.com/outshift-open/ioc-protocols-models)
- [Issue Tracker](https://github.com/outshift-open/ioc-protocols-models/issues)

## License

Apache License 2.0 - See [LICENSE](https://github.com/outshift-open/ioc-protocols-models/blob/main/LICENSE.md) for details.

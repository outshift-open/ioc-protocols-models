---
name: validate-L9-skill
description: Skill for validating IOC L9 protocol messages — covering header routing metadata, payload content, and all nested structures including actors, semantic context, policy labels, and provenance.
---

# validate-L9-skill

## Description

Skill for validating IOC L9 protocol messages. The L9 protocol defines a structured envelope for passing messages between agents and through the Cognitive Function Network (CFN). Every L9 message consists of two top-level components: a `header` (routing and metadata) and a `payload` (content). This skill covers validation of all required fields, nested object structures, and optional governance labels across both Python (Pydantic) and Go (structs) implementations.

## Repository

For complete documentation and specifications, see: https://github.com/cisco-eti/ioc-cfn-protocols-models

---

## Schema Overview

The top-level `L9` object has exactly two required fields:

| Field     | Type        | Required | Description                                      |
|-----------|-------------|----------|--------------------------------------------------|
| `header`  | `L9Header`  | ✅ Yes   | Routing and metadata envelope                    |
| `payload` | `L9Payload` | ✅ Yes   | Actual content carried by the message            |

### L9Header Fields

| Field        | Type              | Required | Description                                                  |
|--------------|-------------------|----------|--------------------------------------------------------------|
| `protocol`   | `string`          | ✅ Yes   | Protocol identifier (e.g. `"L9"`)                            |
| `version`    | `string`          | ✅ Yes   | Protocol version (e.g. `"1.0.0"`)                            |
| `kind`       | `string`          | ✅ Yes   | Top-level message category used by CFN routing               |
| `sub_kind`   | `string`          | ✅ Yes   | Sub-category for fine-grained CE selection                   |
| `group`      | `Group`           | ✅ Yes   | Logical grouping / session scope                             |
| `actors`     | `array[Actor]`    | ✅ Yes   | Participants — senders and receivers                         |
| `semantic`   | `SemanticContext` | ✅ Yes   | Ontological framework for payload interpretation             |
| `policy`     | `PolicyLabel`     | ❌ No    | Data governance and access-control labels (nullable)         |
| `provenance` | `Provenance`      | ❌ No    | Origin and lineage tracking (nullable, fields TBD)           |
| `epistemic`  | `Epistemic`       | ❌ No    | Agent belief/knowledge state at send time (nullable, placeholder) |

### Actor Fields

| Field  | Type     | Required | Description                                      |
|--------|----------|----------|--------------------------------------------------|
| `id`   | `string` | ✅ Yes   | Unique identifier for the actor                  |
| `type` | `string` | ✅ Yes   | Actor type: `"human"`, `"agent"`, or `"system"`  |
| `name` | `string` | ✅ Yes   | Display name                                     |
| `role` | `string` | ✅ Yes   | Functional role in the exchange                  |

### Group Fields

| Field  | Type     | Required | Description                        |
|--------|----------|----------|------------------------------------|
| `id`   | `string` | ✅ Yes   | Unique group identifier            |
| `name` | `string` | ✅ Yes   | Human-readable group name          |

### SemanticContext Fields

| Field                | Type     | Required | Description                                              |
|----------------------|----------|----------|----------------------------------------------------------|
| `schema_id`          | `string` | ✅ Yes   | Identifier for the schema governing this message         |
| `ontology_ref`       | `string` | ✅ Yes   | Reference to the ontology used for interpretation        |
| `cognition_protocol` | `string` | ✅ Yes   | Protocol name passed to the cognitive engine             |

### L9Payload Fields

| Field  | Type     | Required | Description                                      |
|--------|----------|----------|--------------------------------------------------|
| `type` | `string` | ✅ Yes   | Describes the payload format (e.g. `"text"`)     |
| `data` | `object` | ✅ Yes   | Arbitrary content object — schema varies by type |

### PolicyLabel Fields

| Field              | Type     | Required | Description                                  |
|--------------------|----------|----------|----------------------------------------------|
| `sensitivity`      | `string` | ✅ Yes   | Data sensitivity classification              |
| `propagation`      | `string` | ✅ Yes   | How the label propagates downstream          |
| `retention_policy` | `string` | ✅ Yes   | Retention rules for this message             |

---

## Instructions

1. Validate that every L9 message contains both required top-level fields: `header` and `payload`.
2. Validate `L9Header` — all six required fields (`protocol`, `version`, `kind`, `sub_kind`, `group`, `actors`, `semantic`) must be present and non-empty.
3. Validate the `group` object contains both `id` and `name`.
4. Validate that `actors` is a non-empty array and each actor contains all four required fields: `id`, `type`, `name`, `role`.
5. Validate `semantic` contains all three required fields: `schema_id`, `ontology_ref`, `cognition_protocol`.
6. Validate `L9Payload` contains both `type` (string) and `data` (object).
7. When `policy` is present (non-null), validate all three `PolicyLabel` fields: `sensitivity`, `propagation`, `retention_policy`.
8. Treat `provenance` and `epistemic` as valid empty objects `{}` when present — their fields are TBD.
9. Report all validation errors together rather than stopping at the first failure.
10. When generating L9 messages, always set `protocol` to `"L9"` and `version` to `"1.0.0"` unless instructed otherwise.

---

## Basic Examples

### Minimal Valid L9 Message

The smallest valid L9 message — required fields only, no optional governance labels:

```json
{
  "header": {
    "protocol": "L9",
    "version": "1.0.0",
    "kind": "message",
    "sub_kind": "chat",
    "group": {
      "id": "group-001",
      "name": "Test Group"
    },
    "actors": [
      {
        "id": "user-001",
        "type": "human",
        "name": "Jane Smith",
        "role": "analyst"
      }
    ],
    "semantic": {
      "schema_id": "l9_v1",
      "ontology_ref": "standard",
      "cognition_protocol": "chat"
    }
  },
  "payload": {
    "type": "text",
    "data": {
      "content": "Hello, world!"
    }
  }
}
```

### Multi-Actor Message with Policy Label

A message between a human and an AI agent, with data governance labels applied:

```json
{
  "header": {
    "protocol": "L9",
    "version": "1.0.0",
    "kind": "request",
    "sub_kind": "analysis",
    "group": {
      "id": "session-42",
      "name": "Threat Analysis Session"
    },
    "actors": [
      {
        "id": "analyst-007",
        "type": "human",
        "name": "Alice Chen",
        "role": "sender"
      },
      {
        "id": "ce-ioc-engine-01",
        "type": "agent",
        "name": "IOC Cognitive Engine",
        "role": "receiver"
      }
    ],
    "semantic": {
      "schema_id": "ioc_threat_v2",
      "ontology_ref": "mitre-attack-v14",
      "cognition_protocol": "threat-analysis"
    },
    "policy": {
      "sensitivity": "confidential",
      "propagation": "inherit",
      "retention_policy": "90-days"
    },
    "provenance": {},
    "epistemic": {}
  },
  "payload": {
    "type": "ioc_bundle",
    "data": {
      "indicators": ["198.51.100.42", "malware.example.com"],
      "confidence": 0.87,
      "tlp": "amber"
    }
  }
}
```

### System-to-System Message

A message between two system actors routing through the CFN:

```json
{
  "header": {
    "protocol": "L9",
    "version": "1.0.0",
    "kind": "event",
    "sub_kind": "heartbeat",
    "group": {
      "id": "cfn-cluster-prod",
      "name": "Production CFN Cluster"
    },
    "actors": [
      {
        "id": "node-cfn-03",
        "type": "system",
        "name": "CFN Node 03",
        "role": "sender"
      },
      {
        "id": "node-cfn-01",
        "type": "system",
        "name": "CFN Node 01",
        "role": "receiver"
      }
    ],
    "semantic": {
      "schema_id": "cfn_internal_v1",
      "ontology_ref": "cfn-ops",
      "cognition_protocol": "heartbeat"
    }
  },
  "payload": {
    "type": "status",
    "data": {
      "status": "healthy",
      "uptime_seconds": 86400,
      "load": 0.42
    }
  }
}
```

---

## Code Examples

### Python — Pydantic Validation

**Model definitions** (`models/l9.py`):

```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class Actor(BaseModel):
    id: str
    type: str
    name: str
    role: str


class Group(BaseModel):
    id: str
    name: str


class SemanticContext(BaseModel):
    schema_id: str
    ontology_ref: str
    cognition_protocol: str


class PolicyLabel(BaseModel):
    sensitivity: str
    propagation: str
    retention_policy: str


class Provenance(BaseModel):
    """Origin and lineage tracking. Fields TBD."""
    pass


class Epistemic(BaseModel):
    """Agent belief/knowledge state. Currently a placeholder."""
    pass


class L9Header(BaseModel):
    protocol: str
    version: str
    kind: str
    sub_kind: str
    group: Group
    actors: list[Actor]
    semantic: SemanticContext
    policy: Optional[PolicyLabel] = None
    provenance: Optional[Provenance] = None
    epistemic: Optional[Epistemic] = None


class L9Payload(BaseModel):
    type: str
    data: dict


class L9(BaseModel):
    header: L9Header
    payload: L9Payload
```

**Validation helper** (`validation/validate_l9.py`):

```python
import json
from pathlib import Path
from pydantic import ValidationError
from models.l9 import L9


def validate_l9_message(message: dict) -> tuple[bool, list[str]]:
    """
    Validate an L9 message dict against the schema.

    Returns:
        (is_valid, errors) — errors is an empty list when valid.
    """
    try:
        L9.model_validate(message)
        return True, []
    except ValidationError as exc:
        errors = [
            f"{' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        return False, errors


def validate_l9_file(path: str | Path) -> tuple[bool, list[str]]:
    """Load a JSON file and validate it as an L9 message."""
    with open(path) as f:
        data = json.load(f)
    return validate_l9_message(data)


# --- Usage ---
if __name__ == "__main__":
    message = {
        "header": {
            "protocol": "L9",
            "version": "1.0.0",
            "kind": "message",
            "sub_kind": "chat",
            "group": {"id": "g1", "name": "Demo Group"},
            "actors": [
                {"id": "u1", "type": "human", "name": "Bob", "role": "sender"}
            ],
            "semantic": {
                "schema_id": "l9_v1",
                "ontology_ref": "standard",
                "cognition_protocol": "chat"
            }
        },
        "payload": {
            "type": "text",
            "data": {"content": "Validate me."}
        }
    }

    valid, errors = validate_l9_message(message)
    if valid:
        print("✅ Message is valid.")
    else:
        print("❌ Validation failed:")
        for err in errors:
            print(f"  - {err}")
```

**Building an L9 message programmatically**:

```python
from models.l9 import L9, L9Header, L9Payload, Actor, Group, SemanticContext, PolicyLabel

message = L9(
    header=L9Header(
        protocol="L9",
        version="1.0.0",
        kind="request",
        sub_kind="analysis",
        group=Group(id="session-99", name="Analysis Session"),
        actors=[
            Actor(id="analyst-1", type="human", name="Carol", role="sender"),
            Actor(id="ce-engine-1", type="agent", name="CE Engine", role="receiver"),
        ],
        semantic=SemanticContext(
            schema_id="ioc_v2",
            ontology_ref="mitre-attack-v14",
            cognition_protocol="threat-analysis"
        ),
        policy=PolicyLabel(
            sensitivity="internal",
            propagation="inherit",
            retention_policy="30-days"
        )
    ),
    payload=L9Payload(
        type="text",
        data={"content": "Analyze this IOC bundle."}
    )
)

# Serialize to JSON
print(message.model_dump_json(indent=2))
```

---

### Go — Struct Validation

**Model definitions** (`models/l9.go`):

```go
package models

// Actor represents a participant in a protocol exchange.
type Actor struct {
    ID   string `json:"id"`
    Type string `json:"type"`
    Name string `json:"name"`
    Role string `json:"role"`
}

// Group is a logical grouping of actors scoping the message context.
type Group struct {
    ID   string `json:"id"`
    Name string `json:"name"`
}

// SemanticContext describes the ontological framework for payload interpretation.
type SemanticContext struct {
    SchemaID          string `json:"schema_id"`
    OntologyRef       string `json:"ontology_ref"`
    CognitionProtocol string `json:"cognition_protocol"`
}

// PolicyLabel holds data governance and access-control labels.
type PolicyLabel struct {
    Sensitivity     string `json:"sensitivity"`
    Propagation     string `json:"propagation"`
    RetentionPolicy string `json:"retention_policy"`
}

// Provenance tracks message origin and lineage. Fields TBD.
type Provenance struct{}

// Epistemic captures agent belief/knowledge state. Currently a placeholder.
type Epistemic struct{}

// L9Header is the routing and metadata envelope for every L9 message.
type L9Header struct {
    
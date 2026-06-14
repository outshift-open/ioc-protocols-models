---
name: validate-L9-skill
description: Skill for validating IOC L9 protocol messages, including header routing metadata and payload content, for use in CFN-based agent communication pipelines.
---

# validate-L9-skill

## Description
Skill for validating IOC L9 protocol model. The L9 protocol defines a structured message envelope used to route and process communications between agents, humans, and systems through the Cognitive Function Network (CFN). Every L9 message consists of a `header` (routing and metadata) and a `payload` (content). This skill helps developers construct, inspect, and validate L9 messages against the protocol schema.

## Repository
For complete documentation and specifications, see: https://github.com/cisco-eti/ioc-cfn-protocols-models

---

## Schema Overview

The top-level `L9` object has exactly two required fields:

| Field     | Type        | Required | Description                                      |
|-----------|-------------|----------|--------------------------------------------------|
| `header`  | `L9Header`  | Yes      | Routing envelope read by the CFN layer           |
| `payload` | `L9Payload` | Yes      | Content being carried by the message             |

### L9Header Fields

| Field        | Type              | Required | Description                                                  |
|--------------|-------------------|----------|--------------------------------------------------------------|
| `protocol`   | string            | Yes      | Protocol identifier (e.g., `"L9"`)                          |
| `version`    | string            | Yes      | Protocol version (e.g., `"1.0.0"`)                          |
| `kind`       | string            | Yes      | Top-level message category used by CFN for CE routing        |
| `sub_kind`   | string            | Yes      | Subcategory for finer-grained CE selection                   |
| `group`      | `Group`           | Yes      | Logical grouping scoping the message to a shared context     |
| `actors`     | `Actor[]`         | Yes      | List of participants (senders, receivers, observers)         |
| `semantic`   | `SemanticContext` | Yes      | Ontological framework for payload interpretation             |
| `policy`     | `PolicyLabel`     | No       | Data governance and access-control labels                    |
| `provenance` | `Provenance`      | No       | Origin and lineage tracking for the message                  |
| `epistemic`  | `Epistemic`       | No       | Agent belief/knowledge state at time of sending              |

### Actor Fields

| Field  | Type   | Required | Description                                      |
|--------|--------|----------|--------------------------------------------------|
| `id`   | string | Yes      | Unique identifier for the actor                  |
| `type` | string | Yes      | Actor type: `"human"`, `"agent"`, or `"system"`  |
| `name` | string | Yes      | Human-readable display name                      |
| `role` | string | Yes      | Functional role in this exchange                 |

### Group Fields

| Field  | Type   | Required | Description                          |
|--------|--------|----------|--------------------------------------|
| `id`   | string | Yes      | Unique identifier for the group      |
| `name` | string | Yes      | Human-readable name for the group    |

### SemanticContext Fields

| Field                | Type   | Required | Description                                              |
|----------------------|--------|----------|----------------------------------------------------------|
| `schema_id`          | string | Yes      | Identifier for the schema governing the payload          |
| `ontology_ref`       | string | Yes      | Reference to the ontology used for interpretation        |
| `cognition_protocol` | string | Yes      | Cognition protocol used to select the appropriate CE     |

### L9Payload Fields

| Field  | Type   | Required | Description                                    |
|--------|--------|----------|------------------------------------------------|
| `type` | string | Yes      | Describes the payload format (e.g., `"text"`)  |
| `data` | object | Yes      | Arbitrary content object carrying the message  |

### PolicyLabel Fields

| Field              | Type   | Required | Description                                  |
|--------------------|--------|----------|----------------------------------------------|
| `sensitivity`      | string | Yes      | Data sensitivity classification              |
| `propagation`      | string | Yes      | Rules for how labels propagate downstream    |
| `retention_policy` | string | Yes      | Data retention requirements                  |

---

## Instructions

1. Validate that every L9 message contains both required top-level fields: `header` and `payload`.
2. Validate `L9Header` required fields: `protocol`, `version`, `kind`, `sub_kind`, `group`, `actors`, and `semantic`.
3. Validate each `Actor` in the `actors` array contains `id`, `type`, `name`, and `role`.
4. Validate `Group` contains both `id` and `name`.
5. Validate `SemanticContext` contains `schema_id`, `ontology_ref`, and `cognition_protocol`.
6. Validate `L9Payload` contains both `type` and `data`, where `data` must be an object (not a scalar or array).
7. When `policy` is present, validate `PolicyLabel` contains `sensitivity`, `propagation`, and `retention_policy`.
8. Report all missing required fields clearly, referencing the full dot-path (e.g., `header.semantic.schema_id`).
9. Confirm the `protocol` field value matches the expected protocol identifier for the context.
10. When generating L9 messages, always populate all required fields before adding optional ones.

---

## Basic Examples

### Minimal Valid L9 Message

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

### Full L9 Message with Optional Fields

```json
{
  "header": {
    "protocol": "L9",
    "version": "1.0.0",
    "kind": "task",
    "sub_kind": "analysis-request",
    "group": {
      "id": "session-42",
      "name": "Threat Analysis Session"
    },
    "actors": [
      {
        "id": "agent-triage-01",
        "type": "agent",
        "name": "Triage Agent",
        "role": "sender"
      },
      {
        "id": "agent-analysis-02",
        "type": "agent",
        "name": "Analysis Agent",
        "role": "receiver"
      }
    ],
    "semantic": {
      "schema_id": "threat-analysis-v2",
      "ontology_ref": "ioc-ontology-v1",
      "cognition_protocol": "deep-analysis"
    },
    "policy": {
      "sensitivity": "confidential",
      "propagation": "inherit",
      "retention_policy": "30-days"
    },
    "provenance": {},
    "epistemic": {}
  },
  "payload": {
    "type": "structured",
    "data": {
      "task_id": "task-9981",
      "priority": "high",
      "description": "Analyze the attached IOC for threat classification."
    }
  }
}
```

---

## Code Examples

### Python (Pydantic)

#### Defining the Models

```python
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


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
    pass  # Fields TBD


class Epistemic(BaseModel):
    pass  # Fields TBD


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
    data: dict[str, Any]


class L9(BaseModel):
    header: L9Header
    payload: L9Payload
```

#### Constructing and Validating a Message

```python
from pydantic import ValidationError

raw_message = {
    "header": {
        "protocol": "L9",
        "version": "1.0.0",
        "kind": "message",
        "sub_kind": "chat",
        "group": {"id": "group-001", "name": "Test Group"},
        "actors": [
            {"id": "user-001", "type": "human", "name": "Jane Smith", "role": "analyst"}
        ],
        "semantic": {
            "schema_id": "l9_v1",
            "ontology_ref": "standard",
            "cognition_protocol": "chat"
        }
    },
    "payload": {
        "type": "text",
        "data": {"content": "Hello, world!"}
    }
}

try:
    message = L9(**raw_message)
    print(f"Valid L9 message: kind={message.header.kind}, sub_kind={message.header.sub_kind}")
    print(f"Actors: {[a.name for a in message.header.actors]}")
    print(f"Payload type: {message.payload.type}")
except ValidationError as e:
    for error in e.errors():
        field_path = " -> ".join(str(loc) for loc in error["loc"])
        print(f"Validation error at '{field_path}': {error['msg']}")
```

#### Validating from JSON String

```python
import json

def validate_l9_message(json_str: str) -> L9 | None:
    try:
        data = json.loads(json_str)
        return L9(**data)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        return None
    except ValidationError as e:
        print(f"Schema validation failed:\n{e}")
        return None

# Usage
json_input = '{"header": {...}, "payload": {...}}'
msg = validate_l9_message(json_input)
```

#### Serializing a Message

```python
# Build a message programmatically
message = L9(
    header=L9Header(
        protocol="L9",
        version="1.0.0",
        kind="task",
        sub_kind="analysis-request",
        group=Group(id="session-42", name="Threat Analysis Session"),
        actors=[
            Actor(id="agent-01", type="agent", name="Triage Agent", role="sender"),
            Actor(id="agent-02", type="agent", name="Analysis Agent", role="receiver"),
        ],
        semantic=SemanticContext(
            schema_id="threat-analysis-v2",
            ontology_ref="ioc-ontology-v1",
            cognition_protocol="deep-analysis"
        ),
        policy=PolicyLabel(
            sensitivity="confidential",
            propagation="inherit",
            retention_policy="30-days"
        )
    ),
    payload=L9Payload(
        type="structured",
        data={"task_id": "task-9981", "priority": "high"}
    )
)

# Serialize to JSON
print(message.model_dump_json(indent=2, exclude_none=True))
```

---

### Go (Structs)

#### Defining the Structs

```go
package l9protocol

// Actor represents a participant in a protocol exchange.
type Actor struct {
    ID   string `json:"id"`
    Type string `json:"type"`
    Name string `json:"name"`
    Role string `json:"role"`
}

// Group is a logical grouping of actors.
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

// Provenance tracks origin and lineage (fields TBD).
type Provenance struct{}

// Epistemic represents agent belief/knowledge state (fields TBD).
type Epistemic struct{}

// L9Header is the routing and metadata envelope for every L9 message.
type L9Header struct {
    Protocol   string           `json:"protocol"`
    Version    string           `json:"version"`
    Kind       string           `json:"kind"`
    SubKind    string           `json:"sub_kind"`
    Group      Group            `json:"group"`
    Actors     []Actor          `json:"actors"`
    Semantic   SemanticContext  `json:"semantic"`
    Policy     *PolicyLabel     `json:"policy,omitempty"`
    Provenance *Provenance      `json:"provenance,omitempty"`
    Epistemic  *Epistemic       `json:"epistemic,omitempty"`
}

// L9Payload holds the actual content of an L9 message.
type L9Payload struct {
    Type string                 `json:"type"`
    Data map[string]interface{} `json:"data"`
}

// L9 is the top-level L9 message structure.
type L9 struct {
    Header  L9Header  `json:"header"`
    Payload L9Payload `json:"payload"`
}
```

#### Validating a Message

```go
package l9protocol

import (
    "encoding/json"
    "errors"
    "fmt"
)

// Validate checks that all required fields are present and non-empty.
func (m *L9) Validate() error {
    // Header required fields
    if m.Header.Protocol == "" {
        return errors.New("missing required field: header.protocol")
    }
    if m.Header.Version == "" {
        return errors.New("missing required field: header.version")
    }
    if m.Header.Kind == "" {
        return errors.New("missing required field: header.kind")
    }
    if m.Header.SubKind == "" {
        return errors.New("missing required field: header.sub_kind")
    }
    if m.Header.Group.ID == "" || m.Header.Group.Name == "" {
        return errors.New("missing required field(s) in header.group: id, name")
    }
    if len(m.Header.Actors) == 0 {
        return errors.New("header.actors must contain at least one actor")
    }
    for i, actor := range m.Header.Actors {
        if actor.ID == "" || actor.Type == "" || actor.Name == "" || actor.Role == "" {
            return fmt.Errorf("actor at index %d is missing required fields (id, type, name, role)", i)
        }

---
name: validate-L9-skill
description: Skill for validating IOC L9 protocol model
---

# validate-L9-skill

## Description
Skill for validating IOC L9 protocol model. The L9 protocol defines a complete message structure consisting of a header (routing/metadata) and payload (content). This is the top-level structure passed between agents and through the CFN (Cognitive Function Network).

## Repository
For complete documentation and specifications, see: https://github.com/cisco-eti/ioc-cfn-protocols-models

## Schema Version
`0.0.2`

## Instructions
1. Validate L9 messages have required `header` and `payload` fields
2. Validate `L9Header` contains all required fields: `protocol`, `subprotocol`, `version`, `kind`, `subkind`, `actors`
3. Validate `L9Payload` contains all required fields: `type`, `data`
4. Validate `Actors` object contains both `actors` array and `groups` array
5. Validate each `Actor` has required `id` and `role` fields
6. Validate `Message` objects contain `id`, `parents`, and `episode` fields
7. Validate `PolicyLabel` contains `sensitivity`, `propagation`, and `retention_policy`
8. Validate `Semantic` contains `schema_id` and `ontology_ref`
9. Validate `Context` contains required `topic` field
10. Confirm optional fields (`message`, `policy`, `attributes`, `context`, `attestation`, `epistemic`, `semantic`, `provenance`) accept `null` values gracefully

## Message Types

### L9 (Top-Level)
The root message structure. Every L9 message must contain:
- `header` — L9Header (required)
- `payload` — L9Payload (required)

### L9Header
Routing and metadata envelope for every L9 message. The CFN layer reads the header — especially `kind` and `subkind` — to decide which Cognitive Engine (CE) should handle the message.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `protocol` | string | ✅ | Protocol identifier |
| `subprotocol` | string | ✅ | Sub-protocol identifier |
| `version` | string | ✅ | Protocol version |
| `kind` | string | ✅ | Message kind for CE routing |
| `subkind` | string | ✅ | Message sub-kind for CE routing |
| `actors` | Actors | ✅ | Participants in the exchange |
| `message` | Message \| null | ❌ | Message threading metadata |
| `policy` | PolicyLabel \| null | ❌ | Data governance labels |
| `attributes` | object \| null | ❌ | Arbitrary key-value attributes |
| `context` | Context \| null | ❌ | Topic and semantic context |

### L9Payload
The actual content being carried by an L9 message.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Payload format descriptor |
| `data` | object | ✅ | The content data |

### Actor
A participant in a protocol exchange — can be a human, an AI agent, or a system.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique actor identifier |
| `role` | string | ✅ | Actor's role in the exchange |
| `attestation` | string \| null | ❌ | Optional attestation credential |

### Actors
Container for participants and group memberships.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `actors` | Actor[] | ✅ | List of participating actors |
| `groups` | string[] | ✅ | Group identifiers |

### Message
Represents message threading and lineage.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique message identifier |
| `parents` | string | ✅ | Parent message reference |
| `episode` | string | ✅ | Episode/conversation identifier |

### PolicyLabel
Data governance and access-control labels applied to the message.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sensitivity` | string | ✅ | Data sensitivity classification |
| `propagation` | string | ✅ | Propagation rules |
| `retention_policy` | string | ✅ | Data retention policy |

### Context
Contextual metadata for message interpretation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic` | string | ✅ | Conversation topic |
| `epistemic` | Epistemic \| null | ❌ | Agent belief/knowledge state |
| `semantic` | Semantic \| null | ❌ | Semantic framework reference |

### Semantic
Describes the semantic/ontological framework needed to correctly interpret the payload. The CFN routing layer uses this to select appropriate cognitive engines (CEs).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_id` | string | ✅ | Schema identifier |
| `ontology_ref` | string | ✅ | Ontology reference |
| `provenance` | Provenance \| null | ❌ | Origin and lineage tracking |

### Epistemic
Agent epistemic (belief/knowledge) state at the time the message was sent. Currently a placeholder — fields will be added as the model is defined.

### Provenance
Tracks the origin and lineage of a message — who created it, from what source, and through which transformations. Fields TBD.

## Basic Examples

### Valid L9 Message (Minimal):
```json
{
  "header": {
    "protocol": "L9",
    "subprotocol": "chat",
    "version": "0.0.2",
    "kind": "message",
    "subkind": "request",
    "actors": {
      "actors": [
        {"id": "user1", "role": "analyst"},
        {"id": "agent1", "role": "assistant"}
      ],
      "groups": ["team-alpha"]
    }
  },
  "payload": {
    "type": "text",
    "data": {"content": "Hello, world!"}
  }
}
```

### Valid L9 Message (Full):
```json
{
  "header": {
    "protocol": "L9",
    "subprotocol": "reasoning",
    "version": "0.0.2",
    "kind": "cognitive",
    "subkind": "inference",
    "actors": {
      "actors": [
        {"id": "agent-ce-01", "role": "reasoner", "attestation": "sig:abc123"},
        {"id": "user-42", "role": "requester", "attestation": null}
      ],
      "groups": ["research-division", "project-x"]
    },
    "message": {
      "id": "msg-20240115-001",
      "parents": "msg-20240115-000",
      "episode": "episode-7734"
    },
    "policy": {
      "sensitivity": "internal",
      "propagation": "restricted",
      "retention_policy": "30d"
    },
    "attributes": {
      "priority": "high",
      "source_system": "cfn-router-east"
    },
    "context": {
      "topic": "threat-analysis",
      "epistemic": {},
      "semantic": {
        "schema_id": "l9_reasoning_v1",
        "ontology_ref": "cisco-security-ontology-2024",
        "provenance": {}
      }
    }
  },
  "payload": {
    "type": "structured",
    "data": {
      "analysis": "Detected anomalous traffic pattern",
      "confidence": 0.87,
      "indicators": ["ip:192.168.1.100", "port:4444"]
    }
  }
}
```

### Python (Pydantic) Validation:
```python
from pydantic import BaseModel, ValidationError
from typing import Optional

class Actor(BaseModel):
    id: str
    role: str
    attestation: Optional[str] = None

class Actors(BaseModel):
    actors: list[Actor]
    groups: list[str]

class Message(BaseModel):
    id: str
    parents: str
    episode: str

class PolicyLabel(BaseModel):
    sensitivity: str
    propagation: str
    retention_policy: str

class Provenance(BaseModel):
    pass

class Semantic(BaseModel):
    schema_id: str
    ontology_ref: str
    provenance: Optional[Provenance] = None

class Epistemic(BaseModel):
    pass

class Context(BaseModel):
    topic: str
    epistemic: Optional[Epistemic] = None
    semantic: Optional[Semantic] = None

class L9Header(BaseModel):
    protocol: str
    subprotocol: str
    version: str
    kind: str
    subkind: str
    actors: Actors
    message: Optional[Message] = None
    policy: Optional[PolicyLabel] = None
    attributes: Optional[dict] = None
    context: Optional[Context] = None

class L9Payload(BaseModel):
    type: str
    data: dict

class L9(BaseModel):
    header: L9Header
    payload: L9Payload

# Validate a message
try:
    msg = L9.model_validate({
        "header": {
            "protocol": "L9",
            "subprotocol": "chat",
            "version": "0.0.2",
            "kind": "message",
            "subkind": "request",
            "actors": {
                "actors": [{"id": "user1", "role": "analyst"}],
                "groups": ["default"]
            }
        },
        "payload": {
            "type": "text",
            "data": {"content": "Validate this message"}
        }
    })
    print("✅ Valid L9 message")
except ValidationError as e:
    print(f"❌ Validation failed: {e}")
```

### Go (Structs) Validation:
```go
package l9

type Actor struct {
    ID          string  `json:"id"`
    Role        string  `json:"role"`
    Attestation *string `json:"attestation,omitempty"`
}

type Actors struct {
    Actors []Actor  `json:"actors"`
    Groups []string `json:"groups"`
}

type Message struct {
    ID      string `json:"id"`
    Parents string `json:"parents"`
    Episode string `json:"episode"`
}

type PolicyLabel struct {
    Sensitivity     string `json:"sensitivity"`
    Propagation     string `json:"propagation"`
    RetentionPolicy string `json:"retention_policy"`
}

type Provenance struct{}

type Semantic struct {
    SchemaID    string      `json:"schema_id"`
    OntologyRef string     `json:"ontology_ref"`
    Provenance  *Provenance `json:"provenance,omitempty"`
}

type Epistemic struct{}

type Context struct {
    Topic     string     `json:"topic"`
    Epistemic *Epistemic `json:"epistemic,omitempty"`
    Semantic  *Semantic  `json:"semantic,omitempty"`
}

type L9Header struct {
    Protocol    string       `json:"protocol"`
    Subprotocol string       `json:"subprotocol"`
    Version     string       `json:"version"`
    Kind        string       `json:"kind"`
    Subkind     string       `json:"subkind"`
    Actors      Actors       `json:"actors"`
    Message     *Message     `json:"message,omitempty"`
    Policy      *PolicyLabel `json:"policy,omitempty"`
    Attributes  map[string]interface{} `json:"attributes,omitempty"`
    Context     *Context     `json:"context,omitempty"`
}

type L9Payload struct {
    Type string                 `json:"type"`
    Data map[string]interface{} `json:"data"`
}

type L9 struct {
    Header  L9Header  `json:"header"`
    Payload L9Payload `json:"payload"`
}
```

## Validation Rules

### Required Field Checks
1. **Top-level**: Both `header` and `payload` must be present
2. **L9Header**: All of `protocol`, `subprotocol`, `version`, `kind`, `subkind`, `actors` must be non-null strings (or object for `actors`)
3. **L9Payload**: Both `type` (string) and `data` (object) must be present
4. **Actors**: Must contain both `actors` array and `groups` array (can be empty arrays but must exist)
5. **Actor**: Each actor must have `id` and `role` as non-empty strings

### Nullable Field Rules
The following fields accept `null` and default to `null` when omitted:
- `L9Header.message`
- `L9Header.policy`
- `L9Header.attributes`
- `L9Header.context`
- `Actor.attestation`
- `Context.epistemic`
- `Context.semantic`
- `Semantic.provenance`

## Common Mistakes

### ❌ Missing `actors` wrapper object
```json
{
  "header": {
    "protocol": "L9",
    "subprotocol": "chat",
    "version": "0.0.2",
    "kind": "message",
    "subkind": "request",
    "actors": [{"id": "user1", "role": "analyst"}]
  },
  "payload": {"type": "text", "data": {}}
}
```
**Problem**: `actors` must be an `Actors` object with `actors` and `groups` fields, not a bare array.

### ❌ Missing `groups` in Actors
```json
{
  "actors": {
    "actors": [{"id": "user1", "role": "analyst"}]
  }
}
```
**Problem**: `groups` is required in the `Actors` object, even if empty (`"groups": []`).

### ❌ Using `sub_kind` instead of `subkind`
```json
{
  "header": {
    "kind": "message",
    "sub_kind": "chat"
  }
}
```
**Problem**: The schema uses `subkind` (no underscore), not `sub_kind`.

### ❌ Payload `data` as a string instead of object
```json
{
  "payload": {
    "type": "text",
    "data": "Hello, world!"
  }
}
```
**Problem**: `data` must be an object (`{}`), not a primitive value.

### ❌ Missing required `topic` in Context
```json
{
  "header": {
    "context": {
      "semantic": {"schema_id": "v1", "ontology_ref": "std"}
    }
  }
}
```
**Problem**: `topic` is required when `context` is provided.

## Debugging Tips

1. **Validate incrementally**: Start with the minimal required fields, then add optional sections one at a time
2. **Check field naming**: The schema uses `subkind` and `subprotocol` (no underscores) — verify casing
3. **Null vs. absent**: Optional fields can be omitted entirely or set to `null` — both are valid
4. **Empty objects for placeholders**: `Epistemic` and `Provenance` are currently empty objects (`{}`); they will gain fields in future versions
5. **Array requirements**: `Actors.actors` and `Actors.groups` must be arrays — use `[]` for empty, never `null`
6. **Version string**: Current schema version is `"0.0.2"` — ensure your messages reference a valid version

## File Paths
- Schema definition: `schemas/l9_schema.json`
- Python models: `python/models/l9.py`
- Go models: `go/models/l9.go`
- Test fixtures: `tests/fixtures/l9/`
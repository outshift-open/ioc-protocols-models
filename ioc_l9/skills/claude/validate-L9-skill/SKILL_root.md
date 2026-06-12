yaml
---
name: validate-L9-skill
description: Skill for validating IOC L9 protocol model
---

# validate-L9-skill

## Description
Skill for validating IOC L9 protocol model.

## Repository
For complete documentation and specifications, see: https://github.com/cisco-eti/ioc-cfn-protocols-models

## Instructions
1. Validate L9 messages have required `header` and `payload` fields

## Basic Examples

### Valid L9 Message:
```json
{
  "header": {
    "protocol": "L9",
    "version": "1.0",
    "kind": "message",
    "sub_kind": "chat",
    "group": {"id": "group1", "name": "Test Group"},
    "actors": [{"id": "user1", "type": "human", "name": "John", "role": "analyst"}],
    "semantic": {"schema_id": "l9_v1", "ontology_ref": "standard", "cognition_protocol": "chat"}
  },
  "payload": {
    "type": "text",
    "data": {"content": "Hello, world!"}
  }
}
```
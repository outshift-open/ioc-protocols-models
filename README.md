# ioc-cfn-protocols-models

> **L9 / SSTP — Semantic Structured Transfer Protocol**
> Pydantic models for the Agentic Workflow Lifecycle.

---

## Overview

This package defines the protocol models for the **L9/SSTP** agentic workflow lifecycle. The lifecycle is organized into **5 Kinds** (phases), each with typed SubKinds, Actions, Events, and State — all implemented as [Pydantic](https://docs.pydantic.dev/) `BaseModel` classes.

A cross-phase **knowledge pipeline** connects the kinds:

```
Phase 1 (teamwork)      Phase 2 (goal_intent)    Phase 4 (communication)   Phase 5 (validation)
  knowledge_domain  ──▶  evidence_bundle     ──▶   query / ingest       ──▶   learn
 (what agents bring)    (clarify the goal)        (retrieve & absorb)        (update knowledge)
```

---

## Package Structure

```
l9/
├── __init__.py           # L9Protocol — top-level container
├── shared/               # Cross-phase primitives
│   └── models.py         #   Knowledge, EvidenceBundle
├── teamwork/             # Phase 1 — AgentHiring (teamwork)
│   └── models.py         #   Hire agents by skills & knowledge domains
├── goal_intent/          # Phase 2 — GoalIntent
│   └── models.py         #   Goal definition, evidence bundles, consensus commit
│                         #   Implementors: NegMas, Stigmetry
├── planning/             # Phase 3 — Planning
│   └── models.py         #   Task decomposition, resource allocation
├── communication/        # Phase 4 — Communication
│   └── models.py         #   Agent↔Agent, Agent↔Tool, query, ingest
└── validation/           # Phase 5 — Validation
    └── models.py         #   Online/offline validation modes, learn
```

---

## The 5 Kinds

| Phase | Kind | Key SubKinds | Key Actions |
|---|---|---|---|
| 1 | **AgentHiring** (teamwork) | `skill_match`, `knowledge_domain`, `team_formation` | `advertise_role`, `register_knowledge`, `form_team` |
| 2 | **GoalIntent** | `ambiguity`, `negotiation`, `evidence_bundle` | `detect_ambiguity`, `attach_evidence`, `consensus_commit` |
| 3 | **Planning** | `task_decomposition`, `resource_allocation` | `decompose_goal`, `allocate_resources`, `commit_plan` |
| 4 | **Communication** | `agent_agent`, `agent_tool` | `send_message`, `query`, `ingest` |
| 5 | **Validation** | `online`, `offline_triggered`, `pre_commit_eval` | `validate_online`, `run_pre_commit`, `learn` |

---

## Installation

Requires Python 3.10+. Dependencies are managed with [Poetry](https://python-poetry.org/).

```bash
# Install core dependencies
poetry install --only main

# Install all dependencies (including dev: Flask, prometheus, etc.)
poetry install
```

---

## Quick Start

```python
from l9 import L9Protocol, Knowledge, EvidenceBundle
from l9.goal_intent import ConsensusCommitPayload
from l9.communication import QueryRequest
from l9.validation import LearningOutcome

protocol = L9Protocol()

# Phase 1 — register an agent's knowledge domain
protocol.agent_hiring.register_knowledge(
    "agent-nlp",
    Knowledge(domain="NLP", facts=["tokenization", "embeddings"], confidence=0.9)
)

# Phase 2 — attach evidence and commit the goal
bundle = EvidenceBundle(bundle_id="b-001", source="rag-tool", content=["doc A", "doc B"])
protocol.goal_intent.attach_evidence(bundle)
protocol.goal_intent.consensus_commit(ConsensusCommitPayload(
    goal_specified="Build a summarizer",
    intent_behind_it="Reduce reading time",
    problems_found=["ambiguous scope"],
    solution="Limit output to 3 sentences",
    supporting_bundles=[bundle],
))

# Phase 4 — query a source and ingest the result
protocol.communication.query(QueryRequest(query_id="q-1", query_text="NLP papers", target="rag-tool"))
result = protocol.communication.ingest(EvidenceBundle(bundle_id="b-002", source="rag-tool", content=["doc C"]))

# Phase 5 — learn from validation outcomes
protocol.validation.learn(LearningOutcome(
    source_validation_id="val-1",
    updated_knowledge=[Knowledge(domain="NLP", facts=["summarization patterns"], confidence=0.85)],
    insights=["Short summaries score higher on human eval"],
))

# Inspect
print([k.name for k in protocol.kinds])
# ['AgentHiring', 'GoalIntent', 'Planning', 'Communication', 'Validation']

print([k.domain for k in protocol.knowledge_store])
# ['NLP', 'NLP']

# Serialize to JSON
print(protocol.model_dump_json(indent=2))
```

---

## Serialization

All models are Pydantic `BaseModel` subclasses, giving you serialization for free:

```python
# Dict
protocol.model_dump()

# JSON string
protocol.model_dump_json(indent=2)

# Deserialize
L9Protocol.model_validate(data_dict)
L9Protocol.model_validate_json(json_string)

# JSON Schema
L9Protocol.model_json_schema()
```

---

## Development

```bash
poetry add <package>              # add a dependency
poetry add --group dev <package>  # add a dev dependency
poetry run python3 <script>       # run within the env
poetry shell                      # activate the env
```


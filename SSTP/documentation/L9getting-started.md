# Getting started with L9 — the HCPanel example

HCPanel is the reference application for L9.  It runs a joint clinical
debate between 10 AI specialists — five physicians and five
pharmacologists — who debate a patient's symptoms, drug interaction
risk, and treatment options.  No single agent knows the answer; the
answer emerges from the structured debate.

The application uses every part of the L9 protocol stack: team process,
taskwork, CIP pairwise grounding, and SIEP group convergence.  Reading
it is the fastest way to understand what L9 does in practice.

---

## How to run HCPanel

**Prerequisites**

- Python 3.11+
- Install the repo as a package (from the repo root):

```bash
pip install -e .
```

- Optional: create a `.env` file in `SSTP/examples/hcpanel/` for real
  LLM backends (see *LLM backends* below).  Without it, the simulated
  backend runs out of the box.

**Quickstart — simulated LLM, one patient**

```bash
python -m SSTP.examples.hcpanel.main \
    --sessions 1 \
    --llm-backend simulated \
    --fresh-memory
```

Output is a JSON document on stdout:

```
{
  "application": "HCPanel — Joint Clinical Debate",
  "sessions": 1,
  "episodes": [
    {
      "episode_id": "urn:ioc:hcpanel:episode:PT001:...",
      "patient_id": "PT001",
      "symptom_conclusion": "drug_interaction",
      "resolution_label": "accept",
      "convergence_metrics": { "gar": 0.82, "scr": 0.0, "mpc": 0.74 },
      ...
    }
  ]
}
```

**CLI flags**

| Flag | Default | Description |
|------|---------|-------------|
| `-n` / `--sessions` | `1` | Number of patient cases to run |
| `--seed` | `42` | Random seed for patient selection |
| `--llm-backend` | `simulated` | `simulated`, `azure`, or `anthropic` |
| `--model` | `gpt-5` | Model name passed to the LLM backend |
| `--fresh-memory` | off | Start with an empty memory store in a temp file |
| `--patients-file` | `patients.json` | Path to the patient data file |
| `--memory-store-file` | `memory.json` | Path to the persistent memory store |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

**LLM backends**

| Backend | Env vars required | Notes |
|---------|-------------------|-------|
| `simulated` | none | Deterministic stubs; no API calls |
| `azure` | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY` | Falls back to simulated if env is missing |
| `anthropic` | `LITELLM_API_KEY`, `LITELLM_BASE_URL` | Uses LiteLLM proxy; model set via `LITELLM_HAIKU_MODEL` |

**Patients file**

`patients.json` holds the patient cohort.  Each record has:

```json
{
  "patient_id": "PT001",
  "locality": "San Francisco",
  "symptoms": ["fatigue", "muscle weakness", "elevated liver enzymes"],
  "health_history": ["type-2 diabetes", "hypertension"],
  "current_medications": ["metformin", "lisinopril", "atorvastatin"],
  "medication_allergies": ["penicillin"],
  "insurance_plan": "BlueCross-PPO",
  "chat_history": ["I have been feeling very tired for the past two weeks"],
  "calendar_slots_day_offsets": [2, 5, 7]
}
```

Add or edit patients here to change the input to the debate.

**Memory persistence**

Without `--fresh-memory` the system reads and writes `memory.json` on
each run.  Convergence outcomes from previous sessions become priors in
subsequent ones — this is the TeamEpistemicMemory accumulating knowledge
across episodes.  Use `--fresh-memory` to start clean, e.g., for
reproducible test runs.

---

## What happens during a session

Each call to `run_session()` runs three LangGraph nodes in sequence.

```
START → orchestrate → joint_panel → coordination → END
```

**1. orchestrate**

Each specialist independently assesses the patient before any peer
interaction.  These are raw priors — no agent has heard anyone else's
position yet.  The positions are held in memory and injected into the
taskwork episode in the next node.

**2. joint_panel**

This is where the L9 protocol runs.  Three episode phases execute in
sequence:

- **Team process episode** — the diagnostics controller sends a
  `kind=intent` to all 10 specialists naming the task goal and
  assigning each specialist their role.  Each specialist acknowledges.
  The controller closes with `kind=commit:converged`.  This creates the
  shared team structure that the rest of the session operates under.

- **Taskwork episode** — the controller opens a new episode with the
  patient complaint as the second `type=utterance` payload part.  Each
  specialist declares their independent prior — the belief they formed
  in the orchestrate node — as a `kind=exchange` with a `type=cip`
  payload carrying prior, posterior, and supporting evidence.  The
  controller closes with `kind=commit:converged`.

- **SIEP panel** — the controller proposes the most likely diagnosis as
  a starting concept and opens a `kind=intent` to the full panel.
  Specialists respond with counter-proposals, evidence, and uncertainty.
  Each exchange passes through CIP contingency checking: if a response
  does not genuinely engage the prior turn's argument, a
  `kind=contingency` is raised and a repair branch opens.  The panel
  iterates until convergence metrics (GAR, SCR, MPC) meet the threshold
  or the step budget is exhausted.  The controller closes with
  `kind=commit:converged` and emits a `kind=knowledge` to
  TeamEpistemicMemory.

**3. coordination**

The convergence results are written to TeamEpistemicMemory.  Each
specialist's peer interaction outcomes are promoted to their own
PeerInteractionStore.  The `kind=knowledge` messages written during the
SIEP panel are the canonical record of what the team learned.

---

## Software architecture

```
main.py
│
├── HCPanelSystem
│   ├── LLM backend (SimulatedHealthcareLLMClient / Azure / Anthropic)
│   ├── HCPanelMemory              — persistent memory store (memory.json)
│   ├── TeamEpistemicMemoryAgent   — cross-episode knowledge (hcpanel_team_epistemic.json)
│   ├── TheoryOfMindEngine         — ToM predictions and utterance assessment
│   ├── HCPanelAgentBus            — L9 wire-format message log
│   ├── PhysicianController        — owns 5 physician SpecialistAgents
│   ├── PharmacologyController     — owns 5 pharmacology SpecialistAgents
│   └── DebateOrchestrator         — runs the three-phase protocol
│
└── LangGraph (3 nodes)
    ├── orchestrate   → specialists form priors
    ├── joint_panel   → L9 team process + taskwork + SIEP panel
    └── coordination  → promote knowledge to stores
```

### Key modules

| Module | Responsibility |
|--------|---------------|
| `main.py` | Entry point, CLI, LangGraph wiring, session lifecycle |
| `agent_bus.py` | `HCPanelAgentBus` — emits and stores L9 wire-format messages; helpers `emit_team_process_*`, `emit_taskwork_*`, `get_cip_repair`, `get_part` |
| `panel_bus.py` | `PanelBus` + `StarNegotiation` — SIEP star negotiation with inline CIP contingency; emits SIEP `intent`, `exchange`, `contingency`, `commit:converged` |
| `orchestration.py` | `DebateOrchestrator.run_joint_panel()` — sequences team process → taskwork → SIEP; builds role assignments and prior injections |
| `specialists.py` | `PhysicianController`, `PharmacologyController`, `SpecialistAgent` — 10 specialists with per-session `AgentBeliefStore`, `PeerInteractionStore`, `TaskworkStore`, `AgentEpistemicStore` |
| `domain.py` | Data classes: `PatientProfile`, `ClinicalDebateOutcome`, `SpecialistOpinion`, `DebateGraphState` |
| `memory.py` | `HCPanelMemory` — wraps convergence store, likelihood store, semantic rule store, episode archive |
| `tem.py` | `TeamEpistemicMemoryAgent` — cross-episode prior; updated after each `commit:converged` |
| `llm_backends.py` | `SimulatedHealthcareLLMClient`, `AzureOpenAIHealthcareLLMClient`, `AnthropicHealthcareLLMClient` |
| `interaction_semantics.py` | Concept URI helpers |

### The L9 message API

> **Note — Python wheel not yet in use.**  The functions described here
> import directly from the `SSTP.*` source tree inside this repository.
> A packaged Python wheel for the SSTP language bindings is planned; once
> it is available, import paths and some call signatures are expected to
> change.  Treat the API described below as current-state, not as a stable
> public interface.

Every L9 wire message is produced by one of two module-level builder
functions.  They are the only place in the codebase that constructs the
L9 envelope.

**`build_l9_header`** — CIP messages  
(`SSTP/subprotocol/cip/src/l9.py`)

Takes a semantic `event_type` string and maps it to the L9 `kind`:

| `event_type` | `kind` |
|---|---|
| `peer_turn`, `initial_prior`, `outcome_reported` | `exchange` |
| `repair_required`, `epistemic_clarification`, `process_challenged` | `contingency` |
| `repair_applied`, `decision_emitted`, `process_accepted`, `episode_persisted` | `commit` |
| `rule_update` | `knowledge` |

The function also resolves the default `epistemic` block (speech act +
epistemic state) from the event type, fills `message.id` with a fresh
UUIDv4, and assembles the full header dict.

```python
from SSTP.subprotocol.cip.src.l9 import build_l9_header

header = build_l9_header(
    use_case="healthcare",
    event_type="peer_turn",           # → kind=exchange, subprotocol=CIP
    sender="physician-cardiology",
    receiver="diagnostics-controller",
    timestamp_ms=int(time.time() * 1000),
    episode_id="urn:ioc:hcpanel:episode:PT001:...",
    topic="urn:concept:healthcare:drug_interaction",
    parent_ids=[prior_message_id],
    payload_parts=[
        {"type": "utterance", "location": "inline", "content": "...",
         "rationale": "...", "thought_summary": "..."},
        {"type": "cip",       "location": "inline", "content": cip_payload},
    ],
)
```

**`build_snp_l9_header`** — SIEP messages  
(`SSTP/subprotocol/siep/src/l9.py`)

Takes an `operation` from `NegotiationOperation` and maps it to `kind`:

| `operation` | `kind` |
|---|---|
| `propose`, `consider_proposal`, `evaluate_proposal`, `review_proposal`, `negotiate`, `counter_proposal` | `exchange` |
| `accept`, `reject` | `commit` |

`kind_override` bypasses the mapping — used by PanelBus to force
`intent`, `commit:converged`, and `knowledge` kinds that have no
corresponding operation.

```python
from SSTP.subprotocol.siep.src.l9 import build_snp_l9_header, NegotiationOperation

header = build_snp_l9_header(
    operation=NegotiationOperation.PROPOSE,
    use_case="healthcare",
    sender="diagnostics-controller",
    receiver=None,
    timestamp_ms=int(time.time() * 1000),
    proposal_id="intent-abc123",
    episode_id=panel_episode_id,
    kind_override="intent",           # force kind=intent
    recipients=all_panel_ids,
    payload_parts=[intent_utt_part],
)
```

**Common base — `L9HeaderBuilder`**  
(`SSTP/l9_base.py`)

Both builders subclass `L9HeaderBuilder` and call its `build()` method.
`build()` assembles the header dict from the resolved kind, participants
list, message linkage, context block, policy, attributes, and payload.
To add a new sub-protocol, subclass `L9HeaderBuilder`, implement
`kind_for_event_type` and `schema_id_for`, and expose a module-level
convenience function.

**How hcpanel uses the API**

Application code never calls the builders directly.  The call chain is:

```
DebateOrchestrator
  └── HCPanelAgentBus.emit_team_process_open()
  │     └── build_l9_header(event_type="process_proposed", kind_override="intent", ...)
  └── HCPanelAgentBus.emit_cip_exchange()
  │     └── build_l9_header(event_type="peer_turn", ...)
  └── HCPanelAgentBus.emit_team_process_close()
        └── build_l9_header(event_type="process_accepted", kind_override="commit:converged", ...)

StarNegotiation.run()
  └── build_snp_l9_header(kind_override="intent",         ...)   # panel:open
  └── build_snp_l9_header(operation=PROPOSE,              ...)   # specialist exchange
  └── build_snp_l9_header(kind_override="contingency",    ...)   # CIP repair branch
  └── build_snp_l9_header(kind_override="commit:converged", ...) # panel close
  └── build_snp_l9_header(kind_override="knowledge",      ...)   # knowledge emit
```

Every emitted header goes into `HCPanelAgentBus.messages`, the
append-only list that becomes `ie_trace` in the output.

### The bus layer

The bus layer is the only component that emits L9 wire-format messages.
It is intentionally thin — a log and a set of emit helpers.

**`HCPanelAgentBus`** (`agent_bus.py`) handles the CIP side:

- `emit_team_process_open(...)` / `emit_team_process_close(...)` —
  team process episode intent and commit
- `emit_taskwork_open(...)` / `emit_episode_close(...)` —
  taskwork episode intent and commit; `patient_complaint` dict is
  embedded as a second `type=utterance` payload part in the intent
- `emit_cip_exchange(...)` — individual specialist prior declaration
  with `type=cip` payload
- `emit_contingency(...)` / `get_cip_repair(...)` —
  raise and resolve a CIP contingency branch
- `messages` — the append-only list of all emitted L9 headers

**`PanelBus` + `StarNegotiation`** (`panel_bus.py`) handle the SIEP
side.  `StarNegotiation.run()` drives one full panel:

1. Emits SIEP `intent` (panel:open) with controller's concept and
   participants.
2. For each specialist: collects their position, runs CIP contingency
   assessment via `TheoryOfMindEngine`, emits SIEP `exchange`.  If
   contingency is triggered, opens a repair branch, emits `contingency`
   + repair, then `commit:resolved`.
3. After all specialists respond, computes convergence metrics (GAR,
   SCR, MPC), emits `commit:converged` with `type=snp-convergence`
   payload and a `kind=knowledge` message.

> **Note — AgentBus and PanelBus are placeholders.**  Both buses are
> application-internal scaffolding: they exist to emit L9 messages and
> accumulate them in a list.  They will be replaced once the A2A /
> Cognition Fabric integration is in place.  In the target architecture
> (described in [L9A2A.md](./L9A2A.md)), CIP runs inside a `CIP-CE`
> cognitive engine and SIEP inside a `SIEP-CE` cognitive engine, both
> exposed as agent-visible skills on the Cognition Fabric.  The
> `HCPanelAgentBus` and `PanelBus`/`StarNegotiation` classes are the
> seam that will be replaced by `A2AAgentBus`; everything above them
> (orchestration, specialists, stores) stays unchanged.

### Specialist agents

Each `SpecialistAgent` is stateless between sessions.  At the start of
every `run_session()` call all per-agent stores are replaced with fresh
instances:

```python
agent.belief_store    = AgentBeliefStore()        # Bayesian prior/posterior per concept
agent.peer_store      = PeerInteractionStore()    # outcomes of CIP exchanges with each peer
agent.taskwork_store  = TaskworkStore()           # taskwork phase records
agent.epistemic_store = AgentEpistemicStore(id)   # epistemic state log
```

Cross-session knowledge lives only in `TeamEpistemicMemory`, which is
shared and persisted.

### Memory and knowledge stores

| Store | Scope | Persists | What it holds |
|-------|-------|----------|---------------|
| `AgentBeliefStore` | per agent, per session | no | Bayesian prior/posterior per concept |
| `PeerInteractionStore` | per agent, per session | no | CIP exchange outcomes per peer |
| `TaskworkStore` | per agent, per session | no | taskwork phase records |
| `AgentEpistemicStore` | per agent, per session | no | epistemic state log |
| `HCPanelMemory` | system, cross-session | yes (`memory.json`) | convergence store, likelihood store, episode archive |
| `TeamEpistemicMemoryAgent` | system, cross-session | yes (`hcpanel_team_epistemic.json`) | concept posteriors written after each `commit:converged` |

### LangGraph integration

`HCPanelSystem._build_graph()` compiles a three-node `StateGraph` over
`DebateGraphState`.  The state dict carries:

- `patient` — the `PatientProfile` for this session
- `episode_id` — the top-level episode URN
- `physician_positions` / `pharmacy_positions` — priors from orchestrate
- `outcome` — the `ClinicalDebateOutcome` from joint_panel
- `agent_messages` — the full L9 message log (accumulated across nodes)
- `snp_trace` — the SIEP-specific trace
- `orchestration_log` — structured log strings

Each node receives the full state dict and returns a partial update.
The bus's `messages` list is sliced by offset so each node only appends
its own messages into `agent_messages`.

### Theory of Mind engine

`TheoryOfMindEngine` (`tomcore/cognition.py`) is called on every CIP
exchange during the SIEP panel.  It does two things:

- **`assess_utterance`** — checks whether the specialist's response is
  genuinely contingent on the prior turn's argument (CIP grounding
  check).  Returns a contingency score; if below threshold, a
  `contingency` message is raised.
- **`predict_peer_response`** — given agent A's current belief state and
  prior interaction history with agent B, predicts what B will say
  before B speaks.  The prediction is recorded in `PeerInteractionStore`
  and compared to B's actual response; the accuracy drives the ToM
  model update.

---

## Output format

Each session produces a `HealthcareEpisode` serialized to JSON.  The
top-level fields of each episode object are:

| Field | Type | Description |
|-------|------|-------------|
| `episode_id` | string | URN for this session |
| `patient_id` | string | Patient identifier |
| `symptom_conclusion` | string | Winning concept label |
| `drug_interaction_risk` | string | Risk assessment |
| `proposed_drug_changes` | list | Medication change proposals |
| `joint_recommendation` | string | Team's joint recommendation |
| `resolution_label` | string | `accept`, `reject`, or `deferred` |
| `convergence_metrics` | object | `gar`, `scr`, `mpc` |
| `specialist_opinions` | list | Per-specialist position records |
| `ie_trace` | list | Full L9 wire-format message log |
| `snp_trace` | list | SIEP panel message log |
| `llm_trace` | list | Raw LLM prompt/response pairs |
| `debate_log` | list | Human-readable debate summary |
| `orchestration_log` | list | Structured internal log |

The `ie_trace` is the canonical L9 record.  Every message in it is a
full L9 envelope with header + typed payload parts.

---

## Where to go next

- [L9.md](./L9.md) — why L9 exists and what it is
- [L9teamtasks.md](./L9teamtasks.md) — annotated wire examples for
  every message kind used in hcpanel
- [L9header.md](./L9header.md) — full field reference for the L9 header
- [L9lifecycle.md](./L9lifecycle.md) — episode grammar and lifecycle
- [L9A2A.md](./L9A2A.md) — the A2A target architecture (replacing
  AgentBus/PanelBus with CIP-CE and SIEP-CE cognitive engines)
- [CIP.md](../subprotocol/cip/docs/CIP.md) — Contingency Interaction Protocol
- [SIEP.md](../subprotocol/siep/docs/SIEP.md) — Semantic Interaction Exchange Protocol

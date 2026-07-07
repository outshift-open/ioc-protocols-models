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

- **Team process episode** — the controller calls
  `ctrl_l9.open_team_process(group, agreement, task_goal=...)` which emits
  `kind=intent`, then `tp_ep.run()` which drives the proposal/acceptance
  loop for all 10 specialists internally (including ToM assessment per
  exchange).  The controller closes with `tp_ep.close(...)` which emits
  `kind=commit:converged`.  The orchestrator only sees
  `open_team_process → run → close`.

- **Taskwork episode** — the controller builds a list of
  `TaskworkParticipant` structs (agent id, utterance, posterior,
  belief store) from the priors formed in the orchestrate node, then
  calls `ctrl_l9.open_taskwork(group, participants, ...)`.  Inside
  `tw_ep.run()`, for each participant: the belief store is seeded if
  empty, a `kind=exchange` is emitted, ToM assessment is called, and if
  the assessment flags ambiguity or a grounding failure a
  `kind=contingency` repair cycle is driven — all internal to the
  package.  The controller closes with `tw_ep.close(...)`.  The
  orchestrator only sees `open_taskwork → run → close`.

- **SIEP panel** — the controller opens a `TaskEpisode` via
  `ctrl_l9.open_task(...)` and calls `task_ep.run(...)`.  Inside
  `run()`, `StarNegotiation` emits a `kind=intent` to the full panel,
  then in each round proposes the controller's position to each
  specialist.  Specialists respond with accepts or counter-proposals.
  Each response passes through CIP contingency checking: if a response
  does not genuinely engage the prior turn's argument, a
  `kind=contingency` is raised and a repair branch opens.  The panel
  iterates until convergence metrics (GAR, SCR, MPC) meet the threshold
  or the step budget is exhausted.  `run()` closes the episode with
  `kind=commit:converged` and records a `SemanticRule`.  The
  orchestrator then calls `task_ep.announce(...)` which emits
  `kind=knowledge` to TeamEpistemicMemory.  The orchestrator only sees
  `open_task → run → announce`.

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

The full API reference — `L9`, `Episode`, `build_l9_header`,
`build_snp_l9_header`, and all prior helpers — is in
[L9api.md](./L9api.md).

**How hcpanel uses the API**

Application code (orchestrator and specialists) uses the `L9` / `Episode`
application API.  Bus implementations (`agent_bus.py`, `panel_bus.py`) call the
wire-level builders.  Application agents never call the builders directly.

```
DebateOrchestrator
  ├── Episode A — team process
  │     L9.open_team_process(concept_id, group, agreement, ...) → TeamProcessEpisode
  │       └── HCPanelAgentBus._emit_intent(...)
  │     tp_ep.run()
  │       └── emit_process_proposal / emit_process_acceptance per specialist
  │           + ToM assess per exchange (internal)
  │     tp_ep.close(rationale=...) → commit_message_id
  │
  ├── Episode B — taskwork
  │     L9.open_taskwork(concept_id, group, participants, ...) → TaskworkEpisode
  │       └── HCPanelAgentBus._emit_intent(...)
  │     tw_ep.run()
  │       └── per participant: belief seed → Episode.say() → ToM assess → repair if needed
  │           (all internal)
  │     tw_ep.close(rationale=...) → commit_message_id
  │
  └── Episode C — SIEP panel
        L9.open_task(concept_id, group, convergence_store=..., ...) → TaskEpisode
        task_ep.run(controller_position=..., specialist_positions=...) → None
          └── PanelBus + StarNegotiation (internal to package)
                └── build_snp_l9_header(kind_override="intent", ...)
                └── build_snp_l9_header(operation=PROPOSE, ...)     # per specialist
                └── build_snp_l9_header(kind_override="contingency", ...)   # if needed
                └── build_snp_l9_header(kind_override="commit:converged", ...)
                └── build_snp_l9_header(kind_override="knowledge", ...)
        task_ep.announce(concept_id=..., posterior=..., gar=..., scr=...)
```

Every emitted header goes into `HCPanelAgentBus.messages`, the
append-only list that becomes `ie_trace` in the output.

**Opening an episode**

```python
from SSTP.l9 import L9, Episode

ctrl_l9 = L9(bus, agent_id="diagnostics-controller",
              belief_store=belief_store,
              team_epistemic_agent=team_epistemic)

episode = ctrl_l9.open(
    concept_id="urn:concept:healthcare:drug_interaction",
    group=all_specialist_ids,
    episode_id=episode_urn,
    rationale="Opening team process to establish roles and task scope.",
    thought_summary="Patient shows signs of statin myopathy; need specialist alignment.",
)
# episode.prior is the blended prior from agent + team stores
```

**Specialist joining and saying**

```python
# On the specialist side — using on_intent decorator
specialist_l9 = L9(bus, agent_id=specialist_id)

@specialist_l9.on_intent
def handle(ep: Episode) -> None:
    ep.say(
        "I assess drug interaction risk as high based on atorvastatin + metformin.",
        posterior=0.82,
        evidence=["elevated_liver_enzymes", "statin_dose"],
        rationale="Elevated liver enzymes in a patient on dual statin/biguanide therapy.",
        thought_summary="Prior exchange established high-risk pattern; I'm confirming.",
    )

# Or directly when the episode_id is already known:
agent_ep = Episode(
    bus=bus,
    agent_id=specialist_id,
    concept_id="urn:concept:healthcare:drug_interaction",
    episode_id=episode_urn,
    initiator=False,
)
msg_id = agent_ep.say(utterance, posterior=0.74, rationale="...", thought_summary="...")
```

**Handling a contingency**

```python
# Listener detects grounding failure:
contingency_id = episode.dispute(
    message_id=prior_msg_id,
    reason="grounding_failure",
)

# After the offending agent re-asserts, the listener closes the branch:
episode.resolve(contingency_id)
```

**Closing and announcing**

```python
# All group members have called done() or say(final=True)
commit_id = episode.close(
    rationale="All specialists have declared their priors; MPC above threshold.",
    thought_summary="Team process closed; proceeding to taskwork.",
)

# Optionally write to TeamEpistemicMemory:
episode.announce(
    concept_id="urn:concept:healthcare:drug_interaction",
    posterior=episode.mpc,
    gar=episode.gar,
    scr=episode.scr,
)
```

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
- [L9api.md](./L9api.md) — full API reference for `L9`, `Episode`, and the wire-level builders
- [L9teamtasks.md](./L9teamtasks.md) — annotated wire examples for
  every message kind used in hcpanel
- [L9header.md](./L9header.md) — full field reference for the L9 header
- [L9lifecycle.md](./L9lifecycle.md) — episode grammar and lifecycle
- [L9A2A.md](./L9A2A.md) — the A2A target architecture (replacing
  AgentBus/PanelBus with CIP-CE and SIEP-CE cognitive engines)
- [CIP.md](../subprotocol/cip/docs/CIP.md) — Contingency Interaction Protocol
- [SIEP.md](../subprotocol/siep/docs/SIEP.md) — Semantic Interaction Exchange Protocol

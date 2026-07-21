# Dead Letter

Content from the source L9.md that does not belong in the core L9 header/episode/knowledge specification (L9.md), the CIP sub-protocol (CIP.md), or the SIEP sub-protocol (SIEP.md). Items here are either cross-cutting concerns, Layer-8 process API material, or topics that need their own home.

---

## Layer 8: Team Process and Taskwork API

This section covers `sstp/process/` — the adaptation layer between application agents and the L9 Episode / AgentBus APIs. It belongs to a Layer 8 specification, not to the L9 wire protocol.

### Episode taxonomy

| Episode type | Method | concept_id | Phase after |
|---|---|---|---|
| Session open | `TaskSession.open_session()` | subject (e.g. patient id) | — |
| TP-1 | `TeamCoordinator.form_team()` | `concept:role_assignment` | TRANSITION (gate closed) |
| TP-2 | `TeamCoordinator.align_mental_model()` | `concept:shared_mental_model` | ACTION (gate open) |
| TP-R | `TeamCoordinator.reenter()` | trigger-dependent | ACTION (gate re-opened) |
| TW-1 | `TaskSession.assess()` | any clinical concept_id | ACTION (unchanged) |
| TW-2 | `TaskSession.negotiate()` | any clinical concept_id | ACTION (unchanged) |
| Session close | `TaskSession.close_session()` | subject | — |

### Team process concept_id vocabulary

| Constant | Value |
|---|---|
| `CONCEPT_ROLE_ASSIGNMENT` | `concept:role_assignment` |
| `CONCEPT_TEAM_GOAL` | `concept:team_goal` |
| `CONCEPT_SHARED_MENTAL_MODEL` | `concept:shared_mental_model` |
| `CONCEPT_CURRENT_PHASE` | `concept:current_phase` |

### Re-entry trigger → concept_id mapping

| `ReentryTrigger` | concept_id(s) negotiated |
|---|---|
| `REPAIR_FAILED` | `concept:shared_mental_model` |
| `ALIGNMENT_DIVERGED` | `concept:shared_mental_model` |
| `SCR_HIGH` | `concept:role_assignment` |
| `NEW_AGENT` | `concept:role_assignment` |
| `TASK_SHIFT` | `concept:current_phase` + `concept:shared_mental_model` |

### PhaseGate rules

`PhaseGate` is called by `TaskSession` before every turn. Returns `False` silently on suppression.

| Phase | Taskwork turn (coordination=False) | Coordination turn (coordination=True) |
|---|---|---|
| TRANSITION | suppressed | permitted |
| ACTION | permitted if agent owns concept | suppressed |

Sub-concept URI matching: if the clinical concept_id is a sub-concept URI, the gate checks whether the leaf segment of any assigned role appears in the URI.

### Protocol ownership — intent and commit

| Emitter | Kind produced |
|---|---|
| `L9.open()` | `intent` |
| `Episode.close()` | `commit:converged` or `commit:rejected` |
| `Episode.resolve()` | `commit:resolved` |
| `TaskSession.open_session()` | `intent` (outer session frame) |
| `TaskSession.close_session()` | `commit:converged` or `commit:rejected` (outer session frame) |

Application code must never call `AgentBus.emit_peer_turn(kind_override="intent")` or with `kind_override="commit:*"` directly — this raises `ProtocolViolation`.

### Full patient episode example

```python
from sstp.base.episode import L9
from sstp.process import (
    AgentCapability, PhaseGate, TeamCoordinator, TeamProcessStore, TaskSession,
)

bus = HealthcareAgentBus(run_id="run-1", conversation_id="run-1")
store = TeamProcessStore()
gate  = PhaseGate(store)
l9    = L9(bus, agent_id="coordinator")
coord = TeamCoordinator(l9, panel_bus_factory, store, gate)
sess  = TaskSession(bus, gate, coord, store)

sess.open_session(subject="pt-001", episode_id="urn:ioc:healthcare:session:pt-001")

capabilities = [
    AgentCapability("diagnostics-controller", ["concept:drug_interaction"], 1.0),
    AgentCapability("pharmacy-controller",    ["concept:drug_interaction"], 0.9),
    AgentCapability("insurance-controller",   ["concept:coverage_decision"], 1.0),
]
coord.form_team("discharge recommendation for patient P-001", capabilities)

coord.align_mental_model({
    "diagnostics-controller": {"concept:drug_interaction": 0.55},
    "pharmacy-controller":    {"concept:drug_interaction": 0.60},
    "insurance-controller":   {"concept:coverage_decision": 0.50},
})

sess.assess(
    agent_id="doctor-01",
    concept_id="concept:drug_interaction",
    posterior=0.82,
    utterance="warfarin + ibuprofen: high interaction risk",
    scope=["concept:drug_interaction",
           "urn:concept:healthcare:drug_interaction:warfarin+ibuprofen"],
    receiver="diagnostics-controller",
)

result = sess.negotiate(
    concept_id="concept:drug_interaction",
    participants=["doctor-01", "doctor-02", "doctor-03"],
    panel_bus=diag_panel_bus,
)

coord.reenter(ReentryTrigger.TASK_SHIFT, context={"reason": "ICU escalation"})

sess.close_session(subject="pt-001", accepted=True, episode_id="urn:ioc:healthcare:session:pt-001")
```

---

## AgentBus emit_* API (implementation-level)

The following `AgentBus` methods are internal implementation details exposed as a reference. Application code uses the `L9` / `Episode` API instead. These belong in an implementation guide, not the wire protocol spec.

### Constructor

```python
AgentBus(
    run_id: str,
    conversation_id: str,
    use_case: str = "default",
    sensitivity: str = "internal",
    taskwork_store: Any = None,
)
```

### emit_task_assignment

Assigns a task from an orchestrator to an agent. Emits `kind=exchange, subprotocol=CIP, epistemic.state=team_process`.

```python
req = bus.emit_task_assignment(
    sender="orchestrator",
    receiver="diagnostics",
    utterance="assess patient symptoms and medication history",
    episode_id="urn:ioc:healthcare:state:shared_dialogue",
)
```

### emit_taskwork_result

Returns an agent's independent taskwork result. Emits `kind=exchange, subprotocol=CIP, epistemic.state=taskwork`.

```python
bus.emit_taskwork_result(
    sender="diagnostics",
    receiver="orchestrator",
    utterance="likely_cause=drug_interaction confidence=0.96",
    concept_id="concept:drug_interaction",
    posterior=0.96,
    parent_id=task_id,
)
```

### emit_episode_open / emit_episode_close

Open and close a coordination episode. Emits `kind=intent` and `kind=commit` respectively.

```python
open_msg = bus.emit_episode_open(
    coordinator="orchestrator",
    subject="pt-1008",
    episode_id="urn:ioc:healthcare:state:shared_dialogue",
)

bus.emit_episode_close(
    coordinator="orchestrator",
    subject="pt-1008",
    accepted=True,
    episode_id=episode_urn,
)
```

### emit_knowledge_rule

Announces a converged knowledge rule. Emits `kind=knowledge`.

```python
bus.emit_knowledge_rule(
    coordinator="orchestrator",
    concept_id="urn:concept:healthcare:drug_interaction",
    posterior=0.93,
    gar=1.0,
    scr=0.0,
    provenance_weight=1.0,
    episode_id=episode_urn,
)
```

### emit_process_proposal / emit_process_acceptance / emit_process_challenge

Team process negotiation methods. Emit `kind=exchange|commit|contingency` with `epistemic.state=team_process`.

### receive_peer_turn

Processes an incoming CIP message. Runs the contingency check; auto-emits repair_required if it fails. Returns `None` if grounded, or the repair-request header.

### EpistemicStore.apply_message

Passively ingests any L9 message into the epistemic replica without running the contingency check.

### Message routing pattern

The current implementation uses a shared in-memory bus. In a deployed system with a pub-sub transport (Kafka, MQTT), the pattern would be: emit → publish to topic → deliver to subscribers → receiver calls `receive_peer_turn()`.

---

## Teamwork and taskwork — background

The following paragraphs from the original L9.md describe the organisational-psychology motivation behind the team/taskwork distinction. This is background framing, not protocol specification. It belongs in a separate position paper or introduction document.

> There is a distinction of teamwork and taskwork — and their role in team performance. These are findings argued in organizational psychology and cognitive science, cited in the NeurIPS 2026 paper *Multi-agent systems have some more to learn from human multi-agent systems*. That work argues that MAS failures stem not from individual agent incapability but from the absence of collective cognitive scaffolds: goal-setting, role clarity, conflict resolution, transactive memory, shared mental models — that allow small groups to function as a coherent unit rather than a collection of independent actors.
>
> The full operationalization of the team science constructs — dynamic role renegotiation, backup behavior, team mental model maintenance across episodes — remains future work.

---

## Theory of Mind — standalone description

The following ToM description was embedded in the original L9.md in the convergence protocols section. ToM is a cross-cutting concern shared by CIP (drift detection, SCR raw material) and SIEP (convergence efficiency). It does not belong in either sub-protocol spec alone. It should live in a dedicated ToM specification document.

> ToM maintains a model of each other agent, pair-wise — what that other agent believes, how strongly it believes a concept, and how it tends to respond to arguments. It is built up turn by turn from the CIP trace and captures each concept individually.
>
> Before a turn, ToM tells the speaker what agent B is likely to say when presented with a given argument. After a turn, ToM updates its model of B based on what B actually said — whether B's posterior moved, whether B engaged the argument or deflected, and how far B drifted from its initial prior. Drift detection: if B's posterior is moving but B's supporting evidence is empty or weak, ToM flags that B may be complying socially rather than being genuinely persuaded. This is the raw material for SCR.
>
> CIP produces the raw evidence — verified grounding events, belief deltas, revision causes. ToM reads that evidence turn by turn and builds predictive models of each agent (representational state). SCR and GAR are derived from those models. SIEP uses SCR and GAR to weight the convergence.

---

## Fields present in ioc-cfn-protocols-models L9.md but absent from ioc-protocols-models L9.md

The following header fields and behaviours appeared in the newer `ioc-cfn-protocols-models` version of L9.md but are not yet reflected in the canonical `ioc-protocols-models` spec. They should be reviewed and promoted to L9.md or the relevant sub-protocol doc.

- `participants` replacing `actor` — structured `ParticipantSet` with `actors` array and `groups` field.
- `topic` as a top-level header field replacing `epistemic.concept_id`.
- `epistemic.message_act` replacing `epistemic.speech_act`.
- `subkind=resolved` and `subkind=ready` values.
- `payload[type=utterance]` carrying `rationale` and `thought_summary` fields.
- `grounding.repair_reason=initial_prior` distinguishing opening turns from actual failures.
- The `knowledge` post-commit write announcement schema with `provenance_weight` and `revision_cause`.
- TeamEpistemicMemory lookup and write episode flows.
- The `L9` / `Episode` Python API (replaces the raw `AgentBus.emit_*` API).

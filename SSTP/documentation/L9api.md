# L9 API reference

> **Note — Python wheel not yet in use.**  The classes and functions described
> here import directly from the `SSTP.*` source tree inside this repository.
> A packaged Python wheel for the SSTP language bindings is planned; once it
> is available, import paths and some call signatures are expected to change.
> Treat the API described below as current-state, not as a stable public
> interface.

L9 exposes two API layers:

- **Application API** (`SSTP.l9`) — `L9`, `Episode`, `PanelEpisode`, and prior helpers.
  Application agents use this layer exclusively.  They never call builders or
  bus methods directly.
- **Wire-level builders** (`SSTP.subprotocol.cip.src.l9`,
  `SSTP.subprotocol.siep.src.l9`) — `build_l9_header` and
  `build_snp_l9_header`.  Used by bus implementations (`agent_bus.py`,
  `panel_bus.py`).  Application agents do not call these directly.

---

## Application API — `SSTP.l9`

```python
from SSTP.l9 import L9, Episode, PanelEpisode, AgentPrior, TeamPrior, blend_prior
```

### Prior helpers

#### `AgentPrior`

```python
@dataclass
class AgentPrior:
    confidence: float           # agent's own confidence [0, 1]
    episode_count: int = 0      # number of prior episodes for this concept
    specialty_match: float = 1.0  # specialty relevance weight
```

Agent-local prior belief for a concept.  Set from `AgentBeliefStore` at episode
open.

#### `TeamPrior`

```python
@dataclass
class TeamPrior:
    confidence: float            # team-level confidence [0, 1]
    provenance_weight: float     # quality weight from the commit that created it
    episode_count: int           # episodes this team prior aggregates
    source_episode: Optional[str] = None
```

Team-level prior from `TeamEpistemicMemory`.  Carried on every `intent` message
so all participants start from the same shared baseline.

#### `blend_prior(agent, team) → float`

```python
def blend_prior(
    agent: Optional[AgentPrior],
    team: Optional[TeamPrior],
) -> float
```

Blends agent and team priors into a single scalar prior for episode open.

Weight formula:

```
w_team  = team.episode_count × team.provenance_weight
w_agent = agent.episode_count × agent.specialty_match
prior   = (w_agent × agent.confidence + w_team × team.confidence) / (w_agent + w_team)
```

Falls back to `0.5` when both are absent.

---

### `L9`

```python
class L9:
    def __init__(
        self,
        bus: AgentBus,
        agent_id: str,
        belief_store: Any = None,
        team_epistemic_agent: Any = None,
    ) -> None
```

Entry point for application agents.  Wraps the bus and belief stores.
Application agents call `open`, `join`, or register `on_intent` handlers.

#### `L9.open`

```python
def open(
    self,
    concept_id: str,
    group: List[str],
    episode_id: Optional[str] = None,
    team_process: Optional[Dict[str, Any]] = None,
    rationale: str = "",
    thought_summary: str = "",
) -> Episode
```

Open a new coordination episode as initiator.

1. Looks up team prior from `TeamEpistemicMemory`.
2. Reads agent prior from `belief_store`.
3. Blends prior using `blend_prior`.
4. Emits `kind=intent` with team prior (and optional `team_process`) in payload.
5. Returns `Episode` with `.prior` set.

`team_process` is forwarded as `payload[type=team_process]` on the intent.  
`rationale` and `thought_summary` go into `payload[type=utterance]`.

If `episode_id` is omitted, one is generated as:

```
urn:ioc:{use_case}:episode:{concept_id}:{timestamp_ms}
```

#### `L9.join`

```python
def join(self, intent_envelope: Dict[str, Any]) -> Episode
```

Join an existing episode as a participant.  Reads `team_prior` and `concept_id`
from the intent payload, blends with the agent's own prior, and returns an
`Episode` with `.prior` set.

The caller should then call `episode.say(...)` or `episode.done(...)`.

#### `L9.on_intent`

```python
def on_intent(self, handler: Callable) -> Callable
```

Decorator: register a handler called when an intent arrives.  The handler
receives an `Episode` already joined (via `join`).  It should call
`episode.say(...)` or `episode.done(...)` and return.

```python
@l9.on_intent
def handle(episode: Episode) -> None:
    episode.say("My assessment.", posterior=0.71, final=True)
```

#### `L9.dispatch_intent`

```python
def dispatch_intent(self, envelope: Dict[str, Any]) -> None
```

Dispatch an incoming intent envelope to the registered handler.  Calls `join`
internally then invokes the handler.  No-op if no handler is registered.

#### `L9.open_panel`

```python
def open_panel(
    self,
    concept_id: str,
    group: List[str],
    episode_id: Optional[str] = None,
    convergence_store: Any = None,
    semantic_rule_store: Any = None,
    peer_interaction_store: Any = None,
    belief_store: Any = None,
    tom_engine: Any = None,
    repair_fn: Any = None,
    panel_name: str = "panel",
) -> PanelEpisode
```

Open a SIEP panel episode as initiator.  Returns a `PanelEpisode`.  The
`kind=intent` for the panel is emitted inside `PanelEpisode.run()` by
`StarNegotiation`, which owns the SIEP wire format for the panel open.

The SIEP-specific stores are passed through to `PanelBus` inside `run()`.
Application code never constructs `PanelBus` or `StarNegotiation` directly.

```python
panel_ep = ctrl_l9.open_panel(
    concept_id="urn:concept:healthcare:drug_interaction",
    group=all_specialist_ids,
    convergence_store=memory.convergence_store,
    semantic_rule_store=memory.semantic_rule_store,
    peer_interaction_store=memory.peer_interaction_store,
    belief_store=belief_proxy,
    tom_engine=tom_engine,
    repair_fn=repair_fn,
    panel_name="hcpanel",
)
panel_ep.run(
    controller_position=controller_position,
    specialist_positions=all_positions,
    task_goal=task_goal,
    accept_threshold=0.1,
    max_rounds=2,
)
panel_ep.announce(
    concept_id=panel_ep.winning_position_key,
    posterior=panel_ep.mpc,
    gar=panel_ep.gar,
    scr=panel_ep.scr,
)
```

---

### `Episode`

```python
class Episode:
    def __init__(
        self,
        bus: AgentBus,
        agent_id: str,
        concept_id: str,
        episode_id: str,
        initiator: bool = False,
        group: Optional[List[str]] = None,
        prior: float = 0.5,
    ) -> None
```

Application-facing handle for a single L9 coordination episode.  Normally
returned by `L9.open` or `L9.join`; can also be constructed directly when the
`episode_id` is already known.

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `prior` | `float` | Blended prior at episode open/join.  Immutable. |
| `concept_id` | `str` | Concept this episode is about. |
| `episode_id` | `str` | URN scoping all messages in this cycle. |
| `mpc` | `Optional[float]` | Mean position confidence.  Available after `close()`. |
| `gar` | `Optional[float]` | Genuine agreement ratio.  Available after `close()`. |
| `scr` | `Optional[float]` | Social compliance ratio.  Available after `close()`. |

#### `Episode.say`

```python
def say(
    self,
    utterance: str,
    posterior: float,
    *,
    final: bool = False,
    evidence: Optional[List[str]] = None,
    addresses_evidence: Optional[List[str]] = None,
    parent_id: Optional[str] = None,
    rationale: str = "",
    thought_summary: str = "",
) -> str
```

Emit a substantive contribution.  Returns the new `message.id`.

- `final=False` → `kind=exchange`
- `final=True` → `kind=exchange`, `subkind=ready` — final argument and done signal combined

`rationale` and `thought_summary` land in `payload[type=utterance]`.  
`addresses_evidence` lists message ids whose evidence this response directly
engages (CIP grounding chain).

#### `Episode.done`

```python
def done(self, posterior: float) -> str
```

Emit a standalone done signal — `kind=commit:ready`, no content.  Use when the
agent has nothing more to say but has not yet signalled done.  Returns the new
message id.

#### `Episode.dispute`

```python
def dispute(self, message_id: str, reason: str) -> str
```

Raise a grounding problem — `kind=contingency`.  Suspends this agent's done
signal until `resolve` is called.  Returns the contingency message id.

`reason` values: `"grounding_failure"`, `"scope_mismatch"`,
`"ungroundable_novelty"`.

#### `Episode.resolve`

```python
def resolve(self, contingency_id: str) -> str
```

Close a contingency branch — `kind=commit:resolved`.  Must be called by the
same agent that called `dispute`.  Raises `ValueError` if the contingency id is
unknown.  Returns the commit message id.

#### `Episode.close`

```python
def close(
    self,
    *,
    rationale: str = "",
    thought_summary: str = "",
    summary: Optional[Dict[str, Any]] = None,
) -> str
```

Initiator closes the episode.  Only callable by the agent that called `L9.open`.

- Emits `kind=commit:converged` when `mpc >= 0.5`, otherwise `kind=commit:rejected`.
- Raises `RuntimeError` if open contingencies exist or not all group members
  have signalled done.
- After `close()`, `.mpc`, `.gar`, and `.scr` are available.

Returns the commit message id.

#### `Episode.announce`

```python
def announce(
    self,
    concept_id: str,
    posterior: float,
    gar: float,
    scr: float,
) -> str
```

Write a knowledge announcement after `close()`.  Emits `kind=knowledge`
addressed to team-epistemic-memory, parented on the commit message id.  Raises
`RuntimeError` if called before `close()`.

`provenance_weight` is computed as `(1 − scr) × gar`.  Returns the knowledge
message id.

#### `Episode._record_done`

```python
def _record_done(self, agent_id: str, posterior: float) -> None
```

Called externally when a done signal arrives from a group member.  Used by the
orchestrator to track per-agent posteriors for the MPC calculation at `close()`.
Specialists do not call this; the orchestrator does.

---

### `PanelEpisode`

Subclass of `Episode` returned by `L9.open_panel`.  Extends the base class with
`run()` and panel-specific read-only properties.  `say()`, `done()`, and
`close()` are disabled — the negotiation loop manages all exchanges internally.

`announce()` is inherited from `Episode` unchanged.

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `prior` | `float` | Blended prior at panel open. |
| `concept_id` | `str` | Concept this panel is about. |
| `episode_id` | `str` | URN scoping all panel messages. |
| `mpc` | `Optional[float]` | Mean position confidence.  Available after `run()`. |
| `gar` | `Optional[float]` | Genuine agreement ratio.  Available after `run()`. |
| `scr` | `Optional[float]` | Social compliance ratio.  Available after `run()`. |
| `winning_position` | `Any` | Winning position dict.  Available after `run()`. |
| `winning_position_key` | `str` | Concept key string from winning position.  Available after `run()`. |
| `resolution_label` | `Optional[str]` | `"consensus"`, `"majority"`, `"timeout_majority"`, etc.  Available after `run()`. |
| `snp_trace` | `List[Dict]` | SIEP messages from this panel.  Available after `run()`. |

#### `PanelEpisode.run`

```python
def run(
    self,
    controller_position: Dict[str, Any],
    specialist_positions: Dict[str, Any],
    task_goal: str = "",
    accept_threshold: float = 0.1,
    max_rounds: int = 2,
) -> None
```

Execute the full SIEP star negotiation loop inside the package boundary.

Internally constructs `PanelBus` and `StarNegotiation`, runs the negotiation
(including ToM predictions, bilateral grounding verification, CIP repair
branches, Bayesian belief revision, GAR/SCR/MPC computation, `SemanticRule`
recording, and `commit:converged` + `kind=knowledge` emit), and stores the
results on the episode.

After `run()` returns, all properties are set and `announce()` can be called.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `controller_position` | `Dict` | — | Controller's opening position with `likely_cause`, `confidence`, `supporting_evidence`. |
| `specialist_positions` | `Dict[str, Dict]` | — | Per-specialist position dicts keyed by agent id. |
| `task_goal` | `str` | `""` | Task goal string passed to ToM utterance assessment. |
| `accept_threshold` | `float` | `0.1` | Confidence gap below which a specialist accepts the controller's position. |
| `max_rounds` | `int` | `2` | Maximum negotiation rounds before timeout resolution. |

---

## Wire-level builders

Application agents do not call these directly.  Bus implementations
(`agent_bus.py`, `panel_bus.py`) call them to produce L9 wire-format headers.

### `L9HeaderBuilder` (`SSTP/l9_base.py`)

Abstract base for all L9 protocol header builders.  Subclasses override
`kind_for_event_type` and `schema_id_for`.  The base `build()` handles all
envelope construction.

```python
def build(
    self,
    *,
    use_case: str,
    event_type: str,
    sender: str,
    receiver: str | None,
    timestamp_ms: int,
    sensitivity: str = "internal",
    propagation: str = "restricted",
    utterance: str = "",
    parent_ids: Iterable[str] | None = None,
    episode_id: str | None = None,
    provenance_sources: Iterable[str] | None = None,
    provenance_expiry: str | None = None,
    message_id: str | None = None,
    ontology_ref: str | None = None,
    subprotocol: str | None = None,
    epistemic: Dict[str, Any] | None = None,
    topic: str | None = None,
    kind_override: str | None = None,
    subkind: str | None = None,
    sequence_number: int | None = None,
    payload_parts: List[Dict[str, Any]] | None = None,
    role: str | None = None,
    recipients: List[str] | None = None,
) -> Dict[str, Any]
```

`kind_override` bypasses the event_type→kind mapping.  Use it to force `intent`,
`commit:converged`, or `knowledge` kinds that have no corresponding event type.

To add a new sub-protocol: subclass `L9HeaderBuilder`, implement
`kind_for_event_type` and `schema_id_for`, and expose a module-level
convenience function.

---

### `build_l9_header` — CIP (`SSTP/subprotocol/cip/src/l9.py`)

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
        {"type": "cip", "location": "inline", "content": cip_payload},
    ],
)
```

**`event_type` → `kind` mapping**

| `event_type` | `kind` |
|---|---|
| `turn_ingested`, `peer_turn`, `prior_query`, `initial_prior`, `outcome_reported`, `process_proposed` | `exchange` |
| `repair_required`, `epistemic_clarification`, `process_challenged` | `contingency` |
| `repair_applied`, `decision_emitted`, `episode_persisted`, `conversation_terminated`, `process_accepted` | `commit` |
| `rule_update` | `knowledge` |

`kind_override` bypasses the table — used to force `intent`, `commit:converged`,
or `knowledge`.

The function also fills `message.id` with a fresh UUIDv4 and resolves the
default `epistemic` block from the event type.

**Parameters** (keyword-only)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `use_case` | `str` | — | Domain label (e.g. `"healthcare"`).  Normalised to snake_case. |
| `event_type` | `str` | — | Semantic event type (see table above). |
| `sender` | `str` | — | Agent id of the sender. |
| `receiver` | `str \| None` | — | Primary recipient, or `None` for multicast. |
| `timestamp_ms` | `int` | — | Unix timestamp in milliseconds. |
| `episode_id` | `str \| None` | `None` | URN scoping this cycle.  Auto-generated if absent. |
| `topic` | `str \| None` | `None` | Concept URI for `context.topic`. |
| `parent_ids` | `Iterable[str] \| None` | `None` | Causal parent message ids. |
| `payload_parts` | `List[Dict] \| None` | `None` | Typed payload parts list. |
| `kind_override` | `str \| None` | `None` | Override the event_type→kind mapping. |
| `recipients` | `List[str] \| None` | `None` | Full recipient list (multicast).  Supersedes `receiver`. |
| `sensitivity` | `str` | `"internal"` | Policy sensitivity label. |
| `propagation` | `str` | `"restricted"` | Policy propagation label. |
| `subprotocol` | `str \| None` | `"CIP"` | Subprotocol label in the header. |
| `epistemic` | `Dict \| None` | `None` | Override the default epistemic block. |
| `message_id` | `str \| None` | `None` | Override the auto-generated UUIDv4. |

---

### `build_snp_l9_header` — SIEP (`SSTP/subprotocol/siep/src/l9.py`)

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

**`operation` → `kind` mapping**

| `operation` | `kind` |
|---|---|
| `propose`, `consider_proposal`, `evaluate_proposal`, `review_proposal`, `negotiate`, `counter_proposal` | `exchange` |
| `accept`, `reject` | `commit` |

`kind_override` bypasses the mapping — used to force `intent`,
`commit:converged`, and `knowledge` kinds that have no corresponding operation.

**`NegotiationOperation` constants**

```python
NegotiationOperation.PROPOSE
NegotiationOperation.CONSIDER_PROPOSAL
NegotiationOperation.EVALUATE_PROPOSAL
NegotiationOperation.REVIEW_PROPOSAL
NegotiationOperation.COUNTER_PROPOSAL
NegotiationOperation.NEGOTIATE
NegotiationOperation.ACCEPT
NegotiationOperation.REJECT
```

**Parameters** (keyword-only)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | `str \| NegotiationOperation` | — | SNP operation (see table above). |
| `use_case` | `str` | — | Domain label. |
| `sender` | `str` | — | Agent id of the sender. |
| `receiver` | `str \| None` | — | Primary recipient, or `None` for multicast. |
| `timestamp_ms` | `int` | — | Unix timestamp in milliseconds. |
| `proposal_id` | `str` | — | Unique id for this proposal or panel. |
| `episode_id` | `str \| None` | `None` | URN scoping this cycle. |
| `topic` | `str \| None` | `None` | Concept URI. |
| `parent_ids` | `Iterable[str] \| None` | `None` | Causal parent message ids. |
| `payload_parts` | `List[Dict] \| None` | `None` | Typed payload parts list. |
| `kind_override` | `str \| None` | `None` | Override the operation→kind mapping. |
| `recipients` | `List[str] \| None` | `None` | Full recipient list (multicast). |
| `subprotocol` | `str \| None` | `"SIEP"` | Subprotocol label in the header. |
| `epistemic` | `Dict \| None` | `None` | Override the default epistemic block. |

---

### `build_snp_payload` — SIEP payload builder

```python
from SSTP.subprotocol.siep.src.l9 import build_snp_payload, NegotiationStatus

snp_part = build_snp_payload(
    operation=NegotiationOperation.PROPOSE,
    proposal_id="prop-123",
    content="drug_interaction_risk:high",
    status=NegotiationStatus.PENDING,
    posterior=0.82,
    supporting_evidence=["elevated_liver_enzymes", "statin_interaction"],
    reasoning_summary="Patient on atorvastatin + metformin; liver enzyme elevation consistent with statin myopathy.",
)
```

Returns a `type=siep` payload dict for inclusion in `payload_parts`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `operation` | `str \| NegotiationOperation` | yes | SNP operation. |
| `proposal_id` | `str` | yes | Unique proposal id. |
| `content` | `str` | yes | Proposal content string. |
| `status` | `str \| NegotiationStatus` | yes | `pending`, `reviewed`, `incorporated`, or `resolved`. |
| `posterior` | `float \| None` | no | Agent's posterior belief [0, 1]. |
| `supporting_evidence` | `List[str] \| None` | no | Evidence backing the proposal. |
| `against_evidence` | `List[str] \| None` | no | Contrary evidence. |
| `addresses_evidence` | `List[str] \| None` | no | Evidence from prior turn this directly engages. |
| `reasoning_summary` | `str \| None` | no | One-sentence reasoning chain. |
| `deferred_to` | `str \| None` | no | Agent id if deferring position. |
| `proposal_payload` | `Dict \| None` | no | Additional structured payload fields. |

---

## Where to go next

- [L9getting-started.md](./L9getting-started.md) — how to run HCPanel and usage patterns
- [L9header.md](./L9header.md) — full field reference for the L9 envelope
- [L9lifecycle.md](./L9lifecycle.md) — episode grammar and kind vocabulary
- [L9teamtasks.md](./L9teamtasks.md) — annotated wire examples for every message kind
- [CIP.md](../subprotocol/cip/docs/CIP.md) — Contingency Interaction Protocol
- [SIEP.md](../subprotocol/siep/docs/SIEP.md) — Semantic Interaction Exchange Protocol

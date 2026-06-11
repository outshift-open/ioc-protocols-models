# CF A2A Architecture — IE and SNP as Cognitive Engines

**Status:** Initial architecture draft  
**Date:** 2026-06-11

---

## Overview

IE (Interaction Engine) and SNP (Semantic Negotiation Protocol) run as **Cognitive Engines (CEs)** deployed on the Cognition Fabric (CF). Agents are **skill-based plugins** — they never instantiate buses, engines, or negotiation rounds directly. All IoC messaging, group communication, unicast, and multicast logic lives inside the CF.

The CF talks to CEs and to agents using the same A2A protocol, carrying L9 messages in both directions. The CF itself is a **dumb forwarder** — it holds only the routing topology needed to fan out `receiver=None` messages and resolve agent addresses.

---

## Component Roles

### Agent (skill plugin)

An agent is an LLM or rule-based process that exposes capabilities via skill plugins. It has no direct dependency on `AgentBus`, `PanelBus`, or any internal protocol object. It interacts with the rest of the system exclusively by calling methods on two skills:

- **`IESkill`** — `open_episode`, `say`, `done`, `dispute`, `resolve`, `close_episode`, `announce`
- **`SNPSkill`** — `open_convergence`, `say`, `done`, `close_convergence`

Both skills are thin wrappers over `sstp.l9.episode.L9` + `Episode` — the top-level application API. The agent never touches anything below that surface.

### `L9` / `Episode` (top-level API, unchanged)

`sstp.l9.episode.L9` and `Episode` are the canonical application API. Their method signatures do not change. The only thing that changes is what `AgentBus` they are constructed with.

### `A2AAgentBus`

A subclass of `AgentBus` whose emit methods POST to the CF instead of acting in-process. `L9` and `Episode` are unaware of the network — they call the same `_emit_intent`, `emit_grounding_turn`, `_emit_ready`, etc. methods as before, which now serialize the L9 envelope and send it to CF.

```
IESkill / SNPSkill
  └── L9 + Episode           (sstp.l9.episode — unchanged)
        └── A2AAgentBus      (only seam that changes)
              └── POST /cf/a2a/tasks/send
```

### CF (Cognition Fabric — A2A proxy)

The CF receives A2A tasks from agents and from CEs. For each inbound task it:

1. Inspects the L9 `kind` and `episode_id` to decide which CE to call.
2. Forwards the message to the appropriate CE via A2A.
3. Receives a `CEResponse` from the CE with `(action, messages, targets)`.
4. Forwards the returned messages to the listed agent endpoints.

The CF holds no epistemic state. It holds only a routing directory and an episode→group cache (see [CF State](#cf-state)).

### IE-CE (Interaction Engine Cognitive Engine)

Stateful per `episode_id`. Runs the real `AgentBus` + `IEEngine` internally. Receives every `exchange`, `contingency`, and `commit` kind message for a given episode. Returns annotated messages plus any protocol-generated messages (contingency notices, commit signals) with routing targets. Owns:

- `AgentBus._seq_counters` — Lamport clock per agent
- `AgentBus._current_phase` — taskwork | grounding | team_process
- `AgentBus.messages` — ordered L9 message log
- `Episode._done_agents` — done signal set and posterior values
- `Episode._open_contingencies` — blocks `close()`
- Phase gate (`PhaseGate`) — rejects taskwork messages when gate is closed

### SNP-CE (Semantic Negotiation Protocol Cognitive Engine)

Stateful per `session_id`. Runs `PanelBus` (star or ring topology) internally. Receives `convergence` kind messages. Returns `commit:converged` or `commit:failed` with panel member targets. Owns:

- `PanelBus._negotiation_id`, `_common_ground_ids`, `_pending_arg_outcomes`
- `NegotiationStore`, `RoundStore`, `ProposalStore`
- `TeamProcessStore` — role assignments, gate open/closed
- Cross-episode belief and peer interaction stores

---

## Message Flow

### IE episode (exchange path)

```
Agent A                CF                IE-CE              Agent B
   |                    |                   |                   |
   |-- say() ---------> |                   |                   |
   |  [exchange L9]     |-- A2A: exchange ->|                   |
   |                    |                   |-- process turn    |
   |                    |  CEResponse:      |   grounding check |
   |                    |<- fwd,[msg],[B]   |                   |
   |                    |-- A2A: exchange ->|                   |
   |                    |   (annotated)     |                   |
```

### Contingency path

```
Agent B                CF                IE-CE              Agent A
   |                    |                   |                   |
   |-- dispute() -----> |                   |                   |
   |  [contingency L9]  |-- A2A: ctg ------>|                   |
   |                    |                   |-- opens ctg       |
   |                    |  CEResponse:      |                   |
   |                    |<- fwd,[ctg],[A]   |                   |
   |                    |-- A2A: ctg ------>|                   |
   |                    |   (to initiator)  |                   |
```

### SNP convergence

```
Agent (coord)          CF               SNP-CE         Panel members
   |                    |                   |                   |
   |-- open_conv() ---> |                   |                   |
   |  [intent L9]       |-- A2A: intent --->|                   |
   |                    |                   |-- run_round()     |
   |                    |  CEResponse:      |   (star/ring)     |
   |                    |<- fwd,[msgs],     |                   |
   |                    |   [all members]   |                   |
   |                    |-- A2A msgs ------>|                   |
   |                    |   (to each)       |                   |
```

---

## CF→CE Contract: `CEResponse`

Since the CF cannot inspect CE internal state, every CE response carries explicit routing instructions:

```python
@dataclass
class CEResponse:
    action: Literal["forward", "reject", "absorb"]
    messages: list[dict]    # L9 envelopes to route (may be empty)
    targets: list[str]      # agent_ids to deliver to (CF resolves → base_url)
    # "absorb" = CE handled it internally, nothing to route (e.g. internal state update)
    # "reject"  = protocol violation; messages contains error envelope to return to sender
```

Examples:

| Inbound | CE | Response |
|---|---|---|
| `exchange` (normal) | IE-CE | `forward, [annotated exchange], [group - sender]` |
| `close` with open contingency | IE-CE | `reject, [contingency envelope], [initiator]` |
| `commit:ready` (not all done yet) | IE-CE | `absorb, [], []` |
| `commit:ready` (all done) | IE-CE | `forward, [commit:accepted], [group]` |
| `convergence intent` | SNP-CE | `forward, [round messages], [panel members]` |
| SNP converges | SNP-CE | `forward, [commit:converged], [all members]` |

---

## CF State

The CF holds three things only:

```python
@dataclass
class AgentRecord:
    agent_id: str
    base_url: str       # A2A endpoint — sole routing truth
    skills: list[str]   # ["ie", "snp"] — used to validate task dispatch
    last_seen: float    # epoch ms

@dataclass
class EpisodeRoute:
    episode_id: str
    session_id: str
    group: list[str]    # learned from intent message; used to resolve receiver=None
    # deleted when CF sees commit:accepted or commit:rejected from CE

@dataclass
class CFStore:
    agents:   dict[str, AgentRecord]    # global; populated at agent registration
    episodes: dict[str, EpisodeRoute]   # ephemeral; one entry per open episode
```

`EpisodeRoute` exists solely because `episode.say()` and `episode.done()` emit with `receiver=None`. The CF needs `episode_id → group` to know who to fan out to. It learns the group from the `intent` message (which always carries it) and discards the entry on commit close.

**The CF holds no epistemic content:** no posteriors, no sequence counters, no contingency details, no negotiation rounds, no role assignments, no belief state. All of that lives in the CEs.

---

## Module Layout

```
ioc-cfn-protocols-models/
└── SSTP/language-bindings/Python/src/sstp/
    ├── l9/episode.py          (L9, Episode — top-level API, unchanged)
    └── ie/agent_bus.py        (AgentBus — subclassed by A2AAgentBus)

ioc-cfn-cognitive-agents/
├── cf/
│   ├── main.py                FastAPI A2A router service
│   ├── router.py              routing: reads L9 kind → dispatch to CE → forward
│   ├── store.py               CFStore, AgentRecord, EpisodeRoute
│   └── agent_registry.py      registration endpoint + lookup
├── ce/
│   ├── ie_ce/
│   │   ├── main.py            FastAPI A2A endpoint for IE-CE
│   │   └── handler.py         IECEHandler: AgentBus + IEEngine keyed by episode_id
│   └── snp_ce/
│       ├── main.py            FastAPI A2A endpoint for SNP-CE
│       └── handler.py         SNPCEHandler: PanelBus keyed by session_id
└── app/healthcare_ie_snp/
    ├── skills/
    │   ├── ie_skill.py        IESkill: open_episode/say/done/dispute/resolve/close/announce
    │   └── snp_skill.py       SNPSkill: open_convergence/say/done/close_convergence
    ├── a2a_bus.py             A2AAgentBus(AgentBus): emit methods POST to CF
    └── skills_loader.py       wires IESkill(L9(A2AAgentBus(...))) at agent startup
```

---

## Skill Plugin Interface

The LLM agent receives two injected skill objects. These are the complete agent-visible API — no buses, no headers, no protocol objects.

### IESkill

```python
class IESkill:
    def open_episode(self, concept_id: str, group: list[str]) -> str
        # returns episode_id

    def say(self, episode_id: str, utterance: str, posterior: float,
            final: bool = False) -> str
        # returns message_id

    def done(self, episode_id: str, posterior: float) -> str
        # returns message_id

    def dispute(self, episode_id: str, message_id: str, reason: str) -> str
        # returns contingency_id

    def resolve(self, episode_id: str, contingency_id: str) -> str
        # returns message_id

    def close_episode(self, episode_id: str) -> dict
        # returns {"mpc": float, "gar": float, "scr": float}

    def announce(self, episode_id: str, concept_id: str,
                 posterior: float, gar: float, scr: float) -> str
        # returns message_id
```

### SNPSkill

Same shape — wraps `L9` convergence episodes. `open_convergence` maps to `l9.open()` with `kind=convergence`; `close_convergence` calls `episode.close()` and returns MPC/GAR/SCR.

---

## What Changes vs. Current Codebase

| Current | Target |
|---|---|
| `AgentBus` shared in-process object | IE-CE owns one `AgentBus` per `episode_id` |
| `PanelNegotiationBus` shared in-process | SNP-CE owns one `PanelBus` per `session_id` |
| `Orchestrator` calls buses directly | Orchestrator replaced by skill method calls |
| `L9BaseSkillSupport` / `L9IESkillSupport` / `L9SNPSkillSupport` call internal bus methods | Deleted; replaced by `IESkill` / `SNPSkill` over `L9` + `Episode` |
| IoC group/unicast logic in orchestration layer | CF `router.py` — reads `EpisodeRoute.group`, fans out |
| Gate checked in `TaskSession` | IE-CE `handler.py` — CE rejects and returns `contingency` |

The `sstp.l9.episode.L9` and `Episode` classes are **not modified**. The `A2AAgentBus` swap is the only structural change to the protocol library side.

---

## Open Questions

1. **CE deployment boundary** — first cut co-deploys IE-CE and SNP-CE in the same process as CF (in-process calls, no HTTP hop). The A2A interface is defined but the network boundary is optional. Extract to separate services when independent scaling or fault isolation is needed.

2. **IE-CE state persistence** — `AgentBus.messages` is currently in-memory. Cross-episode peer interaction and belief stores already have a JSON persistence path (`_load_cross_episode_state`). IE-CE needs the same for `episode_id`-keyed state.

3. **Async A2A** — first cut is synchronous: CF awaits IE-CE before forwarding to peers. Switch to streaming (A2A SSE) when parallel agent turns are required.

4. **Agent card format** — agents register at CF startup via POST to `/cf/agents/register`. The `AgentRecord.skills` field should align with Google A2A agent card `capabilities` schema once that stabilises.

5. **Session scoping** — `EpisodeRoute` is keyed by `episode_id`. Multiple concurrent episodes in one session share one `AgentBus` instance in IE-CE (same `session_id`). The IE-CE handler must decide whether to share or isolate the bus per episode.

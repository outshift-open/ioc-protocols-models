# L9 message flows

This document describes what each L9 message kind does, what it
carries, and how messages group into episodes.

## The five message kinds

Every L9 message carries a `kind` field. There are exactly five
values, and each has a fixed role in the conversation regardless of
which sub-protocol is running underneath.

### `intent` — open an episode

An `intent` message calls the group together and declares what is
about to be discussed. It carries:

- **Participants** — the full list of agents who are expected to
  contribute, each identified by their `id` and `role`.
- **Topic** — the concept URI that names what is being debated
  (e.g. `urn:concept:healthcare:drug_interaction`). May be `null` for
  session-lifecycle opens where no specific concept has been named yet.
- **Utterance payload** — a short natural-language string that states
  the opening intent, such as `"panel:open concept=drug_interaction"`
  or `"taskwork:open subject=pt-1008"`.
- **Team prior** — optionally, a `team_prior` payload part that
  carries what the shared memory already knows about the topic, so
  every participant enters the episode with the same starting point.

Nothing is decided by an `intent`. It just opens the episode and sets
the shared `episode` URI that all subsequent messages in this cycle
will carry.

### `exchange` — work in progress

`exchange` messages are the substance of the episode. A proposal, a
counter-proposal, an independent prior declaration, a done signal —
all are exchanges. Each one carries:

- **Topic** — the same concept URI as the `intent`, or a sub-concept
  URI that narrows it down to a specific claim
  (e.g. `urn:concept:healthcare:drug_interaction:warfarin+ibuprofen`).
- **Epistemic block** — the sender's stance: the communicative act
  (`assertion`, `challenge`, or `compliance`), the phase of reasoning
  (`taskwork`, `grounding`, or `team_process`), the belief status
  (`asserted`, `deferred`, `revised`, …), and a numeric uncertainty
  score.
- **Utterance payload** — natural-language text of what the agent is
  saying, plus optional `rationale` (clinical or operational
  reasoning) and `thought_summary` (one sentence on what shaped this
  response). 
- **Sub-protocol payload** — alongside the utterance, a typed `cip` or
  `siep` part carries structured protocol data: evidence lists,
  posterior probabilities, proposal IDs, and addressing evidence from
  the prior turn. 
- **Parents** — the message IDs this exchange directly responds to,
  forming a traceable argument graph.

Exchanges are not binding. They are contributions to a debate, not
decisions.

A special subkind `exchange:ready` combines a final argument with a
done signal — the agent is saying "this is my last word and I am ready
to commit."

### `contingency` — grounding problem

A `contingency` message is raised by a listener who detected that the
prior exchange did not actually engage with the argument — the sender
talked past the topic, or was incoherent. The listener owns the repair
branch from this point until it closes. It carries:

- **Topic** — the same concept URI as the exchange it is flagging.
- **Utterance payload** — a terse description of the failure:
  `"repair_required: reason=grounding_failure, target=<message_id>"`.
- **Parents** — the ID of the problematic exchange that triggered the
  repair.

A `contingency` opens a child episode with a deeper episode URI (the
parent URI with a depth suffix, e.g. `:ie:1`). The offending agent
responds with a corrective `exchange` on that child episode URI. If
the repair is accepted, the listener closes the child with
`commit:resolved`.  The parent exchange then resumes.

### `commit` — close the episode

A `commit` message closes the episode and records how it ended. Only
the initiator (the agent who opened with `intent`) emits a commit. It
carries: 

- **Subkind** — required on commit: `converged` (genuine agreement
  reached), `rejected` (no agreement), `resolved` (a contingency
  branch was repaired), or `ready` (standalone done signal with no
  further content). 
- **Topic** — the concept URI the episode was about.
- **Utterance payload** — a summary of the outcome, e.g.
  `"SIEP convergence: drug_interaction → accept posterior=0.76 gar=1.0
  scr=0.0"`.
- **Convergence payload** — on `commit:converged`, a `snp-convergence`
  part that carries the final MPC (mean posterior confidence), GAR
  (genuine agreement ratio), and SCR (social compliance ratio) for the
  episode.
- **Parents** — the last exchange(s) the commit is closing over.

After a `commit`, the episode is over. No more exchanges on that episode URI.

### `knowledge` — write to shared memory

A `knowledge` message writes the outcome of a converged episode into
the team's shared memory. It is sent after `commit:converged` and is
not part of the debate — it is the side-effect of a successful
commit. It carries:

- **Topic** — the concept URI that was converged on.
- **Utterance payload** — a short rule-update string, e.g.
  `"rule_update:drug_interaction:posterior=0.76:gar=1.0:scr=0.0:provenance_weight=1.0"`.
- **Knowledge payload** — a `knowledge` part with the posterior, GAR, SCR,
  provenance weight, and revision cause.
- **Parents** — the ID of the `commit:converged` that produced this
  rule.

A `knowledge` message is a degenerate single-message episode — it acts
as `intent` and `commit:converged` in one. It is routed to all
participants plus the `team-epistemic-memory` agent. There is one
`knowledge` message per converged concept.

## How messages group into an episode

An episode is a bounded conversation about a single concept. All
messages in one episode share the same `message.episode` URI. The
structure is always:

```
intent  →  exchange+  →  commit:(converged|rejected)  →  knowledge*
```

1. **`intent`** opens the episode. It sets the episode URI, declares
   the concept being discussed, lists all participants, and optionally
   carries the team's existing prior on that concept.

2. One or more **`exchange`** messages carry the debate. Each exchange
   names the concept in its `topic` field, states the sender's
   epistemic stance, and carries both a natural-language utterance and
   structured sub-protocol data. If a grounding failure is detected, a
   **`contingency`** opens a repair sub-episode (see below). The
   episode continues after the repair closes.

3. When all participants have signalled they are done — either via
   `exchange:ready` (final argument + done) or `commit:ready`
   (standalone done signal) — the initiator emits a **`commit`**. The
   subkind says whether the episode converged or not.

4. If the commit was `converged`, the initiator immediately sends a
   **`knowledge`** message to shared memory. This records the agreed
   posterior, the quality metrics (GAR, SCR), and the provenance
   weight so future episodes can use this as a prior.

## Nested episodes

When a `contingency` is raised, the listener opens a child
episode. The child episode URI is the parent URI with a depth suffix:

```
parent:  urn:ioc:healthcare:panel:hcpanel:b549254b:…
child:   urn:ioc:healthcare:panel:hcpanel:b549254b:…:ie:1
```

The child follows its own `intent → exchange → commit:resolved`
sequence.  Once the child commits, the parent exchange resumes on the
original episode URI. The parent only commits after all child episodes
are closed.

Multiple repairs can nest — each adds one more suffix level (`:ie:2`,
etc.).  The maximum depth is configured per sub-protocol.

## What `topic` and `utterance` carry at each stage

| Kind | `context.topic` | `payload[type=utterance].content` |
|---|---|---|
| `intent` | concept URI, or `null` for session-open | `"panel:open concept=…"` / `"taskwork:open subject=…"` |
| `exchange` | concept URI or sub-concept URI | agent's position in natural language, with optional `rationale` and `thought_summary` |
| `contingency` | concept URI of the failed exchange | `"repair_required: reason=…, target=<message_id>"` |
| `commit:converged` | concept URI | convergence summary with posterior, GAR, SCR |
| `commit:rejected` | concept URI | rejection summary |
| `commit:resolved` | concept URI | `"repair_verified: <agent> re-anchored"` |
| `knowledge` | concept URI | rule-update string with posterior, GAR, SCR, provenance_weight |

---

## Typical episode call flow

The example below is taken from a real hcpanel run (pt-1008, 2026-06-24,
Anthropic backend). Three episodes run in sequence: team process, taskwork,
and the SIEP panel negotiation. Actors are shortened to their role names for
readability. Message numbers match the full trace.

### Episode 1 — Team process (`…:tp`)

The coordinator assigns roles to all ten specialists. Each proposal/acceptance
pair is a CIP exchange+commit:resolved mini-cycle. The episode closes with
`commit:converged` once all ten have acknowledged.

```
#  Actor                            Kind        Subkind    Utterance
─────────────────────────────────────────────────────────────────────────────
1  diagnostics-controller           intent       —         session:open subject=pt-1008
                                                           topic: null
                                                           participants: all 10 specialists

2  diagnostics-controller           exchange     —         process_proposal:coordinator=diagnostics-controller
                                                           topic: null  ·  state: team_process
3  physician-internal-medicine      commit       —         process_accepted:by=physician-internal-medicine

4  diagnostics-controller           exchange     —         process_proposal:coordinator=diagnostics-controller
5  physician-clinical-pharmacology  commit       —         process_accepted:by=physician-clinical-pharmacology

   … (repeat for each of the remaining 8 specialists) …

20 diagnostics-controller           exchange     —         process_proposal:coordinator=diagnostics-controller
21 pharmacologist-clinical-toxicology commit     —         process_accepted:by=pharmacologist-clinical-toxicology

22 diagnostics-controller           commit       converged grounding:converged status=aligned
                                                           topic: null  ·  state: team_process
```

---

### Episode 2 — Taskwork (`…:tw`)

The coordinator opens a taskwork episode. Each specialist emits one independent
prior assertion. For 9 of 10, the grounding judge fires a contingency because
the initial assertion does not contingently reference any prior message. The
specialist re-asserts; the coordinator closes the repair branch with
`commit:resolved`. After all specialists have been processed, the coordinator
closes the taskwork episode with `commit:converged`.

```
#  Actor                            Kind        Subkind    Utterance / topic
─────────────────────────────────────────────────────────────────────────────
23 diagnostics-controller           intent       —         taskwork:open subject=pt-1008
                                                           topic: null
                                                           participants: all 10 specialists

── specialist 1 ─────────────────────────────────────────────────────────────
24 physician-internal-medicine      exchange     —         "Warfarin-aspirin combination … cannot attribute
                                                           to drug interaction without INR, CBC …"
                                                           topic: urn:concept:healthcare:new_disease
                                                           state: taskwork  ·  belief: asserted  ·  conf: 0.68

25 diagnostics-controller           contingency  —         epistemic_clarification:ambiguous_taskwork:score=0.08
                                                           topic: urn:concept:healthcare:new_disease
                                                           parents: [#24]   ← child episode opens: …:ie:1

26 physician-internal-medicine      exchange     —         (re-assertion of #24)
                                                           topic: urn:concept:healthcare:new_disease
                                                           state: taskwork  ·  belief: asserted

27 diagnostics-controller           commit       resolved  contingency_resolved:urn:concept:healthcare:new_disease
                                                           parents: [#26]   ← child episode …:ie:1 closes

── specialist 2 ─────────────────────────────────────────────────────────────
28 physician-clinical-pharmacology  exchange     —         "Warfarin + aspirin … dual-pathway risk …"
                                                           topic: urn:concept:healthcare:drug_interaction
                                                           state: taskwork  ·  belief: asserted  ·  conf: 0.76

29 diagnostics-controller           contingency  —         epistemic_clarification:ambiguous_taskwork:score=0.12
30 physician-clinical-pharmacology  exchange     —         (re-assertion of #28)
31 diagnostics-controller           commit       resolved  contingency_resolved:…:drug_interaction

   … (repeat for specialists 3–10; pharmacologist-pharmacodynamics passes
      without contingency because the judge LLM call failed and grounding
      passes by default) …

61 diagnostics-controller           commit       converged session:close subject=pt-1008 accepted=True
                                                           topic: null  ·  state: team_process
```

---

### Episode 3 — SIEP panel negotiation (`…:panel:…`)

The coordinator opens a star-negotiation panel over the concept `new_disease`
(its opening position). Each specialist responds; 6 counter-propose
`drug_interaction`. The round produces a majority for `drug_interaction` and
the coordinator commits to it.

```
#  Actor                            Kind        Subkind    Utterance / topic
─────────────────────────────────────────────────────────────────────────────
62 diagnostics-controller           intent       —         panel:open concept=new_disease
                                                           topic: urn:concept:healthcare:new_disease
                                                           participants: coordinator + all 10 specialists
                                                           subprotocol: SIEP

── round 1: controller proposes, each specialist responds ───────────────────
63 diagnostics-controller           exchange     —         diagnostics-controller proposes new_disease
                                                           confidence=0.72
                                                           topic: urn:concept:healthcare:new_disease
                                                           state: taskwork  ·  belief: asserted

64 physician-internal-medicine      exchange     —         physician-internal-medicine accepts new_disease
                                                           confidence=0.68
                                                           state: team_process  ·  belief: asserted

65 diagnostics-controller           exchange     —         diagnostics-controller proposes new_disease
                                                           confidence=0.72

66 physician-clinical-pharmacology  exchange     —         physician-clinical-pharmacology counter-proposes
                                                           drug_interaction  confidence=0.76
                                                           state: team_process  ·  belief: asserted
                                                           addresses_evidence: [warfarin, aspirin, nausea]

   … (6 specialists counter-propose drug_interaction; 4 accept new_disease) …

── convergence ───────────────────────────────────────────────────────────────
82 diagnostics-controller           commit       converged SIEP convergence: drug_interaction → accept
                                                           posterior=0.7573  gar=1.0000  scr=0.0000
                                                           topic: urn:concept:healthcare:drug_interaction
                                                           payload: snp-convergence {mpc, gar, scr,
                                                                    participant_ids}

83 diagnostics-controller           knowledge    —         rule_update:drug_interaction
                                                           :posterior=0.7573:gar=1.0:scr=0.0
                                                           :provenance_weight=1.0
                                                           topic: urn:concept:healthcare:drug_interaction
                                                           parents: [#82]
                                                           recipients: all participants + team-epistemic-memory
```

---

### Full sequence summary

```
Team process episode (…:tp)
  intent                          — open, list all participants
  exchange × 10                   — coordinator proposes role to each specialist
  commit × 10                     — each specialist accepts
  commit:converged                — coordinator closes; all roles acknowledged

Taskwork episode (…:tw)
  intent                          — open, broadcast patient case
  for each specialist (×10):
    exchange                      — specialist declares independent prior
    [contingency                  — coordinator flags grounding failure
     exchange                     — specialist re-asserts
     commit:resolved]             — coordinator closes repair branch
  commit:converged                — coordinator closes; all priors on record

SIEP panel episode (…:panel:…)
  intent                          — open, name concept + all participants
  for each specialist (×10):
    exchange (propose)            — coordinator sends opening position
    exchange (accept/counter)     — specialist responds
  commit:converged                — coordinator commits to winning position
  knowledge                       — coordinator writes rule to shared memory
```

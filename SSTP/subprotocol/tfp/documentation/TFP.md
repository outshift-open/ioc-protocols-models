# Team Formation via Polling (TFP)

## Overview

TFP is an L9 sub-protocol for **assembling a team of agents around a task**. An
*initiator* agent holds a task that requires a set of skills it cannot satisfy
alone. Instead of statically wiring up collaborators, the initiator **polls** a
group of candidate agents, collects their advertised skills, selects a subset
that covers the task's mandatory skills, and **forms** a team.

TFP is the concrete realization of what `SSTP/documentation/L9.md` calls *team
process convergence* — the teamwork dimension that "leads to the definition of
groups that are carried in the L9 header." TFP converges on *who is on the team*
(team_process).

TFP rides the standard L9 envelope: the header carries
`subprotocol="TFP"`, and the TFP-specific content travels in the `payload`
(`type="json-schema"`). The header is the envelope; TFP is the content.

## Purpose

- Discover which peers hold task-relevant skills without prior knowledge of the roster.
- Let candidates self-advertise capability, availability, and fit.
- Select a team that **covers the mandatory skills** while maximizing fit.

Persisting the formed team (to memory or a database) is **out of scope** for TFP.
The protocol concludes at `commit/form`; what the caller does with the result —
including any storage — is its own concern.

## Discovery model: open-world vs. closed-world

TFP does **not** require the initiator to know the roster. There are two ways to
run the poll, with different guarantees:

| Model | How the group is found | What you can guarantee |
|---|---|---|
| **Open-world (broadcast)** | `poll_open` is published to a topic; any subscriber self-selects whether to bid. The initiator learns capabilities only from the bids that return. | "Best team **among agents that responded within the window**." Missing skills may just mean no capable agent answered in time. |
| **Registry-mediated** | The initiator first queries a skill registry/directory (e.g. the management plane) for candidates matching the required skills, then polls exactly those. | Completeness relative to the registry's knowledge. |

Key consequences of open-world discovery:

- **Self-selection** — candidates that hear the poll decide for themselves to
  `bid` or `decline`; the initiator never reads their capability profiles directly.
- **Bounded response window** — bids arriving after the window are dropped. The
  *best* candidate can be missed simply because it answered too late.
- **Silence is valid** — a subscriber may never respond; the initiator cannot
  distinguish "absent" from "uninterested."
- **Termination is timeout-driven**, and `unmet_skills` means "unmet by
  responders," not "unmet, period."

The reference example uses the open-world model: it broadcasts to a topic, an
irrelevant agent self-declines, a silent agent is never heard, and the strongest
threat-intel bidder is dropped for answering after the window.

## Position in L9

TFP addresses **team-process convergence** — *who is on the team* — and tags its
turns with `epistemic.state = team_process`. A typical conversation runs a TFP
episode *first* to establish the group; once the team is formed, the agreed task
is executed within that group.

## Message Flow

One TFP episode is a single L9 episode (`intent → exchange* → [contingency] → commit`)
scoped by a shared `message.episode` UUID.

### `episode` vs. `poll_id`

These are two correlation keys at two different layers; they are **not**
interchangeable:

| Key | Layer | Scope | Answers |
|-----|-------|-------|---------|
| `message.episode` | L9 **header** (envelope) | The whole interaction lifecycle (`intent … commit`). | "Which L9 conversation does this turn belong to?" — protocol-generic L9 envelope correlation. |
| `poll_id` | TFP **payload** | One call-for-bids *round*. | "Which specific poll am I bidding on / responding to?" — TFP-domain; keeps the payload self-contained without reading the transport header. |

In the simple case there is exactly **one poll per episode**, so the two are 1:1
and `poll_id` may look redundant. The distinction matters when an episode runs
**more than one poll**: e.g. a first poll fails to cover the mandatory skills and
the recruiter opens a `re_poll` with relaxed requirements or a wider
audience. That re-poll is a **new `poll_id` within the same `episode`**, so bids
and selections from each round stay unambiguously separable. `poll_id` also lets
external consumers (audit logs, dashboards) reference a poll without parsing L9
envelopes.

```
recruiter ── intent/poll_open ─────────────▶ topic (broadcast)   (task + required_skills)
candidateᵢ ── exchange/bid ─────────────────▶ recruiter           (offer: skill claims, availability)
candidateⱼ ── exchange/decline ─────────────▶ recruiter           (no relevant skills + reason)
recruiter ── exchange/select ───────────────▶ memberₖ             (selection: members, roles)
memberₖ   ── exchange/accept | reject ───────▶ recruiter          (confirms or declines membership + reason)
recruiter ── exchange/select ───────────────▶ fallbackₘ           (re-select after a reject)
recruiter ── exchange/re_poll ─────────▶ [group]             (re-poll if mandatory skills uncovered)
recruiter ── commit/form (converged|rejected)▶ [group]            (team finalized or failed)
```

When a selected candidate **rejects** (`operation=reject`), the recruiter drops
it from the candidate pool and re-selects a fallback for the now-uncovered skill,
repeating until every selected member has accepted or the pool is exhausted.

## Kind / subkind Values

Each turn carries three coordinated discriminators: the L9 `header.kind`
(lifecycle phase), the L9 `header.subkind` (the TFP phase tag), and the payload
`operation` (fine-grained semantics). The `subkind` is one of three canonical
values (`TFPSubkind`):

| `subkind` | Used on | Meaning |
|---|---|---|
| `team_form` | every non-terminal turn (`intent` poll, all `exchange` turns, re-poll) | The episode is in progress — a poll, bid/decline/select/accept/reject, or re-poll. The payload `operation` disambiguates. |
| `team_form_converged` | the closing `commit` | A team was formed (all mandatory skills covered). |
| `team_form_failure` | the closing `commit` | Formation failed (mandatory skills uncovered after re-poll). |

Full per-turn mapping:

| `kind` | `subkind` | `operation` | Meaning |
|---|---|---|---|
| `intent` | `team_form` | `poll_open` | Opens the episode; broadcasts the task and required skills. |
| `exchange` | `team_form` | `bid` | A candidate advertises its skills, availability, and self-assessed fit. |
| `exchange` | `team_form` | `decline` | A candidate opts out of the poll (no relevant skills / unavailable), with a `reason`. |
| `exchange` | `team_form` | `select` | The initiator selects a candidate and assigns a role (the "proposal to join"). |
| `exchange` | `team_form` | `accept` | A selected candidate confirms membership, with a `reason`. |
| `exchange` | `team_form` | `reject` | A selected candidate declines the proposal to join, with a `reason`; the recruiter re-selects a fallback. |
| `exchange` | `team_form` | `re_poll` | Re-poll for mandatory skills still uncovered after selection. |
| `commit` | `team_form_converged` / `team_form_failure` | `form_converged` / `form_failed` | Closes the episode: `team_form_converged` → team formed; `team_form_failure` → formation failed. |

## Payload Schema

The TFP payload (`payload[type=json-schema].data`) is defined by `TFPPayload`. The
JSON Schema in `spec/tfp_schema.json` is the source of truth; the Pydantic models
in `language_bindings/python/generated_models.py` are generated from it via
`language_bindings/python/generate.sh`.

| Field | Type | Set on | Description |
|---|---|---|---|
| `operation` | `TFPOperation` | all | The TFP operation for this turn (see table above). |
| `poll_id` | URN/UUID | all | Identifies one poll *round*. Links every turn of that round; a re-poll within the same `episode` gets a new `poll_id`. |
| `task` | `TaskSpec` | `poll_open` | `task_id`, `description`, optional `objective`, `deadline`. |
| `required_skills` | `[SkillRequirement]` | `poll_open` | Each: `skill`, `min_proficiency`, `weight`, `mandatory`. |
| `offer` | `CandidateOffer` | `bid` | `skills: [SkillClaim]`, `availability`, `fit_score`, `cost`. |
| `selection` | `TeamSelection` | `select`, `form` | `members`, `roles: [RoleAssignment]`, `coverage`, `unmet_skills`, `aggregate_fit`. |
| `reason` | `string` | `accept`, `reject`, `decline` | Why the candidate accepted/rejected the proposal to join (or declined the poll). Logged and feedable into reputation. |
| `reasoning_summary` | `string` | optional | Human-/LLM-readable rationale (e.g. the recruiter's selection logic). |

### Sub-structures

- **SkillRequirement** — `skill`, `min_proficiency [0..1]`, `weight ≥ 0`, `mandatory: bool`
- **SkillClaim** — `skill`, `proficiency [0..1]`
- **CandidateOffer** — `skills: [SkillClaim]`, `availability [0..1]?`, `fit_score [0..1]?`, `cost?`, `notes?`
- **RoleAssignment** — `agent_id`, `role`, `responsible_for: [skill]`
- **TeamSelection** — `members: [agent_id]`, `roles: [RoleAssignment]`, `coverage [0..1]`, `unmet_skills: [skill]`, `aggregate_fit [0..1]?`

## Selection Metrics

- **Coverage** — fraction of *mandatory* required skills satisfied by the selected
  team: `coverage = covered_mandatory / total_mandatory`. The episode commits
  `converged` iff `coverage == 1.0` (`unmet_skills` is empty).
- **Fit** — per-candidate weighted match of claims to requirements:
  `fit(c) = (Σ_r weightᵣ · proficiency(c,r) for r where proficiency ≥ min) / Σ_r weightᵣ`.
- **Aggregate fit** — mean fit across selected members; recorded on the formed team.

The reference selection in the example is a greedy mandatory-skill cover that
picks the highest-`proficiency` qualified candidate per skill. `availability` is
optional metadata on an offer and does not affect this reference selection.

## Well-formedness

- Exactly one `intent`/`poll_open` root and at most one `commit`/`form` leaf per episode.
- Every turn carries both `message.episode` (header) and `poll_id` (payload); all
  turns of one poll round share the same `poll_id`.
- A `select` for an agent must reference a candidate that submitted a `bid` **for the same `poll_id`**.
- Every re-poll  must be resolved before the `commit`. A re-poll opens a new `poll_id` under the same `episode`.
- `commit/form subkind=converged` ⇒ `selection.unmet_skills == []`.

## Schema Reference

- Schema (source of truth): [`../spec/tfp_schema.json`](../spec/tfp_schema.json)
- Generated models: [`../language_bindings/python/generated_models.py`](../language_bindings/python/generated_models.py)
- Runnable example: [`../examples/team_formation_example.py`](../examples/team_formation_example.py)
- Tests: [`../language_bindings/python/test_tfp.py`](../language_bindings/python/test_tfp.py)
- L9 envelope: [`../../../documentation/L9.md`](../../../documentation/L9.md)

## Running the Example

```bash
# from the repo root
poetry install
poetry run python SSTP/subprotocol/tfp/examples/team_formation_example.py
poetry run pytest SSTP/subprotocol/tfp/language_bindings/python/test_tfp.py -v
```

The example runs an **open-world** poll: the recruiter broadcasts to a topic
without knowing the roster, and each candidate agent owns its capability profile
privately. `log-analyst` accepts; `threat-intel` is selected but **rejects**
(reason: "already committed to incident-4470"), so the recruiter re-selects the
`intel-2` fallback, which accepts. The irrelevant `comms-bot` self-declines, the
silent `ghost-agent` is never heard, and `slow-intel` (the strongest threat-intel
bidder) is **dropped for answering after the response window**. Final team:
`log-analyst` + `intel-2` — the best team *among on-time responders*, not
necessarily the global best.

### L9 message dump

Besides the human-readable trace table, the example writes a structured JSON
dump of **every full L9 envelope** (header + payload) exchanged during the
episode. By default it lands at the single, stable, git-visible path
`SSTP/subprotocol/tfp/examples/dumps/team_formation_latest.json` (overwritten each
run); override the destination with `--out`:

```bash
poetry run python SSTP/subprotocol/tfp/examples/team_formation_example.py --out /tmp/tfp_run.json
```

The file is a metadata wrapper around the message array:

```json
{
  "schema": "ioc.tfp.message_dump.v1",
  "episode": "2f9a6c1e-7b3d-4a8e-9c10-6d5e4f3a2b1c",
  "poll_id": "urn:ioc:tfp:poll:d81903ec",
  "message_count": 14,
  "generated_at": "2026-06-18T20:01:27+00:00",
  "messages": [ { "header": { ... }, "payload": { ... } }, ... ]
}
```

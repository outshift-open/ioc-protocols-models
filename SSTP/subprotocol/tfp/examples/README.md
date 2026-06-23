# TFP — Runnable Example

A single, self-contained script — [`team_formation_example.py`](team_formation_example.py)
— that drives a full **Team Formation via Polling** episode end-to-end. Every
message it emits is a real L9 envelope (`ioc_l9.src.L9`) carrying a typed
`TFPPayload`, so the run doubles as a living conformance fixture for the schema.

## Running it

```bash
# from the repo root
poetry install

# success path: a team converges
poetry run python SSTP/subprotocol/tfp/examples/team_formation_example.py

# failure path: an unsatisfiable mandatory skill forces a re-poll + form_failed
poetry run python SSTP/subprotocol/tfp/examples/team_formation_example.py --fail

# the accompanying tests
poetry run pytest SSTP/subprotocol/tfp/language_bindings/python/test_tfp.py -v
```

## The premise

A security operations center catches a **suspicious-login alert** and needs an
incident-response team assembled *now*. A `recruiter` agent owns the task —

> **incident-4471**: "Triage a suspicious-login security incident across SIEM +
> endpoint data," objective *"Confirm or dismiss compromise within 30 minutes."*

— but it cannot do the work alone, and, crucially, **it does not know who is
available or what they can do.** There is no roster. Instead of statically wiring
up collaborators, the recruiter runs an **open-world poll**: it broadcasts the
call-for-bids to the topic `topic:tfp/polls/secops` and waits a bounded
**response window** (100 ms in the simulation) for whoever is listening to
self-select and bid. Each candidate owns its capability profile *privately* — the
recruiter only ever learns what an agent chooses to disclose in a bid.

The task declares three skills:

| Skill | Min proficiency | Weight | Mandatory |
|---|---|---|---|
| `skill:log_triage` | 0.70 | 2.0 | ✅ |
| `skill:threat_intel` | 0.60 | 1.5 | ✅ |
| `skill:host_forensics` | 0.60 | 1.0 | — (nice-to-have) |

### The cast

Seven agents are subscribed to the topic; none was hand-picked by the recruiter:

| Agent | Advertises | Latency | What happens |
|---|---|---|---|
| `log-analyst` | `log_triage` 0.92, `siem_query` 0.80 | 45 ms | Bids on time, selected, **accepts** → on the team. |
| `threat-intel` | `threat_intel` 0.88, `ioc_enrichment` 0.85 | 60 ms | Strongest on-time intel bidder; selected but **rejects** ("already committed to incident-4470; at capacity"), forcing a fallback. |
| `intel-2` | `threat_intel` 0.72 | 85 ms | The fallback the recruiter re-selects after `threat-intel` rejects; **accepts** → on the team. |
| `forensics` | `host_forensics` 0.90, `log_triage` 0.60 | 70 ms | Bids, but only covers the *optional* skill, so it is not needed for mandatory coverage. |
| `comms-bot` | `status_reporting` 0.95 | 30 ms | Hears the poll but has nothing relevant → **self-declines** with a reason. |
| `slow-intel` | `threat_intel` 0.99 | 250 ms | Would be the *best* threat-intel pick, but answers **after the window closes** → **dropped**. |
| `ghost-agent` | `translation` 0.90 | — | Subscribed but **silent**; the recruiter never hears from it. |

### How it resolves

The recruiter collects the on-time bids, then runs a greedy mandatory-skill
cover (highest qualifying proficiency per skill). It proposes membership,
handles the `threat-intel` rejection by re-selecting `intel-2`, and converges on:

> **Final team: `log-analyst` + `intel-2`** — full coverage of the mandatory
> skills (`log_triage`, `threat_intel`).

This is deliberately the *best team among agents that responded within the
window*, **not** the globally best team: `slow-intel` (proficiency 0.99) would
have been the superior threat-intel choice, but it answered too late and was
never considered. That is the defining property of open-world discovery —
`unmet_skills` means "unmet by responders," not "unmet, period."

The `--fail` flag adds a mandatory `skill:quantum_forensics` requirement that no
subscriber can satisfy. Coverage stays incomplete, the recruiter emits a
`re_poll`, and the episode commits as `form_failed` with the
`team_form_failure` subkind — exercising the failure branch of the protocol.

## L9 message dump

Besides the human-readable trace table printed to stdout, the example serializes
**every full L9 envelope** (complete header + payload) exchanged during the
episode to a JSON file, so the whole exchange can be replayed or inspected.

By default the dump is named by scenario so the two runs don't clobber each other:

- normal run → `dumps/team_formation_success.json`
- `--fail` run → `dumps/team_formation_failure.json`

Override the destination with `--out`:

```bash
poetry run python SSTP/subprotocol/tfp/examples/team_formation_example.py --out /tmp/tfp_run.json
```

The file is a small metadata wrapper around the message array:

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

- `episode` — the L9 header `message.episode` UUID shared by every turn.
- `poll_id` — the TFP payload poll-round id (`urn:ioc:tfp:poll:<hex>`).
- `messages` — each entry is one complete `{ "header": …, "payload": … }`
  envelope, in send order.

## See also

- Protocol spec: [`../documentation/TFP.md`](../documentation/TFP.md)
- Source models: [`../src/tfp_models.py`](../src/tfp_models.py)
- Tests: [`../language_bindings/python/test_tfp.py`](../language_bindings/python/test_tfp.py)

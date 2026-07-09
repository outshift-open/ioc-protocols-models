## Header

The L9 header is the envelope every message carries. Sub-protocol-specific content travels in the typed payload. The header covers: protocol identity, message identity and episode linkage, sender and recipients, the concept under discussion, and the sender's epistemic stance.

### L9 header fields

| L9 field | Values | Description |
|---|---|---|
| `protocol` | `"SSTP"` | Always SSTP. |
| `subprotocol` | `string` | Sub-protocol that produced this message. Required — always present. See [§subprotocol](#subprotocol) below. |
| `version` | `"0.0.6"` | Protocol schema version. Receivers reject or downgrade on unknown versions. |
| `kind` | `"intent" \| "exchange" \| "contingency" \| "commit" \| "knowledge"` | Role of this message in the episode flow. See [§kind](#kind) below. |
| `subkind` | `"converged" \| "rejected" \| "resolved" \| "ready" \| null` | Qualifies `commit` and `exchange`. See [§subkind](#subkind) below. |
| `participants` | `{"actors": [Actor+], "groups": object \| null}` | All actors in this message — sender, recipients, and observers. Exactly one actor must have `participant_type="sender"`. `groups` reserved for pub-sub group membership. |
| — Actor | `{"id": string, "role": string, "participant_type": ParticipantType, "attestation": string \| null}` | `id`: stable agent identity. `role`: functional role. `participant_type`: message-level send/receive/observe designation. `attestation`: signing authority or `null`. |
| — ParticipantType | `"sender" \| "recipient" \| "observer"` | `sender`: exactly one per message — the agent emitting this message. `recipient`: agents this message is addressed to. `observer`: agents receiving a copy (audit, logging). |
| `message` | `{"id": UUIDv4, "parents": [UUIDv4*], "episode": URN}` | **Required.** `id`: random UUID (UUIDv4), unique per message. `parents`: messages this message causally depends on. `episode`: URN scoping all messages in this coordination cycle. |
| `context \| null` | `{"topic": URI \| null, "epistemic": Epistemic \| null, "semantic": Semantic \| null}` | Semantic and epistemic context of the message. All three sub-fields are optional. |
| — `context.topic` | `URI \| null` | The concept this message is about. Absent on session-lifecycle messages with no concept. |
| — `context.epistemic` | `{"message_act": "assertion"\|"challenge"\|"compliance"\|null, "state": "taskwork"\|"grounding"\|"team_process"\|null, "belief_status": "asserted"\|"deferred"\|"challenged"\|"revised"\|"retracted"\|"unresolved"\|null, "uncertainty": float [0..1]}` | Sender's communicative act, epistemic phase, and belief stance. |
| — `context.semantic` | `{"schema_id": URN \| null, "ontology_ref": URI \| null}` | `schema_id`: URN of the domain schema (e.g. `urn:ioc:draft:healthcare:…:v0.1`). `ontology_ref`: shared ontology URI, forward-declared, not loaded at runtime. |
| `policy \| null` | `{"sensitivity": "public"\|"internal"\|"restricted"\|"confidential"\|null, "propagation": "forward"\|"restricted"\|"no_forward"\|null, "retention_policy": URN\|null}` | Classification, forwarding rules, retention policy. |
| `attributes \| null` | `{"msg_sources": [string*], "msg_transforms": [string*], "msg_created": ISO 8601 UTC, "msg_expiry": ISO 8601 UTC \| null}` | Origin, transformation history, timestamps. |
| `payload \| null` | `[PayloadPart*]` | Typed payload parts. See [§payload](#payload) below. |

### kind

| Value | Role | Relevant when |
|---|---|---|
| `intent` | Opens an episode. Declares the concept URI and participating group. | Exactly once per episode, at the start. |
| `exchange` | Substantive contribution — assertion, counter, compliance, prior declaration. The bulk of all messages. | Any turn where an agent is contributing content. |
| `contingency` | Listener raises a grounding problem against a specific prior message. The listener owns this branch from open to close. | CIP grounding failures; any sub-protocol that detects a repair requirement. |
| `commit` | Closes an episode or contingency branch. | Episode close (initiator), contingency close (branch owner). |
| `knowledge` | Degenerate single-message episode. Acts as intent + commit:converged in one message — opens and closes immediately. Carries a knowledge payload to update TeamEpistemicMemory. | After `commit:converged` to announce a converged rule; also valid as a standalone announcement outside a full episode. |

### subkind

| Value | Used with | Meaning |
|---|---|---|
| `converged` | `commit` | Episode closed with convergence. MPC ≥ threshold; group reached agreement. Initiator writes `knowledge` next. |
| `rejected` | `commit` | Episode closed without convergence. No `knowledge` follows. |
| `resolved` | `commit` | Contingency branch closed. Repair was grounded; exchange resumes. |
| `ready` | `exchange` or `commit` | Done signal. On `exchange`: final contribution + done signal combined. On `commit`: standalone done signal with no content. |
| `null` | any | No qualifier needed. Most `exchange`, `contingency`, and `intent` messages. |

### subprotocol

`subprotocol` is a required string field that identifies which sub-protocol produced this message. Two sub-protocols are currently defined:

| Value | Used for |
|---|---|
| `"CIP"` | Message carries grounding/belief content, processed by the Contingency Interaction Protocol. |
| `"SIEP"` | Message carries negotiation content, processed by the Semantic Interaction Exchange Protocol. |

The field is extensible: any implementation may introduce a new sub-protocol by choosing a unique string identifier not already in use. A formal sub-protocol registry will be published in a future revision of this specification.

### context.topic

`context.topic` names the concept category this message is about. Absent (null) on session-lifecycle messages. Sub-concept detail is passed in the CIP payload `utterance.evidence` list alongside the category URI.

**Sub-concept URI convention:** `urn:concept:<use_case>:<category>:<specific>`

| Value | Used for |
|---|---|
| `"concept:drug_interaction"` | Category URI — top-level concept. |
| `"urn:concept:healthcare:drug_interaction:warfarin+ibuprofen"` | Sub-concept URI — specific instance. Pair tokens alphabetically ordered and joined with `+`. |
| `null` | Session lifecycle messages with no concept. |

### context.epistemic.message_act

| Value | Meaning |
|---|---|
| `assertion` | Sender holds this position with conviction. GAR counts this as genuine. |
| `challenge` | Sender disagrees and pushes back. |
| `compliance` | Sender is yielding without genuine conviction. SCR counts this as social pressure. |

### context.epistemic.state

| Value | When |
|---|---|
| `taskwork` | Agent forming an independent prior — no peer contact yet. |
| `grounding` | Agent in active pairwise CIP exchange — verifying or repairing positions. |
| `team_process` | Agent in SIEP convergence round or team process negotiation. |

### context.epistemic.belief_status

| Value | Meaning |
|---|---|
| `asserted` | Sender holds this belief and is stating it directly. |
| `deferred` | Sender is holding judgment — waiting for more information. |
| `challenged` | Sender is actively disputing a prior belief. |
| `revised` | Sender updated a prior belief based on new evidence from this exchange. |
| `retracted` | Sender is withdrawing a previously asserted belief entirely. |
| `unresolved` | Exchange ended without convergence on this belief (timeout, max repair depth). |

### context.epistemic.uncertainty

`1 − posterior`. `0.0` = perfect confidence. Process messages (intent, commit:converged, knowledge) carry `0.0`.

## Payload

The payload is a list of typed parts. Each part has:

| Field | Values | Description |
|---|---|---|
| `type` | `"utterance" \| "cip" \| "siep" \| "cip-repair" \| "team_process" \| "knowledge" \| "team_prior" \| "query" \| …` | The type of content in this part. |
| `location` | `"inline" \| "external"` | Whether content is embedded or referenced. |
| `content` | string or dict or null | The payload content. Type-dependent. |
| `rationale` | string or null | *(type=utterance only)* Why this claim — clinical or operational reasoning. |
| `thought_summary` | string or null | *(type=utterance only)* One sentence: what belief state or prior turn shaped this response. |
| `ref` | `"urn:ioc:payload:{message_id}" \| null` | Reference to external payload. |

**type=utterance** carries the natural-language text, rationale, and thought_summary. This is always present alongside any `cip` or `siep` part — the text and the structured protocol data travel together. Task intake (e.g. a patient complaint) is also an utterance — included as a second `type=utterance` part in the taskwork `intent` payload, with `rationale` carrying the clinical or operational context and `thought_summary` stating what the intake establishes for the episode.

**type=cip** carries the CIPPayload (grounding, belief, utterance evidence). See [CIP.md](../../subprotocol/cip/docs/CIP.md).

**type=siep** carries the SIEPPayload (operation, proposal, evidence chain). See [SIEP.md](../../subprotocol/siep/docs/SIEP.md).

**type=knowledge** carries the knowledge rule content (posterior, GAR, SCR, provenance_weight, revision_cause).

**type=team_prior** carries the team prior from TeamEpistemicMemory, included in `intent` messages at episode open.

**type=query** carries a concept lookup request routed to `team-epistemic-memory`.

## Transport assumptions

L9 operates over a transport layer that provides:

- Reliable delivery of messages to all participants in a group (or notification of failure).
- Causal delivery semantics within a group.
- Group membership changes abort any in-flight episode.

The transport-level group is:

| Field | Type | Description |
|---|---|---|
| `group` | `[actor_id*]` | All actors to whom the message must be delivered, including the sender. |

L9 is transport-independent. The transport can be as complex as A2A over SLIM or as simple as an in-process message bus.

## Episode structure and principles

An episode is a bounded coordination context. All messages in one coordination cycle carry the same `message.episode` URN.

**Core principles:**

- An episode that does not commit is void.
- Once an episode starts, the group is committed. If a participant fails silently, the episode fails and must be restarted within a different group.
- Episodes can be nested to address sub-questions. Episodes must not be interleaved.
- Episodes are synchronous. A failed participant aborts the episode.
- Episodes can lead to updated agent epistemic state and to knowledge statements.

## Episode grammar

```
episode :=
  intent                                       -- initiator opens; group + concept declared;
                                               --   team_prior carried in payload
  exchange+                                    -- subkind=null or subkind=ready
  ( contingency exchange+ commit:resolved )*   -- repair branches; listener owns start to finish
  commit:ready*                                -- standalone done signal; no content
  commit:(converged | rejected)                -- initiator closes; triggered when all group members
                                               --   have signalled done (via exchange:ready or commit:ready)
  knowledge*                                   -- degenerate single-message episode;
                                               --   acts as intent + commit:converged in one;
                                               --   one per converged concept;
                                               --   typically after commit:converged;
                                               --   message.parents = [commit:converged.id]  (list of UUIDs)
```

**Two equivalent done signals:**
- `exchange(subkind=ready)` — final argument + done signal combined.
- `commit(subkind=ready)` — standalone done signal with no further content.

**Contingency ownership:** The agent that emits `contingency` owns the branch. It closes with `commit:resolved` after the offending agent's repair `exchange`. A done signal implicitly retracted when a `contingency` opens is re-sent after `commit:resolved`.

## kind=knowledge — degenerate single-message episode

`knowledge` is a valid kind. A knowledge message is a degenerate episode that acts as intent, commit:converged, and payload simultaneously — it opens and closes in a single message. It is typically sent after `commit:converged` to announce a new rule to TeamEpistemicMemory, but it can also be sent independently when new knowledge is available outside a full episode. Routed to the group plus the `team-epistemic-memory` agent.

```
kind=knowledge
message.parents = [commit:converged.id]   -- list of UUIDs; typically one entry
topic = <URI>
payload := [{
  type: "knowledge",
  content: {
    posterior:         float   -- MPC from converged round
    gar:               float
    scr:               float
    provenance_weight: float   -- (1 - SCR) × GAR
    revision_cause:    "converged_episode" | "repair_resolution"
  }
}]
```

- One `knowledge` message per converged concept.
- Only on `commit:converged` — never on `commit:rejected`.
- `message.parents` is a list of UUIDs — typically `[commit:converged.id]` — so provenance traces back to the full episode transcript.

# Team processes, task work and tasks

When you put a group of people in a room to solve a hard problem —
say, a clinical panel reviewing a complex patient case — they do not
just start shouting their opinions at each other.  Before any real
work begins, the group has a short coordination conversation.  Who is
the cardiologist here?  Who is covering pharmacology?  What exactly
are we trying to decide?  What does each person already know going in?
This pre-work takes minutes, but without it the group wastes time
talking past each other, duplicating effort, or worse — converging on
a wrong answer because the loudest voice won rather than the best
argument.

Team processes and task work debates are precisely addressing this for
software agents.

The problem is that today's multi-agent systems skip this entirely and
is one of the reasons why MAS applications typically behave poorly.
Agents are just fired at a problem and expected to produce useful
output through some combination of prompting and hope.  When they fail
— and they fail often — it is not because the individual models are
too weak.  It is because nobody in the group knows what the others
believe, nobody is checking whether responses actually engage the
prior argument, and nobody is measuring whether the final agreement
was genuine or just one agent caving to another.

This system fixes that by making agents behave more like a well-run
human team. It does this in three layers - debates on team process and
task work, before any actual work starts.  These debates are using L9
subprotocols.

- Team process. Before any domain work starts, the agents negotiate
  their working arrangement.  Who owns which part of the problem?
  What is each agent's starting belief?  What is the shared goal?
  This is not chitchat — it is a structured debate that must converge
  before anything else is allowed to proceed. A gate enforces this:
  taskwork is literally blocked until the team has reached agreement
  on how it is going to work.  This is team process work. 

- Taskwork. Once the team is aligned, each agent reasons independently
  about the domain problem it was assigned.  No peer contact yet —
  each agent forms its own position from its own knowledge and memory,
  and declares that position openly to the group.  This matters
  because it creates a fixed baseline.  Later, when agents debate and
  positions shift, the system can tell whether a shift happened
  because of a compelling argument or because someone simply went
  along.  Without a declared starting position per agent that
  distinction is impossible to make.  We call this taskwork. 

- Task. With every agent's starting position on the table, the team
  debates the actual problem. Agents challenge each other's reasoning,
  propose positions, counter-propose with evidence, and either
  converge on a shared answer or surface a genuine disagreement that
  requires repair.  Every exchange is checked: did this response
  actually engage the prior argument, or did it talk past it?  The
  final answer is not just recorded — the quality of how the team got
  there is measured, so that answers reached through genuine
  persuasion are trusted more than answers reached through one agent
  caving to another.  This is the task. 

If anything breaks down during domain work — agents keep failing to
ground their arguments, or the group is converging through pressure
rather than reasoning — the system sends the team back to the
coordination layer to re-establish shared understanding before
continuing. The flow is not a one-way pipeline. It cycles.

The underlying insight, drawn from earlier work on organizational
psychology research, is that taskwork and teamwork are
inseparable. You cannot get a good clinical answer from a group that
has not first agreed on who knows what, what each person believes, and
how disagreements will be resolved.  This system makes those
agreements explicit, measurable, and enforceable.

## Messages for team process, task work and task

Below a set of intent and commit messages are shown for the example
use case in this tree.  Healthcare panel is about aligning between 5
fictitious physicians and 5 pharmacologists each having their own
specific skills on patient use cases.  First a team process executes
to make sure all are aligned on the task at hand, then each independent
position is established, before any real task work begins.

Messages below are taken from a real hcpanel run against the Anthropic
backend (2026-06-26, pt-1008, episode
`urn:ioc:hcpanel:episode:pt-1008:fa94b5ef-f985-4b14-ad80-fa7e2d20e20f`)...
Message IDs and episode UUIDs vary per run; the structure is invariant.

---

### Team process — `CIP intent`

Coordinator opens the role-assignment episode. This is a broadcast —
no recipients are enumerated on the open message; individual
propose/accept exchanges follow with each specialist. No concept yet —
this is a session-lifecycle message.

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "intent",
  "subprotocol": "CIP",
  "subkind": null,
  "participants": {
    "actors": [
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "physician-internal-medicine",
        "role": "physician-internal-medicine",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-clinical-pharmacology",
        "role": "physician-clinical-pharmacology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-cardiology",
        "role": "physician-cardiology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-neurology",
        "role": "physician-neurology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-immunology",
        "role": "physician-immunology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacokinetics",
        "role": "pharmacologist-pharmacokinetics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacodynamics",
        "role": "pharmacologist-pharmacodynamics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-pharmacy",
        "role": "pharmacologist-clinical-pharmacy",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-drug-safety",
        "role": "pharmacologist-drug-safety",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-toxicology",
        "role": "pharmacologist-clinical-toxicology",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "622021c7-8b3b-4646-a7c8-8e2d369b4a3b",
    "parents": [],
    "episode": "urn:ioc:hcpanel:episode:pt-1008:fa94b5ef-f985-4b14-ad80-fa7e2d20e20f:tp"
  },
  "context": {
    "topic": null,
    "epistemic": {
      "message_act": "assertion",
      "state": "team_process",
      "belief_status": "asserted",
      "uncertainty": 0.0
    },
    "semantic": {
      "schema_id": "urn:ioc:draft:healthcare:coordination:peer_message:v0.1",
      "ontology_ref": null
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "session:open subject=pt-1008"
    }
  ]
}
```

### Team process — `CIP commit:converged`

After all role proposals have been accepted, the coordinator closes
the team-process episode. The `team_process` payload records that all
10 roles were acknowledged.

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "commit",
  "subprotocol": "CIP",
  "subkind": "converged",
  "participants": {
    "actors": [
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "physician-internal-medicine",
        "role": "physician-internal-medicine",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-clinical-pharmacology",
        "role": "physician-clinical-pharmacology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-cardiology",
        "role": "physician-cardiology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-neurology",
        "role": "physician-neurology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-immunology",
        "role": "physician-immunology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacokinetics",
        "role": "pharmacologist-pharmacokinetics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacodynamics",
        "role": "pharmacologist-pharmacodynamics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-pharmacy",
        "role": "pharmacologist-clinical-pharmacy",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-drug-safety",
        "role": "pharmacologist-drug-safety",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-toxicology",
        "role": "pharmacologist-clinical-toxicology",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "02fab4f2-ade1-4298-94f2-723d09288343",
    "parents": [],
    "episode": "urn:ioc:hcpanel:episode:pt-1008:fa94b5ef-f985-4b14-ad80-fa7e2d20e20f:tp"
  },
  "context": {
    "topic": null,
    "epistemic": {
      "message_act": "assertion",
      "state": "team_process",
      "belief_status": "asserted",
      "uncertainty": 0.0
    },
    "semantic": {
      "schema_id": "urn:ioc:healthcare:coordination:peer_message:v1.0",
      "ontology_ref": null
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "grounding:converged status=aligned"
    },
    {
      "type": "team_process",
      "location": "inline",
      "content": {
        "coordination_status": "aligned",
        "role_count": 10
      }
    }
  ]
}
```

---

### Taskwork — `CIP intent`

Opens the taskwork episode. The coordinator signals that independent
prior declarations from each specialist should now begin. The patient
complaint is conveyed to each specialist separately as part of their
individual task assignment messages.

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "intent",
  "subprotocol": "CIP",
  "subkind": null,
  "participants": {
    "actors": [
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "physician-internal-medicine",
        "role": "physician-internal-medicine",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-clinical-pharmacology",
        "role": "physician-clinical-pharmacology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-cardiology",
        "role": "physician-cardiology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-neurology",
        "role": "physician-neurology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-immunology",
        "role": "physician-immunology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacokinetics",
        "role": "pharmacologist-pharmacokinetics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacodynamics",
        "role": "pharmacologist-pharmacodynamics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-pharmacy",
        "role": "pharmacologist-clinical-pharmacy",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-drug-safety",
        "role": "pharmacologist-drug-safety",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-toxicology",
        "role": "pharmacologist-clinical-toxicology",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "0c58a10f-63da-44af-9b45-f6205c4f74b4",
    "parents": [],
    "episode": "urn:ioc:hcpanel:episode:pt-1008:fa94b5ef-f985-4b14-ad80-fa7e2d20e20f:tw"
  },
  "context": {
    "topic": null,
    "epistemic": {
      "message_act": "assertion",
      "state": "team_process",
      "belief_status": "asserted",
      "uncertainty": 0.0
    },
    "semantic": {
      "schema_id": "urn:ioc:draft:healthcare:coordination:peer_message:v0.1",
      "ontology_ref": null
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "taskwork:open subject=pt-1008"
    },
    {
      "type": "utterance",
      "location": "inline",
      "content": "patient:pt-1008 symptoms=[nausea, fatigue, dizzy] medications=[warfarin, aspirin] complaint: I have been getting nosebleeds and bruise very easily.; I take both blood thinners as prescribed.; Can we review this soon?",
      "rationale": "Patient intake establishing the clinical question for this episode.",
      "thought_summary": "Case pt-1008: nausea, fatigue, dizzy on warfarin, aspirin."
    }
  ]
}
```

### Taskwork — `CIP exchange` (specialist prior declaration)

Each specialist independently declares a prior before any peer exchange.
This message is from `physician-clinical-pharmacology` — their independent
assessment of the pt-1008 case. `rationale` carries the clinical reasoning;
`thought_summary` states in one sentence what shaped this position.
The CIP payload records the prior and posterior (equal at declaration),
the supporting evidence, and empty `addresses_evidence` (no prior turn to
engage yet).

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "exchange",
  "subprotocol": "CIP",
  "subkind": null,
  "participants": {
    "actors": [
      {
        "id": "physician-clinical-pharmacology",
        "role": "physician-clinical-pharmacology",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "a3f2c1d0-7e4b-4a19-b8c2-1d5e6f7a8b9c",
    "parents": ["0c58a10f-63da-44af-9b45-f6205c4f74b4"],
    "episode": "urn:ioc:hcpanel:episode:pt-1008:fa94b5ef-f985-4b14-ad80-fa7e2d20e20f:tw"
  },
  "context": {
    "topic": "urn:concept:healthcare:drug_interaction",
    "epistemic": {
      "message_act": "assertion",
      "state": "taskwork",
      "belief_status": "asserted",
      "uncertainty": 0.24
    },
    "semantic": {
      "schema_id": "urn:ioc:draft:healthcare:coordination:peer_message:v0.1",
      "ontology_ref": null
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "Warfarin and aspirin together create a dual-pathway bleeding risk — anticoagulant plus antiplatelet. Nosebleeds and easy bruising in a patient on both agents are classic signs of excessive anticoagulation, not a new disease process.",
      "rationale": "Warfarin inhibits vitamin K clotting factors; aspirin irreversibly inhibits platelet aggregation. Combined use elevates haemorrhagic risk substantially. Symptom triad (nausea, fatigue, easy bruising, nosebleeds) is consistent with supratherapeutic anticoagulation.",
      "thought_summary": "Dual anticoagulant/antiplatelet regimen with bleeding symptoms points strongly to drug interaction rather than new disease."
    },
    {
      "type": "cip",
      "location": "inline",
      "content": {
        "utterance": {
          "evidence": [
            "urn:concept:healthcare:drug_interaction:warfarin+aspirin",
            "urn:concept:healthcare:symptom:nosebleed",
            "urn:concept:healthcare:symptom:bruising"
          ],
          "addresses_evidence": [],
          "ring_round": 0,
          "repair_depth": 0
        },
        "grounding": {
          "contingency_verified": null,
          "contingency_score": null,
          "repair_reason": null,
          "challenges": []
        },
        "belief": {
          "prior": 0.76,
          "posterior": 0.76,
          "revision_cause": "semantic_memory"
        }
      }
    }
  ]
}
```

### Taskwork — `CIP commit:converged`

All specialist priors have been declared. The coordinator closes the
taskwork episode, signalling that independent positions are on record
and the panel debate can begin.

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "commit",
  "subprotocol": "CIP",
  "subkind": "converged",
  "participants": {
    "actors": [
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "physician-internal-medicine",
        "role": "physician-internal-medicine",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-clinical-pharmacology",
        "role": "physician-clinical-pharmacology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-cardiology",
        "role": "physician-cardiology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-neurology",
        "role": "physician-neurology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-immunology",
        "role": "physician-immunology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacokinetics",
        "role": "pharmacologist-pharmacokinetics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacodynamics",
        "role": "pharmacologist-pharmacodynamics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-pharmacy",
        "role": "pharmacologist-clinical-pharmacy",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-drug-safety",
        "role": "pharmacologist-drug-safety",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-toxicology",
        "role": "pharmacologist-clinical-toxicology",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "b0ff3eb4-dcf5-4ca8-a422-b4228f059192",
    "parents": [],
    "episode": "urn:ioc:hcpanel:episode:pt-1008:fa94b5ef-f985-4b14-ad80-fa7e2d20e20f:tw"
  },
  "context": {
    "topic": null,
    "epistemic": {
      "message_act": "assertion",
      "state": "team_process",
      "belief_status": "asserted",
      "uncertainty": 0.0
    },
    "semantic": {
      "schema_id": "urn:ioc:healthcare:coordination:peer_message:v1.0",
      "ontology_ref": null
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "session:close subject=pt-1008 accepted=True"
    }
  ]
}
```

---

### Task (SIEP panel) — `SIEP intent`

Opens the star-negotiation panel. The panel concept is `new_disease`
— the coordinator's opening proposition before round-1 votes shift it.
The full participant list is carried in the utterance payload; individual
propose/respond messages follow with each specialist. The panel episode
ID is a flat UUID (no `:tp`/`:tw` suffix) distinct from the CIP episode.

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "intent",
  "subprotocol": "SIEP",
  "subkind": null,
  "participants": {
    "actors": [
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "physician-internal-medicine",
        "role": "physician-internal-medicine",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-clinical-pharmacology",
        "role": "physician-clinical-pharmacology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-cardiology",
        "role": "physician-cardiology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-neurology",
        "role": "physician-neurology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-immunology",
        "role": "physician-immunology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacokinetics",
        "role": "pharmacologist-pharmacokinetics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacodynamics",
        "role": "pharmacologist-pharmacodynamics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-pharmacy",
        "role": "pharmacologist-clinical-pharmacy",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-drug-safety",
        "role": "pharmacologist-drug-safety",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-toxicology",
        "role": "pharmacologist-clinical-toxicology",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "6f5ba398-7126-4591-b5c4-b46c61d92b92",
    "parents": [],
    "episode": "urn:ioc:healthcare:panel:hcpanel:dd73a4e4-39db-4e57-ae26-30e8b3eabfee"
  },
  "context": {
    "topic": null,
    "epistemic": {
      "message_act": "assertion",
      "state": "team_process",
      "belief_status": "asserted",
      "uncertainty": 0.0
    },
    "semantic": {
      "schema_id": "urn:ioc:draft:healthcare:coordination:peer_turn:v0.1",
      "ontology_ref": "protocol/ontology/snp_ontology.ttl"
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "panel:open concept=new_disease participants=['diagnostics-controller', 'physician-internal-medicine', 'physician-clinical-pharmacology', 'physician-cardiology', 'physician-neurology', 'physician-immunology', 'pharmacologist-pharmacokinetics', 'pharmacologist-pharmacodynamics', 'pharmacologist-clinical-pharmacy', 'pharmacologist-drug-safety', 'pharmacologist-clinical-toxicology']"
    }
  ]
}
```

### Task (SIEP panel) — `SIEP exchange` (specialist counter-proposal)

The coordinator proposes `new_disease`; `physician-clinical-pharmacology`
counter-proposes `drug_interaction`. The `rationale` carries the clinical
argument; `thought_summary` states what shaped this response. The SIEP
payload records the operation, the counter-proposal's posterior and evidence,
and the `addresses_evidence` list that feeds the CIP contingency check —
the specialist is engaging the coordinator's evidence directly.

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "exchange",
  "subprotocol": "SIEP",
  "subkind": null,
  "participants": {
    "actors": [
      {
        "id": "physician-clinical-pharmacology",
        "role": "physician-clinical-pharmacology",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "c7d8e9f0-1a2b-4c3d-8e4f-5a6b7c8d9e0f",
    "parents": ["6f5ba398-7126-4591-b5c4-b46c61d92b92"],
    "episode": "urn:ioc:healthcare:panel:hcpanel:dd73a4e4-39db-4e57-ae26-30e8b3eabfee"
  },
  "context": {
    "topic": "urn:concept:healthcare:drug_interaction",
    "epistemic": {
      "message_act": "challenge",
      "state": "team_process",
      "belief_status": "asserted",
      "uncertainty": 0.24
    },
    "semantic": {
      "schema_id": "urn:ioc:draft:healthcare:coordination:peer_turn:v0.1",
      "ontology_ref": "protocol/ontology/snp_ontology.ttl"
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "physician-clinical-pharmacology counter-proposes drug_interaction confidence=0.76",
      "rationale": "The coordinator's new_disease hypothesis does not account for the concurrent warfarin-aspirin regimen. Nosebleeds and easy bruising in this context are haemostatic, not disease-onset symptoms. INR should be checked before attributing symptoms to a new pathology.",
      "thought_summary": "Prior taskwork established drug_interaction with 0.76 confidence; coordinator's new_disease proposal does not engage the anticoagulant evidence."
    },
    {
      "type": "siep",
      "location": "inline",
      "content": {
        "profile": "semantic_negotiation",
        "operation": "counter_proposal",
        "proposal_id": "panel-hcpanel-dd73a4e4-t0-physician-clinical-pharmacology",
        "content": "drug_interaction",
        "status": "pending",
        "negotiation_id": "dd73a4e4-39db-4e57-ae26-30e8b3eabfee",
        "proposal_payload": {
          "posterior": 0.76,
          "supporting_evidence": [
            "urn:concept:healthcare:drug_interaction:warfarin+aspirin",
            "urn:concept:healthcare:symptom:nosebleed",
            "urn:concept:healthcare:symptom:bruising"
          ],
          "against_evidence": [],
          "addresses_evidence": [
            "urn:concept:healthcare:drug_interaction:warfarin+aspirin"
          ],
          "reasoning_summary": "Warfarin+aspirin dual-pathway bleeding risk; symptom triad consistent with supratherapeutic anticoagulation.",
          "deferred_to": null
        }
      }
    }
  ]
}
```

### Task (SIEP panel) — `CIP contingency` (grounding failure during panel)

When a specialist's response fails to engage the prior turn's evidence
(contingency score below θ_c = 0.40), the listener raises a `contingency`.
The `cip-repair` payload names the target message and the failure reason.
The listener owns this branch until it emits `commit:resolved`.

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "contingency",
  "subprotocol": "CIP",
  "subkind": null,
  "participants": {
    "actors": [
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "physician-internal-medicine",
        "role": "physician-internal-medicine",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "e1f2a3b4-c5d6-4e7f-9081-a2b3c4d5e6f7",
    "parents": ["a3f2c1d0-7e4b-4a19-b8c2-1d5e6f7a8b9c"],
    "episode": "urn:ioc:hcpanel:episode:pt-1008:fa94b5ef-f985-4b14-ad80-fa7e2d20e20f:tw:ie:1"
  },
  "context": {
    "topic": "urn:concept:healthcare:drug_interaction",
    "epistemic": {
      "message_act": "assertion",
      "state": "grounding",
      "belief_status": "challenged",
      "uncertainty": 0.0
    },
    "semantic": {
      "schema_id": "urn:ioc:draft:healthcare:coordination:peer_message:v0.1",
      "ontology_ref": null
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "repair_required: reason=grounding_failure, target=a3f2c1d0-7e4b-4a19-b8c2-1d5e6f7a8b9c",
      "rationale": "Response did not reference any evidence from the prior turn — contingency score 0.08, below threshold 0.40.",
      "thought_summary": "Physician-internal-medicine's assertion was self-contained; no engagement with the coordinator's evidence list."
    },
    {
      "type": "cip-repair",
      "location": "inline",
      "content": {
        "target_message_id": "a3f2c1d0-7e4b-4a19-b8c2-1d5e6f7a8b9c",
        "repair_reason": "grounding_failure"
      }
    }
  ]
}
```

### Task (SIEP panel) — `SIEP commit:converged`

The panel converged on `drug_interaction`. The `snp-convergence` part
carries the final MPC, GAR, and SCR for this episode.

```json
{
  "protocol": "SSTP",
  "version": "0.0.5",
  "kind": "commit",
  "subprotocol": "SIEP",
  "subkind": "converged",
  "participants": {
    "actors": [
      {
        "id": "diagnostics-controller",
        "role": "diagnostics-controller",
        "participant_type": "sender",
        "attestation": "self_attested_local"
      },
      {
        "id": "physician-internal-medicine",
        "role": "physician-internal-medicine",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-clinical-pharmacology",
        "role": "physician-clinical-pharmacology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-cardiology",
        "role": "physician-cardiology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-neurology",
        "role": "physician-neurology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "physician-immunology",
        "role": "physician-immunology",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacokinetics",
        "role": "pharmacologist-pharmacokinetics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-pharmacodynamics",
        "role": "pharmacologist-pharmacodynamics",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-pharmacy",
        "role": "pharmacologist-clinical-pharmacy",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-drug-safety",
        "role": "pharmacologist-drug-safety",
        "participant_type": "recipient",
        "attestation": null
      },
      {
        "id": "pharmacologist-clinical-toxicology",
        "role": "pharmacologist-clinical-toxicology",
        "participant_type": "recipient",
        "attestation": null
      }
    ],
    "groups": null
  },
  "message": {
    "id": "441c8b6c-1069-497e-9387-11b1b2ab37fe",
    "parents": [],
    "episode": "urn:ioc:healthcare:panel:hcpanel:dd73a4e4-39db-4e57-ae26-30e8b3eabfee"
  },
  "context": {
    "topic": null,
    "epistemic": {
      "message_act": "assertion",
      "state": "team_process",
      "belief_status": "asserted",
      "uncertainty": 0.0
    },
    "semantic": {
      "schema_id": "urn:ioc:healthcare:coordination:decision_emitted:v1.0",
      "ontology_ref": "protocol/ontology/snp_ontology.ttl"
    }
  },
  "payload": [
    {
      "type": "utterance",
      "location": "inline",
      "content": "SIEP convergence: drug_interaction → accept posterior=0.7368 gar=0.8182 scr=0.0000"
    },
    {
      "type": "snp-convergence",
      "location": "inline",
      "content": {
        "profile": "semantic_negotiation",
        "operation": "accept",
        "participant_ids": [
          "diagnostics-controller",
          "physician-internal-medicine",
          "physician-clinical-pharmacology",
          "physician-cardiology",
          "physician-neurology",
          "physician-immunology",
          "pharmacologist-pharmacokinetics",
          "pharmacologist-pharmacodynamics",
          "pharmacologist-clinical-pharmacy",
          "pharmacologist-drug-safety",
          "pharmacologist-clinical-toxicology"
        ],
        "mpc": 0.7368,
        "gar": 0.8182,
        "scr": 0.0,
        "episode_id": "urn:ioc:healthcare:panel:hcpanel:dd73a4e4-39db-4e57-ae26-30e8b3eabfee"
      }
    }
  ]
}
```

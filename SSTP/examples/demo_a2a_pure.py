# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Pure A2A multi-protocol demo: TFP → SIEP → CIP → SIEP → SAB

Same scenario as multi_protocol_demo.py but expressed entirely in A2A protocol
primitives (AgentCard, Task, Message, Part) — no L9 types used.

Agents: agent-alpha (leads), agent-beta (participant).
cip-engine: protocol-internal component (future: Cognition Engine).

Transport: in-process A2A bus — simulates A2A routing without HTTP servers.

  Step 1 — TFP  (Team Formation via Polling)
    agent-alpha opens poll task, agent-beta bids, alpha selects & commits.

  Step 2 — SIEP (Epistemic Grounding)
    alpha opens grounding task; beta drifts to wrong concept → mismatch.

  Step 3 — CIP  (Contingency Repair)
    alpha raises contingency task; cip-engine issues repair; beta re-anchors.

  Step 4 — SIEP (Commit)
    alpha commits: epistemic alignment converged.

  Step 5 — SAB  (Negotiation: price × delivery_speed)
    alpha and beta exchange offers until agreement.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from a2a.types.a2a_pb2 import (
    AgentCard,
    AgentCapabilities,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.helpers.proto_helpers import (
    new_data_part,
    new_message,
    new_task,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.helpers.agent_card import display_agent_card
from google.protobuf.json_format import MessageToDict

# ── Constants ─────────────────────────────────────────────────────────────────
C_SCOPE    = "concept:deliverable_scope"
C_TIMELINE = "concept:timeline"
_W = 100


# ─────────────────────────────────────────────────────────────────────────────
# In-process A2A bus
# ─────────────────────────────────────────────────────────────────────────────

class A2ABus:
    """Minimal in-process A2A task bus — simulates A2A routing without HTTP."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._cards: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        self._cards[card.name] = card

    def submit(self, task: Task) -> Task:
        self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task:
        return self._tasks[task_id]

    def append_message(self, task_id: str, msg: Message,
                       state: TaskState = TaskState.TASK_STATE_WORKING) -> None:
        task = self._tasks[task_id]
        task.history.append(msg)
        task.status.state = state

    def complete(self, task_id: str, msg: Message | None = None) -> None:
        task = self._tasks[task_id]
        if msg:
            task.history.append(msg)
        task.status.state = TaskState.TASK_STATE_COMPLETED

    def list_tasks(self) -> list[Task]:
        return list(self._tasks.values())


# ─────────────────────────────────────────────────────────────────────────────
# Print helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hr(char: str = "─") -> None:
    print(char * _W)


def _print_msg(phase: str, step: str, sender: str, msg: Message,
               note: str = "") -> None:
    role = Role.Name(msg.role).replace("ROLE_", "").lower()
    text_parts = [p.text for p in msg.parts if p.HasField("text") and p.text]
    data_parts = [p for p in msg.parts if p.HasField("data")]
    preview = text_parts[0][:80] if text_parts else (
        f"[data:{list(MessageToDict(data_parts[0].data).keys())[:3]}]"
        if data_parts else "—")
    _hr()
    print(f"  [{phase}]  {step}  role={role}  sender={sender}")
    if note:
        print(f"           {note}")
    print(f"           msg={msg.message_id[:8]}…  \"{preview}\"")


def _print_task(phase: str, step: str, task: Task, note: str = "") -> None:
    state = TaskState.Name(task.status.state).replace("TASK_STATE_", "").lower()
    _hr()
    print(f"  [{phase}]  {step}  task={task.id[:8]}…  state={state}")
    if note:
        print(f"           {note}")


EpisodeLog = list[tuple[str, str, Message]]


def _print_summary(log: EpisodeLog) -> None:
    _hr("═")
    print("  PURE A2A EPISODE SUMMARY")
    _hr("═")
    for phase, label, _ in log:
        print(f"  [{phase:<4}]  {label}")
    _hr("═")
    print(f"  Total messages: {len(log)}")
    _hr("═")


def _save_json(log: EpisodeLog, bus: A2ABus) -> None:
    import pathlib
    out = pathlib.Path(__file__).resolve().parent / "demo_a2a_pure_run.json"
    tasks_out = []
    for task in bus.list_tasks():
        d = MessageToDict(task, preserving_proto_field_name=True)
        tasks_out.append(d)
    out.write_text(json.dumps({"tasks": tasks_out}, indent=2))
    print(f"\n  JSON saved → {out}")


# ─────────────────────────────────────────────────────────────────────────────
# Agent cards
# ─────────────────────────────────────────────────────────────────────────────

def _make_cards() -> tuple[AgentCard, AgentCard, AgentCard]:
    alpha = AgentCard(
        name="agent-alpha",
        description="Lead agent: scope analysis, negotiation, team coordination.",
        version="1.0",
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(
            url="a2a://agent-alpha", protocol_binding="A2A", protocol_version="1.1")],
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["text/plain", "application/json"],
        skills=[
            AgentSkill(id="scope_analysis", name="Scope Analysis",
                       description="Analyzes and aligns deliverable scope.",
                       tags=["scope", "analysis"], examples=["Align on C_SCOPE."]),
            AgentSkill(id="negotiation", name="Negotiation",
                       description="Negotiates supply terms (price, delivery).",
                       tags=["negotiation", "sab"]),
            AgentSkill(id="team_coordination", name="Team Coordination",
                       description="Opens TFP polls and leads epistemic episodes.",
                       tags=["tfp", "siep"]),
        ],
    )
    beta = AgentCard(
        name="agent-beta",
        description="Participant agent: timeline analysis, scope support.",
        version="1.0",
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(
            url="a2a://agent-beta", protocol_binding="A2A", protocol_version="1.1")],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(id="timeline_analysis", name="Timeline Analysis",
                       description="Analyzes project timelines.",
                       tags=["timeline"]),
            AgentSkill(id="scope_analysis", name="Scope Analysis",
                       description="Secondary scope analysis support.",
                       tags=["scope"]),
        ],
    )
    # cip-engine: protocol-internal component (future Cognition Engine)
    cip_engine = AgentCard(
        name="cip-engine",
        description="CIP contingency engine — protocol-internal (future: Cognition Engine).",
        version="1.0",
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(
            url="a2a://cip-engine", protocol_binding="A2A", protocol_version="1.1")],
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(id="contingency_repair", name="Contingency Repair",
                       description="Detects scope drift and issues repair guidance.",
                       tags=["cip", "repair"]),
        ],
    )
    return alpha, beta, cip_engine


# ─────────────────────────────────────────────────────────────────────────────
# Main demo
# ─────────────────────────────────────────────────────────────────────────────

def run_demo() -> None:
    bus = A2ABus()
    alpha_card, beta_card, cip_card = _make_cards()
    bus.register(alpha_card)
    bus.register(beta_card)
    bus.register(cip_card)
    log: EpisodeLog = []

    def rec(phase: str, label: str, sender: str, msg: Message,
            note: str = "") -> Message:
        log.append((phase, label, msg))
        _print_msg(phase, label, sender, msg, note)
        return msg

    ctx_id = str(uuid.uuid4())

    # ── Step 1: TFP — Team Formation ─────────────────────────────────────────
    _hr("═")
    print("  STEP 1 — TFP   (Team Formation via Polling)")
    _hr("═")

    poll_task_id = str(uuid.uuid4())

    # 1a. alpha opens poll
    poll_open = new_message(
        parts=[
            new_text_part("POLL_OPEN: Seeking agents for supply-chain coordination task."),
            new_data_part({
                "operation": "POLL_OPEN",
                "poll_id": poll_task_id,
                "task": {
                    "description": "Coordinate deliverable scope alignment and supply term negotiation",
                    "objective": "Align on scope then agree delivery terms",
                },
                "required_skills": [
                    {"skill": "scope_analysis",    "min_proficiency": 0.7, "mandatory": True},
                    {"skill": "timeline_analysis", "min_proficiency": 0.6, "mandatory": True},
                    {"skill": "negotiation",       "min_proficiency": 0.6, "mandatory": False},
                ],
            }, media_type="application/json"),
        ],
        role=Role.ROLE_USER,
        task_id=poll_task_id,
        context_id=ctx_id,
    )
    tfp_task = bus.submit(new_task_from_user_message(poll_open))
    rec("TFP", "1a · POLL_OPEN  (agent-alpha opens poll)", "agent-alpha", poll_open,
        "agent-alpha broadcasts poll to topic:tfp/polls")

    # 1b. agent-alpha bids (also a participant)
    alpha_bid = new_message(
        parts=[
            new_text_part("BID: I offer scope_analysis (0.92) and negotiation (0.80). Availability: 90%."),
            new_data_part({
                "operation": "BID",
                "poll_id": poll_task_id,
                "agent_id": "agent-alpha",
                "offer": {
                    "skills": [
                        {"skill": "scope_analysis", "proficiency": 0.92},
                        {"skill": "negotiation",    "proficiency": 0.80},
                    ],
                    "availability": 0.9,
                },
            }, media_type="application/json"),
        ],
        role=Role.ROLE_AGENT,
        task_id=tfp_task.id,
        context_id=ctx_id,
    )
    bus.append_message(tfp_task.id, alpha_bid)
    rec("TFP", "1b · BID  (agent-alpha bids)", "agent-alpha", alpha_bid)

    # 1c. agent-beta bids
    beta_bid = new_message(
        parts=[
            new_text_part("BID: I offer timeline_analysis (0.85) and scope_analysis (0.65). Availability: 80%."),
            new_data_part({
                "operation": "BID",
                "poll_id": poll_task_id,
                "agent_id": "agent-beta",
                "offer": {
                    "skills": [
                        {"skill": "timeline_analysis", "proficiency": 0.85},
                        {"skill": "scope_analysis",    "proficiency": 0.65},
                    ],
                    "availability": 0.8,
                },
            }, media_type="application/json"),
        ],
        role=Role.ROLE_AGENT,
        task_id=tfp_task.id,
        context_id=ctx_id,
    )
    bus.append_message(tfp_task.id, beta_bid)
    rec("TFP", "1c · BID  (agent-beta bids)", "agent-beta", beta_bid)

    # 1d. alpha selects team
    select_msg = new_message(
        parts=[
            new_text_part("SELECT: Forming team [agent-alpha, agent-beta]. Coverage: 100%."),
            new_data_part({
                "operation": "SELECT",
                "poll_id": poll_task_id,
                "selection": {
                    "members": ["agent-alpha", "agent-beta"],
                    "coverage": 1.0,
                    "roles": [
                        {"agent_id": "agent-alpha", "role": "lead",        "responsible_for": ["scope_analysis", "negotiation"]},
                        {"agent_id": "agent-beta",  "role": "contributor", "responsible_for": ["timeline_analysis"]},
                    ],
                },
            }, media_type="application/json"),
        ],
        role=Role.ROLE_AGENT,
        task_id=tfp_task.id,
        context_id=ctx_id,
    )
    bus.append_message(tfp_task.id, select_msg)
    rec("TFP", "1d · SELECT  (agent-alpha selects team)", "agent-alpha", select_msg,
        "team=[agent-alpha, agent-beta]  coverage=1.0")

    # 1e. alpha accepts
    alpha_accept = new_text_message(
        "ACCEPT: Skills match, I have capacity. Joining team.",
        role=Role.ROLE_AGENT, task_id=tfp_task.id, context_id=ctx_id)
    bus.append_message(tfp_task.id, alpha_accept)
    rec("TFP", "1e · ACCEPT  (agent-alpha accepts)", "agent-alpha", alpha_accept)

    # 1f. beta accepts
    beta_accept = new_text_message(
        "ACCEPT: Timeline and scope skills ready. Joining team.",
        role=Role.ROLE_AGENT, task_id=tfp_task.id, context_id=ctx_id)
    bus.append_message(tfp_task.id, beta_accept)
    rec("TFP", "1f · ACCEPT  (agent-beta accepts)", "agent-beta", beta_accept)

    # 1g. alpha commits: team formed
    commit_tfp = new_message(
        parts=[
            new_text_part("FORM_CONVERGED: Team assembled. Starting epistemic grounding."),
            new_data_part({"operation": "FORM_CONVERGED", "poll_id": poll_task_id,
                           "members": ["agent-alpha", "agent-beta"]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=tfp_task.id, context_id=ctx_id)
    bus.complete(tfp_task.id, commit_tfp)
    rec("TFP", "1g · FORM_CONVERGED  (team formed ✓)", "agent-alpha", commit_tfp)

    # ── Step 2: SIEP — Epistemic Grounding ───────────────────────────────────
    _hr("═")
    print("  STEP 2 — SIEP  (Epistemic Grounding)")
    _hr("═")

    siep_task_id = str(uuid.uuid4())

    # 2a. alpha opens grounding task
    siep_intent = new_message(
        parts=[
            new_text_part(f"INTENT: Grounding session on {C_SCOPE}. All members please align."),
            new_data_part({"act": "intent", "concept": C_SCOPE,
                           "subkind": "team-process", "subprotocol": "SIEP"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_USER, task_id=siep_task_id, context_id=ctx_id)
    siep_task = bus.submit(new_task_from_user_message(siep_intent))
    rec("SIEP", "2a · intent  (agent-alpha opens episode)", "agent-alpha", siep_intent)

    # 2b. alpha exchanges on correct concept
    alpha_exchange = new_message(
        parts=[
            new_text_part(f"EXCHANGE: Confirmed alignment on {C_SCOPE}. "
                          "Evidence: spec-v2 and acceptance criteria doc."),
            new_data_part({"act": "exchange", "concept": C_SCOPE,
                           "belief": {"prior": 0.75, "posterior": 0.75},
                           "evidence": [C_SCOPE, "concept:acceptance_criteria"]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=siep_task.id, context_id=ctx_id)
    bus.append_message(siep_task.id, alpha_exchange)
    rec("SIEP", "2b · exchange  (agent-alpha aligns on scope)", "agent-alpha", alpha_exchange)

    # 2c. beta drifts to wrong concept
    beta_drift = new_message(
        parts=[
            new_text_part(f"EXCHANGE: My belief is aligned on {C_TIMELINE}. "
                          "Timeline analysis shows 3-week sprint."),
            new_data_part({"act": "exchange", "concept": C_TIMELINE,
                           "belief": {"prior": 0.55, "posterior": 0.55},
                           "evidence": [C_TIMELINE]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=siep_task.id, context_id=ctx_id)
    bus.append_message(siep_task.id, beta_drift)
    rec("SIEP", "2c · exchange  (agent-beta drifts to timeline ⚠)", "agent-beta", beta_drift,
        f"⚠ scope mismatch: beta replied on '{C_TIMELINE}', expected '{C_SCOPE}' → escalate to CIP")

    # ── Step 3: CIP — Contingency Repair ─────────────────────────────────────
    _hr("═")
    print("  STEP 3 — CIP   (Contingency Repair: scope mismatch on agent-beta)")
    _hr("═")

    cip_task_id = str(uuid.uuid4())

    # 3a. alpha raises contingency task
    repair_req = new_message(
        parts=[
            new_text_part(f"CONTINGENCY: agent-beta drifted to {C_TIMELINE}. "
                          f"Repair required — target must re-anchor on {C_SCOPE}."),
            new_data_part({"act": "contingency", "repair_reason": "scope_mismatch",
                           "target_agent": "agent-beta",
                           "expected_concept": C_SCOPE,
                           "observed_concept": C_TIMELINE,
                           "subprotocol": "CIP"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_USER, task_id=cip_task_id, context_id=ctx_id)
    cip_task = bus.submit(new_task_from_user_message(repair_req))
    rec("CIP", "3a · contingency  (repair request: beta drifted)", "agent-alpha", repair_req)

    # 3b. cip-engine issues repair guidance (simulated — in prod this calls LLM)
    repair_guidance = new_message(
        parts=[
            new_text_part(
                f"REPAIR_GUIDANCE → agent-beta: Hard stop. "
                f"Your last reply addressed {C_TIMELINE}, but the active grounding session "
                f"is anchored on {C_SCOPE}. Please restate your belief strictly against "
                f"deliverable scope. Confirm: what is your understanding of the agreed deliverables?"
            ),
            new_data_part({"act": "repair_guidance", "repair_type": "repair_hard_stop",
                           "issued_by": "cip-engine",
                           "target_agent": "agent-beta",
                           "required_concept": C_SCOPE},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=cip_task.id, context_id=ctx_id)
    bus.append_message(cip_task.id, repair_guidance)
    rec("CIP", "3b · repair_guidance  (cip-engine issues repair)", "cip-engine", repair_guidance,
        "cip-engine (future Cognition Engine) — repair_hard_stop → agent-beta")

    # 3c. beta re-anchors on correct concept
    beta_reanchor = new_message(
        parts=[
            new_text_part(f"REVISED: Re-anchoring on {C_SCOPE}. "
                          "Agreed deliverables: scope spec-v2 and acceptance criteria. Confirmed."),
            new_data_part({"act": "contingency_response", "concept": C_SCOPE,
                           "revision_cause": "repair_resolution",
                           "belief": {"prior": 0.68, "posterior": 0.68},
                           "addresses": [C_SCOPE, "concept:acceptance_criteria"]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=cip_task.id, context_id=ctx_id)
    bus.append_message(cip_task.id, beta_reanchor)
    rec("CIP", "3c · contingency_response  (agent-beta re-anchors)", "agent-beta", beta_reanchor)

    # 3d. cip-engine closes: commit:resolved
    cip_resolved = new_message(
        parts=[
            new_text_part(f"COMMIT_RESOLVED: Contingency closed. "
                          f"agent-beta re-anchored on {C_SCOPE}. Returning to SIEP."),
            new_data_part({"act": "commit_resolved", "concept": C_SCOPE,
                           "issued_by": "cip-engine",
                           "resolution": "re_anchored"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=cip_task.id, context_id=ctx_id)
    bus.complete(cip_task.id, cip_resolved)
    rec("CIP", "3d · commit:resolved  (cip-engine closes branch)", "cip-engine", cip_resolved)

    # ── Step 4: SIEP — Commit ────────────────────────────────────────────────
    _hr("═")
    print("  STEP 4 — SIEP  (Commit: epistemic alignment restored)")
    _hr("═")

    siep_commit = new_message(
        parts=[
            new_text_part(f"COMMIT_CONVERGED: All agents aligned on {C_SCOPE}. "
                          "Proceeding to supply negotiation."),
            new_data_part({"act": "commit_converged", "concept": C_SCOPE,
                           "belief": {"prior": 0.80, "posterior": 0.85},
                           "revision_cause": "grounded_argument"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=siep_task.id, context_id=ctx_id)
    bus.complete(siep_task.id, siep_commit)
    rec("SIEP", "4a · commit:converged  (agent-alpha confirms alignment)", "agent-alpha", siep_commit)

    # ── Step 5: SAB — Negotiate supply terms ─────────────────────────────────
    _hr("═")
    print("  STEP 5 — SAB   (Negotiation: price × delivery_speed)")
    _hr("═")

    sab_task_id = str(uuid.uuid4())
    issues = {"price": ["low", "medium", "high"], "delivery_speed": ["express", "standard", "deferred"]}

    # 5a. alpha opens SAB session
    sab_open = new_message(
        parts=[
            new_text_part("SAB_OPEN: Opening negotiation on price and delivery_speed."),
            new_data_part({"act": "negotiate_open", "session_id": sab_task_id,
                           "issues": issues, "subprotocol": "SAB"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_USER, task_id=sab_task_id, context_id=ctx_id)
    sab_task = bus.submit(new_task_from_user_message(sab_open))
    rec("SAB", "5a · negotiate_open  (agent-alpha opens SAB)", "agent-alpha", sab_open,
        "agent-alpha opens SAB session")

    # 5b. alpha offers high/express
    alpha_offer1 = new_message(
        parts=[
            new_text_part("OFFER: price=high, delivery_speed=express."),
            new_data_part({"act": "offer", "proposer": "agent-alpha", "step": 0,
                           "offer": {"price": "high", "delivery_speed": "express"}},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.append_message(sab_task.id, alpha_offer1)
    rec("SAB", "5b · offer  (agent-alpha offers high/express)", "agent-alpha", alpha_offer1,
        "alpha→beta: price=high, delivery=express")

    # 5c. beta counters low/deferred
    beta_offer = new_message(
        parts=[
            new_text_part("COUNTER: price=low, delivery_speed=deferred."),
            new_data_part({"act": "offer", "proposer": "agent-beta", "step": 1,
                           "offer": {"price": "low", "delivery_speed": "deferred"}},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.append_message(sab_task.id, beta_offer)
    rec("SAB", "5c · offer  (agent-beta counters low/deferred)", "agent-beta", beta_offer,
        "beta→alpha: price=low, delivery=deferred")

    # 5d. alpha concedes medium/standard
    alpha_offer2 = new_message(
        parts=[
            new_text_part("CONCEDE: price=medium, delivery_speed=standard. Final offer."),
            new_data_part({"act": "offer", "proposer": "agent-alpha", "step": 2,
                           "offer": {"price": "medium", "delivery_speed": "standard"}},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.append_message(sab_task.id, alpha_offer2)
    rec("SAB", "5d · offer  (agent-alpha concedes medium/standard)", "agent-alpha", alpha_offer2,
        "alpha→beta: price=medium, delivery=standard")

    # 5e. beta accepts
    beta_accept_sab = new_message(
        parts=[
            new_text_part("ACCEPT: price=medium, delivery_speed=standard. Agreement reached."),
            new_data_part({"act": "accept",  "proposer": "agent-beta", "step": 3,
                           "accepted_offer": {"price": "medium", "delivery_speed": "standard"}},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.append_message(sab_task.id, beta_accept_sab)
    rec("SAB", "5e · accept  (agent-beta accepts ✓)", "agent-beta", beta_accept_sab,
        "beta accepts ✓")

    # 5f. alpha commits: converged
    sab_commit = new_message(
        parts=[
            new_text_part("COMMIT_CONVERGED: price=medium, delivery_speed=standard. "
                          "Supply terms agreed."),
            new_data_part({"act": "commit_converged",
                           "final_agreement": {"price": "medium", "delivery_speed": "standard"},
                           "agents": ["agent-alpha", "agent-beta"]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.complete(sab_task.id, sab_commit)
    rec("SAB", "5f · commit:converged  (supply terms agreed)", "agent-alpha", sab_commit,
        "commit:converged — price=medium, delivery=standard")

    # ── Summary ────────────────────────────────────────────────────────────────
    _print_summary(log)
    _save_json(log, bus)

    # ── Agent cards ────────────────────────────────────────────────────────────
    print()
    for card in [alpha_card, beta_card, cip_card]:
        display_agent_card(card)
        print()


if __name__ == "__main__":
    run_demo()

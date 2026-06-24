# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Pure A2A multi-protocol demo: TFP → SIEP → CIP → SAB

Same scenario as multi_protocol_demo.py but expressed entirely in A2A protocol
primitives (AgentCard, Task, Message, Part) — no L9 types used.

Scenario: Cross-jurisdiction SaaS Enterprise Agreement Review (Legal Tech)

  Agents: commercial-agent (leads — contract law + GDPR expertise),
          liability-agent  (participant — indemnity + damages specialist).
  cip-engine: protocol-internal component (future: Cognition Engine).

Transport: in-process A2A bus — simulates A2A routing without HTTP servers.

  Step 1 — TFP  (Team Formation via Polling)
    commercial-agent opens poll; liability-agent bids; team formed.

  Step 2 — SIEP (Legal Standard Alignment)
    Team aligns on "material breach" (contract-law standard).
    liability-agent drifts to tort "substantial performance" doctrine → mismatch.

  Step 3 — CIP  (Contingency Repair)
    cip-engine detects doctrine mismatch, issues hard-stop repair.
    liability-agent re-anchors on contract-law standard. CIP: commit:resolved.

  Step 4 — SAB  (Semantic Negotiation: consequential damages clause)
    Genuine semantic misalignment on "consequential damages" scope —
    US broad exclusion vs. UK narrower standard. Agents negotiate until agreement.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# ── Path bootstrap (SSTP must be importable) ──────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── LLM credentials (needed by CIPProcessor) ─────────────────────────────────
def _load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env(_REPO_ROOT / "SSTP/subprotocol/cip/llm.env")

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

# ── wheel: CIP (real CIPProcessor — LLM-powered repair) ──────────────────────
from ai.outshift.subprotocols.cip import (
    CIPMessageBuilder,
    CIPPayload,
    CIPUtterance,
    CIPBelief,
    CIPGrounding,
    RepairReason,
    RevisionCause as CIPRevisionCause,
    CIPEngineConfig,
    CIPProcessor,
)

# ── Constants ─────────────────────────────────────────────────────────────────
C_SCOPE    = "concept:material_breach"          # contract-law standard (operative)
C_TIMELINE = "concept:substantial_performance"   # tort doctrine — wrong domain (drift)
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
        name="commercial-agent",
        description="Lead agent: contract law, GDPR compliance, team coordination.",
        version="1.0",
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(
            url="a2a://agent-alpha", protocol_binding="A2A", protocol_version="1.1")],
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["text/plain", "application/json"],
        skills=[
            AgentSkill(id="contract_law", name="Contract Law",
                       description="Applies contract-law standards to SaaS agreements.",
                       tags=["contract", "saas"], examples=["Define material breach under contract law."]),
            AgentSkill(id="gdpr_compliance", name="GDPR Compliance",
                       description="Ensures data processing clauses meet GDPR/CCPA standards.",
                       tags=["gdpr", "privacy"]),
            AgentSkill(id="team_coordination", name="Team Coordination",
                       description="Opens TFP polls and leads legal standard alignment sessions.",
                       tags=["tfp", "siep"]),
        ],
    )
    beta = AgentCard(
        name="liability-agent",
        description="Participant agent: indemnity analysis, damages scope specialist.",
        version="1.0",
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(
            url="a2a://agent-beta", protocol_binding="A2A", protocol_version="1.1")],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(id="indemnity_analysis", name="Indemnity Analysis",
                       description="Analyses indemnity and consequential damages clauses.",
                       tags=["indemnity", "damages"]),
            AgentSkill(id="contract_law", name="Contract Law",
                       description="Secondary contract law support.",
                       tags=["contract"]),
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
                    "description": "Review cross-jurisdiction SaaS enterprise agreement — material breach and consequential damages clauses",
                    "objective": "Align on scope then agree delivery terms",
                },
                "required_skills": [
                    {"skill": "contract_law",       "min_proficiency": 0.8, "mandatory": True},
                    {"skill": "indemnity_analysis", "min_proficiency": 0.7, "mandatory": True},
                    {"skill": "gdpr_compliance",    "min_proficiency": 0.6, "mandatory": False},
                ],
            }, media_type="application/json"),
        ],
        role=Role.ROLE_USER,
        task_id=poll_task_id,
        context_id=ctx_id,
    )
    tfp_task = bus.submit(new_task_from_user_message(poll_open))
    rec("TFP", "1a · POLL_OPEN  (commercial-agent opens poll)", "commercial-agent", poll_open,
        "agent-alpha broadcasts poll to topic:tfp/polls")

    # 1b. agent-alpha bids (also a participant)
    alpha_bid = new_message(
        parts=[
            new_text_part("BID: I offer contract_law (0.92) and gdpr_compliance (0.80). Availability: 90%."),
            new_data_part({
                "operation": "BID",
                "poll_id": poll_task_id,
                "agent_id": "commercial-agent",
                "offer": {
                    "skills": [
                        {"skill": "contract_law", "proficiency": 0.92},
                        {"skill": "gdpr_compliance", "proficiency": 0.80},
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
    rec("TFP", "1b · BID  (commercial-agent bids)", "commercial-agent", alpha_bid)

    # 1c. agent-beta bids
    beta_bid = new_message(
        parts=[
            new_text_part("BID: I offer indemnity_analysis (0.88) and contract_law (0.72). Availability: 80%."),
            new_data_part({
                "operation": "BID",
                "poll_id": poll_task_id,
                "agent_id": "liability-agent",
                "offer": {
                    "skills": [
                        {"skill": "indemnity_analysis", "proficiency": 0.88},
                        {"skill": "contract_law",       "proficiency": 0.72},
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
    rec("TFP", "1c · BID  (liability-agent bids)", "liability-agent", beta_bid)

    # 1d. alpha selects team
    select_msg = new_message(
        parts=[
            new_text_part("SELECT: Forming team [agent-alpha, agent-beta]. Coverage: 100%."),
            new_data_part({
                "operation": "SELECT",
                "poll_id": poll_task_id,
                "selection": {
                    "members": ["commercial-agent", "liability-agent"],
                    "coverage": 1.0,
                    "roles": [
                        {"agent_id": "commercial-agent", "role": "lead",        "responsible_for": ["contract_law", "gdpr_compliance"]},
                        {"agent_id": "liability-agent",  "role": "contributor", "responsible_for": ["indemnity_analysis"]},
                    ],
                },
            }, media_type="application/json"),
        ],
        role=Role.ROLE_AGENT,
        task_id=tfp_task.id,
        context_id=ctx_id,
    )
    bus.append_message(tfp_task.id, select_msg)
    rec("TFP", "1d · SELECT  (commercial-agent selects team)", "commercial-agent", select_msg,
        "team=[agent-alpha, agent-beta]  coverage=1.0")

    # 1e. alpha accepts
    alpha_accept = new_text_message(
        "ACCEPT: Contract law and GDPR expertise confirmed; joining review team.",
        role=Role.ROLE_AGENT, task_id=tfp_task.id, context_id=ctx_id)
    bus.append_message(tfp_task.id, alpha_accept)
    rec("TFP", "1e · ACCEPT  (commercial-agent accepts)", "commercial-agent", alpha_accept)

    # 1f. beta accepts
    beta_accept = new_text_message(
        "ACCEPT: Indemnity and damages analysis skills ready; joining review team.",
        role=Role.ROLE_AGENT, task_id=tfp_task.id, context_id=ctx_id)
    bus.append_message(tfp_task.id, beta_accept)
    rec("TFP", "1f · ACCEPT  (liability-agent accepts)", "liability-agent", beta_accept)

    # 1g. alpha commits: team formed
    commit_tfp = new_message(
        parts=[
            new_text_part("FORM_CONVERGED: Team assembled. Starting legal standard alignment."),
            new_data_part({"operation": "FORM_CONVERGED", "poll_id": poll_task_id,
                           "members": ["commercial-agent", "liability-agent"]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=tfp_task.id, context_id=ctx_id)
    bus.complete(tfp_task.id, commit_tfp)
    rec("TFP", "1g · FORM_CONVERGED  (team formed ✓)", "commercial-agent", commit_tfp)

    # ── Step 2: SIEP — Legal Standard Alignment ──────────────────────────────
    _hr("═")
    print('  STEP 2 — SIEP  (Legal Standard Alignment: aligning on "material breach")')
    _hr("═")

    siep_task_id = str(uuid.uuid4())

    # 2a. commercial-agent opens legal standard alignment task
    siep_intent = new_message(
        parts=[
            new_text_part(f"INTENT: Legal standard alignment on {C_SCOPE}. All agents must confirm interpretive framework."),
            new_data_part({"act": "intent", "concept": C_SCOPE,
                           "subkind": "team-process", "subprotocol": "SIEP"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_USER, task_id=siep_task_id, context_id=ctx_id)
    siep_task = bus.submit(new_task_from_user_message(siep_intent))
    rec("SIEP", "2a · intent  (commercial-agent opens alignment session)", "commercial-agent", siep_intent)

    # 2b. alpha exchanges on correct concept
    alpha_exchange = new_message(
        parts=[
            new_text_part(f"EXCHANGE: Confirmed alignment on {C_SCOPE}. "
                          "Evidence: spec-v2 and acceptance criteria doc."),
            new_data_part({"act": "exchange", "concept": C_SCOPE,
                           "belief": {"prior": 0.75, "posterior": 0.75},
                           "evidence": [C_SCOPE, "concept:sla_breach_threshold"]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=siep_task.id, context_id=ctx_id)
    bus.append_message(siep_task.id, alpha_exchange)
    rec("SIEP", "2b · exchange  (commercial-agent aligns on material breach)", "commercial-agent", alpha_exchange)

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
    rec("SIEP", "2c · exchange  (liability-agent drifts to tort doctrine ⚠)", "liability-agent", beta_drift,
        f"⚠ doctrine mismatch: liability-agent applied tort 'substantial_performance', expected contract-law 'material_breach' → escalate to CIP")

    # ── Step 3: CIP — Contingency Repair ─────────────────────────────────────
    _hr("═")
    print("  STEP 3 — CIP   (Contingency Repair: doctrine mismatch on liability-agent)")
    _hr("═")

    cip_task_id = str(uuid.uuid4())
    cip_episode  = f"urn:ioc:cip:{uuid.uuid4()}"

    # CIPProcessor (real LLM-powered — same as L9 demo)
    cip_config = CIPEngineConfig(
        derailment_causes={
            "scope_mismatch":    ["{listener}, your reply applied the wrong legal doctrine."],
            "alignment_failure": ["{listener}, your reply did not engage the agreed legal standard."],
        },
        nonsense_derailment_causes=set(),
        repair_utterances={
            "repair_hard_stop":      "{listener}, stop — restate only under the contract-law material breach standard.",
            "repair_anchor":         "{listener}, re-anchor on the contract-law material breach definition.",
            "repair_alignment":      "{listener}, restate within the agreed operative legal standard.",
            "request_clarification": "{listener}, clarify how your reply addresses material breach under contract law.",
            "default":               "{listener}, remain within the contract-law material breach standard.",
        },
        normal_utterance_template="{listener}, continue within the shared contract-law material breach standard.",
    )
    cip_proc = CIPProcessor("cip-engine", cip_episode, cip_config)

    def _cip_l9(sender: str) -> CIPMessageBuilder:
        return CIPMessageBuilder(cip_episode, sender)

    def _cip_text(l9_msg: Any) -> str:
        """Extract utterance text from a CIPProcessor L9 result."""
        data = l9_msg.payload.data or {}
        return data.get("utterance", {}).get("text", str(data))

    # 3a. commercial-agent raises contingency (A2A message on bus)
    repair_req = new_message(
        parts=[
            new_text_part(f"CONTINGENCY: liability-agent applied tort doctrine ({C_TIMELINE}). "
                          f"Repair required — must re-anchor on {C_SCOPE} (contract law)."),
            new_data_part({"act": "contingency", "repair_reason": "doctrine_mismatch",
                           "target_agent": "liability-agent",
                           "expected_concept": C_SCOPE,
                           "expected_doctrine": "contract_law",
                           "observed_concept": C_TIMELINE,
                           "observed_doctrine": "tort_law",
                           "subprotocol": "CIP"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_USER, task_id=cip_task_id, context_id=ctx_id)
    cip_task = bus.submit(new_task_from_user_message(repair_req))
    rec("CIP", "3a · contingency  (repair: liability-agent applied tort doctrine)", "commercial-agent", repair_req)

    # Build internal L9 message → run CIPProcessor → LLM generates guidance
    repair_req_l9 = (
        _cip_l9("commercial-agent")
        .contingency().grounding().challenged().concept(C_SCOPE)
        .payload(CIPPayload(
            grounding=CIPGrounding(
                contingency_verified=False, contingency_score=0.0,
                repair_reason=RepairReason.scope_mismatch,
                challenges=[C_SCOPE, "concept:sla_breach_threshold"],
            ),
        ))
        .text("repair_required:reason=doctrine_mismatch:target=liability-agent")
        .build()
    )
    guidance_l9 = cip_proc.process(repair_req_l9)[0]
    guidance_text = _cip_text(guidance_l9)

    # 3b. cip-engine delivers LLM guidance as A2A message
    repair_guidance = new_message(
        parts=[
            new_text_part(f"REPAIR_GUIDANCE → liability-agent: {guidance_text}"),
            new_data_part({"act": "repair_guidance", "repair_type": "repair_hard_stop",
                           "issued_by": "cip-engine",
                           "target_agent": "liability-agent",
                           "required_concept": C_SCOPE,
                           "required_doctrine": "contract_law"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=cip_task.id, context_id=ctx_id)
    bus.append_message(cip_task.id, repair_guidance)
    rec("CIP", "3b · repair_guidance  (cip-engine issues hard-stop repair — LLM)", "cip-engine", repair_guidance,
        "cip-engine (future Cognition Engine) — LLM repair_hard_stop → liability-agent")

    # 3c. liability-agent re-anchors (A2A response on bus)
    beta_reanchor = new_message(
        parts=[
            new_text_part(f"REVISED: Re-anchoring on contract-law {C_SCOPE} standard. "
                          "Confirmed: breach of SLA uptime clause 14.2 constitutes material breach "
                          "as it goes to the root of the agreement. Tort doctrine set aside."),
            new_data_part({"act": "contingency_response", "concept": C_SCOPE,
                           "revision_cause": "repair_resolution",
                           "doctrine_corrected": "contract_law",
                           "belief": {"prior": 0.68, "posterior": 0.75},
                           "addresses": [C_SCOPE, "concept:sla_breach_threshold"]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=cip_task.id, context_id=ctx_id)
    bus.append_message(cip_task.id, beta_reanchor)
    rec("CIP", "3c · contingency_response  (liability-agent re-anchors on contract law)", "liability-agent", beta_reanchor)

    # Pass re-anchor to CIPProcessor → generates commit:resolved
    reanchor_l9 = (
        _cip_l9("liability-agent")
        .contingency().grounding().revised().concept(C_SCOPE)
        .payload(CIPPayload(
            utterance=CIPUtterance(
                text="Re-anchoring on contract-law material breach: breach of SLA uptime clause 14.2 constitutes material breach as it goes to the root of the agreement.",
                evidence=[C_SCOPE, "concept:sla_breach_threshold"],
                addresses_evidence=[C_SCOPE, "concept:sla_breach_threshold"],
                turn_depth=1,
            ),
            belief=CIPBelief(prior=0.68, posterior=0.75,
                             revision_cause=CIPRevisionCause.repair_resolution),
        ))
        .text("Re-anchoring on contract-law material breach.")
        .build()
    )
    resolved_l9 = cip_proc.process(reanchor_l9)[0]
    resolved_text = _cip_text(resolved_l9) or "Contingency closed. Epistemic alignment restored."

    # 3d. cip-engine commits: resolved (A2A message on bus)
    cip_resolved = new_message(
        parts=[
            new_text_part(f"COMMIT_RESOLVED: {resolved_text}"),
            new_data_part({"act": "commit_resolved", "concept": C_SCOPE,
                           "issued_by": "cip-engine",
                           "resolution": "re_anchored"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=cip_task.id, context_id=ctx_id)
    bus.complete(cip_task.id, cip_resolved)
    rec("CIP", "3d · commit:resolved  (cip-engine closes — alignment restored)", "cip-engine", cip_resolved)

    # ── Step 4: SAB — Negotiate supply terms ─────────────────────────────────
    _hr("═")
    print("  STEP 4 — SAB   (Semantic Negotiation: consequential damages clause)")
    _hr("═")

    sab_task_id = str(uuid.uuid4())
    issues = {"governing_interpretation": ["us_standard", "uk_standard", "hybrid"],
              "damages_cap": ["6_months_fees", "12_months_fees", "24_months_fees"]}

    # 4a. alpha opens SAB session
    sab_open = new_message(
        parts=[
            new_text_part("SAB_OPEN: Opening semantic negotiation on consequential damages clause — governing_interpretation and damages_cap."),
            new_data_part({"act": "negotiate_open", "session_id": sab_task_id,
                           "issues": {"governing_interpretation": ["us_standard","uk_standard","hybrid"], "damages_cap": ["6_months_fees","12_months_fees","24_months_fees"]}, "subprotocol": "SAB"},
                          media_type="application/json"),
        ],
        role=Role.ROLE_USER, task_id=sab_task_id, context_id=ctx_id)
    sab_task = bus.submit(new_task_from_user_message(sab_open))
    rec("SAB", "4a · negotiate_open  (commercial-agent opens SAB)", "commercial-agent", sab_open,
        "commercial-agent opens SAB — consequential damages clause")

    # 4b. alpha offers high/express
    alpha_offer1 = new_message(
        parts=[
            new_text_part("OFFER: governing_interpretation=us_standard, damages_cap=6_months_fees."),
            new_data_part({"act": "offer", "proposer": "commercial-agent", "step": 0,
                           "offer": {"governing_interpretation": "us_standard", "damages_cap": "6_months_fees"}},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.append_message(sab_task.id, alpha_offer1)
    rec("SAB", "4b · offer  (commercial-agent proposes us_standard/6_months_fees)", "commercial-agent", alpha_offer1,
        "commercial→liability: us_standard / 6_months_fees")

    # 4c. beta counters low/deferred
    beta_offer = new_message(
        parts=[
            new_text_part("COUNTER: governing_interpretation=uk_standard, damages_cap=24_months_fees."),
            new_data_part({"act": "offer", "proposer": "liability-agent", "step": 1,
                           "offer": {"governing_interpretation": "uk_standard", "damages_cap": "24_months_fees"}},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.append_message(sab_task.id, beta_offer)
    rec("SAB", "4c · offer  (liability-agent counters uk_standard/24_months_fees)", "liability-agent", beta_offer,
        "liability→commercial: uk_standard / 24_months_fees")

    # 4d. alpha concedes medium/standard
    alpha_offer2 = new_message(
        parts=[
            new_text_part("CONCEDE: governing_interpretation=hybrid, damages_cap=12_months_fees. Final offer."),
            new_data_part({"act": "offer", "proposer": "commercial-agent", "step": 2,
                           "offer": {"governing_interpretation": "hybrid", "damages_cap": "12_months_fees"}},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.append_message(sab_task.id, alpha_offer2)
    rec("SAB", "4d · offer  (commercial-agent concedes hybrid/12_months_fees)", "commercial-agent", alpha_offer2,
        "commercial→liability: hybrid / 12_months_fees")

    # 4e. beta accepts
    beta_accept_sab = new_message(
        parts=[
            new_text_part("ACCEPT: governing_interpretation=hybrid, damages_cap=12_months_fees. Damages clause agreed."),
            new_data_part({"act": "accept",  "proposer": "liability-agent", "step": 3,
                           "accepted_offer": {"governing_interpretation": "hybrid", "damages_cap": "12_months_fees"}},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.append_message(sab_task.id, beta_accept_sab)
    rec("SAB", "4e · accept  (agent-liability-agent accepts ✓)", "liability-agent", beta_accept_sab,
        "liability-agent accepts ✓")

    # 4f. alpha commits: converged
    sab_commit = new_message(
        parts=[
            new_text_part("COMMIT_CONVERGED: price=medium, delivery_speed=standard. "
                          "Supply terms agreed."),
            new_data_part({"act": "commit_converged",
                           "final_agreement": {"governing_interpretation": "hybrid", "damages_cap": "12_months_fees"},
                           "agents": ["commercial-agent", "liability-agent"]},
                          media_type="application/json"),
        ],
        role=Role.ROLE_AGENT, task_id=sab_task.id, context_id=ctx_id)
    bus.complete(sab_task.id, sab_commit)
    rec("SAB", "4f · commit:converged  (damages clause agreed)", "commercial-agent", sab_commit,
        "commit:converged — governing=hybrid, cap=12_months_fees")

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

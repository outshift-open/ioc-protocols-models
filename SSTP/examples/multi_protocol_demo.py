# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Multi-protocol SSTP demo: TFP → SIEP → CIP → SAB

All imports from the ai-outshift-subprotocols wheel:
  ai.outshift.subprotocols.{tfp, siep, cip, sab}

Scenario: Cross-jurisdiction SaaS Enterprise Agreement Review (Legal Tech)

  Agents: commercial-agent (leads — contract law + GDPR expertise),
          liability-agent  (participant — indemnity + damages specialist).
  cip-engine: protocol-internal component (future: Cognition Engine).

  Step 1 — TFP  (Team Formation via Polling)
    commercial-agent opens a poll for a contract review team.
    Both agents bid; team commits: converged.

  Step 2 — SIEP (Epistemic Grounding)
    Team aligns on the operative definition of "material breach" (contract-law standard).
    liability-agent drifts — applies tort-law "substantial performance" doctrine instead.

  Step 3 — CIP  (Contingency Repair)
    cip-engine detects doctrine mismatch and issues hard-stop repair.
    liability-agent re-anchors on contract-law standard.
    CIP closes: commit:resolved — epistemic alignment restored.

  Step 4 — SAB  (Semantic Negotiation: consequential damages clause)
    Genuine semantic misalignment: commercial-agent and liability-agent disagree
    on the scope of "consequential damages" — US broad exclusion vs. UK narrower
    standard. They negotiate governing_interpretation and damages_cap until agreement.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
import warnings
from pathlib import Path
from typing import Any, List, Optional, Tuple

# ── path bootstrap ────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TFP_PY = _REPO_ROOT / "SSTP/subprotocol/tfp/language_bindings/python"
for _p in [str(_REPO_ROOT), str(_TFP_PY)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── LLM credentials ───────────────────────────────────────────────────────────
def _load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env(_REPO_ROOT / "SSTP/subprotocol/cip/llm.env")

# ── wheel: L9 data model ──────────────────────────────────────────────────────
from ai.outshift.data_model import (
    L9, L9Header, L9Payload, Actor, Context, Message, ParticipantSet, Semantic,
)

# ── wheel: TFP ────────────────────────────────────────────────────────────────
from ai.outshift.subprotocols.tfp import (
    CandidateOffer,
    RoleAssignment,
    SkillClaim,
    SkillRequirement,
    TaskSpec,
    TeamSelection,
    TFPOperation,
    TFPPayload,
)

# ── wheel: SIEP ───────────────────────────────────────────────────────────────
from ai.outshift.subprotocols.siep import (
    SIEPMessageBuilder,
    SIEPPayload,
    SIEPUtterance,
    SIEPBelief,
    RevisionCause,
    SIEPEngine,
)

# ── wheel: CIP ────────────────────────────────────────────────────────────────
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

# ── wheel: SAB ────────────────────────────────────────────────────────────────
from ai.outshift.subprotocols.sab import (
    SAB,
    SABHeader,
    SABPayload,
    SABActors,
    SABAttributes,
    SABOrigin,
    SABIntentPayloadData,
    SABNegotiatePayloadData,
    SABCommitPayloadData,
    NegotiateSemanticContext,
    NegotiateCommitSemanticContext,
    SemanticContext,
    SAOState,
    SAOResponse,
    SAONMI,
    Outcome,
    ResponseType,
    Kind as SABKind,
    Subkind as SABSubkind,
)

# ── Episode constants ─────────────────────────────────────────────────────────
C_SCOPE    = "concept:material_breach"          # contract-law standard (operative)
C_TIMELINE = "concept:substantial_performance"   # tort doctrine — wrong domain (drift)
C_CRITERIA = "concept:sla_breach_threshold"      # supporting evidence concept

ISSUES  = ["governing_interpretation", "damages_cap"]
OPTIONS = {"governing_interpretation": ["us_standard", "uk_standard", "hybrid"],
           "damages_cap": ["6_months_fees", "12_months_fees", "24_months_fees"]}
N_OUTCOMES = len(OPTIONS["governing_interpretation"]) * len(OPTIONS["damages_cap"])

TFP_PROTOCOL  = "SSTP"
TFP_SUBPROTO  = "TFP"
TFP_VERSION   = "0"
SUBKIND_TF    = "team-formation"
SUBKIND_CONV  = "converged"

EpisodeLog = List[Tuple[str, str, Any]]
_W = 100

_SYS_COMMERCIAL = (
    "You are commercial-agent, a commercial law AI specializing in SaaS enterprise "
    "agreements, contract-law material breach standards, and GDPR compliance. "
    "Respond in 1–2 sentences in professional legal tone. Do not use markdown or bullet points."
)
_SYS_LIABILITY = (
    "You are liability-agent, an indemnity and damages specialist focused on consequential "
    "damages clauses, SLA breach thresholds, and cross-jurisdiction indemnity analysis. "
    "Respond in 1–2 sentences in professional legal tone. Do not use markdown or bullet points."
)


def _agent_llm(agent: str, system: str, user: str, fallback: str) -> str:
    """Call LLM to generate an agent utterance; falls back to `fallback` on error."""
    try:
        import litellm  # type: ignore
        model    = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        base_url = os.environ.get("LLM_API_BASE") or os.environ.get("LLM_BASE_URL") or None
        api_key  = os.environ.get("LLM_API_KEY") or None
        if base_url and not model.startswith("openai/"):
            model = f"openai/{model}"
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": 0.4,
        }
        if api_key:  kwargs["api_key"]  = api_key
        if base_url: kwargs["base_url"] = base_url
        print(f"  [LLM] → agent={agent}  model={model}")
        resp = litellm.completion(**kwargs)
        text = (resp.choices[0].message.content or "").strip()
        print(f"  [LLM] ← {text[:120]}")
        return text or fallback
    except Exception as exc:
        print(f"  [LLM] ✗ {agent}: {exc}")
        return fallback


# ─────────────────────────────────────────────────────────────────────────────
# TFP helpers (minimal inline — mirrors TFPBus from the TFP example)
# ─────────────────────────────────────────────────────────────────────────────

def _tfp_emit(episode: str, sender: str, receivers: List[str],
              kind: str, subkind: str, payload: TFPPayload,
              parent_id: Optional[str] = None,
              topic: Optional[str] = None) -> L9:
    agent_receivers = [r for r in receivers if not r.startswith("topic:")]
    actors = [Actor(id=sender, role="sender", attestation=None)]
    for r in agent_receivers:
        actors.append(Actor(id=r, role="receiver", attestation=None))
    ctx_topic = topic or ""
    return L9(
        header=L9Header(
            protocol=TFP_PROTOCOL, subprotocol=TFP_SUBPROTO,
            version=TFP_VERSION, kind=kind, subkind=subkind,
            participants=ParticipantSet(actors=actors, groups=None),
            message=Message(
                id=str(uuid.uuid4()),
                parents=[parent_id] if parent_id else [],
                episode=episode,
            ),
            context=Context(topic=ctx_topic),
        ),
        payload=L9Payload(
            type="json-schema",
            data=payload.model_dump(exclude_none=True),
        ),
    )


def _tfp_fit(reqs: List[SkillRequirement], offer: CandidateOffer) -> float:
    total_w = sum(r.weight for r in reqs) or 1.0
    score = 0.0
    for r in reqs:
        best = max(
            (c.proficiency for c in offer.skills
             if c.skill == r.skill and c.proficiency >= r.min_proficiency),
            default=0.0,
        )
        score += r.weight * best
    return round(score / total_w, 4)


def _tfp_select(reqs: List[SkillRequirement],
                bids: dict[str, CandidateOffer]) -> TeamSelection:
    mandatory = [r for r in reqs if r.mandatory]
    members: List[str] = []
    roles: List[RoleAssignment] = []
    covered: set[str] = set()
    for r in mandatory:
        if r.skill in covered:
            continue
        best = max(
            (a for a, o in bids.items()
             if any(c.skill == r.skill and c.proficiency >= r.min_proficiency
                    for c in o.skills)),
            key=lambda a: max(
                (c.proficiency for c in bids[a].skills if c.skill == r.skill),
                default=0.0),
            default=None,
        )
        if best is None:
            continue
        owned = sorted(rr.skill for rr in reqs
                       if any(c.skill == rr.skill for c in bids[best].skills))
        covered.update(owned)
        if best not in members:
            members.append(best)
            roles.append(RoleAssignment(agent_id=best,
                                        role="contributor",
                                        responsible_for=owned))
    unmet = [r.skill for r in mandatory if r.skill not in covered]
    coverage = round((len(mandatory) - len(unmet)) / max(len(mandatory), 1), 4)
    agg_fit = round(
        sum(_tfp_fit(reqs, bids[m]) for m in members) / max(len(members), 1), 4
    ) if members else 0.0
    return TeamSelection(members=members, roles=roles,
                         coverage=coverage, unmet_skills=unmet,
                         aggregate_fit=agg_fit)


# ─────────────────────────────────────────────────────────────────────────────
# Main demo
# ─────────────────────────────────────────────────────────────────────────────

def run_demo() -> None:
    episode = f"urn:ioc:episode:{uuid.uuid4()}"
    log: EpisodeLog = []

    def record(phase: str, label: str, msg: Any) -> Any:
        log.append((phase, label, msg))
        return msg

    # ── Step 1: TFP — Team Formation ─────────────────────────────────────────
    _hr("═")
    print("  STEP 1 — TFP   (Team Formation via Polling)")
    _hr("═")

    poll_id  = f"urn:ioc:tfp:poll:{uuid.uuid4().hex[:8]}"
    task     = TaskSpec(
        task_id="task:saas-contract-review",
        description="Review cross-jurisdiction SaaS enterprise agreement — material breach and consequential damages clauses",
        objective="Align team on operative legal definitions then resolve semantic disagreement on damages scope",
    )
    required = [
        SkillRequirement(skill="skill:contract_law",       min_proficiency=0.8,
                         weight=2.0, mandatory=True),
        SkillRequirement(skill="skill:indemnity_analysis", min_proficiency=0.7,
                         weight=1.5, mandatory=True),
        SkillRequirement(skill="skill:gdpr_compliance",    min_proficiency=0.6,
                         weight=1.0, mandatory=False),
    ]
    tf_topic = f"Forming a team to {task.description}"

    # 1a. Poll open — commercial-agent broadcasts to topic
    poll_msg = record("TFP", "1a · intent:team-formation  (commercial-agent opens poll)",
        _tfp_emit(episode, "commercial-agent", ["topic:tfp/polls"],
                  "intent", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.POLL_OPEN,
                             poll_id=poll_id, task=task,
                             required_skills=required,
                             reasoning_summary="Need contract_law + indemnity_analysis + GDPR skills for cross-jurisdiction SaaS review."),
                  topic=tf_topic))
    poll_parent = poll_msg.header.message.id
    _print_l9("TFP", "1a", poll_msg)

    # Agent profiles (private — recruiter only learns via bids)
    alpha_offer = CandidateOffer(
        skills=[SkillClaim(skill="skill:contract_law",    proficiency=0.92),
                SkillClaim(skill="skill:gdpr_compliance", proficiency=0.80)],
        availability=0.9, fit_score=0.88)
    beta_offer = CandidateOffer(
        skills=[SkillClaim(skill="skill:indemnity_analysis", proficiency=0.88),
                SkillClaim(skill="skill:contract_law",       proficiency=0.72)],
        availability=0.8, fit_score=0.75)

    # 1b. commercial-agent bids
    alpha_bid = record("TFP", "1b · exchange:team-formation  (commercial-agent bids)",
        _tfp_emit(episode, "commercial-agent", ["commercial-agent"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.BID, poll_id=poll_id,
                             offer=alpha_offer,
                             reasoning_summary=f"contract_law+GDPR expertise; fit≈{_tfp_fit(required, alpha_offer)}"),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1b", alpha_bid)

    # 1c. liability-agent bids
    beta_bid = record("TFP", "1c · exchange:team-formation  (liability-agent bids)",
        _tfp_emit(episode, "liability-agent", ["commercial-agent"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.BID, poll_id=poll_id,
                             offer=beta_offer,
                             reasoning_summary=f"indemnity+damages specialist; fit≈{_tfp_fit(required, beta_offer)}"),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1c", beta_bid)

    # 1d. commercial-agent selects team
    bids = {"commercial-agent": alpha_offer, "liability-agent": beta_offer}
    selection = _tfp_select(required, bids)
    select_msg = record("TFP", "1d · exchange:team-formation  (commercial-agent selects team)",
        _tfp_emit(episode, "commercial-agent", ["commercial-agent", "liability-agent"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.SELECT, poll_id=poll_id,
                             selection=selection,
                             reasoning_summary=f"coverage={selection.coverage} fit={selection.aggregate_fit}"),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1d", select_msg)
    print(f"           team={selection.members}  coverage={selection.coverage}")

    # 1e. commercial-agent accepts
    _alpha_accept_reason = _agent_llm(
        "commercial-agent", _SYS_COMMERCIAL,
        "You have been selected for a cross-jurisdiction SaaS contract review team. "
        "Confirm your acceptance, briefly stating your contract-law and GDPR expertise.",
        "Contract law and GDPR expertise confirmed; joining review team.",
    )
    record("TFP", "1e · exchange:team-formation  (commercial-agent accepts)",
        _tfp_emit(episode, "commercial-agent", ["commercial-agent"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.ACCEPT, poll_id=poll_id,
                             reason=_alpha_accept_reason),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1e", log[-1][2])

    # 1f. liability-agent accepts
    _beta_accept_reason = _agent_llm(
        "liability-agent", _SYS_LIABILITY,
        "You have been selected for a cross-jurisdiction SaaS contract review team. "
        "Confirm your acceptance, briefly stating your indemnity and damages analysis expertise.",
        "Indemnity and damages analysis skills ready; joining review team.",
    )
    record("TFP", "1f · exchange:team-formation  (liability-agent accepts)",
        _tfp_emit(episode, "liability-agent", ["commercial-agent"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.ACCEPT, poll_id=poll_id,
                             reason=_beta_accept_reason),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1f", log[-1][2])

    # 1g. Commit: converged
    record("TFP", "1g · commit:converged          (team formed ✓)",
        _tfp_emit(episode, "commercial-agent", ["topic:tfp/polls"],
                  "commit", SUBKIND_CONV,
                  TFPPayload(operation=TFPOperation.FORM_CONVERGED, poll_id=poll_id,
                             selection=selection,
                             reasoning_summary=f"Contract review team formed: {selection.members}"),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1g", log[-1][2])

    # ── Step 2: SIEP — Epistemic Grounding ───────────────────────────────────
    _hr("═")
    print("  STEP 2 — SIEP  (Epistemic Grounding: aligning on 'material breach')")
    _hr("═")

    siep_engine = SIEPEngine("commercial-agent", episode)

    def _siep(sender: str) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(episode, sender)

    intent = record("SIEP", "2a · intent      (commercial-agent opens grounding session)",
        _siep("commercial-agent").intent().team_process().concept(C_SCOPE).build())
    siep_engine.process(intent)
    _print_l9("SIEP", "2a", intent)

    _alpha_siep_text = _agent_llm(
        "commercial-agent", _SYS_COMMERCIAL,
        f"You are in a legal standard alignment session on '{C_SCOPE}'. "
        "Confirm your alignment with the contract-law material breach standard, "
        "referencing SLA uptime clause 14.2 and acceptance criteria as evidence.",
        f"Confirmed alignment on {C_SCOPE}: breach of SLA uptime clause 14.2 satisfies the material breach threshold under contract law.",
    )
    alpha_exchange = record("SIEP", "2b · exchange    (commercial-agent aligns on material breach)",
        _siep("commercial-agent")
        .exchange().taskwork().asserted().concept(C_SCOPE)
        .parents(intent.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(text=_alpha_siep_text, evidence=[C_SCOPE, C_CRITERIA]),
            belief=SIEPBelief(prior=0.80, posterior=0.80,
                              revision_cause=RevisionCause.semantic_memory),
        )).build())
    siep_engine.process(alpha_exchange)
    _print_l9("SIEP", "2b", alpha_exchange)

    _beta_drift_text = _agent_llm(
        "liability-agent", _SYS_LIABILITY,
        f"You are in a legal standard alignment session on 'material breach', but you have "
        f"mistakenly applied the tort doctrine of 'substantial performance' ({C_TIMELINE}). "
        "Express your (incorrect) belief that substantial performance is the applicable standard, "
        "citing a performance timeline rationale. Be concise.",
        f"My analysis aligns on {C_TIMELINE}: the vendor's 3-week delivery schedule constitutes substantial performance under accepted tort doctrine.",
    )
    beta_drift = record("SIEP", "2c · exchange    (liability-agent drifts to tort doctrine ⚠)",
        _siep("liability-agent")
        .exchange().taskwork().asserted().concept(C_TIMELINE)
        .parents(intent.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(text=_beta_drift_text, evidence=[C_TIMELINE]),
            belief=SIEPBelief(prior=0.60, posterior=0.60,
                              revision_cause=RevisionCause.semantic_memory),
        )).build())
    siep_engine.process(beta_drift)
    _print_l9("SIEP", "2c", beta_drift)
    print(f"  ⚠  doctrine mismatch: liability-agent applied '{C_TIMELINE}' (tort), "
          f"expected '{C_SCOPE}' (contract law) → escalate to CIP")

    # ── Step 3: CIP — Contingency Repair ─────────────────────────────────────
    _hr("═")
    print("  STEP 3 — CIP   (Contingency Repair: doctrine mismatch on liability-agent)")
    _hr("═")

    cip_config = CIPEngineConfig(
        derailment_causes={
            "scope_mismatch":    ["{listener}, your reply applied the wrong legal doctrine."],
            "grounding_failure": ["{listener}, your reply did not engage the agreed legal standard."],
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
    # cip-engine is a protocol-internal component; will become the Cognition Engine
    cip = CIPProcessor("cip-engine", episode, cip_config)

    def _cip(sender: str) -> CIPMessageBuilder:
        return CIPMessageBuilder(episode, sender)

    repair_request = record("CIP", "3a · contingency (repair: liability-agent drifted to tort doctrine)",
        _cip("commercial-agent")
        .contingency().grounding().challenged().concept(C_SCOPE)
        .parents(beta_drift.header.message.id)
        .payload(CIPPayload(
            grounding=CIPGrounding(
                contingency_verified=False, contingency_score=0.0,
                repair_reason=RepairReason.scope_mismatch,
                challenges=[C_SCOPE, C_CRITERIA],
            ),
        ))
        .text("repair_required:reason=scope_mismatch:doctrine=substantial_performance:target=liability-agent")
        .build())
    _print_l9("CIP", "3a", repair_request)

    guidance = record("CIP", "3b · contingency (cip-engine issues repair — LLM)",
        cip.process(repair_request)[0])
    _print_l9("CIP", "3b", guidance)

    guidance_text = (guidance.payload.data or {}).get("utterance", {}).get("text", "") if guidance.payload else ""

    _beta_reanchor_text = _agent_llm(
        "liability-agent", _SYS_LIABILITY,
        f"You received this hard-stop repair instruction: \"{guidance_text}\"\n"
        f"Acknowledge the correction and restate your position under the contract-law "
        f"material breach standard ({C_SCOPE}), explicitly setting aside the tort doctrine. "
        "Reference SLA uptime clause 14.2.",
        f"Re-anchoring on contract-law {C_SCOPE}: breach of SLA uptime clause 14.2 constitutes "
        "material breach as it goes to the root of the agreement. Tort doctrine set aside.",
    )
    beta_reanchor = record("CIP", "3c · contingency (liability-agent re-anchors on contract law)",
        _cip("liability-agent")
        .contingency().grounding().revised().concept(C_SCOPE)
        .parents(guidance.header.message.id)
        .payload(CIPPayload(
            utterance=CIPUtterance(
                text=_beta_reanchor_text,
                evidence=[C_SCOPE, C_CRITERIA],
                addresses_evidence=[C_SCOPE, C_CRITERIA],
                turn_depth=1,
            ),
            belief=CIPBelief(prior=0.68, posterior=0.75,
                             revision_cause=CIPRevisionCause.repair_resolution),
        ))
        .text("Re-anchoring on contract-law material breach.")
        .build())
    _print_l9("CIP", "3c", beta_reanchor)

    resolved = record("CIP", "3d · commit:resolved (cip-engine closes — epistemic alignment restored)",
        cip.process(beta_reanchor)[0])
    _print_l9("CIP", "3d", resolved)

    # ── Step 4: SAB — Consequential damages clause negotiation ────────────────
    _hr("═")
    print("  STEP 4 — SAB   (Semantic Negotiation: consequential damages clause)")
    _hr("═")

    sab_episode = f"urn:ioc:episode:sab:{uuid.uuid4()}"
    session_id  = f"urn:ioc:sab:session:{uuid.uuid4()}"
    origin_buyer  = SABOrigin(actor_id="commercial-agent", attestation=None)
    origin_seller = SABOrigin(actor_id="liability-agent",  attestation=None)
    attrs         = SABAttributes(msg_created_at="2026-06-24T10:00:00Z")
    payload_hash  = "a3f8e2d1c9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1"
    content_text  = "Consequential damages clause resolved: governing interpretation and liability cap for cross-jurisdiction SaaS enterprise agreement."
    sab_topic     = (f"{content_text} | issues: {json.dumps(ISSUES)} "
                     f"| options_per_issue: {json.dumps(OPTIONS)}")
    agreed        = {"governing_interpretation": "hybrid", "damages_cap": "12_months_fees"}

    def _sab_actors(sender: str, receiver: str) -> SABActors:
        return SABActors(actors=[
            Actor(id=sender,   role="sender",   attestation=None),
            Actor(id=receiver, role="receiver", attestation=None),
        ])

    def _sab_ctx() -> Context:
        return Context(
            topic=sab_topic, epistemic=None,
            semantic=Semantic(schema_id="urn:ioc:schema:sab-l9:v1",
                              ontology_ref="urn:ioc:ontology:sab:v1"))

    def _sab_header(msg_id: str, parents: List[str],
                    sender: str, receiver: str,
                    kind: SABKind, subkind: SABSubkind) -> SABHeader:
        return SABHeader(
            protocol="SSTP", subprotocol="SAB", version="0",
            kind=kind, subkind=subkind,
            participants=_sab_actors(sender, receiver),
            message=Message(id=msg_id, parents=parents,
                            episode=sab_episode),
            policy=None, context=_sab_ctx(), attributes=attrs)

    def _neg(msg_id, dt, origin, step, t, offer, proposer, last_neg, response,
             nmi=None) -> SABPayload:
        return SABPayload(type="json-schema",
                          data=SABNegotiatePayloadData(
                              message_id=msg_id, version="0", dt_created=dt,
                              origin=origin, payload_hash=payload_hash,
                              semantic_context=NegotiateSemanticContext(
                                  session_id=session_id,
                                  sao_state=SAOState(
                                      running=True, started=True, step=step, time=t,
                                      relative_time=round(t/60, 3), timedout=False,
                                      agreement=None, n_negotiators=2,
                                      current_offer=offer, current_proposer=proposer,
                                      current_proposer_agent=proposer,
                                      n_acceptances=0, last_negotiator=last_neg),
                                  sao_response=SAOResponse(
                                      response=ResponseType(response), outcome=offer),
                                  nmi=nmi)))

    nmi = SAONMI(id=session_id, n_outcomes=N_OUTCOMES,
                 shared_time_limit=60.0, shared_n_steps=20,
                 private_time_limit=30.0, step_time_limit=10.0,
                 negotiator_time_limit=5.0, offering_is_accepting=True)

    id_i  = str(uuid.uuid4())
    id_r1 = str(uuid.uuid4()); id_r2 = str(uuid.uuid4())
    id_r3 = str(uuid.uuid4()); id_r4 = str(uuid.uuid4())
    id_c  = str(uuid.uuid4())

    record("SAB", "4a · contingency:negotiate  (commercial-agent opens SAB)",
        SAB(header=_sab_header(id_i, [], "commercial-agent", "topic:sab/sessions",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=SABPayload(type="json-schema",
                               data=SABIntentPayloadData(
                                   message_id=id_i, version="0",
                                   dt_created="2026-06-24T10:00:00Z",
                                   origin=origin_buyer, payload_hash=payload_hash,
                                   semantic_context=SemanticContext(schema_version="1.0")))))
    _print_sab("SAB", "4a", log[-1][2], "commercial-agent opens SAB — consequential damages clause")

    record("SAB", "4b · contingency:negotiate  (commercial-agent proposes us_standard / 6_months_fees)",
        SAB(header=_sab_header(id_r1, [id_i], "commercial-agent", "liability-agent",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_neg(id_r1, "2026-06-24T10:00:02Z", origin_buyer, 0, 2.1,
                         {"governing_interpretation": "us_standard", "damages_cap": "6_months_fees"},
                         "commercial-agent", None, 3, nmi=nmi)))
    _print_sab("SAB", "4b", log[-1][2], "commercial→liability: us_standard / 6_months_fees")

    record("SAB", "4c · contingency:negotiate  (liability-agent counters uk_standard / 24_months_fees)",
        SAB(header=_sab_header(id_r2, [id_i], "liability-agent", "commercial-agent",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_neg(id_r2, "2026-06-24T10:00:08Z", origin_seller, 1, 8.4,
                         {"governing_interpretation": "uk_standard", "damages_cap": "24_months_fees"},
                         "liability-agent", "commercial-agent", 1)))
    _print_sab("SAB", "4c", log[-1][2], "liability→commercial: uk_standard / 24_months_fees")

    record("SAB", "4d · contingency:negotiate  (commercial-agent concedes hybrid / 12_months_fees)",
        SAB(header=_sab_header(id_r3, [id_i], "commercial-agent", "liability-agent",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_neg(id_r3, "2026-06-24T10:00:14Z", origin_buyer, 2, 14.7,
                         agreed, "commercial-agent", "liability-agent", 1)))
    _print_sab("SAB", "4d", log[-1][2], "commercial→liability: hybrid / 12_months_fees")

    record("SAB", "4e · contingency:negotiate  (liability-agent accepts ✓)",
        SAB(header=_sab_header(id_r4, [id_i], "liability-agent", "commercial-agent",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_neg(id_r4, "2026-06-24T10:00:20Z", origin_seller, 3, 20.3,
                         agreed, "commercial-agent", "commercial-agent", 0)))
    _print_sab("SAB", "4e", log[-1][2], "liability-agent accepts ✓")

    record("SAB", "4f · commit:converged       (damages clause agreed)",
        SAB(header=_sab_header(id_c, [id_i], "commercial-agent", "topic:sab/sessions",
                               SABKind.commit, SABSubkind.converged),
            payload=SABPayload(type="json-schema",
                               data=SABCommitPayloadData(
                                   message_id=id_c, version="0",
                                   dt_created="2026-06-24T10:00:25Z",
                                   origin=origin_buyer, payload_hash=payload_hash,
                                   semantic_context=NegotiateCommitSemanticContext(
                                       session_id=session_id,
                                       outcome=Outcome("agreement"),
                                       content_text=content_text,
                                       agents_negotiating=["commercial-agent", "liability-agent"],
                                       final_agreement=[
                                           {"issue_id": "governing_interpretation", "chosen_option": "hybrid"},
                                           {"issue_id": "damages_cap",              "chosen_option": "12_months_fees"},
                                       ])))))
    _print_sab("SAB", "4f", log[-1][2], "commit:converged — governing=hybrid, cap=12_months_fees")

    # ── Summary + JSON ─────────────────────────────────────────────────────────
    _print_episode_summary(log)
    _save_json(log)


# ─────────────────────────────────────────────────────────────────────────────
# Print helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hr(char: str = "─") -> None:
    print(char * _W)


def _actor_id(msg: L9) -> str:
    actors = msg.header.participants.actors
    return actors[0].id if actors else "—"


def _print_l9(phase: str, step: str, msg: L9) -> None:
    kind_str = msg.header.kind.value + (f":{msg.header.subkind}" if msg.header.subkind else "")
    concept  = msg.header.context.topic if msg.header.context else "—"
    _hr()
    print(f"  [{phase}]  {step}  kind={kind_str}  actor={_actor_id(msg)}")
    print(f"           concept={concept[:70]}  msg={msg.header.message.id[:8]}…")
    if msg.payload and isinstance(msg.payload.data, dict):
        utt = msg.payload.data.get("utterance") or {}
        utt_text = utt.get("text", "") if isinstance(utt, dict) else ""
        if utt_text:
            print(f"           utterance=\"{utt_text[:90]}\"")
        reason = msg.payload.data.get("reason", "")
        if reason:
            print(f"           reason=\"{str(reason)[:90]}\"")


def _print_sab(phase: str, step: str, msg: SAB, note: str = "") -> None:
    kind_str = msg.header.kind.value + (f":{msg.header.subkind.value}" if msg.header.subkind else "")
    actors   = msg.header.participants.actors if msg.header.participants else []
    sender   = actors[0].id if actors else "—"
    _hr()
    print(f"  [{phase}]  {step}  kind={kind_str}  actor={sender}")
    if note:
        print(f"           {note}")
    print(f"           msg={msg.header.message.id[:8]}…")


def _print_episode_summary(log: EpisodeLog) -> None:
    _hr("═")
    print("  MULTI-PROTOCOL EPISODE SUMMARY")
    _hr("═")
    for phase, label, _ in log:
        print(f"  [{phase:<4}]  {label}")
    _hr("═")
    print(f"  Total messages: {len(log)}")
    _hr("═")


def _msg_to_dict(msg: Any) -> dict:
    if isinstance(msg, L9):
        return json.loads(msg.model_dump_json())
    if isinstance(msg, SAB):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return msg.model_dump(mode="json")
    return {}


def _save_json(log: EpisodeLog) -> None:
    out = Path(__file__).resolve().parent / "multi_protocol_run.json"
    messages = []
    for phase, label, msg in log:
        d = _msg_to_dict(msg)
        d["_demo_phase"] = phase
        d["_demo_label"] = label
        messages.append(d)
    out.write_text(json.dumps(messages, indent=2))
    print(f"\n  JSON saved → {out}")


__all__ = ["run_demo"]

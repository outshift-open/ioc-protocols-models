# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Multi-protocol SSTP demo: TFP → SIEP → CIP → SIEP → SAB

All imports from the ai-outshift-subprotocols wheel:
  ai.outshift.subprotocols.{tfp, siep, cip, sab}

Scenario: Supply-chain coordination — from team assembly to agreed delivery terms.

  Agents: agent-alpha (leads TFP + SIEP), agent-beta (participant).
  cip-engine is a protocol-internal component (future: Cognition Engine).

  Phase 1 — TFP  (Team Formation via Polling)
    agent-alpha opens a poll; agent-beta bids.
    agent-alpha bids (scope-analysis + negotiation skills).
    Both accept — team commits: converged.

  Phase 2 — SIEP (Epistemic Grounding)
    Formed team aligns on the deliverable scope concept.
    agent-alpha exchanges correctly on deliverable scope.
    agent-beta  drifts to timeline scope — mismatch detected.

  Phase 3 — CIP  (Contingency Repair)
    cip-engine (future Cognition Engine) emits LLM-powered guidance to re-anchor agent-beta.
    agent-beta re-attempts on the correct concept.
    CIP closes the branch: commit:resolved.

  Phase 4 — SIEP (Commit)
    Epistemic alignment restored — agent-alpha commits: converged.

  Phase 5 — SAB  (Negotiation)
    Team negotiates supply terms: price × delivery_speed.
    Two offer rounds → agreement → commit:converged.
"""

from __future__ import annotations

import json
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
C_SCOPE    = "concept:deliverable_scope"
C_TIMELINE = "concept:timeline"
C_CRITERIA = "concept:acceptance_criteria"

ISSUES  = ["price", "delivery_speed"]
OPTIONS = {"price": ["low", "medium", "high"],
           "delivery_speed": ["express", "standard", "deferred"]}
N_OUTCOMES = len(OPTIONS["price"]) * len(OPTIONS["delivery_speed"])

TFP_PROTOCOL  = "SSTP"
TFP_SUBPROTO  = "TFP"
TFP_VERSION   = "0"
SUBKIND_TF    = "team-formation"
SUBKIND_CONV  = "converged"

EpisodeLog = List[Tuple[str, str, Any]]
_W = 100


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

    # ── Phase 1: TFP — Team Formation ─────────────────────────────────────────
    _hr("═")
    print("  PHASE 1 — TFP   (Team Formation via Polling)")
    _hr("═")

    poll_id  = f"urn:ioc:tfp:poll:{uuid.uuid4().hex[:8]}"
    task     = TaskSpec(
        task_id="task:supply-chain-coordination",
        description="Coordinate deliverable scope alignment and supply term negotiation",
        objective="Align team on scope then agree delivery terms within one episode",
    )
    required = [
        SkillRequirement(skill="skill:scope_analysis",     min_proficiency=0.7,
                         weight=2.0, mandatory=True),
        SkillRequirement(skill="skill:timeline_analysis",  min_proficiency=0.6,
                         weight=1.5, mandatory=True),
        SkillRequirement(skill="skill:negotiation",        min_proficiency=0.6,
                         weight=1.0, mandatory=False),
    ]
    tf_topic = f"Forming a team to {task.description}"

    # 1a. Poll open — agent-alpha broadcasts to topic
    poll_msg = record("TFP", "1a · intent:team-formation  (agent-alpha opens poll)",
        _tfp_emit(episode, "agent-alpha", ["topic:tfp/polls"],
                  "intent", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.POLL_OPEN,
                             poll_id=poll_id, task=task,
                             required_skills=required,
                             reasoning_summary="Need scope + timeline + negotiation skills."),
                  topic=tf_topic))
    poll_parent = poll_msg.header.message.id
    _print_l9("TFP", "1a", poll_msg)

    # Agent profiles (private — recruiter only learns via bids)
    alpha_offer = CandidateOffer(
        skills=[SkillClaim(skill="skill:scope_analysis",    proficiency=0.92),
                SkillClaim(skill="skill:negotiation",       proficiency=0.80)],
        availability=0.9, fit_score=0.88)
    beta_offer = CandidateOffer(
        skills=[SkillClaim(skill="skill:timeline_analysis", proficiency=0.85),
                SkillClaim(skill="skill:scope_analysis",    proficiency=0.65)],
        availability=0.8, fit_score=0.75)

    # 1b. agent-alpha bids
    alpha_bid = record("TFP", "1b · exchange:team-formation  (agent-alpha bids)",
        _tfp_emit(episode, "agent-alpha", ["agent-alpha"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.BID, poll_id=poll_id,
                             offer=alpha_offer,
                             reasoning_summary=f"fit≈{_tfp_fit(required, alpha_offer)}"),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1b", alpha_bid)

    # 1c. agent-beta bids
    beta_bid = record("TFP", "1c · exchange:team-formation  (agent-beta bids)",
        _tfp_emit(episode, "agent-beta", ["agent-alpha"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.BID, poll_id=poll_id,
                             offer=beta_offer,
                             reasoning_summary=f"fit≈{_tfp_fit(required, beta_offer)}"),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1c", beta_bid)

    # 1d. Coordinator selects team
    bids = {"agent-alpha": alpha_offer, "agent-beta": beta_offer}
    selection = _tfp_select(required, bids)
    select_msg = record("TFP", "1d · exchange:team-formation  (agent-alpha selects team)",
        _tfp_emit(episode, "agent-alpha", ["agent-alpha", "agent-beta"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.SELECT, poll_id=poll_id,
                             selection=selection,
                             reasoning_summary=f"coverage={selection.coverage} fit={selection.aggregate_fit}"),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1d", select_msg)
    print(f"           team={selection.members}  coverage={selection.coverage}")

    # 1e. agent-alpha accepts
    record("TFP", "1e · exchange:team-formation  (agent-alpha accepts)",
        _tfp_emit(episode, "agent-alpha", ["agent-alpha"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.ACCEPT, poll_id=poll_id,
                             reason="Skills match; I have capacity."),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1e", log[-1][2])

    # 1f. agent-beta accepts
    record("TFP", "1f · exchange:team-formation  (agent-beta accepts)",
        _tfp_emit(episode, "agent-beta", ["agent-alpha"],
                  "exchange", SUBKIND_TF,
                  TFPPayload(operation=TFPOperation.ACCEPT, poll_id=poll_id,
                             reason="Scope analysis and timeline skills engaged; joining."),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1f", log[-1][2])

    # 1g. Commit: converged
    record("TFP", "1g · commit:converged          (team formed ✓)",
        _tfp_emit(episode, "agent-alpha", ["topic:tfp/polls"],
                  "commit", SUBKIND_CONV,
                  TFPPayload(operation=TFPOperation.FORM_CONVERGED, poll_id=poll_id,
                             selection=selection,
                             reasoning_summary=f"Team formed: {selection.members}"),
                  parent_id=poll_parent, topic=tf_topic))
    _print_l9("TFP", "1g", log[-1][2])

    # ── Phase 2: SIEP — Epistemic Grounding ───────────────────────────────────
    _hr("═")
    print("  PHASE 2 — SIEP  (Epistemic Grounding)")
    _hr("═")

    siep_engine = SIEPEngine("agent-alpha", episode)

    def _siep(sender: str) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(episode, sender)

    intent = record("SIEP", "2a · intent      (agent-alpha opens episode)",
        _siep("agent-alpha").intent().team_process().concept(C_SCOPE).build())
    siep_engine.process(intent)
    _print_l9("SIEP", "2a", intent)

    alpha_exchange = record("SIEP", "2b · exchange    (agent-alpha aligns on scope)",
        _siep("agent-alpha")
        .exchange().taskwork().asserted().concept(C_SCOPE)
        .parents(intent.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C_SCOPE, C_CRITERIA]),
            belief=SIEPBelief(prior=0.75, posterior=0.75,
                              revision_cause=RevisionCause.semantic_memory),
        )).build())
    siep_engine.process(alpha_exchange)
    _print_l9("SIEP", "2b", alpha_exchange)

    beta_drift = record("SIEP", "2c · exchange    (agent-beta drifts to timeline ⚠)",
        _siep("agent-beta")
        .exchange().taskwork().asserted().concept(C_TIMELINE)
        .parents(intent.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C_TIMELINE]),
            belief=SIEPBelief(prior=0.55, posterior=0.55,
                              revision_cause=RevisionCause.semantic_memory),
        )).build())
    siep_engine.process(beta_drift)
    _print_l9("SIEP", "2c", beta_drift)
    print(f"  ⚠  scope mismatch: beta replied on '{C_TIMELINE}', "
          f"expected '{C_SCOPE}' → escalate to CIP")

    # ── Phase 3: CIP — Contingency Repair ─────────────────────────────────────
    _hr("═")
    print("  PHASE 3 — CIP   (Contingency Repair: scope mismatch on agent-beta)")
    _hr("═")

    cip_config = CIPEngineConfig(
        derailment_causes={
            "scope_mismatch":    ["{listener}, your reply drifted to timeline scope."],
            "grounding_failure": ["{listener}, your reply did not engage the prior evidence."],
        },
        nonsense_derailment_causes=set(),
        repair_utterances={
            "repair_hard_stop":      "{listener}, stop and restate only against deliverable scope.",
            "repair_anchor":         "{listener}, re-anchor on the deliverable concept.",
            "repair_alignment":      "{listener}, restate within deliverable scope.",
            "request_clarification": "{listener}, clarify how your reply answers deliverable scope.",
            "default":               "{listener}, remain within deliverable scope.",
        },
        normal_utterance_template="{listener}, continue within the shared deliverable scope.",
    )
    # cip-engine is a protocol-internal component; will become the Cognition Engine
    cip = CIPProcessor("cip-engine", episode, cip_config)

    def _cip(sender: str) -> CIPMessageBuilder:
        return CIPMessageBuilder(episode, sender)

    repair_request = record("CIP", "3a · contingency (repair request: beta drifted)",
        _cip("agent-alpha")
        .contingency().grounding().challenged().concept(C_SCOPE)
        .parents(beta_drift.header.message.id)
        .payload(CIPPayload(
            grounding=CIPGrounding(
                contingency_verified=False, contingency_score=0.0,
                repair_reason=RepairReason.scope_mismatch,
                challenges=[C_SCOPE, C_CRITERIA],
            ),
        ))
        .text("repair_required:reason=scope_mismatch:target=agent-beta")
        .build())
    _print_l9("CIP", "3a", repair_request)

    guidance = record("CIP", "3b · contingency (cip guidance — LLM)",
        cip.process(repair_request)[0])
    _print_l9("CIP", "3b", guidance)

    beta_reanchor = record("CIP", "3c · contingency (agent-beta re-anchors on scope)",
        _cip("agent-beta")
        .contingency().grounding().revised().concept(C_SCOPE)
        .parents(guidance.header.message.id)
        .payload(CIPPayload(
            utterance=CIPUtterance(
                text="Re-anchoring on deliverable scope: confirms spec and criteria.",
                evidence=[C_SCOPE, C_CRITERIA],
                addresses_evidence=[C_SCOPE, C_CRITERIA],
                turn_depth=1,
            ),
            belief=CIPBelief(prior=0.68, posterior=0.68,
                             revision_cause=CIPRevisionCause.repair_resolution),
        ))
        .text("Re-anchoring on deliverable scope.")
        .build())
    _print_l9("CIP", "3c", beta_reanchor)

    resolved = record("CIP", "3d · commit:resolved (cip closes branch)",
        cip.process(beta_reanchor)[0])
    _print_l9("CIP", "3d", resolved)

    # ── Phase 4: SIEP — Commit ────────────────────────────────────────────────
    _hr("═")
    print("  PHASE 4 — SIEP  (Commit: epistemic alignment restored)")
    _hr("═")

    siep_commit = record("SIEP", "4a · commit      (agent-alpha confirms alignment)",
        _siep("agent-alpha")
        .commit_converged().grounding().concept(C_SCOPE)
        .parents(intent.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(
                evidence=[C_SCOPE, C_CRITERIA],
                addresses_evidence=[C_SCOPE, C_CRITERIA],
            ),
            belief=SIEPBelief(prior=0.80, posterior=0.85,
                              revision_cause=RevisionCause.grounded_argument),
        )).build())
    siep_engine.process(siep_commit)
    _print_l9("SIEP", "4a", siep_commit)

    # ── Phase 5: SAB — Negotiate supply terms ─────────────────────────────────
    _hr("═")
    print("  PHASE 5 — SAB   (Negotiation: price × delivery_speed)")
    _hr("═")

    sab_episode = f"urn:ioc:episode:sab:{uuid.uuid4()}"
    session_id  = f"urn:ioc:sab:session:{uuid.uuid4()}"
    origin_buyer  = SABOrigin(actor_id="agent-alpha", attestation=None)
    origin_seller = SABOrigin(actor_id="agent-beta",  attestation=None)
    attrs         = SABAttributes(msg_created_at="2026-06-24T10:00:00Z")
    payload_hash  = "a3f8e2d1c9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1"
    content_text  = "Team negotiates supply price and delivery speed for the agreed deliverable scope."
    sab_topic     = (f"{content_text} | issues: {json.dumps(ISSUES)} "
                     f"| options_per_issue: {json.dumps(OPTIONS)}")
    agreed        = {"price": "medium", "delivery_speed": "standard"}

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

    record("SAB", "5a · contingency:negotiate  (agent-alpha opens SAB)",
        SAB(header=_sab_header(id_i, [], "agent-alpha", "topic:sab/sessions",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=SABPayload(type="json-schema",
                               data=SABIntentPayloadData(
                                   message_id=id_i, version="0",
                                   dt_created="2026-06-24T10:00:00Z",
                                   origin=origin_buyer, payload_hash=payload_hash,
                                   semantic_context=SemanticContext(schema_version="1.0")))))
    _print_sab("SAB", "5a", log[-1][2], "agent-alpha opens SAB session")

    record("SAB", "5b · contingency:negotiate  (agent-alpha offers high/express)",
        SAB(header=_sab_header(id_r1, [id_i], "agent-alpha", "agent-beta",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_neg(id_r1, "2026-06-24T10:00:02Z", origin_buyer, 0, 2.1,
                         {"price": "high", "delivery_speed": "express"},
                         "agent-alpha", None, 3, nmi=nmi)))
    _print_sab("SAB", "5b", log[-1][2], "alpha→beta: price=high, delivery=express")

    record("SAB", "5c · contingency:negotiate  (agent-beta counters low/deferred)",
        SAB(header=_sab_header(id_r2, [id_i], "agent-beta", "agent-alpha",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_neg(id_r2, "2026-06-24T10:00:08Z", origin_seller, 1, 8.4,
                         {"price": "low", "delivery_speed": "deferred"},
                         "agent-beta", "agent-alpha", 1)))
    _print_sab("SAB", "5c", log[-1][2], "beta→alpha: price=low, delivery=deferred")

    record("SAB", "5d · contingency:negotiate  (agent-alpha concedes medium/standard)",
        SAB(header=_sab_header(id_r3, [id_i], "agent-alpha", "agent-beta",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_neg(id_r3, "2026-06-24T10:00:14Z", origin_buyer, 2, 14.7,
                         agreed, "agent-alpha", "agent-beta", 1)))
    _print_sab("SAB", "5d", log[-1][2], "alpha→beta: price=medium, delivery=standard")

    record("SAB", "5e · contingency:negotiate  (agent-beta accepts)",
        SAB(header=_sab_header(id_r4, [id_i], "agent-beta", "agent-alpha",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_neg(id_r4, "2026-06-24T10:00:20Z", origin_seller, 3, 20.3,
                         agreed, "agent-alpha", "agent-alpha", 0)))
    _print_sab("SAB", "5e", log[-1][2], "beta accepts ✓")

    record("SAB", "5f · commit:converged       (supply terms agreed)",
        SAB(header=_sab_header(id_c, [id_i], "agent-alpha", "topic:sab/sessions",
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
                                       agents_negotiating=["agent-alpha", "agent-beta"],
                                       final_agreement=[
                                           {"issue_id": "price",          "chosen_option": "medium"},
                                           {"issue_id": "delivery_speed", "chosen_option": "standard"},
                                       ])))))
    _print_sab("SAB", "5f", log[-1][2], "commit:converged — price=medium, delivery=standard")

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

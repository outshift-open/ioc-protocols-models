# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Multi-protocol SSTP demo: SIEP → CIP → SAB

Imports exclusively from the ai-outshift-subprotocols wheel:
  ai.outshift.subprotocols.siep
  ai.outshift.subprotocols.cip
  ai.outshift.subprotocols.sab

Scenario: Supply-chain coordination between a coordinator and two agents.

  Phase 1 — SIEP (Epistemic Grounding, kind=intent/exchange)
    Coordinator opens the episode with an intent.
    Agent-alpha aligns on the deliverable scope (exchange).
    Agent-beta drifts to timeline scope — epistemic mismatch detected.

  Phase 2 — CIP (Contingency Repair, kind=contingency→commit:resolved)
    CIP receives the off-scope exchange as a repair request.
    CIP emits LLM-powered guidance: re-anchor on deliverable concept.
    Agent-beta re-attempts with correct scope.
    CIP closes the branch: commit:resolved.

  Phase 3 — SIEP (Commit, kind=commit:converged)
    Epistemic alignment restored — coordinator emits a commit.

  Phase 4 — SAB (Negotiation, kind=contingency:negotiate→commit:converged)
    Agents negotiate supply terms (price × delivery_speed).
    Two counter-offer rounds → agreed → commit:converged.
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
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── wheel: L9 data model ──────────────────────────────────────────────────────
from ai.outshift.data_model import L9, Actor, Context, Message, Semantic

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

EpisodeLog = List[Tuple[str, str, Any]]
_W = 100


# ─────────────────────────────────────────────────────────────────────────────
# Main demo
# ─────────────────────────────────────────────────────────────────────────────

def run_demo() -> None:
    """Run the full multi-protocol episode: SIEP → CIP → SIEP → SAB."""
    episode = f"urn:ioc:episode:{uuid.uuid4()}"
    log: EpisodeLog = []

    def record(phase: str, label: str, msg: Any) -> Any:
        log.append((phase, label, msg))
        return msg

    # ── Phase 1: SIEP — Epistemic Grounding ──────────────────────────────────
    _hr("═")
    print("  PHASE 1 — SIEP  (Epistemic Grounding)")
    _hr("═")

    siep_engine = SIEPEngine("coordinator", episode)

    def _siep(sender: str) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(episode, sender)

    # 1a. Intent: coordinator opens the episode
    intent = record("SIEP", "1a · intent      (coordinator opens episode)",
        _siep("coordinator").intent().team_process().concept(C_SCOPE).build())
    siep_engine.process(intent)
    _print_l9("SIEP", "1a", intent)

    # 1b. Exchange: agent-alpha aligns on deliverable scope
    alpha_exchange = record("SIEP", "1b · exchange    (agent-alpha aligns on scope)",
        _siep("agent-alpha")
        .exchange().taskwork().asserted().concept(C_SCOPE)
        .parents(intent.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C_SCOPE, C_CRITERIA]),
            belief=SIEPBelief(prior=0.75, posterior=0.75,
                              revision_cause=RevisionCause.semantic_memory),
        ))
        .build())
    siep_engine.process(alpha_exchange)
    _print_l9("SIEP", "1b", alpha_exchange)

    # 1c. Exchange: agent-beta drifts to timeline scope
    beta_drift = record("SIEP", "1c · exchange    (agent-beta drifts to timeline ⚠)",
        _siep("agent-beta")
        .exchange().taskwork().asserted().concept(C_TIMELINE)
        .parents(intent.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C_TIMELINE]),
            belief=SIEPBelief(prior=0.55, posterior=0.55,
                              revision_cause=RevisionCause.semantic_memory),
        ))
        .build())
    siep_engine.process(beta_drift)
    _print_l9("SIEP", "1c", beta_drift)
    print(f"  ⚠  scope mismatch: beta replied on '{C_TIMELINE}', "
          f"expected '{C_SCOPE}' → escalate to CIP")

    # ── Phase 2: CIP — Repair agent-beta's scope mismatch ────────────────────
    _hr("═")
    print("  PHASE 2 — CIP   (Contingency Repair: scope mismatch on agent-beta)")
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
    cip = CIPProcessor("cip-agent", episode, cip_config)

    def _cip(sender: str) -> CIPMessageBuilder:
        return CIPMessageBuilder(episode, sender)

    # 2a. Contingency repair request
    repair_request = record("CIP", "2a · contingency (repair request: beta drifted)",
        _cip("agent-alpha")
        .contingency().grounding().challenged().concept(C_SCOPE)
        .parents(beta_drift.header.message.id)
        .payload(CIPPayload(
            grounding=CIPGrounding(
                contingency_verified=False,
                contingency_score=0.0,
                repair_reason=RepairReason.scope_mismatch,
                challenges=[C_SCOPE, C_CRITERIA],
            ),
        ))
        .text("repair_required:reason=scope_mismatch:target=agent-beta")
        .build())
    _print_l9("CIP", "2a", repair_request)

    # 2b. CIP guidance (LLM-powered)
    guidance = record("CIP", "2b · contingency (cip guidance)",
        cip.process(repair_request)[0])
    _print_l9("CIP", "2b", guidance)

    # 2c. Agent-beta re-attempts, re-anchored on deliverable scope
    beta_reanchor = record("CIP", "2c · contingency (agent-beta re-anchors on scope)",
        _cip("agent-beta")
        .contingency().grounding().revised().concept(C_SCOPE)
        .parents(guidance.header.message.id)
        .payload(CIPPayload(
            utterance=CIPUtterance(
                text="Re-anchoring on deliverable scope: confirms spec and acceptance criteria.",
                evidence=[C_SCOPE, C_CRITERIA],
                addresses_evidence=[C_SCOPE, C_CRITERIA],
                turn_depth=1,
            ),
            belief=CIPBelief(
                prior=0.68, posterior=0.68,
                revision_cause=CIPRevisionCause.repair_resolution,
            ),
        ))
        .text("Re-anchoring: confirms spec and acceptance criteria against deliverable scope.")
        .build())
    _print_l9("CIP", "2c", beta_reanchor)

    # 2d. CIP commit:resolved
    resolved = record("CIP", "2d · commit:resolved (cip closes branch)",
        cip.process(beta_reanchor)[0])
    _print_l9("CIP", "2d", resolved)

    # ── Phase 3: SIEP — Commit ────────────────────────────────────────────────
    _hr("═")
    print("  PHASE 3 — SIEP  (Commit: epistemic alignment restored after repair)")
    _hr("═")

    siep_commit = record("SIEP", "3a · commit      (coordinator confirms alignment)",
        _siep("coordinator")
        .commit_converged().grounding().concept(C_SCOPE)
        .parents(intent.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(
                evidence=[C_SCOPE, C_CRITERIA],
                addresses_evidence=[C_SCOPE, C_CRITERIA],
            ),
            belief=SIEPBelief(prior=0.80, posterior=0.85,
                              revision_cause=RevisionCause.grounded_argument),
        ))
        .build())
    siep_engine.process(siep_commit)
    _print_l9("SIEP", "3a", siep_commit)

    # ── Phase 4: SAB — Negotiate supply terms ────────────────────────────────
    _hr("═")
    print("  PHASE 4 — SAB   (Negotiation: price × delivery_speed)")
    _hr("═")

    sab_episode = f"urn:ioc:episode:sab:{uuid.uuid4()}"
    session_id  = f"urn:ioc:sab:session:{uuid.uuid4()}"
    origin_buyer  = SABOrigin(actor_id="agent-alpha", attestation=None)
    origin_seller = SABOrigin(actor_id="agent-beta",  attestation=None)
    attrs         = SABAttributes(msg_created_at="2026-06-24T10:00:00Z")
    payload_hash  = "a3f8e2d1c9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1"
    content_text  = "Agents negotiate supply price and delivery speed for the agreed deliverable scope."
    sab_topic     = (f"{content_text} | issues: {json.dumps(ISSUES)} "
                     f"| options_per_issue: {json.dumps(OPTIONS)}")

    def _sab_actors(sender: str, receiver: str) -> SABActors:
        return SABActors(actors=[
            Actor(id=sender,   role="sender",   attestation=None),
            Actor(id=receiver, role="receiver", attestation=None),
        ])

    def _sab_ctx() -> Context:
        return Context(
            topic=sab_topic, epistemic=None,
            semantic=Semantic(schema_id="urn:ioc:schema:sab-l9:v1",
                              ontology_ref="urn:ioc:ontology:sab:v1"),
        )

    def _sab_header(msg_id: str, parents: List[str],
                    sender: str, receiver: str,
                    kind: SABKind, subkind: SABSubkind) -> SABHeader:
        return SABHeader(
            protocol="SSTP", subprotocol="SAB", version="0",
            kind=kind, subkind=subkind,
            participants=_sab_actors(sender, receiver),
            message=Message(id=msg_id, parents=json.dumps(parents), episode=sab_episode),
            policy=None, context=_sab_ctx(), attributes=attrs,
        )

    def _sao(step: int, t: float, offer: dict, proposer: str,
             last_neg: Optional[str], running: bool,
             agreement: Optional[dict] = None, n_acc: int = 0) -> SAOState:
        return SAOState(
            running=running, started=True, step=step, time=t,
            relative_time=round(t / 60.0, 3), timedout=False,
            agreement=agreement, n_negotiators=2,
            current_offer=offer, current_proposer=proposer,
            current_proposer_agent=proposer, n_acceptances=n_acc,
            last_negotiator=last_neg,
        )

    def _negotiate_payload(msg_id: str, dt: str, origin: SABOrigin,
                           step: int, t: float, offer: dict,
                           proposer: str, last_neg: Optional[str],
                           response: int,
                           nmi: Optional[SAONMI] = None) -> SABPayload:
        return SABPayload(type="json-schema",
                          data=SABNegotiatePayloadData(
                              message_id=msg_id, version="0", dt_created=dt,
                              origin=origin, payload_hash=payload_hash,
                              semantic_context=NegotiateSemanticContext(
                                  session_id=session_id,
                                  sao_state=_sao(step, t, offer, proposer, last_neg, True),
                                  sao_response=SAOResponse(
                                      response=ResponseType(response), outcome=offer),
                                  nmi=nmi)))

    nmi = SAONMI(id=session_id, n_outcomes=N_OUTCOMES,
                 shared_time_limit=60.0, shared_n_steps=20,
                 private_time_limit=30.0, step_time_limit=10.0,
                 negotiator_time_limit=5.0, offering_is_accepting=True)
    agreed = {"price": "medium", "delivery_speed": "standard"}

    id_intent = str(uuid.uuid4())
    id_r1 = str(uuid.uuid4()); id_r2 = str(uuid.uuid4())
    id_r3 = str(uuid.uuid4()); id_r4 = str(uuid.uuid4())
    id_commit = str(uuid.uuid4())

    # 4a. Intent — open SAB session
    sab_intent = record("SAB", "4a · contingency:negotiate  (agent-alpha opens SAB)",
        SAB(
            header=_sab_header(id_intent, [], "agent-alpha", "topic:sab/sessions",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=SABPayload(type="json-schema",
                               data=SABIntentPayloadData(
                                   message_id=id_intent, version="0",
                                   dt_created="2026-06-24T10:00:00Z",
                                   origin=origin_buyer, payload_hash=payload_hash,
                                   semantic_context=SemanticContext(schema_version="1.0")))))
    _print_sab("SAB", "4a", sab_intent, "agent-alpha opens SAB session")

    # 4b. Round 1 — agent-alpha opens high
    sab_r1 = record("SAB", "4b · contingency:negotiate  (agent-alpha offers high/express)",
        SAB(header=_sab_header(id_r1, [id_intent], "agent-alpha", "agent-beta",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_negotiate_payload(id_r1, "2026-06-24T10:00:02Z", origin_buyer,
                                       0, 2.1, {"price": "high", "delivery_speed": "express"},
                                       "agent-alpha", None, 3, nmi=nmi)))
    _print_sab("SAB", "4b", sab_r1, "alpha→beta: price=high, delivery=express")

    # 4c. Round 2 — agent-beta counters low
    sab_r2 = record("SAB", "4c · contingency:negotiate  (agent-beta counters low/deferred)",
        SAB(header=_sab_header(id_r2, [id_intent], "agent-beta", "agent-alpha",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_negotiate_payload(id_r2, "2026-06-24T10:00:08Z", origin_seller,
                                       1, 8.4, {"price": "low", "delivery_speed": "deferred"},
                                       "agent-beta", "agent-alpha", 1)))
    _print_sab("SAB", "4c", sab_r2, "beta→alpha: price=low, delivery=deferred")

    # 4d. Round 3 — agent-alpha concedes to medium/standard
    sab_r3 = record("SAB", "4d · contingency:negotiate  (agent-alpha concedes medium/standard)",
        SAB(header=_sab_header(id_r3, [id_intent], "agent-alpha", "agent-beta",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_negotiate_payload(id_r3, "2026-06-24T10:00:14Z", origin_buyer,
                                       2, 14.7, agreed, "agent-alpha", "agent-beta", 1)))
    _print_sab("SAB", "4d", sab_r3, "alpha→beta: price=medium, delivery=standard")

    # 4e. Round 4 — agent-beta accepts (ResponseType 0 = accept)
    sab_r4 = record("SAB", "4e · contingency:negotiate  (agent-beta accepts)",
        SAB(header=_sab_header(id_r4, [id_intent], "agent-beta", "agent-alpha",
                               SABKind.contingency, SABSubkind.negotiate),
            payload=_negotiate_payload(id_r4, "2026-06-24T10:00:20Z", origin_seller,
                                       3, 20.3, agreed, "agent-alpha", "agent-alpha", 0)))
    _print_sab("SAB", "4e", sab_r4, "beta accepts ✓")

    # 4f. Commit:converged
    sab_commit = record("SAB", "4f · commit:converged       (supply terms agreed)",
        SAB(
            header=_sab_header(id_commit, [id_intent], "agent-alpha", "topic:sab/sessions",
                               SABKind.commit, SABSubkind.converged),
            payload=SABPayload(type="json-schema",
                               data=SABCommitPayloadData(
                                   message_id=id_commit, version="0",
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
    _print_sab("SAB", "4f", sab_commit, "commit:converged — price=medium, delivery=standard")

    # ── Summary + JSON output ─────────────────────────────────────────────────
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
    print(f"           concept={concept}  msg={msg.header.message.id[:8]}…")


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

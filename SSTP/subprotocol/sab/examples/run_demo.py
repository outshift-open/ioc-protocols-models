#!/usr/bin/env python3

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Generate SAB example message dumps for the Quick Deal mission.

Produces two files in the same directory:
  quick_deal_agreement.json    — 6 messages, converged after 2 counter-offers
  quick_deal_disagreement.json — 8 messages, step budget exhausted

Run from anywhere:
  python3 SSTP/subprotocol/sab/examples/run_demo.py
  # or, from this directory:
  python3 run_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.primitives import Actor, Context, Message, Semantic
from SSTP.subprotocol.sab.language_bindings.python.data_model import (
    SAB,
    SABActors,
    SABAttributes,
    SABCommitPayloadData,
    SABHeader,
    SABIntentPayloadData,
    SABNegotiatePayloadData,
    SABOrigin,
    SABPayload,
    NegotiateCommitSemanticContext,
    NegotiateSemanticContext,
    Outcome,
    ResponseType,
    SAOResponse,
    SAOState,
    SAONMI,
    SemanticContext,
)

# ---------------------------------------------------------------------------
# Mission constants
# ---------------------------------------------------------------------------

EPISODE_AGREEMENT    = "urn:ioc:episode:supply-order-urgent-2026-001"
EPISODE_DISAGREEMENT = "urn:ioc:episode:supply-order-urgent-2026-002"
SESSION_AGREEMENT    = "urn:ioc:sab:session:qd-2026-06-22-001"
SESSION_DISAGREEMENT = "urn:ioc:sab:session:qd-2026-06-22-002"

CONTENT_TEXT = (
    "Two parties need to agree on price and delivery speed "
    "for an urgent supply order."
)
ISSUES   = ["price", "delivery_speed"]
OPTIONS  = {"price": ["low", "medium", "high"],
            "delivery_speed": ["express", "standard", "deferred"]}
TOPIC    = (
    f"{CONTENT_TEXT} | issues: {json.dumps(ISSUES)} "
    f"| options_per_issue: {json.dumps(OPTIONS)}"
)
CONTEXT_SEMANTIC = Semantic(
    schema_id="urn:ioc:schema:sab-l9:v1",
    ontology_ref="urn:ioc:ontology:sab:v1",
)
ORIGIN_BUYER  = SABOrigin(actor_id="agent-buyer",  attestation=None)
ORIGIN_SELLER = SABOrigin(actor_id="agent-seller", attestation=None)
PAYLOAD_HASH  = "a3f8e2d1c9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1"
ATTRS         = SABAttributes(msg_created_at="2026-06-22T09:58:00Z")

N_OUTCOMES = len(OPTIONS["price"]) * len(OPTIONS["delivery_speed"])  # 9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _actors(sender: str, receiver: str) -> SABActors:
    return SABActors(actors=[
        Actor(id=sender,   role="sender",   attestation=None),
        Actor(id=receiver, role="receiver", attestation=None),
    ])


def _context() -> Context:
    return Context(topic=TOPIC, epistemic=None, semantic=CONTEXT_SEMANTIC)


def _header(
    msg_id: str,
    parents: list[str],
    episode: str,
    sender: str,
    receiver: str,
    kind: str,
    subkind: str,
) -> SABHeader:
    return SABHeader(
        protocol="SSTP",
        subprotocol="SAB",
        version="0",
        kind=kind,
        subkind=subkind,
        participants=_actors(sender, receiver),
        message=Message(id=msg_id, parents=parents, episode=episode),
        policy=None,
        context=_context(),
        attributes=ATTRS,
    )


def _nmi(session_id: str, n_steps: int) -> SAONMI:
    return SAONMI(
        id=session_id,
        n_outcomes=N_OUTCOMES,
        shared_time_limit=60.0,
        shared_n_steps=n_steps,
        private_time_limit=30.0,
        step_time_limit=10.0,
        negotiator_time_limit=5.0,
        offering_is_accepting=True,
    )


def _sao_state(
    step: int,
    time: float,
    offer: dict,
    proposer: str,
    last_negotiator: str | None,
    running: bool,
    timedout: bool = False,
    agreement: dict | None = None,
    n_acceptances: int = 0,
) -> SAOState:
    return SAOState(
        running=running,
        started=True,
        step=step,
        time=time,
        relative_time=round(time / 60.0, 3),
        timedout=timedout,
        agreement=agreement,
        n_negotiators=2,
        current_offer=offer,
        current_proposer=proposer,
        current_proposer_agent=proposer,
        n_acceptances=n_acceptances,
        last_negotiator=last_negotiator,
    )


def _negotiate_payload(
    msg_id: str,
    dt: str,
    origin: SABOrigin,
    session_id: str,
    sao_state: SAOState,
    response: int,
    offer: dict,
    nmi: SAONMI | None = None,
) -> SABPayload:
    sem_ctx = NegotiateSemanticContext(
        session_id=session_id,
        sao_state=sao_state,
        sao_response=SAOResponse(response=ResponseType(response), outcome=offer),
        nmi=nmi,
    )
    data = SABNegotiatePayloadData(
        message_id=msg_id,
        version="0",
        dt_created=dt,
        origin=origin,
        payload_hash=PAYLOAD_HASH,
        semantic_context=sem_ctx,
    )
    return SABPayload(type="json-schema", data=data.model_dump())


def _commit_payload(
    msg_id: str,
    dt: str,
    origin: SABOrigin,
    session_id: str,
    outcome: str,
    final_agreement: list[dict] | None,
    agents: list[str],
) -> SABPayload:
    sem_ctx = NegotiateCommitSemanticContext(
        session_id=session_id,
        outcome=Outcome(outcome),
        content_text=CONTENT_TEXT,
        agents_negotiating=agents,
        final_agreement=final_agreement,
    )
    data = SABCommitPayloadData(
        message_id=msg_id,
        version="0",
        dt_created=dt,
        origin=origin,
        payload_hash=PAYLOAD_HASH,
        semantic_context=sem_ctx,
    )
    return SABPayload(type="json-schema", data=data.model_dump())


def _to_dict(msg: SAB) -> dict:
    return msg.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Agreement scenario — converged after 2 counter-offers (4 negotiate rounds)
# ---------------------------------------------------------------------------

def build_agreement() -> list[dict]:
    ep  = EPISODE_AGREEMENT
    sid = SESSION_AGREEMENT

    intent_id = "f1a2b3c4-d5e6-f780-9abc-def012345678"
    r1_id     = "b2c3d4e5-f6a7-8901-bcde-f01234567890"
    r2_id     = "c3d4e5f6-a7b8-9012-cdef-012345678901"
    r3_id     = "d4e5f6a7-b8c9-0123-def0-123456789012"
    r4_id     = "e5f6a7b8-c9d0-1234-ef01-234567890123"
    commit_id = "f6a7b8c9-d0e1-2345-f012-345678901234"

    agreed = {"price": "medium", "delivery_speed": "standard"}

    intent = SAB(
        header=_header(intent_id, [], ep, "agent-buyer", "topic:sab/sessions",
                       "contingency", "negotiate"),
        payload=SABPayload(
            type="json-schema",
            data=SABIntentPayloadData(
                message_id=intent_id,
                version="0",
                dt_created="2026-06-22T10:00:00Z",
                origin=ORIGIN_BUYER,
                payload_hash=PAYLOAD_HASH,
                semantic_context=SemanticContext(schema_version="1.0"),
            ).model_dump(),
        ),
    )

    r1_offer = {"price": "high", "delivery_speed": "express"}
    round1 = SAB(
        header=_header(r1_id, [intent_id], ep, "agent-buyer", "agent-seller",
                       "contingency", "negotiate"),
        payload=_negotiate_payload(
            r1_id, "2026-06-22T10:00:02Z", ORIGIN_BUYER, sid,
            _sao_state(0, 2.1, r1_offer, "agent-buyer", None, True),
            response=3, offer=r1_offer,
            nmi=_nmi(sid, n_steps=40),
        ),
    )

    r2_offer = {"price": "low", "delivery_speed": "deferred"}
    round2 = SAB(
        header=_header(r2_id, [intent_id], ep, "agent-seller", "agent-buyer",
                       "contingency", "negotiate"),
        payload=_negotiate_payload(
            r2_id, "2026-06-22T10:00:08Z", ORIGIN_SELLER, sid,
            _sao_state(1, 8.4, r2_offer, "agent-seller", "agent-buyer", True),
            response=1, offer=r2_offer,
        ),
    )

    r3_offer = {"price": "medium", "delivery_speed": "standard"}
    round3 = SAB(
        header=_header(r3_id, [intent_id], ep, "agent-buyer", "agent-seller",
                       "contingency", "negotiate"),
        payload=_negotiate_payload(
            r3_id, "2026-06-22T10:00:14Z", ORIGIN_BUYER, sid,
            _sao_state(2, 14.7, r3_offer, "agent-buyer", "agent-seller", True),
            response=1, offer=r3_offer,
        ),
    )

    round4 = SAB(
        header=_header(r4_id, [intent_id], ep, "agent-seller", "agent-buyer",
                       "contingency", "negotiate"),
        payload=_negotiate_payload(
            r4_id, "2026-06-22T10:00:20Z", ORIGIN_SELLER, sid,
            _sao_state(3, 20.3, agreed, "agent-buyer", "agent-buyer",
                       running=False, agreement=agreed, n_acceptances=1),
            response=0, offer=agreed,
        ),
    )

    commit = SAB(
        header=_header(commit_id, [intent_id], ep, "agent-buyer", "topic:sab/sessions",
                       "commit", "converged"),
        payload=_commit_payload(
            commit_id, "2026-06-22T10:00:25Z", ORIGIN_BUYER, sid,
            outcome="agreement",
            final_agreement=[
                {"issue_id": "price",          "chosen_option": "medium"},
                {"issue_id": "delivery_speed", "chosen_option": "standard"},
            ],
            agents=["agent-buyer", "agent-seller"],
        ),
    )

    return [_to_dict(m) for m in [intent, round1, round2, round3, round4, commit]]


# ---------------------------------------------------------------------------
# Disagreement scenario — step budget (6) exhausted, no agreement
# ---------------------------------------------------------------------------

def build_disagreement() -> list[dict]:
    ep  = EPISODE_DISAGREEMENT
    sid = SESSION_DISAGREEMENT

    intent_id = "a0b1c2d3-e4f5-6789-abcd-ef0123456789"
    r1_id     = "b1c2d3e4-f5a6-7890-bcde-f01234567890"
    r2_id     = "c2d3e4f5-a6b7-8901-cdef-012345678901"
    r3_id     = "d3e4f5a6-b7c8-9012-def0-123456789012"
    r4_id     = "e4f5a6b7-c8d9-0123-ef01-234567890123"
    r5_id     = "f5a6b7c8-d9e0-1234-f012-345678901234"
    r6_id     = "a6b7c8d9-e0f1-2345-0123-456789012345"
    commit_id = "b7c8d9e0-f1a2-3456-1234-567890123456"

    ph = "b4f9e3c2d1a0f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3"

    def _payload_hash_override(data: SABNegotiatePayloadData) -> SABPayload:
        d = data.model_dump()
        return SABPayload(type="json-schema", data=d)

    def _np(msg_id, dt, origin, step, time, offer, proposer, last_neg,
            response, running=True, timedout=False, nmi=None):
        sem_ctx = NegotiateSemanticContext(
            session_id=sid,
            sao_state=_sao_state(step, time, offer, proposer, last_neg,
                                 running, timedout),
            sao_response=SAOResponse(response=ResponseType(response), outcome=offer),
            nmi=nmi,
        )
        data = SABNegotiatePayloadData(
            message_id=msg_id, version="0", dt_created=dt,
            origin=origin, payload_hash=ph,
            semantic_context=sem_ctx,
        )
        return SABPayload(type="json-schema", data=data.model_dump())

    intent = SAB(
        header=_header(intent_id, [], ep, "agent-buyer", "topic:sab/sessions",
                       "contingency", "negotiate"),
        payload=SABPayload(
            type="json-schema",
            data=SABIntentPayloadData(
                message_id=intent_id, version="0",
                dt_created="2026-06-22T11:00:00Z",
                origin=ORIGIN_BUYER, payload_hash=ph,
                semantic_context=SemanticContext(schema_version="1.0"),
            ).model_dump(),
        ),
    )

    # Buyer and seller are stuck on opposite ends; buyer makes a late
    # concession on price (step 4) but seller resets and the budget runs out.
    rounds = [
        SAB(header=_header(r1_id, [intent_id], ep, "agent-buyer", "agent-seller",
                           "contingency", "negotiate"),
            payload=_np(r1_id, "2026-06-22T11:00:02Z", ORIGIN_BUYER,
                        0, 2.0, {"price": "low",    "delivery_speed": "express"},
                        "agent-buyer",  None,           3,
                        nmi=_nmi(sid, n_steps=6))),
        SAB(header=_header(r2_id, [intent_id], ep, "agent-seller", "agent-buyer",
                           "contingency", "negotiate"),
            payload=_np(r2_id, "2026-06-22T11:00:08Z", ORIGIN_SELLER,
                        1, 8.1, {"price": "high",   "delivery_speed": "deferred"},
                        "agent-seller", "agent-buyer",  1)),
        SAB(header=_header(r3_id, [intent_id], ep, "agent-buyer", "agent-seller",
                           "contingency", "negotiate"),
            payload=_np(r3_id, "2026-06-22T11:00:14Z", ORIGIN_BUYER,
                        2, 14.3, {"price": "low",   "delivery_speed": "standard"},
                        "agent-buyer",  "agent-seller", 1)),
        SAB(header=_header(r4_id, [intent_id], ep, "agent-seller", "agent-buyer",
                           "contingency", "negotiate"),
            payload=_np(r4_id, "2026-06-22T11:00:20Z", ORIGIN_SELLER,
                        3, 20.5, {"price": "high",  "delivery_speed": "standard"},
                        "agent-seller", "agent-buyer",  1)),
        SAB(header=_header(r5_id, [intent_id], ep, "agent-buyer", "agent-seller",
                           "contingency", "negotiate"),
            payload=_np(r5_id, "2026-06-22T11:00:26Z", ORIGIN_BUYER,
                        4, 26.8, {"price": "medium", "delivery_speed": "express"},
                        "agent-buyer",  "agent-seller", 1)),
        SAB(header=_header(r6_id, [intent_id], ep, "agent-seller", "agent-buyer",
                           "contingency", "negotiate"),
            payload=_np(r6_id, "2026-06-22T11:00:32Z", ORIGIN_SELLER,
                        5, 32.4, {"price": "high",  "delivery_speed": "deferred"},
                        "agent-seller", "agent-buyer",  1,
                        running=False, timedout=True)),
    ]

    commit = SAB(
        header=_header(commit_id, [intent_id], ep, "agent-buyer", "topic:sab/sessions",
                       "commit", "disagreement"),
        payload=_commit_payload(
            commit_id, "2026-06-22T11:00:35Z", ORIGIN_BUYER, sid,
            outcome="disagreement",
            final_agreement=None,
            agents=["agent-buyer", "agent-seller"],
        ),
    )

    return [_to_dict(m) for m in [intent, *rounds, commit]]


# ---------------------------------------------------------------------------
# Write dumps
# ---------------------------------------------------------------------------

def _dump(messages: list[dict], out_path: Path, outcome: str) -> None:
    out_path.write_text(json.dumps(messages, indent=2))
    print(f"  wrote {out_path.relative_to(REPO_ROOT)}  ({len(messages)} messages, outcome={outcome})")


def run_demo() -> None:
    out_dir = Path(__file__).resolve().parent

    _dump(build_agreement(),    out_dir / "demo_agreement.json",    outcome="agreement")
    _dump(build_disagreement(), out_dir / "demo_disagreement.json", outcome="disagreement")


if __name__ == "__main__":
    print("Generating SAB Quick Deal examples...")
    run_demo()
    print("Done.")

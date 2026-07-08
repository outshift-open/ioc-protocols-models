#!/usr/bin/env python3

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Generate SAB example message dumps for the Quick Deal mission.

Each message is a canonical **L9** envelope built with
:class:`SABMessageBuilder` — SAB does not define its own header, and
``msg_created_at`` lives in the standard ``header.attributes``.

Produces two files in this directory:
  demo_agreement.json    — intent + 4 negotiate rounds + commit/converged
  demo_disagreement.json — intent + 6 negotiate rounds + commit/disagreement

Run from anywhere:
  python3 SSTP/examples/hcpanel/run_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import the SAB src package first — its __init__ puts the L9 core binding
# (ai.outshift.data_model) on sys.path.
from SSTP.subprotocol.sab.src import (  # noqa: E402
    NegotiateCommitSemanticContext,
    NegotiateSemanticContext,
    ResponseType,
    SABCommitPayloadData,
    SABIntentPayloadData,
    SABMessageBuilder,
    SABNegotiatePayloadData,
    SABOrigin,
    SAONMI,
    SAOResponse,
    SAOState,
    SemanticContext,
)
from ai.outshift.data_model import Actor  # noqa: E402

# ---------------------------------------------------------------------------
# Mission constants
# ---------------------------------------------------------------------------

EPISODE_AGREEMENT = "urn:ioc:episode:supply-order-urgent-2026-001"
EPISODE_DISAGREEMENT = "urn:ioc:episode:supply-order-urgent-2026-002"
SESSION_AGREEMENT = "urn:ioc:sab:session:qd-2026-06-22-001"
SESSION_DISAGREEMENT = "urn:ioc:sab:session:qd-2026-06-22-002"

CONTENT_TEXT = (
    "Two parties need to agree on price and delivery speed "
    "for an urgent supply order."
)
ISSUES = ["price", "delivery_speed"]
OPTIONS = {
    "price": ["low", "medium", "high"],
    "delivery_speed": ["express", "standard", "deferred"],
}
ORIGIN_BUYER = SABOrigin(actor_id="agent-buyer", attestation=None)
ORIGIN_SELLER = SABOrigin(actor_id="agent-seller", attestation=None)
PAYLOAD_HASH = "a3f8e2d1c9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1"

N_OUTCOMES = len(OPTIONS["price"]) * len(OPTIONS["delivery_speed"])  # 9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _builder(session_id: str, episode: str, msg_id: str, parents: list[str],
             sender: str, receiver: str, dt: str) -> SABMessageBuilder:
    """Builder pre-wired with sender/receiver actors, topic, identity and dt."""
    return (
        SABMessageBuilder(session_id)
        .actors(
            Actor(id=sender, role="sender", attestation=None),
            Actor(id=receiver, role="receiver", attestation=None),
        )
        .topic(CONTENT_TEXT, issues=ISSUES, options_per_issue=OPTIONS)
        .message(msg_id, parents=parents, episode=episode)
        .created_at(dt)
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


def _intent_data(msg_id: str, dt: str, origin: SABOrigin, payload_hash: str) -> SABIntentPayloadData:
    return SABIntentPayloadData(
        message_id=msg_id, version="0", dt_created=dt, origin=origin,
        payload_hash=payload_hash, semantic_context=SemanticContext(schema_version="1.0"),
    )


def _negotiate_data(
    msg_id: str,
    dt: str,
    origin: SABOrigin,
    session_id: str,
    sao_state: SAOState,
    response: int,
    offer: dict,
    payload_hash: str,
    nmi: SAONMI | None = None,
) -> SABNegotiatePayloadData:
    return SABNegotiatePayloadData(
        message_id=msg_id, version="0", dt_created=dt, origin=origin, payload_hash=payload_hash,
        semantic_context=NegotiateSemanticContext(
            session_id=session_id,
            sao_state=sao_state,
            sao_response=SAOResponse(response=ResponseType(response), outcome=offer),
            nmi=nmi,
        ),
    )


def _commit_data(
    msg_id: str,
    dt: str,
    origin: SABOrigin,
    session_id: str,
    outcome: str,
    final_agreement: list[dict] | None,
    agents: list[str],
    payload_hash: str,
) -> SABCommitPayloadData:
    return SABCommitPayloadData(
        message_id=msg_id, version="0", dt_created=dt, origin=origin, payload_hash=payload_hash,
        semantic_context=NegotiateCommitSemanticContext(
            session_id=session_id, outcome=outcome, content_text=CONTENT_TEXT,
            agents_negotiating=agents, final_agreement=final_agreement,
        ),
    )


# ---------------------------------------------------------------------------
# Agreement scenario — converged after 2 counter-offers (4 negotiate rounds)
# ---------------------------------------------------------------------------


def build_agreement() -> list[dict]:
    ep = EPISODE_AGREEMENT
    sid = SESSION_AGREEMENT
    ph = PAYLOAD_HASH

    intent_id = "f1a2b3c4-d5e6-f780-9abc-def012345678"
    r1_id = "b2c3d4e5-f6a7-8901-bcde-f01234567890"
    r2_id = "c3d4e5f6-a7b8-9012-cdef-012345678901"
    r3_id = "d4e5f6a7-b8c9-0123-def0-123456789012"
    r4_id = "e5f6a7b8-c9d0-1234-ef01-234567890123"
    commit_id = "f6a7b8c9-d0e1-2345-f012-345678901234"
    agreed = {"price": "medium", "delivery_speed": "standard"}

    intent = (
        _builder(sid, ep, intent_id, [], "agent-buyer", "topic:sab/sessions", "2026-06-22T10:00:00Z")
        .intent(_intent_data(intent_id, "2026-06-22T10:00:00Z", ORIGIN_BUYER, ph))
        .build()
    )

    r1_offer = {"price": "high", "delivery_speed": "express"}
    round1 = (
        _builder(sid, ep, r1_id, [intent_id], "agent-buyer", "agent-seller", "2026-06-22T10:00:02Z")
        .negotiate(_negotiate_data(r1_id, "2026-06-22T10:00:02Z", ORIGIN_BUYER, sid,
                                   _sao_state(0, 2.1, r1_offer, "agent-buyer", None, True),
                                   response=3, offer=r1_offer, payload_hash=ph, nmi=_nmi(sid, 40)))
        .build()
    )

    r2_offer = {"price": "low", "delivery_speed": "deferred"}
    round2 = (
        _builder(sid, ep, r2_id, [intent_id], "agent-seller", "agent-buyer", "2026-06-22T10:00:08Z")
        .negotiate(_negotiate_data(r2_id, "2026-06-22T10:00:08Z", ORIGIN_SELLER, sid,
                                   _sao_state(1, 8.4, r2_offer, "agent-seller", "agent-buyer", True),
                                   response=1, offer=r2_offer, payload_hash=ph))
        .build()
    )

    r3_offer = {"price": "medium", "delivery_speed": "standard"}
    round3 = (
        _builder(sid, ep, r3_id, [intent_id], "agent-buyer", "agent-seller", "2026-06-22T10:00:14Z")
        .negotiate(_negotiate_data(r3_id, "2026-06-22T10:00:14Z", ORIGIN_BUYER, sid,
                                   _sao_state(2, 14.7, r3_offer, "agent-buyer", "agent-seller", True),
                                   response=1, offer=r3_offer, payload_hash=ph))
        .build()
    )

    round4 = (
        _builder(sid, ep, r4_id, [intent_id], "agent-seller", "agent-buyer", "2026-06-22T10:00:20Z")
        .negotiate(_negotiate_data(r4_id, "2026-06-22T10:00:20Z", ORIGIN_SELLER, sid,
                                   _sao_state(3, 20.3, agreed, "agent-buyer", "agent-buyer",
                                              running=False, agreement=agreed, n_acceptances=1),
                                   response=0, offer=agreed, payload_hash=ph))
        .build()
    )

    commit = (
        _builder(sid, ep, commit_id, [intent_id], "agent-buyer", "topic:sab/sessions", "2026-06-22T10:00:25Z")
        .converged(_commit_data(commit_id, "2026-06-22T10:00:25Z", ORIGIN_BUYER, sid,
                                outcome="agreement",
                                final_agreement=[
                                    {"issue_id": "price", "chosen_option": "medium"},
                                    {"issue_id": "delivery_speed", "chosen_option": "standard"},
                                ],
                                agents=["agent-buyer", "agent-seller"], payload_hash=ph))
        .build()
    )

    return [m.model_dump(mode="json") for m in [intent, round1, round2, round3, round4, commit]]


# ---------------------------------------------------------------------------
# Disagreement scenario — step budget (6) exhausted, no agreement
# ---------------------------------------------------------------------------


def build_disagreement() -> list[dict]:
    ep = EPISODE_DISAGREEMENT
    sid = SESSION_DISAGREEMENT
    ph = "b4f9e3c2d1a0f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3"

    intent_id = "a0b1c2d3-e4f5-6789-abcd-ef0123456789"
    r_ids = [
        "b1c2d3e4-f5a6-7890-bcde-f01234567890",
        "c2d3e4f5-a6b7-8901-cdef-012345678901",
        "d3e4f5a6-b7c8-9012-def0-123456789012",
        "e4f5a6b7-c8d9-0123-ef01-234567890123",
        "f5a6b7c8-d9e0-1234-f012-345678901234",
        "a6b7c8d9-e0f1-2345-0123-456789012345",
    ]
    commit_id = "b7c8d9e0-f1a2-3456-1234-567890123456"

    intent = (
        _builder(sid, ep, intent_id, [], "agent-buyer", "topic:sab/sessions", "2026-06-22T11:00:00Z")
        .intent(_intent_data(intent_id, "2026-06-22T11:00:00Z", ORIGIN_BUYER, ph))
        .build()
    )

    # (msg_id, dt, origin, sender, receiver, step, time, offer, proposer, last_neg, response, running, timedout, nmi)
    specs = [
        (r_ids[0], "2026-06-22T11:00:02Z", ORIGIN_BUYER, "agent-buyer", "agent-seller",
         0, 2.0, {"price": "low", "delivery_speed": "express"}, "agent-buyer", None, 3, True, False, _nmi(sid, 6)),
        (r_ids[1], "2026-06-22T11:00:08Z", ORIGIN_SELLER, "agent-seller", "agent-buyer",
         1, 8.1, {"price": "high", "delivery_speed": "deferred"}, "agent-seller", "agent-buyer", 1, True, False, None),
        (r_ids[2], "2026-06-22T11:00:14Z", ORIGIN_BUYER, "agent-buyer", "agent-seller",
         2, 14.3, {"price": "low", "delivery_speed": "standard"}, "agent-buyer", "agent-seller", 1, True, False, None),
        (r_ids[3], "2026-06-22T11:00:20Z", ORIGIN_SELLER, "agent-seller", "agent-buyer",
         3, 20.5, {"price": "high", "delivery_speed": "standard"}, "agent-seller", "agent-buyer", 1, True, False, None),
        (r_ids[4], "2026-06-22T11:00:26Z", ORIGIN_BUYER, "agent-buyer", "agent-seller",
         4, 26.8, {"price": "medium", "delivery_speed": "express"}, "agent-buyer", "agent-seller", 1, True, False, None),
        (r_ids[5], "2026-06-22T11:00:32Z", ORIGIN_SELLER, "agent-seller", "agent-buyer",
         5, 32.4, {"price": "high", "delivery_speed": "deferred"}, "agent-seller", "agent-buyer", 1, False, True, None),
    ]

    rounds = []
    for (mid, dt, origin, sender, receiver, step, t, offer, proposer, last_neg,
         resp, running, timedout, nmi) in specs:
        rounds.append(
            _builder(sid, ep, mid, [intent_id], sender, receiver, dt)
            .negotiate(_negotiate_data(mid, dt, origin, sid,
                                       _sao_state(step, t, offer, proposer, last_neg, running, timedout),
                                       response=resp, offer=offer, payload_hash=ph, nmi=nmi))
            .build()
        )

    commit = (
        _builder(sid, ep, commit_id, [intent_id], "agent-buyer", "topic:sab/sessions", "2026-06-22T11:00:35Z")
        .disagreement(_commit_data(commit_id, "2026-06-22T11:00:35Z", ORIGIN_BUYER, sid,
                                   outcome="disagreement", final_agreement=None,
                                   agents=["agent-buyer", "agent-seller"], payload_hash=ph))
        .build()
    )

    return [m.model_dump(mode="json") for m in [intent, *rounds, commit]]


# ---------------------------------------------------------------------------
# Write dumps
# ---------------------------------------------------------------------------


def _dump(messages: list[dict], out_path: Path, outcome: str) -> None:
    out_path.write_text(json.dumps(messages, indent=2))
    print(f"  wrote {out_path.relative_to(REPO_ROOT)}  ({len(messages)} messages, outcome={outcome})")


def run_demo() -> None:
    out_dir = Path(__file__).resolve().parent
    _dump(build_agreement(), out_dir / "demo_agreement.json", outcome="agreement")
    _dump(build_disagreement(), out_dir / "demo_disagreement.json", outcome="disagreement")


if __name__ == "__main__":
    print("Generating SAB Quick Deal examples...")
    run_demo()
    print("Done.")

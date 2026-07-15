#!/usr/bin/env python3

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Generate SAB example message dumps for the Quick Deal mission.

Each message is a full canonical **L9** envelope built with
:class:`SABMessageBuilder`; ``msg_created_at`` lives in ``header.attributes``.

Produces two files in this directory:
  demo_agreement.json    — intent + 4 negotiate rounds + commit/resolved
  demo_disagreement.json — intent + 6 negotiate rounds + commit/unresolved

Run from anywhere:
  python3 SSTP/subprotocol/sab/examples/run_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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

# ---------------------------------------------------------------------------
# Mission constants
# ---------------------------------------------------------------------------

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
AGENTS = ["agent-buyer", "agent-seller"]
ORIGIN_BUYER = SABOrigin(actor_id="agent-buyer", attestation=None)
ORIGIN_SELLER = SABOrigin(actor_id="agent-seller", attestation=None)
PAYLOAD_HASH = "a3f8e2d1c9b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1"
N_OUTCOMES = len(OPTIONS["price"]) * len(OPTIONS["delivery_speed"])  # 9


# ---------------------------------------------------------------------------
# Payload-data helpers (payload.data models — the L9 envelope is built below)
# ---------------------------------------------------------------------------


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


def _intent_data(msg_id: str, dt: str, origin: SABOrigin) -> SABIntentPayloadData:
    return SABIntentPayloadData(
        message_id=msg_id,
        version="0",
        dt_created=dt,
        origin=origin,
        payload_hash=PAYLOAD_HASH,
        semantic_context=SemanticContext(schema_version="1.0"),
    )


def _negotiate_data(
    msg_id: str,
    dt: str,
    origin: SABOrigin,
    session_id: str,
    sao_state: SAOState,
    response: int,
    offer: dict,
    nmi: SAONMI | None = None,
) -> SABNegotiatePayloadData:
    return SABNegotiatePayloadData(
        message_id=msg_id,
        version="0",
        dt_created=dt,
        origin=origin,
        payload_hash=PAYLOAD_HASH,
        semantic_context=NegotiateSemanticContext(
            session_id=session_id,
            issues=ISSUES,
            options_per_issue=OPTIONS,
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
) -> SABCommitPayloadData:
    return SABCommitPayloadData(
        message_id=msg_id,
        version="0",
        dt_created=dt,
        origin=origin,
        payload_hash=PAYLOAD_HASH,
        semantic_context=NegotiateCommitSemanticContext(
            session_id=session_id,
            outcome=outcome,
            content_text=CONTENT_TEXT,
            agents_negotiating=AGENTS,
            issues=ISSUES,
            options_per_issue=OPTIONS,
            final_agreement=final_agreement,
        ),
    )


def _builder(session_id: str, episode: str, msg_id: str, dt: str) -> SABMessageBuilder:
    """A builder pre-wired with participants, topic, message identity and dt."""
    return (
        SABMessageBuilder(session_id)
        .participants(AGENTS)
        # topic carries the mission summary only; issues/options ride in the
        # canonical semantic_context (set on the negotiate/commit payload data).
        .topic(CONTENT_TEXT)
        .message(msg_id, parents=[], episode=episode)
        .created_at(dt)
    )


# ---------------------------------------------------------------------------
# Agreement scenario — converged after 2 counter-offers (4 negotiate rounds)
# ---------------------------------------------------------------------------


def build_agreement() -> list[dict]:
    ep = "urn:ioc:episode:supply-order-urgent-2026-001"
    sid = SESSION_AGREEMENT
    agreed = {"price": "medium", "delivery_speed": "standard"}

    intent = (
        _builder(sid, ep, "f1a2b3c4-d5e6-f780-9abc-def012345678", "2026-06-22T10:00:00Z")
        .intent(_intent_data("f1a2b3c4-d5e6-f780-9abc-def012345678", "2026-06-22T10:00:00Z", ORIGIN_BUYER))
        .build()
    )

    r1_offer = {"price": "high", "delivery_speed": "express"}
    round1 = (
        _builder(sid, ep, "b2c3d4e5-f6a7-8901-bcde-f01234567890", "2026-06-22T10:00:02Z")
        .negotiate(_negotiate_data(
            "b2c3d4e5-f6a7-8901-bcde-f01234567890", "2026-06-22T10:00:02Z", ORIGIN_BUYER, sid,
            _sao_state(0, 2.1, r1_offer, "agent-buyer", None, True),
            response=3, offer=r1_offer, nmi=_nmi(sid, n_steps=40)))
        .build()
    )

    r2_offer = {"price": "low", "delivery_speed": "deferred"}
    round2 = (
        _builder(sid, ep, "c3d4e5f6-a7b8-9012-cdef-012345678901", "2026-06-22T10:00:08Z")
        .negotiate(_negotiate_data(
            "c3d4e5f6-a7b8-9012-cdef-012345678901", "2026-06-22T10:00:08Z", ORIGIN_SELLER, sid,
            _sao_state(1, 8.4, r2_offer, "agent-seller", "agent-buyer", True),
            response=1, offer=r2_offer))
        .build()
    )

    r3_offer = {"price": "medium", "delivery_speed": "standard"}
    round3 = (
        _builder(sid, ep, "d4e5f6a7-b8c9-0123-def0-123456789012", "2026-06-22T10:00:14Z")
        .negotiate(_negotiate_data(
            "d4e5f6a7-b8c9-0123-def0-123456789012", "2026-06-22T10:00:14Z", ORIGIN_BUYER, sid,
            _sao_state(2, 14.7, r3_offer, "agent-buyer", "agent-seller", True),
            response=1, offer=r3_offer))
        .build()
    )

    round4 = (
        _builder(sid, ep, "e5f6a7b8-c9d0-1234-ef01-234567890123", "2026-06-22T10:00:20Z")
        .negotiate(_negotiate_data(
            "e5f6a7b8-c9d0-1234-ef01-234567890123", "2026-06-22T10:00:20Z", ORIGIN_SELLER, sid,
            _sao_state(3, 20.3, agreed, "agent-buyer", "agent-buyer",
                       running=False, agreement=agreed, n_acceptances=1),
            response=0, offer=agreed))
        .build()
    )

    commit = (
        _builder(sid, ep, "f6a7b8c9-d0e1-2345-f012-345678901234", "2026-06-22T10:00:25Z")
        .resolved(_commit_data(
            "f6a7b8c9-d0e1-2345-f012-345678901234", "2026-06-22T10:00:25Z", ORIGIN_BUYER, sid,
            outcome="agreement",
            final_agreement=[
                {"issue_id": "price", "chosen_option": "medium"},
                {"issue_id": "delivery_speed", "chosen_option": "standard"},
            ]))
        .build()
    )

    return [m.model_dump(mode="json") for m in [intent, round1, round2, round3, round4, commit]]


# ---------------------------------------------------------------------------
# Disagreement scenario — step budget (6) exhausted, no agreement
# ---------------------------------------------------------------------------


def build_disagreement() -> list[dict]:
    ep = "urn:ioc:episode:supply-order-urgent-2026-002"
    sid = SESSION_DISAGREEMENT

    ids = [
        "a0b1c2d3-e4f5-6789-abcd-ef0123456789",  # intent
        "b1c2d3e4-f5a6-7890-bcde-f01234567890",
        "c2d3e4f5-a6b7-8901-cdef-012345678901",
        "d3e4f5a6-b7c8-9012-def0-123456789012",
        "e4f5a6b7-c8d9-0123-ef01-234567890123",
        "f5a6b7c8-d9e0-1234-f012-345678901234",
        "a6b7c8d9-e0f1-2345-0123-456789012345",
        "b7c8d9e0-f1a2-3456-1234-567890123456",  # commit
    ]

    intent = (
        _builder(sid, ep, ids[0], "2026-06-22T11:00:00Z")
        .intent(_intent_data(ids[0], "2026-06-22T11:00:00Z", ORIGIN_BUYER))
        .build()
    )

    steps = [
        (ids[1], "2026-06-22T11:00:02Z", ORIGIN_BUYER, 0, 2.0,
         {"price": "low", "delivery_speed": "express"}, "agent-buyer", None, 3, True, False, _nmi(sid, 6)),
        (ids[2], "2026-06-22T11:00:08Z", ORIGIN_SELLER, 1, 8.1,
         {"price": "high", "delivery_speed": "deferred"}, "agent-seller", "agent-buyer", 1, True, False, None),
        (ids[3], "2026-06-22T11:00:14Z", ORIGIN_BUYER, 2, 14.3,
         {"price": "low", "delivery_speed": "standard"}, "agent-buyer", "agent-seller", 1, True, False, None),
        (ids[4], "2026-06-22T11:00:20Z", ORIGIN_SELLER, 3, 20.5,
         {"price": "high", "delivery_speed": "standard"}, "agent-seller", "agent-buyer", 1, True, False, None),
        (ids[5], "2026-06-22T11:00:26Z", ORIGIN_BUYER, 4, 26.8,
         {"price": "medium", "delivery_speed": "express"}, "agent-buyer", "agent-seller", 1, True, False, None),
        (ids[6], "2026-06-22T11:00:32Z", ORIGIN_SELLER, 5, 32.4,
         {"price": "high", "delivery_speed": "deferred"}, "agent-seller", "agent-buyer", 1, False, True, None),
    ]

    rounds = []
    for mid, dt, origin, step, t, offer, proposer, last_neg, resp, running, timedout, nmi in steps:
        rounds.append(
            _builder(sid, ep, mid, dt)
            .negotiate(_negotiate_data(
                mid, dt, origin, sid,
                _sao_state(step, t, offer, proposer, last_neg, running, timedout),
                response=resp, offer=offer, nmi=nmi))
            .build()
        )

    commit = (
        _builder(sid, ep, ids[7], "2026-06-22T11:00:35Z")
        .unresolved(_commit_data(
            ids[7], "2026-06-22T11:00:35Z", ORIGIN_BUYER, sid,
            outcome="disagreement", final_agreement=None))
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

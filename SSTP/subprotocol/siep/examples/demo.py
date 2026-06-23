# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Verbose SIEP demo showcasing the repair cycle."""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from typing import List, Tuple

from src import L9
from SSTP.subprotocol.siep.src.siep_models import siep_parents, siep_epistemic
from SSTP.subprotocol.siep.src.builder import (
    RevisionCause,
    SIEPBelief,
    SIEPMessageBuilder,
    SIEPPayload,
    SIEPUtterance,
)
from SSTP.subprotocol.siep.src.engine import SIEPEngine
from SSTP.subprotocol.siep.src.message_store import MessageStore
from SSTP.subprotocol.siep.src.siep_payload import SIEPMessagePayload

C    = "concept:task_objective"
SUB  = "urn:concept:task_objective:deliverable_spec"
C2   = "concept:timeline"
C3   = "concept:resource_allocation"
C4   = "concept:acceptance_criteria"
SCOPE = "concept:scope"
EpisodeLog = List[Tuple[str, L9]]
_W = 100


def run_demo() -> None:
    episode = f"urn:ioc:episode:{uuid.uuid4()}"
    engine = SIEPEngine("agent-beta", episode)
    store = MessageStore()
    log: EpisodeLog = []

    def builder(sender: str) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(episode, sender)

    def emit(label: str, msg: L9) -> L9:
        log.append((label, msg))
        store.append(label, msg)
        return msg

    def engine_responses(msg: L9, label: str) -> List[L9]:
        responses = engine.process(msg)
        for response in responses:
            log.append((label, response))
            store.append(label, response)
        return responses

    s1 = emit("1 · intent", builder("coordinator").intent().team_process().concept(C).build())
    engine.process(s1)

    s2 = emit(
        "2 · prior (agent-alpha)",
        builder("agent-alpha").exchange().taskwork().asserted().concept(C)
        .parents(s1.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C, SUB, C4]),
            belief=SIEPBelief(prior=0.72, posterior=0.72, revision_cause=RevisionCause.semantic_memory),
        ))
        .build(),
    )
    engine.process(s2)

    s3 = emit(
        "3 · prior (agent-beta)",
        builder("agent-beta").exchange().taskwork().asserted().concept(C)
        .parents(s1.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C, SUB, C4]),
            belief=SIEPBelief(prior=0.65, posterior=0.65, revision_cause=RevisionCause.semantic_memory),
        ))
        .build(),
    )
    engine.process(s3)

    # GOOD: evidence overlaps 2 of 3 prior concepts → score ≈ 0.667 (passes THETA_C=0.40)
    s4 = emit(
        "4 · exchange  GOOD ✓",
        builder("agent-alpha").exchange().grounding().asserted().concept(C)
        .uncertainty(0.28).parents(s3.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C, SUB, C2], addresses_evidence=[C, SUB]),
            belief=SIEPBelief(prior=0.72, posterior=0.72),
        ))
        .text("agent-beta, addressing task_objective + deliverable_spec; introducing timeline constraint")
        .build(),
    )
    engine_responses(s4, "5 · exchange  grounding_ok ✓")

    # BAD: drifts to new concepts — only 1 of 3 prior concepts covered → score ≈ 0.333 (fails THETA_C)
    s6 = emit(
        "6 · exchange  BAD ✗",
        builder("agent-alpha").exchange().grounding().asserted().concept(C)
        .uncertainty(0.28).parents(s4.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(
                evidence=[C, C4, C3],
                addresses_evidence=[],
            ),
            belief=SIEPBelief(prior=0.72, posterior=0.72),
        ))
        .text("What about resource allocation and acceptance criteria? Timeline seems secondary.")
        .build(),
    )
    contingency_msg = engine_responses(s6, "7 · contingency  repair_required")[0]

    # REPAIR: re-anchors to 2 of 3 challenged concepts → score ≈ 0.667 (passes, repair accepted)
    s8 = emit(
        "8 · exchange  REPAIR",
        builder("agent-alpha").exchange().grounding().asserted().concept(C)
        .uncertainty(0.28).parents(contingency_msg.header.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C, SUB, SCOPE], addresses_evidence=[C, SUB], turn_depth=1),
            belief=SIEPBelief(
                prior=0.72,
                posterior=0.72,
                revision_cause=RevisionCause.repair_resolution,
            ),
        ))
        .text("Re-anchoring: task_objective + deliverable_spec are the primary scope; adding scope clarification")
        .build(),
    )
    engine_responses(s8, "9 · commit:converged  repair_verified ✓")

    _print_verbose(log)
    _print_summary(log)
    store.flush()
    print()
    store.print_table()

    _SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
    store.write_json(_SCRIPTS / "siep_run.json")


def _sender_id(msg: L9) -> str:
    return msg.header.participants.actors[0].id


def _siep_payload(msg: L9) -> SIEPMessagePayload:
    return SIEPMessagePayload.model_validate(msg.payload.data)


def _utterance_text(msg: L9) -> str | None:
    attributes = msg.header.attributes or {}
    return attributes.get("utterance_text")


def _hr(char: str = "─") -> None:
    print(char * _W)


def _print_verbose(log: EpisodeLog) -> None:
    _hr("═")
    print("  SIEP EPISODE  —  kind=contingency repair cycle")
    _hr("═")
    for label, msg in log:
        _hr()
        print(f"  {label}")
        _hr()
        _print_message(msg)
    _hr("═")


def _print_message(msg: L9) -> None:
    header = msg.header
    epistemic = siep_epistemic(msg)
    kind_str = header.kind + (f":{header.subkind}" if header.subkind else "")
    print(f"  protocol     : {header.protocol} v{header.version}")
    print(f"  kind         : {kind_str}")
    print(f"  subprotocol  : {header.subprotocol}")
    print(f"  actor        : {_sender_id(msg)}")
    print(f"  message.id   : {header.message.id[:8]}…")
    print(f"  parents      : {[p[:8] + '…' for p in siep_parents(msg)] or '[]'}")
    print(f"  episode      : {header.message.episode}")
    print(f"  epistemic ({epistemic.epistemic_kind if epistemic else '—'}):")
    print(f"    state        = {epistemic.state if epistemic and epistemic.state else '—'}")
    print(f"    message_act  = {epistemic.message_act if epistemic and epistemic.message_act else '—'}")
    print(f"    uncertainty  = {epistemic.uncertainty if epistemic else '—'}")
    print(f"    belief_status= {epistemic.belief_status if epistemic and epistemic.belief_status else '—'}")
    print(f"    concept_id   = {epistemic.concept_id if epistemic and epistemic.concept_id else '—'}")
    siep_payload = _siep_payload(msg)
    print("  siep.utterance :")
    print(f"    evidence          = {siep_payload.utterance.evidence}")
    print(f"    addresses_evidence= {siep_payload.utterance.addresses_evidence}")
    print(f"    turn_depth        = {siep_payload.utterance.turn_depth}")
    print("  siep.grounding :")
    print(f"    contingency_verified = {siep_payload.grounding.contingency_verified}")
    print(f"    contingency_score    = {siep_payload.grounding.contingency_score}")
    if siep_payload.grounding.repair_reason:
        print(f"    repair_reason        = {siep_payload.grounding.repair_reason}")
    if siep_payload.grounding.challenges:
        print(f"    challenges           = {siep_payload.grounding.challenges}")
    print("  siep.belief    :")
    print(f"    prior             = {siep_payload.belief.prior}")
    print(f"    posterior         = {siep_payload.belief.posterior}")
    if siep_payload.belief.revision_cause:
        print(f"    revision_cause    = {siep_payload.belief.revision_cause}")
    utterance_text = _utterance_text(msg)
    if utterance_text:
        wrapped = textwrap.fill(str(utterance_text), width=_W - 18, subsequent_indent=" " * 18)
        print(f"  utterance    : {wrapped}")


def _print_summary(log: EpisodeLog) -> None:
    print()
    _hr("═")
    print("  EPISODE SUMMARY")
    _hr("═")
    header = f"  {'step / label':<34}  {'actor':<14}  {'score':>7}  {'verified':<10}"
    print(header)
    _hr()
    for label, msg in log:
        siep_payload = _siep_payload(msg)
        score = siep_payload.grounding.contingency_score
        verified = siep_payload.grounding.contingency_verified
        score_str = f"{score:.3f}" if score is not None else "  —  "
        verified_str = ("✓" if verified else "✗") if verified is not None else "—"
        print(f"  {label:<34}  {_sender_id(msg):<14}  {score_str:>7}  {verified_str:<10}")
    _hr("═")


__all__ = ["run_demo"]

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Verbose SIEP demo showcasing the repair cycle."""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from typing import List, Tuple

from SSTP.subprotocol.siep.src.builder import (
    L9Message,
    RevisionCause,
    SIEPBelief,
    SIEPMessageBuilder,
    SIEPPayload,
    SIEPUtterance,
)
from SSTP.subprotocol.siep.src.engine import SIEPEngine
from SSTP.subprotocol.siep.src.message_store import MessageStore

C = "concept:task_objective"
SUB = "urn:concept:task_objective:deliverable_spec"
EpisodeLog = List[Tuple[str, L9Message]]
_W = 100


def run_demo() -> None:
    episode = f"urn:ioc:episode:{uuid.uuid4()}"
    engine = SIEPEngine("agent-beta", episode)
    store = MessageStore()
    log: EpisodeLog = []

    def builder(sender: str) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(episode, sender)

    def emit(label: str, msg: L9Message) -> L9Message:
        log.append((label, msg))
        store.append(label, msg)
        return msg

    def engine_responses(msg: L9Message, label: str) -> List[L9Message]:
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
        .parents(s1.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C]),
            belief=SIEPBelief(prior=0.72, posterior=0.72, revision_cause=RevisionCause.semantic_memory),
        ))
        .build(),
    )
    engine.process(s2)

    s3 = emit(
        "3 · prior (agent-beta)",
        builder("agent-beta").exchange().taskwork().asserted().concept(C)
        .parents(s1.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C]),
            belief=SIEPBelief(prior=0.65, posterior=0.65, revision_cause=RevisionCause.semantic_memory),
        ))
        .build(),
    )

    s4 = emit(
        "4 · exchange  GOOD ✓",
        builder("agent-alpha").exchange().grounding().asserted().concept(C)
        .uncertainty(0.28).parents(s3.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C, SUB], addresses_evidence=[C]),
            belief=SIEPBelief(prior=0.72, posterior=0.72),
        ))
        .text("agent-beta, bound to task_objective:deliverable_spec pathway only")
        .build(),
    )
    engine_responses(s4, "5 · exchange  grounding_ok ✓")

    s6 = emit(
        "6 · exchange  BAD ✗",
        builder("agent-alpha").exchange().grounding().asserted().concept(C)
        .uncertainty(0.28).parents(s4.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(
                evidence=["concept:timeline", "concept:resource_availability"],
                addresses_evidence=[],
            ),
            belief=SIEPBelief(prior=0.72, posterior=0.72),
        ))
        .text("What does the timeline look like for next sprint?")
        .build(),
    )
    contingency_msg = engine_responses(s6, "7 · contingency  repair_required")[0]

    s8 = emit(
        "8 · exchange  REPAIR",
        builder("agent-alpha").exchange().grounding().asserted().concept(C)
        .uncertainty(0.28).parents(contingency_msg.message.id)
        .payload(SIEPPayload(
            utterance=SIEPUtterance(evidence=[C, SUB], addresses_evidence=[C, SUB], turn_depth=1),
            belief=SIEPBelief(
                prior=0.72,
                posterior=0.72,
                revision_cause=RevisionCause.repair_resolution,
            ),
        ))
        .text("agent-alpha, re-anchored to task_objective:deliverable_spec pathway")
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


def _print_message(msg: L9Message) -> None:
    kind_str = msg.kind.value + (f":{msg.subkind.value}" if msg.subkind else "")
    print(f"  protocol     : {msg.protocol} v{msg.version}")
    print(f"  kind         : {kind_str}")
    print(f"  subprotocol  : {msg.subprotocol}")
    print(f"  actor        : {msg.actor.id}")
    print(f"  message.id   : {msg.message.id[:8]}…")
    print(f"  parents      : {[p[:8] + '…' for p in msg.message.parents] or '[]'}")
    print(f"  episode      : {msg.message.episode}")
    print(f"  epistemic ({msg.epistemic.epistemic_kind}):")
    print(f"    state        = {msg.epistemic.state.value if msg.epistemic.state else '—'}")
    print(f"    message_act  = {msg.epistemic.message_act.value if msg.epistemic.message_act else '—'}")
    print(f"    uncertainty  = {msg.epistemic.uncertainty}")
    print(f"    belief_status= {msg.epistemic.belief_status.value if msg.epistemic.belief_status else '—'}")
    print(f"    concept_id   = {msg.epistemic.concept_id or '—'}")
    siep_payload = msg.siep_payload()
    if siep_payload:
        print("  siep.utterance :")
        print(f"    evidence          = {siep_payload.utterance.evidence}")
        print(f"    addresses_evidence= {siep_payload.utterance.addresses_evidence}")
        print(f"    turn_depth        = {siep_payload.utterance.turn_depth}")
        print("  siep.grounding :")
        print(f"    contingency_verified = {siep_payload.grounding.contingency_verified}")
        print(f"    contingency_score    = {siep_payload.grounding.contingency_score}")
        if siep_payload.grounding.repair_reason:
            print(f"    repair_reason        = {siep_payload.grounding.repair_reason.value}")
        if siep_payload.grounding.challenges:
            print(f"    challenges           = {siep_payload.grounding.challenges}")
        print("  siep.belief    :")
        print(f"    prior             = {siep_payload.belief.prior}")
        print(f"    posterior         = {siep_payload.belief.posterior}")
        if siep_payload.belief.revision_cause:
            print(f"    revision_cause    = {siep_payload.belief.revision_cause.value}")
    for part in msg.payload:
        if part.type == "utterance" and part.content:
            wrapped = textwrap.fill(str(part.content), width=_W - 18, subsequent_indent=" " * 18)
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
        siep_payload = msg.siep_payload()
        score = siep_payload.grounding.contingency_score if siep_payload else None
        verified = siep_payload.grounding.contingency_verified if siep_payload else None
        score_str = f"{score:.3f}" if score is not None else "  —  "
        verified_str = ("✓" if verified else "✗") if verified is not None else "—"
        print(f"  {label:<34}  {msg.actor.id:<14}  {score_str:>7}  {verified_str:<10}")
    _hr("═")


__all__ = ["run_demo"]

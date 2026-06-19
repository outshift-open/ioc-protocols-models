# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Verbose CIP demo showcasing a contingency repair cycle."""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from typing import List, Tuple

from ioc_l9.src import L9
from SSTP.subprotocol.cip.src.builder import (
    CIPBelief,
    CIPMessageBuilder,
    CIPPayload,
    CIPUtterance,
    RepairReason,
    RevisionCause,
)
from SSTP.subprotocol.cip.src.engine import CIPEngineConfig
from SSTP.subprotocol.cip.src.processor import CIPProcessor
from SSTP.subprotocol.cip.src.cip_payload import CIPMessagePayload
from SSTP.subprotocol.siep.src.builder import SIEPGrounding, SIEPMessageBuilder, SIEPPayload
from SSTP.subprotocol.siep.src.message_store import MessageStore

C = "concept:task_objective"
SUB = "urn:concept:task_objective:deliverable_spec"
ALT = "concept:timeline"
EpisodeLog = List[Tuple[str, L9]]
_W = 100


def run_demo() -> None:
    episode = f"urn:ioc:episode:{uuid.uuid4()}"
    config = CIPEngineConfig(
        derailment_causes={
            "scope_mismatch": ["{listener}, your reply drifted to adjacent planning scope."],
            "grounding_failure": ["{listener}, your reply did not engage the prior evidence."],
            "ungroundable_novelty": ["{listener}, that introduced unsupported new concepts."],
        },
        nonsense_derailment_causes=set(),
        repair_utterances={
            "repair_hard_stop": "{listener}, stop and restate only against the challenged evidence.",
            "repair_anchor": "{listener}, re-anchor on the cited concept before continuing.",
            "repair_alignment": "{listener}, restate within the requested scope and address the cited evidence.",
            "request_clarification": "{listener}, clarify how your reply answers the challenged point.",
            "default": "{listener}, remain within task scope.",
        },
        normal_utterance_template="{listener}, continue within the shared task scope.",
    )
    processor = CIPProcessor("cip-agent", episode, config)
    store = MessageStore()
    log: EpisodeLog = []

    def cip_builder(sender: str) -> CIPMessageBuilder:
        return CIPMessageBuilder(episode, sender)

    def siep_builder(sender: str) -> SIEPMessageBuilder:
        return SIEPMessageBuilder(episode, sender)

    def emit(label: str, msg: L9) -> L9:
        log.append((label, msg))
        store.append(label, msg)
        return msg

    def process_and_store(msg: L9, label: str) -> List[L9]:
        responses = processor.process(msg)
        for response in responses:
            log.append((label, response))
            store.append(label, response)
        return responses

    repair_request = emit(
        "1 · siep contingency request",
        siep_builder("agent-beta").contingency().grounding().challenged().concept(C)
        .parents("msg-bad-scope")
        .payload(SIEPPayload(
            grounding=SIEPGrounding(
                contingency_verified=False,
                contingency_score=0.0,
                repair_reason=RepairReason.scope_mismatch,
                challenges=[C, SUB],
            ),
        ))
        .text("repair_required:reason=scope_mismatch:target=msg-bad-scope")
        .build(),
    )
    guidance = process_and_store(repair_request, "2 · cip guidance emitted")[0]

    repair_attempt = emit(
        "3 · agent re-attempt",
        cip_builder("agent-alpha").contingency().grounding().revised().concept(C)
        .parents(guidance.header.message.id)
        .payload(CIPPayload(
            utterance=CIPUtterance(
                text="Re-anchoring on deliverable scope only.",
                evidence=[C, SUB],
                addresses_evidence=[C, SUB],
                turn_depth=1,
            ),
            belief=CIPBelief(
                prior=0.62,
                posterior=0.62,
                revision_cause=RevisionCause.repair_resolution,
            ),
        ))
        .text("Re-anchoring on deliverable scope only.")
        .build(),
    )
    process_and_store(repair_attempt, "4 · cip commit resolved")[0]

    _print_verbose(log)
    _print_summary(log)
    store.flush()
    print()
    store.print_table()
    store.write_json(Path(__file__).resolve().parents[1] / "scripts" / "cip_run.json")


def _sender_id(msg: L9) -> str:
    return msg.header.actors.actors[0].id


def _cip_payload(msg: L9) -> CIPMessagePayload:
    return CIPMessagePayload.model_validate(msg.payload.data)


def _utterance_text(msg: L9) -> str | None:
    attributes = msg.header.attributes or {}
    return attributes.get("utterance_text")


def _hr(char: str = "─") -> None:
    print(char * _W)


def _print_verbose(log: EpisodeLog) -> None:
    _hr("═")
    print("  CIP EPISODE  —  contingency repair cycle")
    _hr("═")
    for label, msg in log:
        _hr()
        print(f"  {label}")
        _hr()
        _print_message(msg)
    _hr("═")


def _print_message(msg: L9) -> None:
    header = msg.header
    context = header.context
    epistemic = context.epistemic if context else None
    kind_str = header.kind + (f":{header.subkind}" if header.subkind else "")
    print(f"  protocol     : {header.protocol} v{header.version}")
    print(f"  kind         : {kind_str}")
    print(f"  subprotocol  : {header.subprotocol}")
    print(f"  actor        : {_sender_id(msg)}")
    print(f"  message.id   : {header.message.id[:8]}…")
    print(f"  parents      : {[p[:8] + '…' for p in header.message.parents] or '[]'}")
    print(f"  episode      : {header.message.episode}")
    print(f"  epistemic ({epistemic.epistemic_kind if epistemic else '—'}):")
    print(f"    state        = {epistemic.state if epistemic and epistemic.state else '—'}")
    print(f"    message_act  = {epistemic.message_act if epistemic and epistemic.message_act else '—'}")
    print(f"    uncertainty  = {epistemic.uncertainty if epistemic else '—'}")
    print(f"    belief_status= {epistemic.belief_status if epistemic and epistemic.belief_status else '—'}")
    print(f"    concept_id   = {epistemic.concept_id if epistemic and epistemic.concept_id else '—'}")
    payload = _cip_payload(msg)
    print("  cip.utterance :")
    print(f"    evidence          = {payload.utterance.evidence}")
    print(f"    addresses_evidence= {payload.utterance.addresses_evidence}")
    print(f"    turn_depth        = {payload.utterance.turn_depth}")
    print("  cip.grounding :")
    print(f"    contingency_verified = {payload.grounding.contingency_verified}")
    print(f"    contingency_score    = {payload.grounding.contingency_score}")
    if payload.grounding.repair_reason:
        print(f"    repair_reason        = {payload.grounding.repair_reason}")
    if payload.grounding.challenges:
        print(f"    challenges           = {payload.grounding.challenges}")
    print("  cip.belief    :")
    print(f"    prior             = {payload.belief.prior}")
    print(f"    posterior         = {payload.belief.posterior}")
    if payload.belief.revision_cause:
        print(f"    revision_cause    = {payload.belief.revision_cause}")
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
        payload = _cip_payload(msg)
        score = payload.grounding.contingency_score
        verified = payload.grounding.contingency_verified
        score_str = f"{score:.3f}" if score is not None else "  —  "
        verified_str = ("✓" if verified else "✗") if verified is not None else "—"
        print(f"  {label:<34}  {_sender_id(msg):<14}  {score_str:>7}  {verified_str:<10}")
    _hr("═")


__all__ = ["run_demo"]

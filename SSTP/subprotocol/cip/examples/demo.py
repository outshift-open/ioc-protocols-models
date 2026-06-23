# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""CIP demo: contingency repair cycle.

CIP only operates on messages with kind=contingency.  The cycle is:

  1. Incoming contingency  — an agent signals a grounding failure/scope mismatch.
  2. CIP guidance          — CIP emits a contingency repair directive.
  3. Agent re-attempt      — the agent resubmits a corrected contingency reply.
  4. CIP commit:resolved   — CIP closes the branch once grounding is verified.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Tuple

from ai.outshift.data_model import L9
from SSTP.subprotocol.cip.src.builder import (
    CIPBelief,
    CIPGrounding,
    CIPMessageBuilder,
    CIPPayload,
    CIPUtterance,
    RepairReason,
    RevisionCause,
)
from SSTP.subprotocol.cip.src.engine import CIPEngineConfig
from SSTP.subprotocol.cip.src.processor import CIPProcessor
from SSTP.subprotocol.cip.src.cip_payload import CIPMessagePayload
from SSTP.subprotocol.cip.examples.message_store import MessageStore

# Concept URIs used throughout the episode
C = "concept:task_objective"
SUB = "urn:concept:task_objective:deliverable_spec"

EpisodeLog = List[Tuple[str, L9]]
_W = 100


def run_demo() -> None:
    """Run a single contingency repair cycle through CIP."""
    episode = f"urn:ioc:episode:{uuid.uuid4()}"

    # CIP engine configuration: repair templates keyed by reason
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

    def build(sender: str) -> CIPMessageBuilder:
        return CIPMessageBuilder(episode, sender)

    def emit(label: str, msg: L9) -> L9:
        log.append((label, msg))
        store.append(label, msg)
        return msg

    def process(msg: L9, label: str) -> L9:
        """Feed msg to CIP and store the first response."""
        responses = processor.process(msg)
        if not responses:
            raise RuntimeError(f"CIP returned no response for: {label}")
        response = responses[0]
        log.append((label, response))
        store.append(label, response)
        return response

    # ── Step 1: incoming contingency ──────────────────────────────────────────
    # An agent reports a grounding failure (scope mismatch) on a prior message.
    repair_request = emit(
        "1 · contingency  (repair request)",
        build("agent-beta")
        .contingency().grounding().challenged().concept(C)
        .parents("msg-bad-scope")
        .payload(CIPPayload(
            grounding=CIPGrounding(
                contingency_verified=False,
                contingency_score=0.0,
                repair_reason=RepairReason.scope_mismatch,
                challenges=[C, SUB],
            ),
        ))
        .text("repair_required:reason=scope_mismatch:target=msg-bad-scope")
        .build(),
    )

    # ── Step 2: CIP guidance ──────────────────────────────────────────────────
    # CIP processes the contingency and emits a repair directive.
    guidance = process(repair_request, "2 · contingency  (cip guidance)")

    # ── Step 3: agent re-attempt ──────────────────────────────────────────────
    # The agent resubmits a revised reply anchored to the challenged concepts.
    repair_attempt = emit(
        "3 · contingency  (agent re-attempt)",
        build("agent-alpha")
        .contingency().grounding().revised().concept(C)
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

    # ── Step 4: CIP commit:resolved ───────────────────────────────────────────
    # CIP verifies grounding and closes the branch with a commit.
    process(repair_attempt, "4 · commit:resolved (cip closes branch)")

    _print_cycle(log)
    store.flush()
    print()
    store.print_table()
    _save_json(store, Path(__file__).resolve().parent / "cip_run.json")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sender_id(msg: L9) -> str:
    return msg.header.participants.actors[0].id


def _cip_payload(msg: L9) -> CIPMessagePayload:
    return CIPMessagePayload.model_validate(msg.payload.data)


def _parents_list(msg: L9) -> list:
    raw = msg.header.message.parents
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else [raw]
        except Exception:
            return [raw] if raw else []
    return []


def _utterance_text(msg: L9) -> str | None:
    return (msg.header.attributes or {}).get("utterance_text")


def _hr(char: str = "─") -> None:
    print(char * _W)


def _print_cycle(log: EpisodeLog) -> None:
    _hr("═")
    print("  CIP — CONTINGENCY REPAIR CYCLE")
    _hr("═")
    for label, msg in log:
        payload = _cip_payload(msg)
        kind_str = msg.header.kind.value + (f":{msg.header.subkind}" if msg.header.subkind else "")
        score = payload.grounding.contingency_score
        verified = payload.grounding.contingency_verified
        score_str = f"{score:.3f}" if score is not None else "—"
        verified_str = ("✓" if verified else "✗") if verified is not None else "—"
        parents = _parents_list(msg)
        utterance = _utterance_text(msg)

        _hr()
        print(f"  {label}")
        _hr()
        print(f"  kind       : {kind_str}")
        print(f"  actor      : {_sender_id(msg)}")
        print(f"  message.id : {msg.header.message.id[:8]}…")
        print(f"  parents    : {[p[:8] + '…' for p in parents] or '[]'}")
        print(f"  score      : {score_str}   verified: {verified_str}")
        if payload.grounding.repair_reason:
            print(f"  reason     : {payload.grounding.repair_reason}")
        if payload.grounding.challenges:
            print(f"  challenges : {payload.grounding.challenges}")
        if payload.utterance.evidence:
            print(f"  evidence   : {payload.utterance.evidence}")
        if utterance:
            print(f"  utterance  : {utterance}")
    _hr("═")


def _save_json(store: MessageStore, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    store.write_json(path)
    print(f"\n  JSON saved → {path}")


__all__ = ["run_demo"]


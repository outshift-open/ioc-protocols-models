"""
SIEP demo episode — declarative, scannable.

Shows the full kind=contingency repair cycle for two generic agents.

Episode map:
  step  kind               from          note
  ────  ─────────────────  ────────────  ──────────────────────────────
    1   intent             coordinator   open episode
    2   exchange (prior)   agent-alpha   declare taskwork belief
    3   exchange (prior)   agent-beta    declare taskwork belief
    4   exchange           agent-alpha   GOOD: engages task_objective ✓
    5     └─ exchange      agent-beta    grounding_ok (engine response)
    6   exchange           agent-alpha   BAD:  off-topic ✗
    7     └─ contingency   agent-beta    repair_required (engine response)
    8   exchange           agent-alpha   repair attempt: re-engages evidence
    9     └─ commit:cvg    agent-beta    repair_verified (engine response)
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ioc_l9 import SIEPBelief, SIEPPayload, SIEPUtterance, L9Message, RevisionCause
from ioc_l9.epistemic import SIEPEpistemic
from ioc_l9.siep_builder import SIEPMessageBuilder
from ioc_l9.siep_engine import SIEPEngine


# ── Concept URIs used in this episode ─────────────────────────────────────────

C   = "concept:task_objective"
SUB = "urn:concept:task_objective:deliverable_spec"

EpisodeLog = List[Tuple[str, L9Message]]


# ── Episode ────────────────────────────────────────────────────────────────────

def run_demo() -> None:
    ep     = f"urn:ioc:episode:{uuid.uuid4()}"
    engine = SIEPEngine("agent-beta", ep)
    log: EpisodeLog = []

    def B(sender: str) -> SIEPMessageBuilder:
        """Shorthand: create a builder scoped to this episode and sender."""
        return SIEPMessageBuilder(ep, sender)

    def emit(label: str, msg: L9Message) -> L9Message:
        log.append((label, msg))
        return msg

    def engine_responses(msg: L9Message, label: str) -> List[L9Message]:
        responses = engine.process(msg)
        for r in responses:
            log.append((label, r))
        return responses

    # ── 1  open episode ────────────────────────────────────────────────────────
    s1 = emit("1 · intent",
        B("coordinator").intent().team_process().concept(C).build())
    engine.process(s1)

    # ── 2  agent-alpha declares prior ─────────────────────────────────────────
    s2 = emit("2 · prior (agent-alpha)",
        B("agent-alpha").exchange().taskwork().asserted().concept(C)
            .parents(s1.message.id)
            .payload(SIEPPayload(
                utterance=SIEPUtterance(evidence=[C]),
                belief=SIEPBelief(prior=0.72, posterior=0.72,
                                revision_cause=RevisionCause.semantic_memory),
            ))
            .build())
    engine.process(s2)

    # ── 3  agent-beta declares prior ──────────────────────────────────────────
    s3 = emit("3 · prior (agent-beta)",
        B("agent-beta").exchange().taskwork().asserted().concept(C)
            .parents(s1.message.id)
            .payload(SIEPPayload(
                utterance=SIEPUtterance(evidence=[C]),
                belief=SIEPBelief(prior=0.65, posterior=0.65,
                                revision_cause=RevisionCause.semantic_memory),
            ))
            .build())

    # ── 4  good exchange — evidence overlaps task_objective ✓ ─────────────────
    s4 = emit("4 · exchange  GOOD ✓",
        B("agent-alpha").exchange().grounding().asserted().concept(C)
            .uncertainty(0.28).parents(s3.message.id)
            .payload(SIEPPayload(
                utterance=SIEPUtterance(evidence=[C, SUB], addresses_evidence=[C]),
                belief=SIEPBelief(prior=0.72, posterior=0.72),
            ))
            .text("agent-beta, bound to task_objective:deliverable_spec pathway only")
            .build())
    engine_responses(s4, "5 · exchange  grounding_ok ✓")

    # ── 6  bad exchange — off-topic, zero overlap ✗ ────────────────────────────
    s6 = emit("6 · exchange  BAD ✗",
        B("agent-alpha").exchange().grounding().asserted().concept(C)
            .uncertainty(0.28).parents(s4.message.id)
            .payload(SIEPPayload(
                utterance=SIEPUtterance(
                    evidence=["concept:timeline", "concept:resource_availability"],
                    addresses_evidence=[],
                ),
                belief=SIEPBelief(prior=0.72, posterior=0.72),
            ))
            .text("What does the timeline look like for next sprint?")
            .build())
    repair_msgs = engine_responses(s6, "7 · contingency  repair_required")
    contingency_msg = repair_msgs[0] if repair_msgs else None

    # ── 8  repair attempt — re-engages original task_objective evidence ────────
    assert contingency_msg is not None
    s8 = emit("8 · exchange  REPAIR",
        B("agent-alpha").exchange().grounding().asserted().concept(C)
            .uncertainty(0.28).parents(contingency_msg.message.id)
            .payload(SIEPPayload(
                utterance=SIEPUtterance(
                    evidence=[C, SUB],
                    addresses_evidence=[C, SUB],
                    turn_depth=1,
                ),
                belief=SIEPBelief(prior=0.72, posterior=0.72,
                                revision_cause=RevisionCause.repair_resolution),
            ))
            .text("agent-alpha, re-anchored to task_objective:deliverable_spec pathway")
            .build())
    engine_responses(s8, "9 · commit:converged  repair_verified ✓")

    # ── display ────────────────────────────────────────────────────────────────
    _print_verbose(log)
    _print_summary(log)


# ── Verbose display ────────────────────────────────────────────────────────────

_W = 100  # display width

def _hr(c: str = "─") -> None:
    print(c * _W)


def _print_verbose(log: EpisodeLog) -> None:
    _hr("═")
    print("  IE EPISODE  —  kind=contingency repair cycle  (L9 spec §IE Repair Cycle)")
    _hr("═")
    for label, msg in log:
        _hr()
        print(f"  {label}")
        _hr()
        _print_message(msg)
    _hr("═")


def _print_message(msg: L9Message) -> None:
    actor    = msg.actor.id if msg.actor else "—"
    kind_str = msg.kind.value + (f":{msg.subkind.value}" if msg.subkind else "")
    subproto = msg.subprotocol.value if msg.subprotocol else "—"

    print(f"  protocol     : {msg.protocol} v{msg.version}")
    print(f"  kind         : {kind_str}")
    print(f"  subprotocol  : {subproto}")
    print(f"  actor        : {actor}")
    print(f"  message.id   : {msg.message.id[:8]}…")
    print(f"  parents      : {[p[:8]+'…' for p in msg.message.parents] or '[]'}")
    print(f"  episode      : {msg.message.episode}")

    ep = msg.epistemic
    print(f"  epistemic ({ep.epistemic_kind}):")
    print(f"    state        = {ep.state.value if ep.state else '—'}")
    print(f"    message_act  = {ep.message_act.value if ep.message_act else '—'}")
    print(f"    uncertainty  = {ep.uncertainty}")
    if isinstance(ep, SIEPEpistemic):
        print(f"    belief_status= {ep.belief_status.value if ep.belief_status else '—'}")
        print(f"    concept_id   = {ep.concept_id or '—'}")

    siep = msg.siep_payload()
    if siep:
        u, g, b = siep.utterance, siep.grounding, siep.belief
        print(f"  siep.utterance :")
        print(f"    evidence          = {u.evidence}")
        print(f"    addresses_evidence= {u.addresses_evidence}")
        print(f"    turn_depth        = {u.turn_depth}")
        print(f"  siep.grounding :")
        print(f"    contingency_verified = {g.contingency_verified}")
        print(f"    contingency_score    = {g.contingency_score}")
        if g.repair_reason:
            print(f"    repair_reason        = {g.repair_reason.value}")
        if g.challenges:
            print(f"    challenges           = {g.challenges}")
        print(f"  siep.belief    :")
        print(f"    prior             = {b.prior}")
        print(f"    posterior         = {b.posterior}")
        if b.revision_cause:
            print(f"    revision_cause    = {b.revision_cause.value}")

    for part in msg.payload:
        if part.type == "utterance" and part.content:
            import textwrap
            wrapped = textwrap.fill(str(part.content), width=_W - 18,
                                    subsequent_indent=" " * 18)
            print(f"  utterance    : {wrapped}")


# ── Summary table ──────────────────────────────────────────────────────────────

def _print_summary(log: EpisodeLog) -> None:
    print()
    _hr("═")
    print("  EPISODE SUMMARY")
    _hr("═")

    col_label  = 34
    col_actor  = 14
    col_score  = 7
    col_verify = 10
    header = (
        f"  {'step / label':<{col_label}}"
        f"  {'actor':<{col_actor}}"
        f"  {'score':>{col_score}}"
        f"  {'verified':<{col_verify}}"
    )
    print(header)
    _hr()

    for label, msg in log:
        siep  = msg.siep_payload()
        score = siep.grounding.contingency_score if siep else None
        ver   = siep.grounding.contingency_verified if siep else None

        score_str = f"{score:.3f}" if score is not None else "  —  "
        ver_str   = ("✓" if ver else "✗") if ver is not None else "—"

        actor = msg.actor.id if msg.actor else "—"
        print(
            f"  {label:<{col_label}}"
            f"  {actor:<{col_actor}}"
            f"  {score_str:>{col_score}}"
            f"  {ver_str:<{col_verify}}"
        )

    _hr("═")


if __name__ == "__main__":
    run_demo()

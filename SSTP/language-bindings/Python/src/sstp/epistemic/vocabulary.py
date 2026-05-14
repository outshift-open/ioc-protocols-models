# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""
epistemic/vocabulary.py — Speech act vocabulary and epistemic block builder.

Defines the five SpeechAct types, three TaskPhase values, and five BeliefStatus
values that qualify every L9 message epistemically. Also provides:

- make_epistemic_block(): construct a validated epistemic dict for the wire
- infer_snp_speech_act(): deterministically infer SpeechAct from SNP ACCEPT context
  without extra wire messages
"""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional


class SpeechAct(str, enum.Enum):
    """The five communicative acts an agent can perform."""
    BELIEF_ASSERTION    = "belief_assertion"    # sender commits a belief to the group
    HELP_REQUEST        = "help_request"         # sender needs information to form a belief
    TASK_HANDOFF        = "task_handoff"         # sender delegates a sub-problem
    ALIGNMENT_CHALLENGE = "alignment_challenge"  # sender disagrees with a peer assertion
    DELIBERATION_PASS   = "deliberation_pass"    # sender yields — explicit deference, not agreement


class TaskPhase(str, enum.Enum):
    """The three phases of a team process."""
    TRANSITION    = "transition"    # goal-setting, role assignment, delegation
    ACTION        = "action"        # independent belief formation — no peer influence yet
    INTERPERSONAL = "interpersonal" # alignment, negotiation, repair


class BeliefStatus(str, enum.Enum):
    """The lifecycle state of an asserted belief."""
    ASSERTED   = "asserted"    # sender currently holds this belief
    DEFERRED   = "deferred"    # sender withholds judgement
    RETRACTED  = "retracted"   # sender withdraws a prior assertion
    CHALLENGED = "challenged"  # sender's assertion has been challenged by a peer
    UNRESOLVED = "unresolved"  # epistemic clarification failed after max attempts


def make_epistemic_block(
    *,
    speech_act: SpeechAct | str,
    task_phase: TaskPhase | str,
    belief_status: BeliefStatus | str = BeliefStatus.ASSERTED,
    uncertainty: float = 0.0,
    scope: List[str] | None = None,
    deferred_to: Optional[str] = None,
    challenges: List[str] | None = None,
) -> Dict[str, Any]:
    """Return a validated epistemic block for inclusion in an L9 header."""
    def _val(v: Any) -> str:
        return v.value if isinstance(v, enum.Enum) else str(v)

    block: Dict[str, Any] = {
        "speech_act": _val(speech_act),
        "task_phase": _val(task_phase),
        "belief_status": _val(belief_status),
        "uncertainty": max(0.0, min(1.0, float(uncertainty))),
    }
    if scope:
        block["scope"] = list(scope)
    if deferred_to:
        block["deferred_to"] = str(deferred_to)
    if challenges:
        block["challenges"] = list(challenges)
    return block


def infer_snp_speech_act(
    *,
    operation: str,
    ctrl_position_key: str,
    member_position_key: str,
    ctrl_conf: float,
    member_conf: float,
    accept_threshold: float = 0.1,
) -> SpeechAct:
    """Infer the SpeechAct for an SNP operation from local context — no wire messages needed.

    For ACCEPT: genuine BELIEF_ASSERTION if positions matched; DELIBERATION_PASS if
    the controller's confidence dominated by >= accept_threshold.
    For COUNTER_PROPOSAL / REJECT: always ALIGNMENT_CHALLENGE.
    For PROPOSE / NEGOTIATE: always BELIEF_ASSERTION.
    For all others: BELIEF_ASSERTION as default.
    """
    op = operation.lower()
    if op in ("accept",):
        if ctrl_position_key == member_position_key:
            return SpeechAct.BELIEF_ASSERTION
        if ctrl_conf >= member_conf + accept_threshold:
            return SpeechAct.DELIBERATION_PASS
        return SpeechAct.BELIEF_ASSERTION
    if op in ("counter_proposal", "reject"):
        return SpeechAct.ALIGNMENT_CHALLENGE
    if op in ("propose", "negotiate"):
        return SpeechAct.BELIEF_ASSERTION
    return SpeechAct.BELIEF_ASSERTION


__all__ = [
    "SpeechAct", "TaskPhase", "BeliefStatus",
    "make_epistemic_block", "infer_snp_speech_act",
]

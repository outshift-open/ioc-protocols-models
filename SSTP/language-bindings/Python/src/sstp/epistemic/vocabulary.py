# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""
epistemic/vocabulary.py — Speech act vocabulary and epistemic block builder.

Defines the five SpeechAct types, four TaskPhase values, and six BeliefStatus
values that qualify every L9 message epistemically. Also provides:

- make_epistemic_block(): construct a validated epistemic dict for the wire
- infer_snp_epistemic(): deterministically infer (SpeechAct, TaskPhase) from SNP
  operation context without extra wire messages
- infer_snp_speech_act(): backward-compatible wrapper returning SpeechAct only

TaskPhase alignment with Marks et al. team process taxonomy:
  TASKWORK      — individual domain work; NOT a Marks team process
  TRANSITION    — mission analysis, goal spec, strategy formulation, role assignment
  ACTION        — coordination during execution (Marks: monitoring + coordination)
  INTERPERSONAL — conflict management, deference, repair
"""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional, Tuple


class SpeechAct(str, enum.Enum):
    """The five communicative acts an agent can perform."""
    BELIEF_ASSERTION    = "belief_assertion"    # sender commits a belief to the group
    HELP_REQUEST        = "help_request"         # sender needs information to form a belief
    TASK_HANDOFF        = "task_handoff"         # sender delegates a sub-problem
    ALIGNMENT_CHALLENGE = "alignment_challenge"  # sender disagrees with a peer assertion
    DELIBERATION_PASS   = "deliberation_pass"    # sender yields — explicit deference, not agreement


class TaskPhase(str, enum.Enum):
    """The four phases qualifying epistemic acts.

    TASKWORK is not a Marks team process — it is individual domain work done
    before or outside peer coordination.  The other three follow Marks et al. [57].
    """
    TASKWORK      = "taskwork"      # individual domain work — NOT a team process
    TRANSITION    = "transition"    # goal-setting, role assignment, strategy formulation
    ACTION        = "action"        # coordination during execution (monitoring + negotiation)
    INTERPERSONAL = "interpersonal" # conflict, deference, repair


class BeliefStatus(str, enum.Enum):
    """The lifecycle state of an asserted belief."""
    ASSERTED   = "asserted"    # sender currently holds this belief
    DEFERRED   = "deferred"    # sender withholds judgement
    RETRACTED  = "retracted"   # sender withdraws a prior assertion without replacement
    REVISED    = "revised"     # sender replaces a prior assertion with a new one
    CHALLENGED = "challenged"  # sender's assertion has been challenged by a peer
    UNRESOLVED = "unresolved"  # epistemic clarification failed after max attempts


class RepairReason(str, enum.Enum):
    """Why a repair_required message was emitted (Layer 3: IE semantic repair)."""
    DELIVERY_FAILURE     = "delivery_failure"      # message never arrived
    GROUNDING_FAILURE    = "grounding_failure"      # arrived but contingency check failed
    UNGROUNDABLE_NOVELTY = "ungroundable_novelty"  # presupposes context receiver doesn't have
    SCOPE_MISMATCH       = "scope_mismatch"        # response scope doesn't overlap utterance scope


def make_epistemic_block(
    *,
    speech_act: SpeechAct | str,
    task_phase: TaskPhase | str,
    belief_status: BeliefStatus | str = BeliefStatus.ASSERTED,
    uncertainty: float = 0.0,
    scope: List[str] | None = None,
    deferred_to: Optional[str] = None,
    challenges: List[str] | None = None,
    repair_reason: RepairReason | str | None = None,
    addresses_evidence: List[str] | None = None,
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
    if repair_reason is not None:
        block["repair_reason"] = _val(repair_reason)
    if addresses_evidence:
        block["addresses_evidence"] = list(addresses_evidence)
    return block


def infer_snp_epistemic(
    *,
    operation: str,
    ctrl_position_key: str,
    member_position_key: str,
    ctrl_conf: float,
    member_conf: float,
    accept_threshold: float = 0.1,
) -> Tuple[SpeechAct, TaskPhase]:
    """Infer (SpeechAct, TaskPhase) from SNP operation context — no wire messages needed.

    PROPOSE          → (BELIEF_ASSERTION,    TRANSITION)   strategy commitment
    NEGOTIATE        → (BELIEF_ASSERTION,    ACTION)       coordination round
    ACCEPT genuine   → (BELIEF_ASSERTION,    ACTION)       coordination resolved
    ACCEPT forced    → (DELIBERATION_PASS,   INTERPERSONAL) social compliance
    COUNTER_PROPOSAL → (ALIGNMENT_CHALLENGE, INTERPERSONAL) conflict
    REJECT           → (ALIGNMENT_CHALLENGE, INTERPERSONAL) conflict
    """
    op = operation.lower()
    if op == "propose":
        return SpeechAct.BELIEF_ASSERTION, TaskPhase.TRANSITION
    if op == "negotiate":
        return SpeechAct.BELIEF_ASSERTION, TaskPhase.ACTION
    if op == "accept":
        if ctrl_position_key == member_position_key:
            return SpeechAct.BELIEF_ASSERTION, TaskPhase.ACTION
        if ctrl_conf >= member_conf + accept_threshold:
            return SpeechAct.DELIBERATION_PASS, TaskPhase.INTERPERSONAL
        return SpeechAct.BELIEF_ASSERTION, TaskPhase.ACTION
    if op in ("counter_proposal", "reject"):
        return SpeechAct.ALIGNMENT_CHALLENGE, TaskPhase.INTERPERSONAL
    return SpeechAct.BELIEF_ASSERTION, TaskPhase.ACTION


def infer_snp_speech_act(
    *,
    operation: str,
    ctrl_position_key: str,
    member_position_key: str,
    ctrl_conf: float,
    member_conf: float,
    accept_threshold: float = 0.1,
) -> SpeechAct:
    """Backward-compatible wrapper — returns SpeechAct only.

    Prefer infer_snp_epistemic() which also returns the correct TaskPhase.
    """
    return infer_snp_epistemic(
        operation=operation,
        ctrl_position_key=ctrl_position_key,
        member_position_key=member_position_key,
        ctrl_conf=ctrl_conf,
        member_conf=member_conf,
        accept_threshold=accept_threshold,
    )[0]


__all__ = [
    "SpeechAct", "TaskPhase", "BeliefStatus", "RepairReason",
    "make_epistemic_block", "infer_snp_epistemic", "infer_snp_speech_act",
]

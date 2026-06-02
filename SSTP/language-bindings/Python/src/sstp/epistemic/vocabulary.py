# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""
epistemic/vocabulary.py — Speech act vocabulary and epistemic block builder.

Defines the five SpeechAct types, three EpistemicState values, and six BeliefStatus
values that qualify every L9 message epistemically. Also provides:

- make_epistemic_block(): construct a validated epistemic dict for the wire
- infer_snp_epistemic(): deterministically infer (SpeechAct, EpistemicState) from SNP
  operation context without extra wire messages
- infer_snp_speech_act(): backward-compatible wrapper returning SpeechAct only

EpistemicState — three first-class states that drive the L9 epistemic block:
  TASKWORK      — agent forming independent prior; no peer contact yet
  GROUNDING     — pairwise IE exchange; positions being verified or repaired
  TEAM_PROCESS  — SNP convergence round; team negotiating shared position

TaskPhase is kept as a deprecated alias for backward compatibility.
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


class EpistemicState(str, enum.Enum):
    """The three epistemic states that qualify every L9 peer_turn."""
    TASKWORK     = "taskwork"      # independent prior formation; no peer contact
    GROUNDING    = "grounding"     # pairwise IE exchange; verifying or repairing positions
    TEAM_PROCESS = "team_process"  # SNP convergence; team negotiating shared position


class TaskPhase(str, enum.Enum):
    """Deprecated — use EpistemicState.  Kept for backward compatibility."""
    TASKWORK      = "taskwork"
    TRANSITION    = "team_process"   # maps to TEAM_PROCESS
    ACTION        = "grounding"      # maps to GROUNDING
    INTERPERSONAL = "grounding"      # maps to GROUNDING (IE repair); SNP callers use TEAM_PROCESS


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
    epistemic_state: EpistemicState | str | None = None,
    belief_status: BeliefStatus | str = BeliefStatus.ASSERTED,
    uncertainty: float = 0.0,
    scope: List[str] | None = None,
    deferred_to: Optional[str] = None,
    challenges: List[str] | None = None,
    repair_reason: RepairReason | str | None = None,
    addresses_evidence: List[str] | None = None,
    task_phase: "TaskPhase | str | None" = None,  # deprecated; use epistemic_state
) -> Dict[str, Any]:
    """Return a validated epistemic block for inclusion in an L9 header."""
    def _val(v: Any) -> str:
        return v.value if isinstance(v, enum.Enum) else str(v)

    resolved_state = epistemic_state if epistemic_state is not None else (
        task_phase if task_phase is not None else EpistemicState.GROUNDING
    )

    block: Dict[str, Any] = {
        "speech_act": _val(speech_act),
        "epistemic_state": _val(resolved_state),
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
) -> Tuple[SpeechAct, EpistemicState]:
    """Infer (SpeechAct, EpistemicState) from SNP operation context — no wire messages needed.

    PROPOSE          → (BELIEF_ASSERTION,    TEAM_PROCESS)  opens convergence round
    NEGOTIATE        → (BELIEF_ASSERTION,    TEAM_PROCESS)  convergence in progress
    ACCEPT genuine   → (BELIEF_ASSERTION,    TEAM_PROCESS)  convergence resolved
    ACCEPT forced    → (DELIBERATION_PASS,   TEAM_PROCESS)  social compliance
    COUNTER_PROPOSAL → (ALIGNMENT_CHALLENGE, TEAM_PROCESS)  position challenge
    REJECT           → (ALIGNMENT_CHALLENGE, TEAM_PROCESS)  position challenge
    """
    op = operation.lower()
    if op == "propose":
        return SpeechAct.BELIEF_ASSERTION, EpistemicState.TEAM_PROCESS
    if op == "negotiate":
        return SpeechAct.BELIEF_ASSERTION, EpistemicState.TEAM_PROCESS
    if op == "accept":
        if ctrl_position_key == member_position_key:
            return SpeechAct.BELIEF_ASSERTION, EpistemicState.TEAM_PROCESS
        if ctrl_conf >= member_conf + accept_threshold:
            return SpeechAct.DELIBERATION_PASS, EpistemicState.TEAM_PROCESS
        return SpeechAct.BELIEF_ASSERTION, EpistemicState.TEAM_PROCESS
    if op in ("counter_proposal", "reject"):
        return SpeechAct.ALIGNMENT_CHALLENGE, EpistemicState.TEAM_PROCESS
    return SpeechAct.BELIEF_ASSERTION, EpistemicState.TEAM_PROCESS


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

    Prefer infer_snp_epistemic() which also returns the correct EpistemicState.
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
    "SpeechAct", "EpistemicState", "TaskPhase", "BeliefStatus", "RepairReason",
    "make_epistemic_block", "infer_snp_epistemic", "infer_snp_speech_act",
]

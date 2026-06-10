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
    """Three essential communicative acts. Delegation and repair are carried by event_type."""
    ASSERTION  = "assertion"   # sender commits a position or prior
    CHALLENGE  = "challenge"   # sender disputes; contingency always true in IE
    COMPLIANCE = "compliance"  # sender yields to social pressure; no posterior update

    # Deprecated aliases — kept for backwards compatibility with persisted data
    BELIEF_ASSERTION    = "assertion"    # → ASSERTION
    ALIGNMENT_CHALLENGE = "challenge"    # → CHALLENGE
    DELIBERATION_PASS   = "compliance"   # → COMPLIANCE
    TASK_HANDOFF        = "assertion"    # → ASSERTION (delegation carried by event_type)
    HELP_REQUEST        = "assertion"    # → ASSERTION (repair carried by event_type)


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
    concept_id: Optional[str] = None,
    task_phase: "TaskPhase | str | None" = None,  # deprecated; use epistemic_state
) -> Dict[str, Any]:
    """Return a validated epistemic block for inclusion in the L9 header.

    Produces base fields only — sub-protocol agnostic:
      speech_act, epistemic_state, belief_status, concept_id, uncertainty

    IE sub-protocol extension fields (scope, addresses_evidence, repair_reason,
    challenges) belong in IEPayload — not in the L9 header.

    SNP sub-protocol extension (deferred_to) is set via make_snp_epistemic_extension()
    and belongs in NegotiationPayload.proposal_payload.
    """
    def _val(v: Any) -> str:
        return v.value if isinstance(v, enum.Enum) else str(v)

    resolved_state = epistemic_state if epistemic_state is not None else (
        task_phase if task_phase is not None else EpistemicState.GROUNDING
    )

    block: Dict[str, Any] = {
        "speech_act":    _val(speech_act),
        "state":         _val(resolved_state),   # was "epistemic_state"
        "belief_status": _val(belief_status),
        "uncertainty":   max(0.0, min(1.0, float(uncertainty))),
    }
    if concept_id:
        block["concept_id"] = str(concept_id)
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
        return SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS
    if op == "negotiate":
        return SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS
    if op == "accept":
        if ctrl_position_key == member_position_key:
            return SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS
        if ctrl_conf >= member_conf + accept_threshold:
            return SpeechAct.COMPLIANCE, EpistemicState.TEAM_PROCESS
        return SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS
    if op in ("counter_proposal", "reject"):
        return SpeechAct.CHALLENGE, EpistemicState.TEAM_PROCESS
    return SpeechAct.ASSERTION, EpistemicState.TEAM_PROCESS


def make_snp_epistemic_extension(
    block: Dict[str, Any],
    *,
    deferred_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge SNP sub-protocol extension fields into an existing epistemic block.

    SNP extension fields (set only by the SNP layer):
      deferred_to — agent_id this deliberation_pass defers to; only set when
                    speech_act=deliberation_pass and the deferral target is known.

    Call after make_epistemic_block() when the block is for an SNP message:
        block = make_epistemic_block(speech_act=DELIBERATION_PASS, ...)
        block = make_snp_epistemic_extension(block, deferred_to="agent:cardiologist")
    """
    if deferred_to:
        block = dict(block)
        block["deferred_to"] = str(deferred_to)
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
    "make_epistemic_block", "make_snp_epistemic_extension",
    "infer_snp_epistemic", "infer_snp_speech_act",
]

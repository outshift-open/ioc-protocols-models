# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/ie/grounding.py — IE Layer 3: semantic grounding checks.

Every response B sends to A must engage the specific argument A made.
This module provides the structural checks that enforce that constraint
and detect when repair is needed.

Functions:
    contingency_check()           — does B's response engage A's argument?
    detect_ungroundable_novelty() — does B's utterance presuppose context A lacks?
    concept_overlap_ratio()       — fraction of A's concept_ids present in B's response
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from SSTP.subprotocol.cip.src.cip_payload import RepairReason
from SSTP.subprotocol.cip.src.builder import build_l9_header
from SSTP.subprotocol.siep.src.epistemic.vocabulary import (
    SpeechAct, EpistemicState, BeliefStatus, make_epistemic_block,
)
from SSTP.subprotocol.siep.src.epistemic.stores import CommonGround

if TYPE_CHECKING:
    pass

# Minimum overlap fraction between A's concept_ids and B's addresses_evidence
# for the response to be considered contingent.
CONTINGENCY_THRESHOLD: float = 0.5


def _get_concept_ids(
    epistemic: Optional[Dict[str, Any]],
    ie_concept_ids: Optional[List[str]] = None,
    ie_addresses_evidence: Optional[List[str]] = None,
) -> Set[str]:
    """Extract concept_ids for grounding checks.

    Primary source: ``concept_id`` from the L9 header epistemic block.
    IE payload fields: ``ie_concept_ids`` and ``ie_addresses_evidence`` from ReplicaEntry
    (populated from IEPayload.utterance when the message was applied to the replica).
    Fallback: ``scope`` and ``addresses_evidence`` from epistemic block for backwards compat
    with messages that pre-date the payload migration.
    """
    if not epistemic and not ie_concept_ids and not ie_addresses_evidence:
        return set()
    ep = epistemic or {}
    primary = ep.get("concept_id")
    # IE payload fields take precedence over header fallbacks
    concepts = set(ie_concept_ids or ep.get("scope") or [])
    addresses = set(ie_addresses_evidence or ep.get("addresses_evidence") or [])
    result = concepts | addresses
    if primary:
        result.add(primary)
    return result


def concept_overlap_ratio(
    utterance_concepts: Set[str],
    response_concepts: Set[str],
) -> float:
    """Fraction of utterance concepts that appear in the response concepts.

    Returns 0.0 if utterance_concepts is empty (no constraint to check).
    Returns 1.0 if all utterance concepts are addressed.
    """
    if not utterance_concepts:
        return 1.0
    overlap = utterance_concepts & response_concepts
    return len(overlap) / len(utterance_concepts)


def contingency_check(
    utterance_a_epistemic: Optional[Dict[str, Any]],
    response_b_epistemic: Optional[Dict[str, Any]],
    threshold: float = CONTINGENCY_THRESHOLD,
    a_ie_concept_ids: Optional[List[str]] = None,
    a_ie_addresses_evidence: Optional[List[str]] = None,
    b_ie_concept_ids: Optional[List[str]] = None,
    b_ie_addresses_evidence: Optional[List[str]] = None,
) -> tuple[bool, float]:
    """Check whether B's response is contingent on A's argument.

    Primary concept data comes from IE payload fields (ie_concept_ids,
    ie_addresses_evidence) stored on ReplicaEntry. Falls back to epistemic
    block scope/addresses_evidence for backwards compat.

    ALIGNMENT_CHALLENGE speech_act is always treated as contingent.
    Returns (is_contingent: bool, overlap_ratio: float).
    """
    if response_b_epistemic is None and not b_ie_concept_ids and not b_ie_addresses_evidence:
        return False, 0.0

    # An explicit challenge counts as contingent — B engaged with the argument
    if (response_b_epistemic or {}).get("speech_act") in ("challenge", "alignment_challenge"):
        return True, 1.0

    a_concepts = _get_concept_ids(utterance_a_epistemic, a_ie_concept_ids, a_ie_addresses_evidence)
    b_concepts = _get_concept_ids(response_b_epistemic, b_ie_concept_ids, b_ie_addresses_evidence)

    ratio = concept_overlap_ratio(a_concepts, b_concepts)
    return ratio >= threshold, round(ratio, 4)


def detect_scope_mismatch(
    utterance_a_epistemic: Optional[Dict[str, Any]],
    response_b_epistemic: Optional[Dict[str, Any]],
    a_ie_concept_ids: Optional[List[str]] = None,
    b_ie_concept_ids: Optional[List[str]] = None,
) -> bool:
    """True if B's response scope has zero overlap with A's utterance scope."""
    a_concepts = _get_concept_ids(utterance_a_epistemic, a_ie_concept_ids)
    b_concepts = _get_concept_ids(response_b_epistemic, b_ie_concept_ids)
    if not a_concepts:
        return False
    return len(a_concepts & b_concepts) == 0


def detect_ungroundable_novelty(
    utterance_b_epistemic: Optional[Dict[str, Any]],
    receiver_known_concept_ids: Set[str],
    episode_concept_ids: Set[str],
    b_ie_concept_ids: Optional[List[str]] = None,
) -> bool:
    """True if B's utterance references concepts unknown to receiver A."""
    b_concepts = _get_concept_ids(utterance_b_epistemic, b_ie_concept_ids)
    known = receiver_known_concept_ids | episode_concept_ids
    novel = b_concepts - known
    return len(novel) > 0


def diagnose_repair_reason(
    utterance_a_epistemic: Optional[Dict[str, Any]],
    response_b_epistemic: Optional[Dict[str, Any]],
    delivered: bool = True,
    a_ie_concept_ids: Optional[List[str]] = None,
    a_ie_addresses_evidence: Optional[List[str]] = None,
    b_ie_concept_ids: Optional[List[str]] = None,
    b_ie_addresses_evidence: Optional[List[str]] = None,
) -> Optional[RepairReason]:
    """Determine the appropriate repair_reason, or None if no repair is needed."""
    if not delivered:
        return RepairReason.DELIVERY_FAILURE

    if detect_scope_mismatch(utterance_a_epistemic, response_b_epistemic,
                             a_ie_concept_ids, b_ie_concept_ids):
        return RepairReason.SCOPE_MISMATCH

    is_contingent, _ = contingency_check(
        utterance_a_epistemic, response_b_epistemic,
        a_ie_concept_ids=a_ie_concept_ids,
        a_ie_addresses_evidence=a_ie_addresses_evidence,
        b_ie_concept_ids=b_ie_concept_ids,
        b_ie_addresses_evidence=b_ie_addresses_evidence,
    )
    if not is_contingent:
        return RepairReason.GROUNDING_FAILURE

    return None


def verify_grounding_bilateral(
    utterance_a: str,
    response_b: str,
    debate_message_id: str,
    task_goal: str,
    speaker: str,
    listener: str,
    listener_actual_confidence: float,
    listener_belief: Dict[str, Any],
    concept_id: str = "",
    forced_accept: bool = False,
    speaker_epistemic: Optional[Dict[str, Any]] = None,
    listener_epistemic: Optional[Dict[str, Any]] = None,
    *,
    tom_engine: Any,
    use_case: str,
    episode_id: str,
    message_bus: Any,
    common_ground_ids: List[str],
) -> None:
    """Verify bilateral grounding using B's actual response (CIP §3.1).

    Called AFTER listener has responded with response_b. Assesses whether
    response_b is contingent on utterance_a. Records CommonGround with actual
    posteriors for both parties.

    forced_accept=True: accept driven by controller confidence dominance, not
    genuine agreement. Suppresses CommonGround to avoid polluting SCR.
    """
    if tom_engine is None:
        return

    # Team-process tokens carry epistemic_state=TEAM_PROCESS and no clinical
    # content — grounding is structurally guaranteed by the auto-accept contract.
    _spk_ep_state = (speaker_epistemic or {}).get("state", "")
    _lst_ep_state = (listener_epistemic or {}).get("state", "")
    if _spk_ep_state == "team_process" or _lst_ep_state == "team_process":
        return

    cid = concept_id or f"urn:concept:{use_case}:{task_goal[:32]}"
    confidence_before = 0.5
    result: Dict[str, Any] = {}

    if forced_accept:
        is_deliberation_pass = True
        contingency_score = 0.0
    else:
        _spk_ids = _get_concept_ids(speaker_epistemic)
        _lst_ids = _get_concept_ids(listener_epistemic)
        if _spk_ids and _lst_ids:
            _contingent, _ratio = contingency_check(speaker_epistemic, listener_epistemic)
            if not _contingent:
                contingency_score = _ratio
                is_deliberation_pass = True
                result = {"contingency_score": contingency_score, "posterior_confidence": None}
            else:
                result = tom_engine.agent(listener).assess_utterance(
                    response_b, task_goal,
                    speaker=listener,
                    listener=speaker,
                    listener_prior_utterance=utterance_a,
                    confidence_before=confidence_before,
                    speaker_epistemic=listener_epistemic,
                    listener_prior_epistemic=speaker_epistemic,
                    concept_id=cid,
                    use_case=use_case,
                )
                llm_contingency = float(result.get("contingency_score", 1.0))
                contingency_score = round(min(_ratio, llm_contingency), 4)
                result["contingency_score"] = contingency_score
                is_deliberation_pass = contingency_score < 0.4
        else:
            result = tom_engine.agent(listener).assess_utterance(
                response_b, task_goal,
                speaker=listener,
                listener=speaker,
                listener_prior_utterance=utterance_a,
                confidence_before=confidence_before,
                concept_id=cid,
                use_case=use_case,
            )
            contingency_score = float(result.get("contingency_score", 1.0))
            is_deliberation_pass = contingency_score < 0.4

    ts = int(time.time() * 1000)

    if not forced_accept and result.get("grounding_failure"):
        _repair_child = f"{episode_id}:cip_repair:{debate_message_id[-8:]}"
        _repair_req = build_l9_header(
            use_case=use_case,
            event_type="repair_required",
            sender=listener,
            receiver=speaker,
            timestamp_ms=ts,
            sensitivity="confidential",
            utterance=response_b,
            parent_ids=[debate_message_id],
            episode_id=_repair_child,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                belief_status=BeliefStatus.DEFERRED,
            ),
        )
        message_bus.messages.append(_repair_req)
        _repair_applied = build_l9_header(
            use_case=use_case,
            event_type="repair_applied",
            sender=speaker,
            receiver=listener,
            timestamp_ms=ts + 1,
            sensitivity="confidential",
            utterance=f"re-anchor to task: {task_goal}",
            parent_ids=[_repair_req["message"]["id"]],
            episode_id=_repair_child,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                belief_status=BeliefStatus.REVISED,
            ),
        )
        message_bus.messages.append(_repair_applied)

    if not is_deliberation_pass and not forced_accept:
        contingency_verified = contingency_score >= 0.4
        ground = CommonGround(
            holder_id=speaker,
            confirmer_id=listener,
            concept_id=cid,
            use_case=use_case,
            episode_id=episode_id,
            grounding_confidence=contingency_score,
            holder_confidence=0.5,
            confirmer_confidence=listener_actual_confidence,
            contingency_verified=contingency_verified,
            speech_acts=["belief_assertion", "belief_assertion"],
            grounding_message_ids=[debate_message_id],
            formed_at_ms=ts,
        )
        tom_engine.agent(listener)._epistemic_store.record_common_ground(ground)
        tom_engine.agent(speaker)._epistemic_store.record_common_ground(ground)
        common_ground_ids.append(
            ground.grounding_message_ids[0] if ground.grounding_message_ids else episode_id
        )


__all__ = [
    "CONTINGENCY_THRESHOLD",
    "concept_overlap_ratio",
    "contingency_check",
    "detect_scope_mismatch",
    "detect_ungroundable_novelty",
    "diagnose_repair_reason",
    "verify_grounding_bilateral",
]

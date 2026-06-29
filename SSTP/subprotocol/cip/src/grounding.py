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

from typing import Any, Dict, List, Optional, Set

from SSTP.subprotocol.cip.src.cip_payload import RepairReason

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


__all__ = [
    "CONTINGENCY_THRESHOLD",
    "concept_overlap_ratio",
    "contingency_check",
    "detect_scope_mismatch",
    "detect_ungroundable_novelty",
    "diagnose_repair_reason",
]

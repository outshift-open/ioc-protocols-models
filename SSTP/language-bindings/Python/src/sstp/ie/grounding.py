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

from sstp.epistemic.vocabulary import RepairReason

# Minimum overlap fraction between A's concept_ids and B's addresses_evidence
# for the response to be considered contingent.
CONTINGENCY_THRESHOLD: float = 0.5


def _get_concept_ids(epistemic: Optional[Dict[str, Any]]) -> Set[str]:
    """Extract concept_ids from an epistemic block's scope or addresses_evidence field."""
    if not epistemic:
        return set()
    scope = epistemic.get("scope") or []
    addresses = epistemic.get("addresses_evidence") or []
    return set(scope) | set(addresses)


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
) -> tuple[bool, float]:
    """Check whether B's response is contingent on A's argument.

    A response is contingent if B's addresses_evidence (or scope) overlaps
    with A's concept_ids (scope) above the threshold.

    ALIGNMENT_CHALLENGE speech_act is always treated as contingent — B engaged,
    even if disagreeing.

    Returns (is_contingent: bool, overlap_ratio: float).
    """
    if response_b_epistemic is None:
        return False, 0.0

    # An explicit challenge counts as contingent — B engaged with the argument
    if response_b_epistemic.get("speech_act") == "alignment_challenge":
        return True, 1.0

    a_concepts = _get_concept_ids(utterance_a_epistemic)
    b_concepts = _get_concept_ids(response_b_epistemic)

    ratio = concept_overlap_ratio(a_concepts, b_concepts)
    return ratio >= threshold, round(ratio, 4)


def detect_scope_mismatch(
    utterance_a_epistemic: Optional[Dict[str, Any]],
    response_b_epistemic: Optional[Dict[str, Any]],
) -> bool:
    """True if B's response scope has zero overlap with A's utterance scope.

    Distinct from a low-overlap grounding failure: zero overlap means B
    is responding to something different entirely.
    """
    a_concepts = _get_concept_ids(utterance_a_epistemic)
    b_concepts = _get_concept_ids(response_b_epistemic)
    if not a_concepts:
        return False
    return len(a_concepts & b_concepts) == 0


def detect_ungroundable_novelty(
    utterance_b_epistemic: Optional[Dict[str, Any]],
    receiver_known_concept_ids: Set[str],
    episode_concept_ids: Set[str],
) -> bool:
    """True if B's utterance references concepts unknown to receiver A.

    A concept is ungroundable if it appears in B's scope but is absent from
    both A's belief store and the current episode context.
    """
    b_concepts = _get_concept_ids(utterance_b_epistemic)
    known = receiver_known_concept_ids | episode_concept_ids
    novel = b_concepts - known
    return len(novel) > 0


def diagnose_repair_reason(
    utterance_a_epistemic: Optional[Dict[str, Any]],
    response_b_epistemic: Optional[Dict[str, Any]],
    delivered: bool = True,
) -> Optional[RepairReason]:
    """Determine the appropriate repair_reason, or None if no repair is needed.

    Priority order:
        1. DELIVERY_FAILURE — message never arrived
        2. SCOPE_MISMATCH  — zero concept overlap
        3. GROUNDING_FAILURE — overlap below threshold
    """
    if not delivered:
        return RepairReason.DELIVERY_FAILURE

    if detect_scope_mismatch(utterance_a_epistemic, response_b_epistemic):
        return RepairReason.SCOPE_MISMATCH

    is_contingent, _ = contingency_check(utterance_a_epistemic, response_b_epistemic)
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

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
SSTP/base/grounding.py — CIP inbound-grounding logic as free functions.

receive_peer_turn() is the episode-layer counterpart to emit_peer_turn():
it verifies contingency, writes to the belief and common-ground stores,
and emits a semantic repair if grounding fails.  It belongs here, not on
the bus, because it reasons about epistemic content — that is episode-layer
work, not transport work.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from SSTP.subprotocol.siep.src.epistemic.stores import BeliefRevision, CommonGround
from SSTP.subprotocol.siep.src.epistemic.vocabulary import RepairReason

if TYPE_CHECKING:
    from SSTP.subprotocol.siep.src.panel import NetworkHandle


def receive_peer_turn(
    net: "NetworkHandle",
    envelope: Dict[str, Any],
    *,
    replica: Optional[Any] = None,
    belief_store: Optional[Any] = None,
    common_ground_store: Optional[Any] = None,
    use_case: str = "",
) -> Optional[Dict[str, Any]]:
    """Verify CIP contingency for an inbound peer turn and update epistemic stores.

    On success (contingency verified):
      - Updates ``belief_store`` with a BeliefRevision for the sender.
      - Updates ``common_ground_store`` with a CommonGround record for the pair.
      - Returns None.

    On failure (grounding failure):
      - Emits a semantic repair via ``net``.
      - Returns the emitted repair header.
    """
    from SSTP.subprotocol.cip.src.grounding import contingency_check, diagnose_repair_reason
    from SSTP.subprotocol.cip.src.message import get_part
    from SSTP.subprotocol.cip.src.builder import get_topic
    from SSTP.base.emit import emit_semantic_repair

    header = {k: v for k, v in envelope.items() if k != "payload"}
    ie_content = get_part(envelope, "cip")
    grounding = ie_content.get("grounding") or {}
    utterance = ie_content.get("utterance") or {}
    belief = ie_content.get("belief") or {}

    parents = (header.get("message") or {}).get("parents") or []
    prior_turn_mid = parents[0] if parents else None
    prior_epistemic: Optional[Dict[str, Any]] = None
    prior_ie_concept_ids: List[str] = []
    prior_ie_addresses_evidence: List[str] = []
    if prior_turn_mid is not None and replica is not None:
        for e in getattr(replica, "_entries", []):
            if e.message_id == prior_turn_mid:
                prior_epistemic = e.epistemic or {}
                prior_ie_concept_ids = list(getattr(e, "ie_concept_ids", []))
                prior_ie_addresses_evidence = list(getattr(e, "ie_addresses_evidence", []))
                break

    current_ie_concept_ids = list(utterance.get("evidence") or utterance.get("concept_ids") or [])
    current_ie_addresses_evidence = list(utterance.get("addresses_evidence") or [])
    current_epistemic = header.get("epistemic") or {}

    verified, score = contingency_check(
        prior_epistemic, current_epistemic,
        a_ie_concept_ids=prior_ie_concept_ids,
        a_ie_addresses_evidence=prior_ie_addresses_evidence,
        b_ie_concept_ids=current_ie_concept_ids,
        b_ie_addresses_evidence=current_ie_addresses_evidence,
    )

    ie_content = dict(ie_content)
    ie_content["grounding"] = {**grounding, "contingency_verified": verified, "contingency_score": score}

    if replica is not None:
        replica.apply(header, payload=ie_content)

    if verified:
        ep_concept_id = get_topic(header) or ""
        if belief_store is not None and ep_concept_id:
            sender = (
                (header.get("participants") or {}).get("actors")
                or header.get("actors")
                or [{}]
            )[0].get("id", "unknown")
            ep_id = (header.get("message") or {}).get("episode", "")
            revision = BeliefRevision(
                cause=belief.get("revision_cause") or "grounded_argument",
                confidence_before=float(belief.get("prior", 0.5)),
                confidence_after=float(belief.get("posterior", 0.5)),
                caused_by_agent=None,
                argument_concept_ids=list(utterance.get("evidence") or utterance.get("concept_ids", [])),
                episode_id=ep_id,
            )
            bus_use_case = getattr(net, "use_case", "")
            belief_store.record_revision(
                sender, ep_concept_id, use_case or bus_use_case, ep_id,
                revision, new_status="asserted",
                new_public_confidence=float(belief.get("posterior", 0.5)),
            )
        if common_ground_store is not None:
            sender = (
                (header.get("participants") or {}).get("actors")
                or header.get("actors")
                or [{}]
            )[0].get("id", "unknown")
            ep = header.get("epistemic") or {}
            prior_sender = ""
            if prior_epistemic is not None and prior_turn_mid is not None and replica is not None:
                for e in getattr(replica, "_entries", []):
                    if e.message_id == prior_turn_mid:
                        prior_sender = e.sender
                        break
            bus_use_case = getattr(net, "use_case", "")
            cg = CommonGround(
                holder_id=prior_sender,
                confirmer_id=sender,
                concept_id=ep_concept_id,
                use_case=use_case or bus_use_case,
                episode_id=(header.get("message") or {}).get("episode", ""),
                grounding_confidence=score,
                holder_confidence=float(belief.get("prior", 0.5)),
                confirmer_confidence=float(belief.get("posterior", 0.5)),
                contingency_verified=True,
                speech_acts=[ep.get("message_act", "")],
                grounding_message_ids=[prior_turn_mid or "", header["message"]["id"]],
                formed_at_ms=int(time.time() * 1000),
            )
            common_ground_store.record(cg)
        return None
    else:
        repair_reason = diagnose_repair_reason(prior_epistemic, current_epistemic)
        if repair_reason is None:
            repair_reason = RepairReason.GROUNDING_FAILURE
        sender_id = getattr(net, "run_id", "")
        return emit_semantic_repair(
            net,
            sender=sender_id,
            receiver=(
                (header.get("participants") or {}).get("actors")
                or header.get("actors")
                or [{}]
            )[0].get("id", "unknown"),
            target_message_id=header["message"]["id"],
            repair_reason=repair_reason,
            target_epistemic=current_epistemic,
            episode_id=(header.get("message") or {}).get("episode"),
        )


__all__ = ["receive_peer_turn"]

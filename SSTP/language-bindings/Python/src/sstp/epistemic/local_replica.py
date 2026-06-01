# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""
epistemic/local_replica.py — Per-agent grow-only message log (CRDT).

Each agent maintains one LocalStateReplica per episode_id it participates in.
The replica is a grow-only set — entries are never deleted, duplicates are ignored.
State is derived by folding all entries; there is no central coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


def _parse_timestamp_ms(header: Dict[str, Any]) -> int:
    """Parse dt_created ISO string from L9 header to milliseconds."""
    dt_str = header.get("dt_created", "")
    if not dt_str:
        return 0
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return 0


@dataclass
class ReplicaEntry:
    """A single message recorded in a local replica."""
    message_id: str
    sender: str
    sequence: int                        # -1 if state_sequence not provided
    timestamp_ms: int
    epistemic: Optional[Dict[str, Any]]  # the epistemic block, if present
    operation: Optional[str]             # SNP/IE operation, for local inference


class LocalStateReplica:
    """Per-agent, per-state-object grow-only message log (CRDT).

    Entries are appended on apply(); never removed. Duplicates are silently
    ignored via _seen_ids. State = fold over all entries.
    """

    def __init__(self, episode_id: str, owner_agent_id: str) -> None:
        self.episode_id = episode_id
        self.owner_agent_id = owner_agent_id
        self._entries: List[ReplicaEntry] = []
        self._seen_ids: Set[str] = set()
        self._sender_high_water: Dict[str, int] = {}

    def apply(self, header: Dict[str, Any], operation: str | None = None) -> bool:
        """Ingest one L9 header. Returns True if new, False if already seen."""
        mid = header.get("message_id", "")
        if not mid or mid in self._seen_ids:
            return False
        sender = header.get("origin", {}).get("actor_id", "unknown")
        seq_block = header.get("state_sequence") or {}
        seq = int(seq_block.get("counter", -1))
        entry = ReplicaEntry(
            message_id=mid,
            sender=sender,
            sequence=seq,
            timestamp_ms=_parse_timestamp_ms(header),
            epistemic=header.get("epistemic"),
            operation=operation,
        )
        self._entries.append(entry)
        self._seen_ids.add(mid)
        if seq >= 0:
            prev = self._sender_high_water.get(sender, -1)
            if seq > prev:
                self._sender_high_water[sender] = seq
        return True

    def get_derived_state(self) -> Dict[str, Any]:
        """Fold all entries into a current epistemic summary for this namespace."""
        by_sender: Dict[str, List[ReplicaEntry]] = {}
        for e in self._entries:
            by_sender.setdefault(e.sender, []).append(e)

        belief_counts: Dict[str, int] = {"asserted": 0, "deferred": 0,
                                          "retracted": 0, "revised": 0,
                                          "challenged": 0, "unresolved": 0}
        speech_act_counts: Dict[str, int] = {}
        phase_counts: Dict[str, int] = {"taskwork": 0, "transition": 0,
                                         "action": 0, "interpersonal": 0}

        taskwork_total = 0
        taskwork_assertions = 0
        interp_belief_assertions = 0
        interp_delib_passes = 0

        for e in self._entries:
            ep = e.epistemic or {}
            bs = ep.get("belief_status", "asserted")
            belief_counts[bs] = belief_counts.get(bs, 0) + 1
            sa = ep.get("speech_act", "")
            if sa:
                speech_act_counts[sa] = speech_act_counts.get(sa, 0) + 1
            phase = ep.get("task_phase", "")
            if phase in phase_counts:
                phase_counts[phase] += 1
            if phase == "taskwork":
                taskwork_total += 1
                if sa == "belief_assertion" and bs == "asserted":
                    taskwork_assertions += 1
            elif phase == "interpersonal":
                if sa == "belief_assertion":
                    interp_belief_assertions += 1
                elif sa == "deliberation_pass":
                    interp_delib_passes += 1

        total_accepts = belief_counts["asserted"] + belief_counts["deferred"]
        genuine = sum(
            1 for e in self._entries
            if (e.epistemic or {}).get("speech_act") == "belief_assertion"
            and (e.epistemic or {}).get("belief_status") == "asserted"
        )
        epistemic_strength = genuine / total_accepts if total_accepts > 0 else 0.0

        taskwork_independence_ratio = (
            taskwork_assertions / taskwork_total if taskwork_total > 0 else 1.0
        )
        interp_accepts = interp_belief_assertions + interp_delib_passes
        social_compliance_ratio = (
            interp_delib_passes / interp_accepts if interp_accepts > 0 else 0.0
        )

        return {
            "episode_id": self.episode_id,
            "message_count": len(self._entries),
            "participants": sorted(by_sender.keys()),
            "sender_message_counts": {s: len(es) for s, es in by_sender.items()},
            "sender_high_water": dict(self._sender_high_water),
            "last_speech_acts": {
                s: (es[-1].epistemic or {}).get("speech_act")
                for s, es in by_sender.items()
            },
            "belief_counts": belief_counts,
            "speech_act_counts": speech_act_counts,
            "phase_counts": phase_counts,
            "epistemic_strength": round(epistemic_strength, 4),
            "taskwork_independence_ratio": round(taskwork_independence_ratio, 4),
            "social_compliance_ratio": round(social_compliance_ratio, 4),
        }

    def detect_gaps(self) -> Dict[str, List[int]]:
        """Return {sender: [missing_seq_numbers]} for senders with dropped messages."""
        by_sender: Dict[str, Set[int]] = {}
        for e in self._entries:
            if e.sequence >= 0:
                by_sender.setdefault(e.sender, set()).add(e.sequence)
        gaps: Dict[str, List[int]] = {}
        for sender, seen in by_sender.items():
            high = self._sender_high_water.get(sender, -1)
            if high < 0:
                continue
            missing = [i for i in range(0, high + 1) if i not in seen]
            if missing:
                gaps[sender] = missing
        return gaps

    def merge(self, other: "LocalStateReplica") -> None:
        """Merge entries from another replica (gossip anti-entropy)."""
        for entry in other._entries:
            if entry.message_id not in self._seen_ids:
                self._entries.append(entry)
                self._seen_ids.add(entry.message_id)
                if entry.sequence >= 0:
                    prev = self._sender_high_water.get(entry.sender, -1)
                    if entry.sequence > prev:
                        self._sender_high_water[entry.sender] = entry.sequence

    def entries_since_sequence(self, sender: str, after: int) -> List[ReplicaEntry]:
        """Return entries from sender with sequence > after (for anti-entropy)."""
        return [e for e in self._entries if e.sender == sender and e.sequence > after]


__all__ = ["ReplicaEntry", "LocalStateReplica"]

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
    """Parse created timestamp from L9 header to milliseconds.

    New format: provenance.created (ISO 8601).
    Old format: dt_created (backwards compat).
    """
    dt_str = (
        header.get("attributes", {}).get("msg_created", "")
        or header.get("provenance", {}).get("created", "")
    )
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
    # Grounding state from IE payload — populated by LocalStateReplica.apply()
    posterior:            Optional[float] = None   # sender's current belief strength
    contingency_verified: Optional[bool]  = None   # receiver-verified grounding result
    # IE utterance concept fields — from IEPayload.utterance (replaces epistemic.scope)
    ie_concept_ids:        List = field(default_factory=list)  # concept URIs this turn asserts about
    ie_addresses_evidence: List = field(default_factory=list)  # concept URIs from prior turn engaged
    # Taskwork chain from IE payload — present on initial_prior turns
    taskwork_findings:    Optional[List]  = None   # [{finding_id, value, source}]
    taskwork_likelihoods: Optional[List]  = None   # [(finding_id, ratio)]


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

    def apply(
        self,
        header: Dict[str, Any],
        operation: str | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> bool:
        """Ingest one L9 header. Returns True if new, False if already seen.

        If ``payload`` is supplied and contains an IE payload dict, the
        ``belief.posterior`` and ``grounding.contingency_verified`` values are
        extracted and stored on the ReplicaEntry so ReplicaToM can use them.
        """
        # New wire format: message.id; old: message_id (backwards compat)
        mid = header["message"]["id"]
        if not mid or mid in self._seen_ids:
            return False
        # New: actors[0].id; old: origin.actor_id
        sender = (
            (header.get("actors") or [{}])[0].get("id", "unknown")
        )
        seq_block = header.get("state_sequence") or {}
        seq = int(seq_block.get("counter", -1))

        posterior: Optional[float] = None
        contingency_verified: Optional[bool] = None
        ie_concept_ids: List = []
        ie_addresses_evidence: List = []
        taskwork_findings: Optional[List] = None
        taskwork_likelihoods: Optional[List] = None
        if payload:
            belief = payload.get("belief") or {}
            if "posterior" in belief:
                try:
                    posterior = float(belief["posterior"])
                except (TypeError, ValueError):
                    pass
            grounding = payload.get("grounding") or {}
            cv = grounding.get("contingency_verified")
            if cv is not None:
                contingency_verified = bool(cv)
            utterance = payload.get("utterance") or {}
            ie_concept_ids = list(utterance.get("evidence") or utterance.get("concept_ids", []))
            ie_addresses_evidence = list(utterance.get("addresses_evidence") or [])
            tw = payload.get("taskwork") or {}
            if tw:
                taskwork_findings = tw.get("findings")
                taskwork_likelihoods = tw.get("likelihoods")

        entry = ReplicaEntry(
            message_id=mid,
            sender=sender,
            sequence=seq,
            timestamp_ms=_parse_timestamp_ms(header),
            epistemic=header.get("epistemic"),
            operation=operation,
            posterior=posterior,
            contingency_verified=contingency_verified,
            ie_concept_ids=ie_concept_ids,
            ie_addresses_evidence=ie_addresses_evidence,
            taskwork_findings=taskwork_findings,
            taskwork_likelihoods=taskwork_likelihoods,
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
        phase_counts: Dict[str, int] = {"taskwork": 0, "grounding": 0, "team_process": 0}

        taskwork_total = 0
        taskwork_assertions = 0
        team_process_belief_assertions = 0
        team_process_delib_passes = 0

        # Posterior tracking per agent for grounding-verified turns
        agent_posteriors: Dict[str, List[float]] = {}
        grounding_total = 0
        grounding_verified = 0

        # Phase transition tracking per sender
        last_phase_by_sender: Dict[str, str] = {}
        phase_transitions: List[Dict[str, Any]] = []

        for e in self._entries:
            ep = e.epistemic or {}
            bs = ep.get("belief_status", "asserted")
            belief_counts[bs] = belief_counts.get(bs, 0) + 1
            sa = ep.get("speech_act", "")
            if sa:
                speech_act_counts[sa] = speech_act_counts.get(sa, 0) + 1
            phase = ep.get("state", "")
            if phase in phase_counts:
                phase_counts[phase] += 1
            if phase == "taskwork":
                taskwork_total += 1
                if sa in ("assertion", "belief_assertion") and bs == "asserted":
                    taskwork_assertions += 1
            elif phase == "team_process":
                if sa in ("assertion", "belief_assertion"):
                    team_process_belief_assertions += 1
                elif sa in ("compliance", "deliberation_pass"):
                    team_process_delib_passes += 1
            if phase == "grounding":
                grounding_total += 1
                if e.contingency_verified is True:
                    grounding_verified += 1
            if e.posterior is not None:
                agent_posteriors.setdefault(e.sender, []).append(e.posterior)
            if phase:
                prev = last_phase_by_sender.get(e.sender)
                if prev is not None and prev != phase:
                    phase_transitions.append({
                        "sender":      e.sender,
                        "from_phase":  prev,
                        "to_phase":    phase,
                        "message_id":  e.message_id,
                        "timestamp_ms": e.timestamp_ms,
                    })
                last_phase_by_sender[e.sender] = phase

        total_accepts = belief_counts["asserted"] + belief_counts["deferred"]
        genuine = sum(
            1 for e in self._entries
            if (e.epistemic or {}).get("speech_act") in ("assertion", "belief_assertion")
            and (e.epistemic or {}).get("belief_status") == "asserted"
        )
        epistemic_strength = genuine / total_accepts if total_accepts > 0 else 0.0

        taskwork_independence_ratio = (
            taskwork_assertions / taskwork_total if taskwork_total > 0 else 1.0
        )
        team_process_accepts = team_process_belief_assertions + team_process_delib_passes
        social_compliance_ratio = (
            team_process_delib_passes / team_process_accepts
            if team_process_accepts > 0 else 0.0
        )
        grounding_verified_ratio = (
            grounding_verified / grounding_total if grounding_total > 0 else None
        )
        mean_posterior_by_agent = {
            agent: round(sum(ps) / len(ps), 4)
            for agent, ps in agent_posteriors.items()
        }

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
            "grounding_verified_ratio": round(grounding_verified_ratio, 4) if grounding_verified_ratio is not None else None,
            "mean_posterior_by_agent": mean_posterior_by_agent,
            "phase_transitions": phase_transitions,
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

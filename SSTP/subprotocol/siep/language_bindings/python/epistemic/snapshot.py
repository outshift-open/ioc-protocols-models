# Copyright 2026 Cisco Systems, Inc. and its affiliates
# SPDX-License-Identifier: Apache-2.0

"""
epistemic/snapshot.py — Checkpoint and roll-forward for local replicas.

EpistemicSnapshot materialises the derived state of a replica at a point in time.
roll_forward() applies new entries to a snapshot without full replay.
replay_from_origin() recomputes from scratch (expensive; for repair/verification).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from SSTP.subprotocol.siep.language_bindings.python.epistemic.local_replica import LocalStateReplica, ReplicaEntry


@dataclass
class EpistemicSnapshot:
    """Materialised state of a LocalStateReplica at a point in time."""
    episode_id: str
    snapshot_message_id: str       # message_id of the last applied entry
    snapshot_at_ms: int
    derived_state: Dict[str, Any]
    sender_high_water: Dict[str, int]
    entry_count: int


def snapshot(replica: LocalStateReplica) -> EpistemicSnapshot:
    """Materialise a point-in-time snapshot from a replica."""
    last_id = replica._entries[-1].message_id if replica._entries else ""
    return EpistemicSnapshot(
        episode_id=replica.episode_id,
        snapshot_message_id=last_id,
        snapshot_at_ms=int(time.time() * 1000),
        derived_state=replica.get_derived_state(),
        sender_high_water=dict(replica._sender_high_water),
        entry_count=len(replica._entries),
    )


def roll_forward(
    snap: EpistemicSnapshot,
    new_entries: List[ReplicaEntry],
) -> Dict[str, Any]:
    """Apply entries received after a snapshot to derive updated state."""
    state = dict(snap.derived_state)
    high_water = dict(snap.sender_high_water)
    seen_after: set = set()

    # Carry forward phase-stratified accumulators from snapshot
    phase_counts = dict(state.get("phase_counts", {"taskwork": 0, "grounding": 0, "team_process": 0}))
    # Reconstruct running totals needed for ratio recomputation
    prev_entries = snap.entry_count
    prev_tw_ratio = state.get("taskwork_independence_ratio", 1.0)
    prev_sc_ratio = state.get("social_compliance_ratio", 0.0)
    prev_tw_total = phase_counts.get("taskwork", 0)
    prev_tp_total = phase_counts.get("team_process", 0)

    # Back-compute absolute counts from ratios + totals
    taskwork_assertions = int(round(prev_tw_ratio * prev_tw_total))
    team_process_delib_passes = int(round(prev_sc_ratio * prev_tp_total))
    team_process_belief_assertions = prev_tp_total - team_process_delib_passes

    # Grounding verification tracking
    prev_gv_ratio = state.get("grounding_verified_ratio")
    prev_grounding_total = phase_counts.get("grounding", 0)
    prev_grounding_verified = int(round((prev_gv_ratio or 0.0) * prev_grounding_total))
    grounding_total = prev_grounding_total
    grounding_verified = prev_grounding_verified

    # Posterior tracking per agent
    mean_posterior_by_agent = dict(state.get("mean_posterior_by_agent", {}))
    # Carry forward as running sums (approximate; exact requires full replay)
    agent_posterior_sums: Dict[str, float] = {
        agent: mean * phase_counts.get("grounding", 1)
        for agent, mean in mean_posterior_by_agent.items()
    }
    agent_posterior_counts: Dict[str, int] = {
        agent: phase_counts.get("grounding", 0)
        for agent in mean_posterior_by_agent
    }

    for entry in new_entries:
        if entry.message_id in seen_after:
            continue
        seen_after.add(entry.message_id)

        state["message_count"] = state.get("message_count", 0) + 1
        participants = set(state.get("participants", []))
        participants.add(entry.sender)
        state["participants"] = sorted(participants)

        counts = state.get("sender_message_counts", {})
        counts[entry.sender] = counts.get(entry.sender, 0) + 1
        state["sender_message_counts"] = counts

        if entry.sequence >= 0 and entry.sequence > high_water.get(entry.sender, -1):
            high_water[entry.sender] = entry.sequence

        ep = entry.epistemic or {}
        sa = ep.get("speech_act", "")
        bs = ep.get("belief_status", "asserted")
        phase = ep.get("state", "")

        if sa:
            acts = state.get("last_speech_acts", {})
            acts[entry.sender] = sa
            state["last_speech_acts"] = acts
            sa_counts = dict(state.get("speech_act_counts", {}))
            sa_counts[sa] = sa_counts.get(sa, 0) + 1
            state["speech_act_counts"] = sa_counts

        belief_counts = dict(state.get("belief_counts", {}))
        belief_counts[bs] = belief_counts.get(bs, 0) + 1
        state["belief_counts"] = belief_counts

        if phase in phase_counts:
            phase_counts[phase] += 1
        if phase == "taskwork":
            if sa in ("assertion", "belief_assertion") and bs == "asserted":
                taskwork_assertions += 1
        elif phase == "team_process":
            if sa in ("assertion", "belief_assertion"):
                team_process_belief_assertions += 1
            elif sa in ("compliance", "deliberation_pass"):
                team_process_delib_passes += 1
        if phase == "grounding":
            grounding_total += 1
            if entry.contingency_verified is True:
                grounding_verified += 1
        if entry.posterior is not None:
            agent_posterior_sums[entry.sender] = (
                agent_posterior_sums.get(entry.sender, 0.0) + entry.posterior
            )
            agent_posterior_counts[entry.sender] = (
                agent_posterior_counts.get(entry.sender, 0) + 1
            )

    state["phase_counts"] = phase_counts
    state["sender_high_water"] = high_water

    tw_total = phase_counts.get("taskwork", 0)
    state["taskwork_independence_ratio"] = round(
        taskwork_assertions / tw_total if tw_total > 0 else 1.0, 4
    )
    tp_accepts = team_process_belief_assertions + team_process_delib_passes
    state["social_compliance_ratio"] = round(
        team_process_delib_passes / tp_accepts if tp_accepts > 0 else 0.0, 4
    )
    state["grounding_verified_ratio"] = (
        round(grounding_verified / grounding_total, 4) if grounding_total > 0 else None
    )
    state["mean_posterior_by_agent"] = {
        agent: round(agent_posterior_sums[agent] / agent_posterior_counts[agent], 4)
        for agent in agent_posterior_sums
        if agent_posterior_counts.get(agent, 0) > 0
    }

    # Recompute overall epistemic_strength
    total = state.get("belief_counts", {}).get("asserted", 0) + state.get("belief_counts", {}).get("deferred", 0)
    prev_genuine = int(round(state.get("epistemic_strength", 0.0) * prev_entries))
    new_genuine = sum(
        1 for e in new_entries
        if (e.epistemic or {}).get("speech_act") in ("assertion", "belief_assertion")
        and (e.epistemic or {}).get("belief_status") == "asserted"
    )
    state["epistemic_strength"] = round(
        (prev_genuine + new_genuine) / total if total > 0 else 0.0, 4
    )

    return state


def replay_from_origin(replica: LocalStateReplica) -> Dict[str, Any]:
    """Full replay from origin — expensive; use only for repair or verification."""
    return replica.get_derived_state()


__all__ = ["EpistemicSnapshot", "snapshot", "roll_forward", "replay_from_origin"]

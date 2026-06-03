# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/ie/epistemic_store.py — Domain-agnostic epistemic state store.

EpistemicStore wraps LocalStateReplica (episodic) and the four cross-episode
stores (CommonGroundStore, ConvergenceStore, SemanticRuleStore, AgentBeliefStore).
Zero domain-specific logic — applications instantiate with use_case and owner_agent_id.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sstp.epistemic import LocalStateReplica, ReplicaToM, snapshot
from sstp.epistemic.snapshot import EpistemicSnapshot
from sstp.epistemic.stores import (
    AgentBeliefStore,
    CommonGround,
    CommonGroundStore,
    ConvergenceStore,
    SemanticRule,
    SemanticRuleStore,
    TeamGroundedTruth,
)


class EpistemicStore:
    """Domain-agnostic epistemic state store for one agent across episodes.

    Parameters
    ----------
    owner_agent_id: agent whose epistemic state this store tracks
    use_case:       domain label; prevents cross-domain belief merges

    Episodic state (per episode_id) lives in LocalStateReplica instances.
    Cross-episode state lives in the four persistent stores:
      - AgentBeliefStore       — per-agent belief with Bayesian decomposition
      - CommonGroundStore      — pairwise IE grounding records
      - ConvergenceStore       — SNP convergence (TeamGroundedTruth) records
      - SemanticRuleStore      — stabilised rules from convergence → semantic memory
    """

    def __init__(self, owner_agent_id: str, use_case: str = "") -> None:
        self.owner_agent_id = owner_agent_id
        self.use_case = use_case
        self._replicas: Dict[str, LocalStateReplica] = {}
        self._belief_store = AgentBeliefStore()
        self._common_ground = CommonGroundStore()
        self._convergence = ConvergenceStore()
        self._rule_store = SemanticRuleStore()

    # ── cross-episode stores ──────────────────────────────────────────────────

    @property
    def belief_store(self) -> AgentBeliefStore:
        return self._belief_store

    @property
    def common_ground_store(self) -> CommonGroundStore:
        return self._common_ground

    @property
    def convergence_store(self) -> ConvergenceStore:
        return self._convergence

    @property
    def rule_store(self) -> SemanticRuleStore:
        return self._rule_store

    def record_common_ground(self, ground: CommonGround) -> None:
        self._common_ground.record(ground)

    def record_convergence(self, truth: TeamGroundedTruth) -> None:
        self._convergence.record(truth)

    def record_rule(self, rule: SemanticRule) -> None:
        self._rule_store.record(rule)

    # ── episodic replica operations ───────────────────────────────────────────

    def _replica(self, episode_id: str) -> LocalStateReplica:
        if episode_id not in self._replicas:
            self._replicas[episode_id] = LocalStateReplica(
                episode_id=episode_id,
                owner_agent_id=self.owner_agent_id,
            )
        return self._replicas[episode_id]

    def apply_message(self, header: Dict[str, Any]) -> bool:
        # Skip non-L9 metadata records (inline dicts without message block)
        if "message" not in header:
            return False
        episode_id = (header.get("message") or {}).get("episode")
        if not episode_id:
            return False
        return self._replica(str(episode_id)).apply(header)

    def derived_state(self, episode_id: str) -> Dict[str, Any]:
        if episode_id not in self._replicas:
            return {}
        return self._replicas[episode_id].get_derived_state()

    def take_snapshot(self, episode_id: str) -> Optional[EpistemicSnapshot]:
        if episode_id not in self._replicas:
            return None
        return snapshot(self._replicas[episode_id])

    def detect_all_gaps(self) -> Dict[str, Dict[str, Any]]:
        return {
            episode_id: replica.detect_gaps()
            for episode_id, replica in self._replicas.items()
        }

    def tom(self, episode_id: str) -> Optional[ReplicaToM]:
        if episode_id not in self._replicas:
            return None
        return ReplicaToM(self._replicas[episode_id], self.owner_agent_id)


__all__ = ["EpistemicStore"]

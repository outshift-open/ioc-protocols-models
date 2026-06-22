# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0
#
# !! AUTO-GENERATED — do not edit by hand !!
# Generated from: SSTP/spec/siep.ioc
# Run:  python scripts/compile_spec.py SSTP/spec/siep.ioc
#
# Grounding-based semantic interaction exchange with belief tracking and repair cycles.

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, List

from src import L9
from SSTP.pipeline.base import SubprotocolBase
from SSTP.pipeline.phase import Phase


class SIEPBase(SubprotocolBase):
    """
    Generated base class for the SIEP subprotocol (v0.0.3).

    Concrete implementations must extend this class and:
      1. Override each abstract gate predicate (see below).
      2. Implement each abstract handler method (see below).
         handle() is auto-generated and dispatches by (phase, kind).

    Phase pipeline:
      shared-knowledge     kinds=['knowledge']  gate=knowledge-established?  handlers=[on_knowledge_query]
      planning             kinds=['intent']  gate=intent-received?  handlers=[on_intent]
      team-formed          kinds=['intent']  gate=team-complete?  handlers=[on_team_form]
      goal-alignment       kinds=['intent']  gate=alignment-reached?  handlers=[on_alignment_intent]
      execution            kinds=['exchange', 'contingency']  gate=repairs-resolved?  handlers=[on_exchange, on_contingency] [concurrent]
      state-management     kinds=['commit', 'knowledge']  gate=committed?  handlers=[on_commit, on_knowledge_store]
    """

    name    = "SIEP"
    version = "0.0.3"

    active_phases: List[Phase] = [
        Phase.SHARED_KNOWLEDGE,
        Phase.PLANNING,
        Phase.TEAM_FORMED,
        Phase.GOAL_ALIGNMENT,
        Phase.EXECUTION,
        Phase.STATE_MANAGEMENT,
    ]

    allowed_kinds: Dict[Phase, List[str]] = {
        Phase.SHARED_KNOWLEDGE: ["knowledge"],
        Phase.PLANNING: ["intent"],
        Phase.TEAM_FORMED: ["intent"],
        Phase.GOAL_ALIGNMENT: ["intent"],
        Phase.EXECUTION: ["exchange", "contingency"],
        Phase.STATE_MANAGEMENT: ["commit", "knowledge"],
    }

    concurrent_phases: List[Phase] = [Phase.EXECUTION]

    _gate_methods: Dict[Phase, str] = {
        Phase.SHARED_KNOWLEDGE: "knowledge_established",
        Phase.PLANNING: "intent_received",
        Phase.TEAM_FORMED: "team_complete",
        Phase.GOAL_ALIGNMENT: "alignment_reached",
        Phase.EXECUTION: "repairs_resolved",
        Phase.STATE_MANAGEMENT: "committed",
    }

    # ------------------------------------------------------------------
    # Abstract gate predicates — implement in your concrete subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def knowledge_established(self, state: Dict[str, Any]) -> bool:
        """Gate condition for phase: shared-knowledge. Return True to advance to the next phase."""
        ...

    @abstractmethod
    def intent_received(self, state: Dict[str, Any]) -> bool:
        """Gate condition for phase: planning. Return True to advance to the next phase."""
        ...

    @abstractmethod
    def team_complete(self, state: Dict[str, Any]) -> bool:
        """Gate condition for phase: team-formed. Return True to advance to the next phase."""
        ...

    @abstractmethod
    def alignment_reached(self, state: Dict[str, Any]) -> bool:
        """Gate condition for phase: goal-alignment. Return True to advance to the next phase."""
        ...

    @abstractmethod
    def repairs_resolved(self, state: Dict[str, Any]) -> bool:
        """Gate condition for phase: execution. Return True to advance to the next phase."""
        ...

    @abstractmethod
    def committed(self, state: Dict[str, Any]) -> bool:
        """Gate condition for phase: state-management. Return True to advance to the next phase."""
        ...

    # ------------------------------------------------------------------
    # Abstract handler methods — implement in your concrete subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def on_knowledge_query(self, msg: L9, state: Dict[str, Any]) -> List[L9]:
        """
        Retrieve ontology or application schema from memory store and return as a knowledge response.
        
        Reads:       payload.data, header.context.semantic.schema_id
        Returns:     kinds=['knowledge']
        Pre:         schema-registered?
        Post:        knowledge-provided?
        Raises:      schema-not-found
        Idempotent:  True
        """
        ...

    @abstractmethod
    def on_intent(self, msg: L9, state: Dict[str, Any]) -> List[L9]:
        """
        Receive and acknowledge planning intent; record goal framing for downstream phases.
        
        Reads:       payload.data, header.context.epistemic
        Returns:     kinds=['intent']
        Pre:         True
        Post:        intent-recorded?
        Mutates:     _intent_log
        Idempotent:  False
        """
        ...

    @abstractmethod
    def on_team_form(self, msg: L9, state: Dict[str, Any]) -> List[L9]:
        """
        Register a participant into the team; advance when all expected members have joined.
        
        Reads:       payload.data, header.actors
        Returns:     kinds=['intent']
        Pre:         True
        Post:        team-membership-recorded?
        Mutates:     _team_members
        Idempotent:  False
        """
        ...

    @abstractmethod
    def on_alignment_intent(self, msg: L9, state: Dict[str, Any]) -> List[L9]:
        """
        Exchange alignment signals; update per-participant alignment score until consensus reached.
        
        Reads:       payload.data, header.context.epistemic
        Returns:     kinds=['intent']
        Pre:         team-complete?
        Post:        alignment-score-updated?
        Mutates:     _alignment_scores
        Idempotent:  False
        """
        ...

    @abstractmethod
    def on_exchange(self, msg: L9, state: Dict[str, Any]) -> List[L9]:
        """
        Verify grounding score against prior evidence; emit contingency repair request if below threshold.
        
        Reads:       payload.utterance, payload.belief, header.context.epistemic
        Returns:     kinds=['exchange', 'contingency']
        Pre:         True
        Post:        belief-updated?
        Mutates:     _last_exchange, _priors, _repairs
        Raises:      grounding-failure, scope-mismatch, ungroundable-novelty
        Idempotent:  False
        """
        ...

    @abstractmethod
    def on_contingency(self, msg: L9, state: Dict[str, Any]) -> List[L9]:
        """
        Process repair attempt; close branch on success or escalate until max-retries exhausted.
        
        Reads:       payload.grounding, header.message.parents
        Returns:     kinds=['exchange', 'commit']
        Pre:         open-repair-branch?
        Post:        repair-depth-incremented?
        Mutates:     _repairs
        Raises:      repair-exhausted
        Idempotent:  False
        Max-retries: 3
        """
        ...

    @abstractmethod
    def on_commit(self, msg: L9, state: Dict[str, Any]) -> List[L9]:
        """
        Close the episode with a converged or rejected outcome; update final belief state.
        
        Reads:       payload.grounding, header.context.epistemic
        Pre:         repairs-resolved?
        Post:        episode-closed?
        Mutates:     _committed
        Idempotent:  True
        """
        ...

    @abstractmethod
    def on_knowledge_store(self, msg: L9, state: Dict[str, Any]) -> List[L9]:
        """
        Persist episode outcomes and belief updates to the shared memory store.
        
        Reads:       payload.data
        Pre:         episode-closed?
        Post:        outcome-persisted?
        Mutates:     _knowledge_store
        Raises:      store-failure
        Idempotent:  True
        Max-retries: 3
        """
        ...

    # ------------------------------------------------------------------
    # Auto-generated dispatcher — do not override
    # ------------------------------------------------------------------

    def handle(self, msg: L9) -> List[L9]:
        """Route message to the appropriate per-kind handler (auto-generated)."""
        dispatch = {
            (Phase.SHARED_KNOWLEDGE, "knowledge"): self.on_knowledge_query,
            (Phase.PLANNING, "intent"): self.on_intent,
            (Phase.TEAM_FORMED, "intent"): self.on_team_form,
            (Phase.GOAL_ALIGNMENT, "intent"): self.on_alignment_intent,
            (Phase.EXECUTION, "exchange"): self.on_exchange,
            (Phase.EXECUTION, "contingency"): self.on_contingency,
            (Phase.STATE_MANAGEMENT, "commit"): self.on_commit,
            (Phase.STATE_MANAGEMENT, "knowledge"): self.on_knowledge_store,
        }
        fn = dispatch.get((self.current_phase, msg.header.kind))
        return fn(msg, self._state) if fn else []


__all__ = ["SIEPBase"]

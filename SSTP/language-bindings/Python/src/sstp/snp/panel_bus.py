# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/snp/panel_bus.py — Domain-agnostic SNP panel negotiation bus.

Three classes:
  PanelBus          — shared message bus; use_case is a constructor param
  StarNegotiation   — hub-and-spoke: controller proposes → N members respond → commit
  RingNegotiation   — ring: each member proposes to the next → rotate until convergence

Every SNP message (build_snp_l9_header) is appended directly to ie_bus.messages so
that SNP and IE messages share a single ordered stream.  snp_trace is a read-only
property that returns the filtered subset (subprotocol=="SNP").

Ported from app/healthcare_ie_snp/panel_negotiation_bus.py; only use_case hardcode
and the episode_id format have been parameterised.
"""
from __future__ import annotations

import json as _json
import logging
import time
import uuid
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from sstp.snp.l9 import (
    NegotiationOperation,
    NegotiationStatus,
    build_snp_l9_header,
    build_snp_payload,
)
from sstp.ie.l9 import build_l9_header
from sstp.ie.message import get_part as _get_part
from sstp.epistemic import (
    SpeechAct, EpistemicState, BeliefStatus,
    make_epistemic_block, infer_snp_epistemic,
)
from sstp.epistemic.stores import (
    AgentBeliefStore,
    ArgumentOutcome,
    BeliefRevision,
    CommonGround,
    ConvergenceStore,
    NegotiationIndex,
    NegotiationMessage,
    NegotiationRound,
    NegotiationStore,
    ProposalStore,
    RoundStore,
    SemanticProposal,
    SemanticRule,
    SemanticRuleStore,
    TeamGroundedTruth,
)

if TYPE_CHECKING:
    from sstp.ie.agent_bus import AgentBus
    from sstp.ie.tom import TheoryOfMindEngineBase
    from sstp.epistemic.stores import PeerInteractionStore

LOGGER = logging.getLogger(__name__)

SCR_ALARM_THRESHOLD: float = 0.6


class IERepairExhausted(Exception):
    """Raised when the IE repair cycle reaches max_ie_depth without alignment."""

    def __init__(self, snp_message_id: str, ie_depth: int, cause: str | None) -> None:
        self.snp_message_id = snp_message_id
        self.ie_depth = ie_depth
        self.cause = cause
        super().__init__(f"IE repair exhausted at depth {ie_depth}: {cause}")


class PanelBus:
    """Dual-protocol message bus for one panel negotiation session.

    Parameters
    ----------
    panel_name: logical name of the panel (e.g. "diagnostics", "pharmacy")
    ie_bus:     AgentBus instance shared by all panel members
    use_case:   domain label written into L9 headers and episode_id
    """

    def __init__(
        self,
        panel_name: str,
        ie_bus: "AgentBus",
        use_case: str,
        tom_engine: "TheoryOfMindEngineBase | None" = None,
        repair_fn: "Callable[[str, str, str, str, Dict, str | None, int], str] | None" = None,
        convergence_store: Optional[ConvergenceStore] = None,
        belief_store: Optional[AgentBeliefStore] = None,
        semantic_rule_store: Optional[SemanticRuleStore] = None,
        peer_interaction_store: Optional["PeerInteractionStore"] = None,
        proposal_store: Optional[ProposalStore] = None,
        persistence_path: Optional[str] = None,
        team_process_store: Optional[Any] = None,
    ) -> None:
        self.panel_name = panel_name
        self.ie_bus = ie_bus
        self.use_case = use_case
        self.tom_engine = tom_engine
        self.repair_fn = repair_fn
        self.convergence_store = convergence_store
        self.belief_store = belief_store
        self.semantic_rule_store = semantic_rule_store
        self.peer_interaction_store = peer_interaction_store
        self.proposal_store = proposal_store
        self.persistence_path = persistence_path
        self.team_process_store = team_process_store
        self.negotiation_store = NegotiationStore()
        self.negotiation_index = NegotiationIndex()
        self.round_store = RoundStore()
        self._negotiation_id: str = str(uuid.uuid4())
        self._common_ground_ids: List[str] = []
        self._pending_arg_outcomes: Dict[tuple, List[ArgumentOutcome]] = {}
        if persistence_path:
            self._load_cross_episode_state(persistence_path)

    @property
    def snp_trace(self) -> List[Dict[str, Any]]:
        """Filtered view of ie_bus.messages containing only SNP messages."""
        return [m for m in self.ie_bus.messages if m.get("subprotocol") == "SNP"]

    def reset(self, negotiation_id: str | None = None) -> None:
        self._common_ground_ids = []
        self._negotiation_id = negotiation_id or str(uuid.uuid4())
        self._pending_arg_outcomes = {}

    def _load_cross_episode_state(self, path: str) -> None:
        """Load serialized store state from a JSON file at path (if it exists)."""
        import os
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = _json.load(fh)
        except (OSError, ValueError):
            return
        if self.peer_interaction_store is not None and "peer_interaction" in data:
            self.peer_interaction_store._restore_flat(data["peer_interaction"])
        if self.belief_store is not None and "belief_store" in data:
            self.belief_store._restore_flat(data["belief_store"])
        if self.semantic_rule_store is not None and "semantic_rules" in data:
            self.semantic_rule_store._restore_flat(data["semantic_rules"])

    def _save_cross_episode_state(self, path: str) -> None:
        """Serialize store state to a JSON file at path."""
        data: Dict[str, Any] = {}
        if self.peer_interaction_store is not None:
            data["peer_interaction"] = self.peer_interaction_store._store_flat()
        if self.belief_store is not None:
            data["belief_store"] = self.belief_store._store_flat()
        if self.semantic_rule_store is not None:
            data["semantic_rules"] = self.semantic_rule_store._store_flat()
        try:
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(data, fh, indent=2)
        except OSError:
            pass

    def _inject_skill_maps(self, all_agent_ids: List[str]) -> None:
        """Enrich each agent's peer belief models with social skill map data.

        Reads argument_types_that_move, argument_types_ignored, and evidence_weights
        from PeerInteractionStore and merges them into _peer_beliefs[subject] for every
        (observer, subject) pair. These fields then flow into assess_utterance() and
        predict_peer_response() LLM payloads automatically, closing the read path.
        """
        if self.tom_engine is None or self.peer_interaction_store is None:
            return
        for observer_id in all_agent_ids:
            agent_tom = self.tom_engine.agent(observer_id)
            for subject_id in all_agent_ids:
                if subject_id == observer_id:
                    continue
                record = self.peer_interaction_store.get_peer_record(
                    observer_id, subject_id, self.use_case
                )
                if record is None:
                    continue
                peer_model = dict(agent_tom._peer_beliefs.get(subject_id, {}))
                if record.argument_types_that_move:
                    peer_model["argument_types_that_move"] = list(record.argument_types_that_move)
                if record.argument_types_ignored:
                    peer_model["argument_types_ignored"] = list(record.argument_types_ignored)
                if record.evidence_weights:
                    peer_model["evidence_weights"] = dict(record.evidence_weights)
                if peer_model:
                    agent_tom._peer_beliefs[subject_id] = peer_model

    def _episode_id(self) -> str:
        return f"urn:ioc:{self.use_case}:panel:{self.panel_name}:{self._negotiation_id}"

    def _proposal_id(self, turn: int, sender: str) -> str:
        return f"panel-{self.panel_name}-{self._negotiation_id[:8]}-t{turn}-{sender}"

    def inject_prior(
        self,
        agent_id: str,
        concept_id: str,
        prior: float,
        prior_weight: float = 1.0,
    ) -> None:
        """Seed an agent's prior for concept_id before the negotiation round opens.

        If semantic_rule_store has a record for concept_id, that rule's confidence
        overrides the passed-in prior and its provenance_weight overrides prior_weight.
        """
        if self.belief_store is None:
            return
        semantic_prior: Optional[float] = None
        if self.semantic_rule_store is not None:
            rule = self.semantic_rule_store.latest(concept_id, self.use_case)
            if rule is not None:
                prior = rule.confidence
                prior_weight = rule.provenance_weight
                semantic_prior = prior
        self.ie_bus.messages.append({
            "type": "prior_query",
            "agent_id": agent_id,
            "concept_id": concept_id,
            "result": semantic_prior if semantic_prior is not None else "none",
        })
        revision = BeliefRevision(
            revision_id=str(uuid.uuid4()),
            timestamp_ms=int(time.time() * 1000),
            episode_id=self._episode_id(),
            message_id=None,
            confidence_before=prior,
            confidence_after=prior,
            cause="semantic_memory",
            caused_by_agent=None,
            argument_concept_ids=[concept_id],
        )
        self.belief_store.record_revision(
            agent_id, concept_id, self.use_case,
            self._episode_id(), revision,
            new_status="held", new_public_confidence=prior,
        )
        self.belief_store.set_prior(agent_id, concept_id, self.use_case, prior, prior_weight)
        self.ie_bus.messages.append({
            "type": "initial_prior",
            "agent_id": agent_id,
            "concept_id": concept_id,
            "prior": prior,
            "prior_weight": prior_weight,
        })

    def negotiate_process(
        self,
        coordinator_id: str,
        participant_ids: List[str],
        role_assignments: List[Dict[str, Any]],
    ) -> Any:
        """Emit process_proposed to each participant and collect acknowledgements.

        Returns a TeamProcessAgreement and records it in team_process_store if available.
        In this implementation all accepts are auto-acknowledged (no LLM challenge path).
        A real implementation would await actual process_accepted/challenged messages.
        """
        from sstp.epistemic.stores import TeamProcessAgreement, RoleAssignment
        episode_id = self._episode_id()
        assignments = [
            RoleAssignment(
                agent_id=ra["agent_id"],
                role=ra["role"],
                responsible_for=list(ra.get("responsible_for", [])),
                assigned_at_ms=int(time.time() * 1000),
                agreed=False,
            )
            for ra in role_assignments
        ]
        agreement = TeamProcessAgreement(
            episode_id=episode_id,
            round_id=self._negotiation_id,
            coordinator_id=coordinator_id,
            participant_ids=list(participant_ids),
            role_assignments=assignments,
            formed_at_ms=int(time.time() * 1000),
        )
        # Emit process_proposed to each participant
        for participant_id in participant_ids:
            proposal_header = self.ie_bus.emit_process_proposal(
                sender=coordinator_id,
                receiver=participant_id,
                agreement=agreement,
                episode_id=episode_id,
            )
            # Emit process_accepted on behalf of each participant (auto-accept)
            self.ie_bus.emit_process_acceptance(
                sender=participant_id,
                receiver=coordinator_id,
                parent_id=(proposal_header["message"]["id"]),
                episode_id=episode_id,
            )
            if self.team_process_store is not None:
                self.team_process_store.update_role_ack(episode_id, participant_id)

        agreement.decomposition_agreed = True
        if self.team_process_store is not None:
            self.team_process_store.record(agreement)
        return agreement

    def _ie_gate(
        self,
        utterance: str,
        snp_message_id: str,
        task_goal: str,
        sender: str,
        listener: str,
        listener_belief: Dict[str, Any],
        ie_depth: int = 1,
        max_ie_depth: int = 3,
        _accumulated: Optional[List[Dict[str, Any]]] = None,
        concept_id: str = "",
        listener_prior_utterance: str = "",
    ) -> Tuple[str, List[Dict[str, Any]]]:
        acc: List[Dict[str, Any]] = _accumulated if _accumulated is not None else []

        if self.tom_engine is None:
            return utterance, acc

        cid = concept_id or f"urn:concept:{self.use_case}:{task_goal[:32]}"
        if self.belief_store is not None:
            current_bs_pre = self.belief_store.current_belief(listener, cid, self.use_case)
            confidence_before = current_bs_pre.current_confidence if current_bs_pre is not None else 0.5
        else:
            confidence_before = 0.5

        result = self.tom_engine.agent(listener).assess_utterance(
            utterance, task_goal, speaker=sender, listener=listener,
            listener_prior_utterance=listener_prior_utterance or None,
            confidence_before=confidence_before,
        )

        alignment_score: float = float(result.get("alignment_score", 0.82))
        contingency_score: float = float(result.get("contingency_score", 1.0))

        if result.get("aligned", True):
            ts = int(time.time() * 1000)
            ep_id = self._episode_id()

            # Spec IE §3.1: deliberation_pass speech_act does not constitute grounding.
            # Use explicit speech_act from result if present; fall back to contingency proxy.
            _sa = result.get("speech_act", "")
            is_deliberation_pass = (
                _sa == "deliberation_pass" if _sa else contingency_score < 0.4
            )

            if self.belief_store is not None:
                if is_deliberation_pass:
                    rev = BeliefRevision(
                        revision_id=str(uuid.uuid4()),
                        timestamp_ms=ts,
                        episode_id=ep_id,
                        message_id=snp_message_id,
                        confidence_before=confidence_before,
                        confidence_after=confidence_before,
                        cause="social_compliance",
                        caused_by_agent=sender,
                        argument_concept_ids=[cid],
                    )
                    self.belief_store.record_revision(
                        listener, cid, self.use_case, ep_id, rev,
                        new_status="asserted", new_public_confidence=confidence_before,
                    )
                    if self.tom_engine is not None:
                        _tom_l = self.tom_engine.agent(listener)
                        _bs_dp = self.belief_store.current_belief(listener, cid, self.use_case)
                        if _bs_dp is not None:
                            pass  # _belief removed; posterior tracked in AgentBeliefStore
                else:
                    posterior_confidence = result.get("posterior_confidence")
                    if posterior_confidence is not None:
                        confidence_after = float(posterior_confidence)
                    else:
                        confidence_after = min(1.0, confidence_before + alignment_score * 0.2)
                    rev = BeliefRevision(
                        revision_id=str(uuid.uuid4()),
                        timestamp_ms=ts,
                        episode_id=ep_id,
                        message_id=snp_message_id,
                        confidence_before=confidence_before,
                        confidence_after=confidence_after,
                        cause="grounded_argument",
                        caused_by_agent=sender,
                        argument_concept_ids=[cid],
                    )
                    self.belief_store.record_revision(
                        listener, cid, self.use_case, ep_id, rev,
                        new_status="asserted", new_public_confidence=confidence_after,
                    )
                    if self.tom_engine is not None:
                        _tom_l = self.tom_engine.agent(listener)
                        _bs_sync = self.belief_store.current_belief(listener, cid, self.use_case)
                        if _bs_sync is not None:
                            pass  # _belief removed; posterior tracked in AgentBeliefStore
                    # SCR gate: suppress CommonGround when social compliance is dominant
                    _bs_scr = self.belief_store.current_belief(listener, cid, self.use_case)
                    if _bs_scr is not None and _bs_scr.social_compliance_ratio >= SCR_ALARM_THRESHOLD:
                        is_deliberation_pass = True
                    # Fix 1: accumulate ArgumentOutcome for batch promote at episode close
                    _bs_after = self.belief_store.current_belief(listener, cid, self.use_case)
                    _l9_ep = result.get("epistemic", {}) if isinstance(result, dict) else {}
                    _epistemic_state = _l9_ep.get("epistemic_state", "team_process")
                    _arg_type = str(result.get("argument_type", "grounded_evidence"))
                    _ao = ArgumentOutcome(
                        episode_id=ep_id,
                        message_id=snp_message_id,
                        epistemic_state=_epistemic_state,
                        argument_concept_id=cid,
                        argument_type=_arg_type,
                        subject_confidence_before=confidence_before,
                        subject_confidence_after=confidence_after,
                        contingent=contingency_score >= 0.4,
                        moved=abs(confidence_after - confidence_before) > 0.02,
                        move_cause=_arg_type,
                    )
                    self._pending_arg_outcomes.setdefault((sender, listener), []).append(_ao)

            if not is_deliberation_pass and self.tom_engine is not None:
                _sender_bs = self.belief_store.current_belief(sender, cid, self.use_case) if self.belief_store else None
                _sender_pub = _sender_bs.public_confidence if _sender_bs is not None else alignment_score
                ground = CommonGround(
                    holder_id=sender,
                    confirmer_id=listener,
                    concept_id=cid,
                    use_case=self.use_case,
                    episode_id=ep_id,
                    grounding_confidence=alignment_score,
                    holder_confidence=_sender_pub,
                    confirmer_confidence=alignment_score,
                    contingency_verified=contingency_score >= 0.4,
                    speech_acts=["belief_assertion", "belief_assertion"],
                    grounding_message_ids=[snp_message_id],
                    formed_at_ms=ts,
                )
                self.tom_engine.agent(listener)._epistemic_store.record_common_ground(ground)
                self.tom_engine.agent(sender)._epistemic_store.record_common_ground(ground)
                self._common_ground_ids.append(ground.grounding_message_ids[0] if ground.grounding_message_ids else ep_id)

            return utterance, acc

        derailment_cause: str | None = result.get("derailment_cause")
        grounding_failure: bool = bool(result.get("grounding_failure", False))

        if grounding_failure:
            self.ie_bus.messages.append({
                "type": "contingency_escalated",
                "speaker": sender,
                "listener": listener,
                "concept_id": cid,
                "contingency_score": result.get("contingency_score", 0.0),
                "message_id": snp_message_id,
            })

        if ie_depth > max_ie_depth:
            raise IERepairExhausted(snp_message_id, ie_depth, derailment_cause)

        ts = int(time.time() * 1000)
        child_state_id = f"{self._episode_id()}:ie:{ie_depth}"

        repair_required_header = build_l9_header(
            use_case=self.use_case,
            event_type="repair_required",
            sender=listener,
            receiver=sender,
            timestamp_ms=ts,
            sensitivity="confidential",
            utterance=utterance,
            parent_ids=[snp_message_id],
            episode_id=child_state_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TEAM_PROCESS,
                belief_status=BeliefStatus.DEFERRED,
            ),
        )
        self.ie_bus.messages.append(
            {"type": "repair_required", "l9_header": repair_required_header,
             "utterance": utterance, "derailment_cause": derailment_cause}
        )
        acc.append(repair_required_header)

        _failure_type = (
            "grounding_failure" if grounding_failure else
            "derailment" if result.get("derailed") else
            "ambiguity" if result.get("ambiguous") else
            "unknown"
        )
        if self.repair_fn is not None:
            try:
                repaired = self.repair_fn(
                    sender, listener, utterance, task_goal,
                    listener_belief, derailment_cause, ie_depth,
                    failure_type=_failure_type,
                )
            except TypeError:
                repaired = self.repair_fn(
                    sender, listener, utterance, task_goal,
                    listener_belief, derailment_cause, ie_depth,
                )
        else:
            repaired = f"{listener}, re-anchor to task goal: {task_goal}"

        repair_applied_header = build_l9_header(
            use_case=self.use_case,
            event_type="repair_applied",
            sender=sender,
            receiver=listener,
            timestamp_ms=int(time.time() * 1000),
            sensitivity="confidential",
            utterance=repaired,
            parent_ids=[repair_required_header["message"]["id"]],
            episode_id=child_state_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TEAM_PROCESS,
                belief_status=BeliefStatus.REVISED,
            ),
        )
        self.ie_bus.messages.append(
            {"type": "repair_applied", "l9_header": repair_applied_header,
             "utterance": repaired}
        )
        acc.append(repair_applied_header)

        if self.belief_store is not None:
            ep_id = self._episode_id()
            rev = BeliefRevision(
                revision_id=str(uuid.uuid4()),
                timestamp_ms=int(time.time() * 1000),
                episode_id=ep_id,
                message_id=repair_applied_header["message"]["id"],
                confidence_before=confidence_before,
                confidence_after=confidence_before,
                cause="repair_resolution",
                caused_by_agent=sender,
                argument_concept_ids=[cid],
            )
            self.belief_store.record_revision(
                listener, cid, self.use_case, ep_id, rev,
                new_status="asserted", new_public_confidence=confidence_before,
            )

        return self._ie_gate(
            repaired, repair_applied_header["message"]["id"], task_goal,
            sender, listener, listener_belief,
            ie_depth + 1, max_ie_depth, acc, concept_id,
            listener_prior_utterance=utterance,
        )

    def _verify_grounding_bilateral(
        self,
        utterance_a: str,
        response_b: str,
        snp_message_id: str,
        task_goal: str,
        speaker: str,
        listener: str,
        listener_actual_confidence: float,
        listener_belief: Dict[str, Any],
        concept_id: str = "",
        forced_accept: bool = False,
        speaker_epistemic: Dict[str, Any] | None = None,
        listener_epistemic: Dict[str, Any] | None = None,
    ) -> None:
        """Verify grounding using B's actual response, not a pre-response prediction.

        Called AFTER listener has responded with response_b. Assesses whether
        response_b is contingent on utterance_a (spec §IE-3.1 condition a).
        Uses listener's real expressed confidence for the belief revision, not
        a simulated posterior. Records CommonGround with actual BeliefState
        posteriors for both parties.

        forced_accept=True signals that the accept was driven by controller confidence
        dominance, not genuine position agreement. Causes social_compliance revision
        and suppresses CommonGround to avoid polluting SCR.
        """
        if self.tom_engine is None:
            return

        cid = concept_id or f"urn:concept:{self.use_case}:{task_goal[:32]}"
        if self.belief_store is not None:
            bs_pre = self.belief_store.current_belief(listener, cid, self.use_case)
            confidence_before = bs_pre.current_confidence if bs_pre is not None else 0.5
        else:
            confidence_before = 0.5

        if forced_accept:
            # Forced accept: controller dominance, not genuine engagement.
            # Skip the LLM contingency call — we already know this is social compliance.
            is_deliberation_pass = True
            contingency_score = 0.0
        else:
            # Use structured concept_id overlap when both sides carry epistemic blocks (D1).
            # Fall through to LLM assess_utterance when concept IDs are absent.
            from sstp.ie.grounding import contingency_check as _contingency_check, _get_concept_ids
            _spk_ids = _get_concept_ids(speaker_epistemic)
            _lst_ids = _get_concept_ids(listener_epistemic)
            if _spk_ids and _lst_ids:
                _contingent, _ratio = _contingency_check(speaker_epistemic, listener_epistemic)
                contingency_score = _ratio
                is_deliberation_pass = not _contingent
                result = {"contingency_score": contingency_score, "posterior_confidence": None}
            else:
                # Ask listener's model: does my response engage with what speaker said?
                result = self.tom_engine.agent(listener).assess_utterance(
                    response_b, task_goal,
                    speaker=listener,
                    listener=speaker,
                    listener_prior_utterance=utterance_a,
                    confidence_before=confidence_before,
                )
                contingency_score = float(result.get("contingency_score", 1.0))
                is_deliberation_pass = contingency_score < 0.4

        ts = int(time.time() * 1000)
        ep_id = self._episode_id()

        if self.belief_store is not None:
            if is_deliberation_pass:
                rev = BeliefRevision(
                    revision_id=str(uuid.uuid4()),
                    timestamp_ms=ts,
                    episode_id=ep_id,
                    message_id=snp_message_id,
                    confidence_before=confidence_before,
                    confidence_after=confidence_before,
                    cause="social_compliance",
                    caused_by_agent=speaker,
                    argument_concept_ids=[cid],
                )
                self.belief_store.record_revision(
                    listener, cid, self.use_case, ep_id, rev,
                    new_status="asserted", new_public_confidence=confidence_before,
                )
            else:
                rev = BeliefRevision(
                    revision_id=str(uuid.uuid4()),
                    timestamp_ms=ts,
                    episode_id=ep_id,
                    message_id=snp_message_id,
                    confidence_before=confidence_before,
                    confidence_after=listener_actual_confidence,
                    cause="grounded_argument",
                    caused_by_agent=speaker,
                    argument_concept_ids=[cid],
                )
                self.belief_store.record_revision(
                    listener, cid, self.use_case, ep_id, rev,
                    new_status="asserted", new_public_confidence=listener_actual_confidence,
                )

        # D3: sync AgentTOM._belief["confidence"] so the agent's self-model tracks the Bayesian posterior
        if self.belief_store is not None and self.tom_engine is not None:
            _bs_sync = self.belief_store.current_belief(listener, cid, self.use_case)
            if _bs_sync is not None:
                pass  # _belief removed

        # forced_accept suppresses CommonGround: a social-compliance accept
        # doesn't establish shared understanding, it just records deference.
        if not is_deliberation_pass and not forced_accept:
            if self.belief_store is not None:
                bs_a = self.belief_store.current_belief(speaker, cid, self.use_case)
                bs_b = self.belief_store.current_belief(listener, cid, self.use_case)
                holder_conf = bs_a.public_confidence if bs_a is not None else 0.5
                confirmer_conf = bs_b.public_confidence if bs_b is not None else listener_actual_confidence
            else:
                holder_conf = 0.5
                confirmer_conf = listener_actual_confidence
            # For SNP utterances (machine-generated position strings), genuine content
            # contingency is not measurable. Use position change as the proxy: if the
            # listener's expressed position differs from the prior, they engaged.
            contingency_verified = contingency_score >= 0.4
            ground = CommonGround(
                holder_id=speaker,
                confirmer_id=listener,
                concept_id=cid,
                use_case=self.use_case,
                episode_id=ep_id,
                grounding_confidence=contingency_score,
                holder_confidence=holder_conf,
                confirmer_confidence=confirmer_conf,
                contingency_verified=contingency_verified,
                speech_acts=["belief_assertion", "belief_assertion"],
                grounding_message_ids=[snp_message_id],
                formed_at_ms=ts,
            )
            self.tom_engine.agent(listener)._epistemic_store.record_common_ground(ground)
            self.tom_engine.agent(speaker)._epistemic_store.record_common_ground(ground)
            self._common_ground_ids.append(ground.grounding_message_ids[0] if ground.grounding_message_ids else ep_id)

    def emit_negotiate(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        turn: int,
        confidence: float,
        parent_snp_id: str | None = None,
        epistemic_state: EpistemicState = EpistemicState.TEAM_PROCESS,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        proposal_id = self._proposal_id(turn, sender)
        ts = int(time.time() * 1000)
        epistemic_block = make_epistemic_block(
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=epistemic_state,
            belief_status=BeliefStatus.ASSERTED,
            uncertainty=round(1.0 - confidence, 4),
        )
        snp_header = build_snp_l9_header(
            operation=NegotiationOperation.NEGOTIATE,
            use_case=self.use_case,
            sender=sender,
            receiver=receiver,
            timestamp_ms=ts,
            proposal_id=proposal_id,
            utterance=utterance,
            parent_ids=[parent_snp_id] if parent_snp_id else None,
            episode_id=self._episode_id(),
            epistemic=epistemic_block,
        )
        self.ie_bus.messages.append(snp_header)
        return snp_header

    def emit_decision(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        operation: str,
        turn: int,
        confidence: float,
        ie_request_message_id: str,
        parent_snp_id: str | None = None,
        ctrl_position_key: str = "",
        ctrl_conf: float = 0.5,
        accept_threshold: float = 0.1,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        proposal_id = self._proposal_id(turn, sender)
        ts = int(time.time() * 1000)
        op_str = operation.value if hasattr(operation, "value") else str(operation)
        speech_act, epistemic_state = infer_snp_epistemic(
            operation=op_str,
            ctrl_position_key=ctrl_position_key,
            member_position_key=ctrl_position_key,
            ctrl_conf=ctrl_conf,
            member_conf=confidence,
            accept_threshold=accept_threshold,
        )
        belief_status = BeliefStatus.DEFERRED if speech_act == SpeechAct.COMPLIANCE else BeliefStatus.ASSERTED
        epistemic_block = make_epistemic_block(
            speech_act=speech_act,
            epistemic_state=epistemic_state,
            belief_status=belief_status,
            uncertainty=round(1.0 - confidence, 4),
        )
        snp_header = build_snp_l9_header(
            operation=operation,
            use_case=self.use_case,
            sender=sender,
            receiver=receiver,
            timestamp_ms=ts,
            proposal_id=proposal_id,
            utterance=utterance,
            parent_ids=[parent_snp_id] if parent_snp_id else None,
            episode_id=self._episode_id(),
            topic=ctrl_position_key if ctrl_position_key else None,
            epistemic=epistemic_block,
        )
        self.ie_bus.messages.append(snp_header)
        return snp_header


def get_snp_convergence_metrics(header: Dict[str, Any]) -> Dict[str, Any]:
    """Return convergence metrics from a commit:converged L9 header.

    Reads from payload[type=snp-convergence].content.  Returns an empty dict
    if the header carries no convergence payload (not a convergence message).

    Keys: mpc, gar, scr, participant_ids, episode_id.
    """
    for part in header.get("payload") or []:
        if part.get("type") == "snp-convergence":
            return dict(part.get("content") or {})
    return {}


class StarNegotiation:
    """Star-topology (hub-and-spoke) SNP negotiation: controller ↔ N members."""

    def __init__(self, panel_bus: PanelBus, panel_name: str) -> None:
        self.panel_bus = panel_bus
        self.panel_name = panel_name

    @staticmethod
    def _position_key(pos: Any) -> str:
        if isinstance(pos, dict):
            return str(pos.get("likely_cause") or pos.get("risk_bucket") or pos.get("decision_key") or pos)
        return str(pos)

    @staticmethod
    def _confidence(pos: Any) -> float:
        if isinstance(pos, dict):
            return float(pos.get("confidence") or pos.get("roi_score") or 0.5)
        return 0.5

    @staticmethod
    def _leading_position(positions: Dict[str, Any]) -> Any:
        by_key: Dict[str, List[Any]] = {}
        for pos in positions.values():
            by_key.setdefault(StarNegotiation._position_key(pos), []).append(pos)
        best_key = max(
            by_key,
            key=lambda k: (
                len(by_key[k]),
                round(sum(StarNegotiation._confidence(p) for p in by_key[k]) / len(by_key[k]), 4),
                k,
            ),
        )
        return max(by_key[best_key], key=StarNegotiation._confidence)

    def _emit_propose(
        self,
        controller: str,
        specialist: str,
        position: Any,
        turn: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        conf = self._confidence(position)
        key = self._position_key(position)
        utterance = f"{controller} proposes {key} confidence={conf:.2f}"
        proposal_id = self.panel_bus._proposal_id(turn, controller)
        ts = int(time.time() * 1000)
        pos_dict = position if isinstance(position, dict) else {}
        supporting_ev: List[str] | None = pos_dict.get("supporting_evidence") or ([key] if key else None)
        # Initial proposal (turn 0) carries taskwork label — agent's prior-driven position
        _epistemic_state = EpistemicState.TASKWORK if turn == 0 else EpistemicState.TEAM_PROCESS
        epistemic_block = make_epistemic_block(
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=_epistemic_state,
            belief_status=BeliefStatus.ASSERTED,
            uncertainty=round(1.0 - conf, 4),
        )
        _snp_payload = build_snp_payload(
            operation=NegotiationOperation.PROPOSE,
            proposal_id=proposal_id,
            content=key,
            status=NegotiationStatus.PENDING,
            negotiation_id=self.panel_bus._negotiation_id,
            posterior=pos_dict.get("posterior") or conf,
            supporting_evidence=pos_dict.get("supporting_evidence"),
            against_evidence=pos_dict.get("against_evidence"),
            reasoning_summary=pos_dict.get("reasoning_summary") or pos_dict.get("rationale"),
        )
        snp_header = build_snp_l9_header(
            operation=NegotiationOperation.PROPOSE,
            use_case=self.panel_bus.use_case,
            sender=controller,
            receiver=specialist,
            timestamp_ms=ts,
            proposal_id=proposal_id,
            utterance=utterance,
            episode_id=self.panel_bus._episode_id(),
            topic=key if key else None,
            epistemic=epistemic_block,
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": utterance},
                {"type": "snp", "location": "inline", "content": _snp_payload},
            ],
        )
        if self.panel_bus.proposal_store is not None:
            self.panel_bus.proposal_store.record(SemanticProposal(
                proposal_id=proposal_id,
                concept_id=key or "",
                episode_id=self.panel_bus._episode_id(),
                sender=controller,
                receiver=specialist,
                payload=pos_dict,
                timestamp_ms=ts,
            ))
        self.panel_bus.ie_bus.messages.append(snp_header)
        return snp_header

    def _emit_specialist_response(
        self,
        specialist: str,
        controller: str,
        position: Any,
        operation: str,
        turn: int,
        ie_request_message_id: str,
        ctrl_position_key: str = "",
        ctrl_conf: float = 0.5,
        accept_threshold: float = 0.1,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        key = self._position_key(position)
        # Read specialist's own posterior from BeliefStore if wired — this is their
        # independent calibrated belief, not a copy of the controller's position.
        _concept_id_for_bs = f"urn:concept:{self.panel_bus.use_case}:{ctrl_position_key or key}"
        if self.panel_bus.belief_store is not None:
            _bs = self.panel_bus.belief_store.current_belief(
                specialist, _concept_id_for_bs, self.panel_bus.use_case
            )
            conf = _bs.posterior if _bs is not None else self._confidence(position)
        else:
            conf = self._confidence(position)
        verb = "accepts" if operation == NegotiationOperation.ACCEPT else "counter-proposes"
        utterance = f"{specialist} {verb} {key} confidence={conf:.2f}"
        proposal_id = self.panel_bus._proposal_id(turn, specialist)
        ts = int(time.time() * 1000)
        op_str = operation.value if hasattr(operation, "value") else str(operation)
        speech_act, epistemic_state = infer_snp_epistemic(
            operation=op_str,
            ctrl_position_key=ctrl_position_key,
            member_position_key=key,
            ctrl_conf=ctrl_conf,
            member_conf=conf,
            accept_threshold=accept_threshold,
        )
        belief_status = BeliefStatus.DEFERRED if speech_act == SpeechAct.COMPLIANCE else BeliefStatus.ASSERTED
        pos_dict = position if isinstance(position, dict) else {}
        # Use specialist's own supporting_evidence as concept IDs so they overlap
        # with the proposal's scope (same symptom/evidence vocabulary).
        # Fall back to ctrl_position_key proxy for counter-proposals with no evidence.
        addresses_ev: List[str] | None = (
            pos_dict.get("addresses_evidence")
            or pos_dict.get("supporting_evidence")
            or ([ctrl_position_key] if ctrl_position_key and operation in (
                NegotiationOperation.COUNTER_PROPOSAL, NegotiationOperation.ACCEPT
            ) else None)
        )
        _is_delib_pass = speech_act in (SpeechAct.COMPLIANCE, SpeechAct.DELIBERATION_PASS)
        epistemic_block = make_epistemic_block(
            speech_act=speech_act,
            epistemic_state=epistemic_state,
            belief_status=belief_status,
            uncertainty=round(1.0 - conf, 4),
        )
        _snp_payload = build_snp_payload(
            operation=operation,
            proposal_id=proposal_id,
            content=key,
            status=NegotiationStatus.PENDING,
            negotiation_id=self.panel_bus._negotiation_id,
            posterior=pos_dict.get("posterior") or conf,
            supporting_evidence=pos_dict.get("supporting_evidence"),
            against_evidence=pos_dict.get("against_evidence"),
            reasoning_summary=pos_dict.get("reasoning_summary") or pos_dict.get("rationale"),
            addresses_evidence=addresses_ev,
            deferred_to=controller if _is_delib_pass else None,
        )
        # All specialist responses during debate are exchanges — only the final
        # decision commit closes the negotiation branch.
        snp_header = build_snp_l9_header(
            operation=operation,
            use_case=self.panel_bus.use_case,
            sender=specialist,
            receiver=controller,
            timestamp_ms=ts,
            proposal_id=proposal_id,
            utterance=utterance,
            episode_id=self.panel_bus._episode_id(),
            topic=ctrl_position_key if ctrl_position_key else None,
            epistemic=epistemic_block,
            kind_override="exchange",
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": utterance},
                {"type": "snp", "location": "inline", "content": _snp_payload},
            ],
        )
        self.panel_bus.ie_bus.messages.append(snp_header)
        return snp_header

    def _emit_final_decision(
        self,
        controller: str,
        specialist: str,
        position: Any,
        turn: int,
        ie_request_message_id: str,
        specialist_position: Any = None,
        accept_threshold: float = 0.1,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        conf = self._confidence(position)
        key = self._position_key(position)
        utterance = f"{controller} commits {key} confidence={conf:.2f}"
        proposal_id = self.panel_bus._proposal_id(turn, controller)
        ts = int(time.time() * 1000)
        spec_key = self._position_key(specialist_position) if specialist_position is not None else key
        if spec_key != key:
            speech_act_v: SpeechAct = SpeechAct.COMPLIANCE
            epistemic_state_v: EpistemicState = EpistemicState.TEAM_PROCESS
            belief_status_v: BeliefStatus = BeliefStatus.DEFERRED
        else:
            speech_act_v = SpeechAct.ASSERTION
            epistemic_state_v = EpistemicState.TEAM_PROCESS
            belief_status_v = BeliefStatus.ASSERTED
        epistemic_block = make_epistemic_block(
            speech_act=speech_act_v,
            epistemic_state=epistemic_state_v,
            belief_status=belief_status_v,
            uncertainty=round(1.0 - conf, 4),
        )
        snp_header = build_snp_l9_header(
            operation=NegotiationOperation.ACCEPT,
            use_case=self.panel_bus.use_case,
            sender=controller,
            receiver=specialist,
            timestamp_ms=ts,
            proposal_id=proposal_id,
            utterance=utterance,
            episode_id=self.panel_bus._episode_id(),
            epistemic=epistemic_block,
            kind_override="commit",
        )
        self.panel_bus.ie_bus.messages.append(snp_header)
        return snp_header

    def run(
        self,
        controller_id: str,
        member_ids: List[str],
        controller_position: Dict[str, Any],
        specialist_positions: Dict[str, Any],
        accept_threshold: float = 0.1,
        max_rounds: int = 2,
        task_goal: str = "",
        agent_beliefs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, str, List[Dict[str, Any]]]:
        n = len(member_ids)
        ctrl_pos = dict(controller_position)
        resolution_label = "timeout_majority"

        # Derive concept_id for _ie_gate and belief_store operations
        ctrl_key_init = self._position_key(ctrl_pos)
        concept_id = f"urn:concept:{self.panel_bus.use_case}:{ctrl_key_init}"

        # Inject cross-episode social skill map into peer belief models before negotiation
        self.panel_bus._inject_skill_maps([controller_id] + list(member_ids))

        # Panel session open — emit intent on the panel episode
        _panel_episode_id = self.panel_bus._episode_id()
        _intent_utterance = f"panel:open concept={ctrl_key_init} participants={[controller_id]+list(member_ids)}"
        _intent_header = build_snp_l9_header(
            operation=NegotiationOperation.PROPOSE,
            use_case=self.panel_bus.use_case,
            sender=controller_id,
            receiver=None,
            timestamp_ms=int(time.time() * 1000),
            proposal_id=f"intent-{self.panel_bus._negotiation_id[:8]}",
            utterance=_intent_utterance,
            episode_id=_panel_episode_id,
            kind_override="intent",
            payload_parts=[{"type": "utterance", "location": "inline", "content": _intent_utterance}],
        )
        self.panel_bus.ie_bus.messages.append(_intent_header)

        # Step 3: inject priors before the round opens
        if self.panel_bus.belief_store is not None:
            for agent_id, pos in (
                [(controller_id, controller_position)]
                + [(mid, specialist_positions[mid]) for mid in member_ids]
            ):
                self.panel_bus.inject_prior(
                    agent_id=agent_id,
                    concept_id=concept_id,
                    prior=self._confidence(pos),
                    prior_weight=1.0,
                )

        # Step 3/4: initial_priors from BeliefState.prior if belief_store is wired
        if self.panel_bus.belief_store is not None:
            def _prior(aid: str, fallback: float) -> float:
                bs = self.panel_bus.belief_store.current_belief(aid, concept_id, self.panel_bus.use_case)
                return bs.prior if bs is not None else fallback
            initial_priors = {mid: _prior(mid, self._confidence(specialist_positions[mid]))
                              for mid in member_ids}
            initial_priors[controller_id] = _prior(controller_id, self._confidence(controller_position))
        else:
            initial_priors = {mid: self._confidence(specialist_positions[mid]) for mid in member_ids}
            initial_priors[controller_id] = self._confidence(controller_position)

        # AF1: sync controller's proposal confidence from BeliefState.posterior when a
        # SemanticRule exists. Only the controller's position is aligned to the rule —
        # specialists express their own independent priors, not the rule confidence.
        if (self.panel_bus.belief_store is not None
                and self.panel_bus.semantic_rule_store is not None):
            _af1_rule = self.panel_bus.semantic_rule_store.latest(concept_id, self.panel_bus.use_case)
            if _af1_rule is not None:
                _af1_bs = self.panel_bus.belief_store.current_belief(
                    controller_id, concept_id, self.panel_bus.use_case)
                if _af1_bs is not None:
                    controller_position["confidence"] = _af1_bs.posterior

        for round_idx in range(max_rounds):
            # Record NegotiationRound at start with current position snapshot
            _round_id = f"{self.panel_bus._negotiation_id}:star:round:{round_idx}"
            _round_positions = {
                **{mid: self._confidence(specialist_positions[mid]) for mid in member_ids},
                controller_id: self._confidence(ctrl_pos),
            }
            _neg_round = NegotiationRound(
                round_id=_round_id,
                proposal_id=self.panel_bus._proposal_id(round_idx, controller_id),
                participants=[controller_id] + list(member_ids),
                individual_positions=_round_positions,
            )
            self.panel_bus.round_store.record(_neg_round)

            prop_utt = (
                f"{controller_id} proposes {self._position_key(ctrl_pos)}"
                f" confidence={self._confidence(ctrl_pos):.2f}"
            )
            tom_predictions: Dict[str, Dict] = {}
            if self.panel_bus.tom_engine is not None:
                ctrl_agent = self.panel_bus.tom_engine.agent(controller_id)
                _ctrl_conf_for_tom = self._confidence(ctrl_pos)
                for mid in member_ids:
                    # Use predict_peer_response (real LLM ToM call) when available;
                    # fall back to predict_belief stub when the agent lacks it.
                    if hasattr(ctrl_agent, "predict_peer_response"):
                        raw = ctrl_agent.predict_peer_response(
                            mid, prop_utt, task_goal,
                        )
                        tom_predictions[mid] = {
                            "predicted_confidence": raw.get("predicted_alignment", 0.5),
                            "reliability": raw.get("confidence", 0.1),
                            "predicted_derailment": raw.get("predicted_derailment", False),
                            "predicted_contingency": raw.get("predicted_contingency", "normal"),
                        }
                    else:
                        from sstp.epistemic.tom import predict_belief
                        ctrl_key_for_tom = self._position_key(ctrl_pos)
                        ctrl_evidence = (ctrl_pos if isinstance(ctrl_pos, dict) else {}).get(
                            "supporting_evidence"
                        ) or [ctrl_key_for_tom]
                        tom_predictions[mid] = predict_belief(
                            ctrl_agent,
                            subject_id=mid,
                            concept_id=ctrl_key_for_tom,
                            new_evidence=ctrl_evidence,
                            peer_interaction_store=self.panel_bus.peer_interaction_store,
                        )

            accept_count = 0
            countering: List[str] = []

            for member_id in member_ids:
                snp_hdr = self._emit_propose(controller_id, member_id, ctrl_pos, round_idx)
                _prop_id = _get_part(snp_hdr, "snp").get("proposal_id") or snp_hdr["message"]["id"]
                _prop_msg = NegotiationMessage(
                    negotiation_id=self.panel_bus._negotiation_id,
                    proposal_id=_prop_id,
                    sender=controller_id,
                    receiver=member_id,
                    operation=NegotiationOperation.PROPOSE,
                    content=ctrl_pos if isinstance(ctrl_pos, dict) else {},
                    timestamp_sec=int(time.time()),
                )
                self.panel_bus.negotiation_store.record(_prop_msg)
                self.panel_bus.negotiation_index.record(_prop_msg)
                _neg_round.messages.append(_prop_msg)
                if self.panel_bus.tom_engine is not None:
                    listener_belief = self.panel_bus.tom_engine.agent(member_id).belief()
                else:
                    listener_belief = (agent_beliefs or {}).get(member_id, {})
                if member_id in tom_predictions:
                    listener_belief = {**listener_belief, "tom_prediction": tom_predictions[member_id]}

                member_pos = specialist_positions[member_id]
                ctrl_conf = self._confidence(ctrl_pos)
                ctrl_key = self._position_key(ctrl_pos)
                member_key = self._position_key(member_pos)

                # Fix A: read BeliefState.posterior back into the decision threshold.
                # inject_prior() may have shifted the posterior; using it closes the
                # Bayesian loop: semantic rule → prior → posterior → accept decision.
                # In episode 1 round 1, posterior == prior (only inject_prior has run),
                # so the warm-up round correctly uses the raw prior.
                if self.panel_bus.belief_store is not None:
                    _bs = self.panel_bus.belief_store.current_belief(
                        member_id, concept_id, self.panel_bus.use_case
                    )
                    if _bs is not None:
                        member_conf_for_decision = _bs.posterior
                    else:
                        member_conf_for_decision = self._confidence(member_pos)
                else:
                    member_conf_for_decision = self._confidence(member_pos)

                tom_pred = tom_predictions.get(member_id, {})
                spec_threshold = accept_threshold
                if tom_pred.get("reliability", 0.0) > 0.3 and tom_pred.get("predicted_confidence", 0.5) < 0.4:
                    spec_threshold = max(0.02, accept_threshold - 0.04)

                same = ctrl_key == member_key
                ctrl_dominates = ctrl_conf >= member_conf_for_decision + spec_threshold

                if same or ctrl_dominates:
                    operation = NegotiationOperation.ACCEPT
                    specialist_positions[member_id] = ctrl_pos
                    accept_count += 1
                else:
                    operation = NegotiationOperation.COUNTER_PROPOSAL
                    countering.append(member_id)

                resp_snp = self._emit_specialist_response(
                    specialist=member_id,
                    controller=controller_id,
                    position=specialist_positions[member_id],
                    operation=operation,
                    turn=round_idx,
                    ie_request_message_id=snp_hdr["message"]["id"],
                    ctrl_position_key=ctrl_key,
                    ctrl_conf=ctrl_conf,
                    accept_threshold=accept_threshold,
                )
                _resp_prop_id = _get_part(resp_snp, "snp").get("proposal_id") or resp_snp["message"]["id"]
                _resp_msg = NegotiationMessage(
                    negotiation_id=self.panel_bus._negotiation_id,
                    proposal_id=_prop_id,
                    sender=member_id,
                    receiver=controller_id,
                    operation=operation,
                    content=specialist_positions[member_id] if isinstance(specialist_positions[member_id], dict) else {},
                    timestamp_sec=int(time.time()),
                    status="pending",
                )
                self.panel_bus.negotiation_store.record(_resp_msg)
                self.panel_bus.negotiation_index.record(_resp_msg)
                _neg_round.messages.append(_resp_msg)

                # Post-response bilateral grounding verification using B's actual response
                verb = "accepts" if operation == NegotiationOperation.ACCEPT else "counter-proposes"
                response_utt = (
                    f"{member_id} {verb} "
                    f"{self._position_key(specialist_positions[member_id])} "
                    f"confidence={self._confidence(specialist_positions[member_id]):.2f}"
                )
                self.panel_bus._verify_grounding_bilateral(
                    utterance_a=prop_utt,
                    response_b=response_utt,
                    snp_message_id=snp_hdr["message"]["id"],
                    task_goal=task_goal,
                    speaker=controller_id,
                    listener=member_id,
                    listener_actual_confidence=self._confidence(specialist_positions[member_id]),
                    listener_belief=listener_belief,
                    concept_id=concept_id,
                    forced_accept=ctrl_dominates and not same,
                    speaker_epistemic=snp_hdr.get("epistemic"),
                    listener_epistemic=resp_snp.get("epistemic"),
                )

            if accept_count == n:
                resolution_label = "consensus"
                break
            # Spec §4.7: count(positions >= threshold) / len(positions) >= threshold
            _all_positions = {**{mid: specialist_positions[mid] for mid in member_ids}, controller_id: ctrl_pos}
            _all_confs = [self._confidence(p) for p in _all_positions.values()]
            _frac_above = sum(1 for c in _all_confs if c >= accept_threshold) / len(_all_confs) if _all_confs else 0.0
            if _frac_above >= accept_threshold:
                resolution_label = "majority"
                break
            if accept_count > n / 2:
                resolution_label = "majority"
                break
            if not countering:
                resolution_label = "consensus"
                break

            counter_pos_map = {mid: specialist_positions[mid] for mid in countering}
            leading_counter = self._leading_position(counter_pos_map)
            leading_counter_key = self._position_key(leading_counter)
            leading_counter_count = sum(
                1 for mid in countering
                if self._position_key(specialist_positions[mid]) == leading_counter_key
            )
            if leading_counter_count > accept_count:
                ctrl_pos = leading_counter

        if resolution_label == "timeout_majority":
            all_positions = {**specialist_positions, controller_id: ctrl_pos}
            keys = [self._position_key(p) for p in all_positions.values()]
            top_count = max(Counter(keys).values())
            if top_count > n / 2:
                resolution_label = "timeout_majority"

        pre_final_positions = dict(specialist_positions)
        winning_position = self._leading_position(specialist_positions)
        win_key = self._position_key(winning_position)
        # Count genuine accepts for GAR computation
        genuine_accept_count = sum(
            1 for mid in member_ids
            if self._position_key(pre_final_positions.get(mid, winning_position)) == win_key
        )

        if self.panel_bus.convergence_store is not None:
            # GAR: fraction of agents whose posterior moved in same direction as grounded argument
            if self.panel_bus.belief_store is not None:
                _cons_conf = self._confidence(winning_position)
                consistent = 0
                total_agents = len(member_ids) + 1
                for _gid in [controller_id] + list(member_ids):
                    _bs = self.panel_bus.belief_store.current_belief(
                        _gid, concept_id, self.panel_bus.use_case
                    )
                    if _bs is not None:
                        _ip = initial_priors.get(_gid, 0.5)
                        if (_bs.posterior - _ip) * (_cons_conf - 0.5) >= 0:
                            consistent += 1
                    else:
                        consistent += 1
                gar = round(consistent / total_agents, 4) if total_agents > 0 else 1.0
            else:
                # Fallback: direction-of-movement consistency with consensus direction
                _cons_conf = self._confidence(winning_position)
                _star_all = [controller_id] + list(member_ids)
                _star_final = {**{mid: specialist_positions[mid] for mid in member_ids},
                               controller_id: ctrl_pos}
                _genuine = sum(
                    1 for _gid in _star_all
                    if (self._confidence(_star_final[_gid]) >= _cons_conf)
                    == (_cons_conf >= initial_priors.get(_gid, 0.5))
                )
                gar = round(_genuine / len(_star_all), 4) if _star_all else 1.0

            # Step 4: individual_posteriors from BeliefState.posterior if wired
            if self.panel_bus.belief_store is not None:
                def _posterior(aid: str, fallback: float) -> float:
                    bs = self.panel_bus.belief_store.current_belief(
                        aid, concept_id, self.panel_bus.use_case
                    )
                    return bs.posterior if bs is not None else fallback
                final_posteriors = {mid: _posterior(mid, self._confidence(specialist_positions[mid]))
                                    for mid in member_ids}
                final_posteriors[controller_id] = _posterior(
                    controller_id, self._confidence(winning_position)
                )
            else:
                final_posteriors = {mid: self._confidence(specialist_positions[mid]) for mid in member_ids}
                final_posteriors[controller_id] = self._confidence(winning_position)

            # Step 5: SCR from BeliefState.social_compliance_ratio per agent
            if self.panel_bus.belief_store is not None:
                all_scrs = []
                for aid in [controller_id] + list(member_ids):
                    bs = self.panel_bus.belief_store.current_belief(
                        aid, concept_id, self.panel_bus.use_case
                    )
                    if bs is not None:
                        all_scrs.append(bs.social_compliance_ratio)
                scr = round(sum(all_scrs) / len(all_scrs), 4) if all_scrs else 0.0
            else:
                scr = 0.0

            mpc = round(sum(final_posteriors.values()) / len(final_posteriors), 4)
            outcome_map = {
                "consensus": "accept", "majority": "accept",
                "timeout_majority": "accept", "stale_majority": "deferred",
            }
            truth = TeamGroundedTruth(
                concept_id=win_key,
                use_case=self.panel_bus.use_case,
                episode_id=self.panel_bus._episode_id(),
                participant_ids=[controller_id] + list(member_ids),
                individual_priors=dict(initial_priors),
                individual_posteriors=final_posteriors,
                consensus_posterior=mpc,
                genuine_agreement_ratio=gar,
                social_compliance_ratio=scr,
                common_ground_ids=list(self.panel_bus._common_ground_ids),
                outcome=outcome_map.get(resolution_label, "deferred"),
                formed_at_ms=int(time.time() * 1000),
            )
            self.panel_bus.convergence_store.record(truth)

            # Emit one commit:converged — panel_bus is a shared observable bus,
            # all participants see it without individual addressing.
            _conv_proposal_id = f"convergence-{self.panel_bus._negotiation_id[:8]}"
            _conv_utterance = (
                f"SNP convergence: {win_key} → {truth.outcome}"
                f" posterior={truth.consensus_posterior:.4f}"
                f" gar={truth.genuine_agreement_ratio:.4f}"
                f" scr={truth.social_compliance_ratio:.4f}"
            )
            _snp_convergence = {
                "profile": "semantic_negotiation",
                "operation": NegotiationOperation.ACCEPT,
                "participant_ids": list(truth.participant_ids),
                "mpc": truth.consensus_posterior,
                "gar": truth.genuine_agreement_ratio,
                "scr": truth.social_compliance_ratio,
                "episode_id": truth.episode_id,
            }
            convergence_header = build_snp_l9_header(
                operation=NegotiationOperation.ACCEPT,
                use_case=self.panel_bus.use_case,
                sender=controller_id,
                receiver=None,
                timestamp_ms=truth.formed_at_ms,
                proposal_id=_conv_proposal_id,
                utterance=_conv_utterance,
                episode_id=truth.episode_id,
                kind_override="commit:converged",
                payload_parts=[
                    {"type": "utterance", "location": "inline", "content": _conv_utterance},
                    {"type": "snp-convergence", "location": "inline", "content": _snp_convergence},
                ],
            )
            self.panel_bus.ie_bus.messages.append(convergence_header)

            # C10: push consensus_posterior into each participant's AgentTOM and BeliefState.
            # Use URN concept_id (matching inject_prior's lookup key) not bare win_key.
            _conv_concept_id = f"urn:concept:{self.panel_bus.use_case}:{win_key}"
            if self.panel_bus.tom_engine is not None:
                for _pid in truth.participant_ids:
                    _agent = self.panel_bus.tom_engine.agent(_pid)
                    _prev = truth.consensus_posterior
                    pass  # _belief removed
                    if self.panel_bus.belief_store is not None:
                        _crev = BeliefRevision(
                            revision_id=str(uuid.uuid4()),
                            timestamp_ms=truth.formed_at_ms,
                            episode_id=truth.episode_id,
                            message_id=convergence_header["message"]["id"],
                            confidence_before=_prev,
                            confidence_after=truth.consensus_posterior,
                            cause="new_evidence",
                            caused_by_agent=None,
                            argument_concept_ids=[_conv_concept_id],
                        )
                        self.panel_bus.belief_store.record_revision(
                            _pid, _conv_concept_id, self.panel_bus.use_case, truth.episode_id, _crev,
                            new_status="asserted", new_public_confidence=truth.consensus_posterior,
                        )

            if (
                self.panel_bus.semantic_rule_store is not None
                and truth.outcome == "accept"
            ):
                provenance_weight = round(
                    (1.0 - truth.social_compliance_ratio) * truth.genuine_agreement_ratio, 4
                )
                rule = SemanticRule(
                    concept_id=_conv_concept_id,
                    use_case=self.panel_bus.use_case,
                    confidence=truth.consensus_posterior,
                    provenance_weight=provenance_weight,
                    source_episode_id=truth.episode_id,
                    payload={
                        "participant_ids": truth.participant_ids,
                        "individual_priors": truth.individual_priors,
                        "individual_posteriors": truth.individual_posteriors,
                        "gar": truth.genuine_agreement_ratio,
                        "scr": truth.social_compliance_ratio,
                    },
                    recorded_at_ms=truth.formed_at_ms,
                    description=f"Team converged: {win_key} at posterior={truth.consensus_posterior:.2f}",
                )
                self.panel_bus.semantic_rule_store.record(rule)
                # Emit rule_update (kind=knowledge) on the panel SNP trace
                _rule_utterance = (
                    f"rule_update:{win_key}"
                    f":posterior={truth.consensus_posterior:.4f}"
                    f":gar={truth.genuine_agreement_ratio:.4f}"
                    f":scr={truth.social_compliance_ratio:.4f}"
                    f":provenance_weight={provenance_weight:.4f}"
                )
                _rule_header = build_snp_l9_header(
                    operation=NegotiationOperation.ACCEPT,
                    use_case=self.panel_bus.use_case,
                    sender=controller_id,
                    receiver=None,
                    timestamp_ms=truth.formed_at_ms + 1,
                    proposal_id=f"rule-{self.panel_bus._negotiation_id[:8]}",
                    utterance=_rule_utterance,
                    episode_id=truth.episode_id,
                    kind_override="knowledge",
                    topic=_conv_concept_id,
                    epistemic=make_epistemic_block(
                        speech_act=SpeechAct.ASSERTION,
                        epistemic_state=EpistemicState.TASKWORK,
                    ),
                    payload_parts=[
                        {"type": "utterance", "location": "inline", "content": _rule_utterance},
                    ],
                )
                self.panel_bus.ie_bus.messages.append(_rule_header)

        # Fix 4: batch-promote accumulated ArgumentOutcomes and write-back to AgentEpistemicStore
        if self.panel_bus.peer_interaction_store is not None:
            for (agent_a, agent_b), _outcomes in self.panel_bus._pending_arg_outcomes.items():
                self.panel_bus.peer_interaction_store.promote_outcomes_for_pair(
                    agent_a, agent_b,
                    use_case=self.panel_bus.use_case,
                    episode_id=self.panel_bus._episode_id(),
                    argument_outcomes=_outcomes,
                    prediction_records=[],
                )
                rec = self.panel_bus.peer_interaction_store.get_peer_record(
                    agent_a, agent_b, self.panel_bus.use_case
                )
                if rec is not None and self.panel_bus.tom_engine is not None:
                    try:
                        _tom_a = self.panel_bus.tom_engine.agent(agent_a)
                        _persisted = _tom_a._epistemic_store.load_peer_model(agent_b) or {}
                        _persisted.update({
                            "argument_types_that_move": rec.argument_types_that_move,
                            "argument_types_ignored":   rec.argument_types_ignored,
                            "evidence_weights":         rec.evidence_weights,
                            "predictive_accuracy":      rec.predictive_accuracy,
                        })
                        _tom_a._epistemic_store.save_peer_model(agent_b, _persisted)
                    except Exception:
                        pass
            self.panel_bus._pending_arg_outcomes.clear()

        if self.panel_bus.persistence_path:
            self.panel_bus._save_cross_episode_state(self.panel_bus.persistence_path)

        return winning_position, resolution_label, list(self.panel_bus.snp_trace)


class RingNegotiation:
    """Ring-topology semantic negotiation among N panel members."""

    def __init__(self, panel_bus: PanelBus, panel_name: str) -> None:
        self.panel_bus = panel_bus
        self.panel_name = panel_name

    @staticmethod
    def _position_key(pos: Any) -> str:
        if isinstance(pos, dict):
            return str(pos.get("likely_cause") or pos.get("risk_bucket") or pos.get("decision_key") or pos)
        return str(pos)

    @staticmethod
    def _confidence(pos: Any) -> float:
        if isinstance(pos, dict):
            return float(pos.get("confidence") or pos.get("roi_score") or 0.5)
        return 0.5

    @staticmethod
    def _utterance(member_id: str, pos: Any, operation: str) -> str:
        key = RingNegotiation._position_key(pos)
        conf = RingNegotiation._confidence(pos)
        verb = {"negotiate": "proposes", "accept": "accepts", "reject": "rejects"}[operation]
        return f"{member_id} {verb} {key} confidence={conf:.2f}"

    @staticmethod
    def _check_termination(positions: Dict[str, Any], n: int, accept_threshold: float = 0.6) -> str | None:
        keys = [RingNegotiation._position_key(p) for p in positions.values()]
        counts = Counter(keys)
        top_count = counts.most_common(1)[0][1]
        if top_count == n:
            return "consensus"
        # Spec §4.7: count(positions >= threshold) / len(positions) >= threshold
        _confs = [RingNegotiation._confidence(p) for p in positions.values()]
        _frac_above = sum(1 for c in _confs if c >= accept_threshold) / len(_confs) if _confs else 0.0
        if _frac_above >= accept_threshold:
            return "majority"
        if top_count > n / 2:
            return "majority"
        return None

    @staticmethod
    def _leading_position(positions: Dict[str, Any]) -> Any:
        by_key: Dict[str, List[Any]] = {}
        for pos in positions.values():
            by_key.setdefault(RingNegotiation._position_key(pos), []).append(pos)
        best_key = max(
            by_key,
            key=lambda k: (
                len(by_key[k]),
                round(sum(RingNegotiation._confidence(p) for p in by_key[k]) / len(by_key[k]), 4),
                k,
            ),
        )
        return max(by_key[best_key], key=RingNegotiation._confidence)

    def run(
        self,
        member_ids: List[str],
        initial_positions: Dict[str, Any],
        accept_threshold: float = 0.1,
        max_rounds: int = 3,
        task_goal: str = "",
        agent_beliefs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, str, List[Dict[str, Any]]]:
        n = len(member_ids)
        positions = dict(initial_positions)
        initial_pos_keys = {mid: self._position_key(positions[mid]) for mid in member_ids}
        stale_rounds = 0
        resolution_label = "timeout_majority"

        # Derive concept_id from leading initial position key
        first_init_key = self._position_key(initial_positions[member_ids[0]]) if member_ids else ""
        concept_id = f"urn:concept:{self.panel_bus.use_case}:{first_init_key}"

        # Inject cross-episode social skill map into peer belief models before negotiation
        self.panel_bus._inject_skill_maps(list(member_ids))

        # Panel session open — emit intent on the panel episode
        _ring_episode_id = self.panel_bus._episode_id()
        _ring_intent_utterance = f"panel:open concept={first_init_key} participants={list(member_ids)}"
        _ring_intent_header = build_snp_l9_header(
            operation=NegotiationOperation.NEGOTIATE,
            use_case=self.panel_bus.use_case,
            sender=member_ids[0] if member_ids else "ring",
            receiver=None,
            timestamp_ms=int(time.time() * 1000),
            proposal_id=f"intent-{self.panel_bus._negotiation_id[:8]}",
            utterance=_ring_intent_utterance,
            episode_id=_ring_episode_id,
            kind_override="intent",
            payload_parts=[{"type": "utterance", "location": "inline", "content": _ring_intent_utterance}],
        )
        self.panel_bus.ie_bus.messages.append(_ring_intent_header)

        # Inject priors from SemanticRuleStore (or positional confidence) before loop
        for mid in member_ids:
            self.panel_bus.inject_prior(
                agent_id=mid,
                concept_id=concept_id,
                prior=self._confidence(initial_positions[mid]),
            )

        # Snapshot initial priors from BeliefState (after inject_prior has run)
        if self.panel_bus.belief_store is not None:
            initial_priors = {}
            for mid in member_ids:
                bs = self.panel_bus.belief_store.current_belief(mid, concept_id, self.panel_bus.use_case)
                initial_priors[mid] = bs.prior if bs is not None else self._confidence(initial_positions[mid])
        else:
            initial_priors = {mid: self._confidence(initial_positions[mid]) for mid in member_ids}

        # AF1: sync proposal confidence from BeliefState.posterior when a SemanticRule exists.
        if (self.panel_bus.belief_store is not None
                and self.panel_bus.semantic_rule_store is not None):
            _af1_rule = self.panel_bus.semantic_rule_store.latest(concept_id, self.panel_bus.use_case)
            if _af1_rule is not None:
                for _af1_mid in member_ids:
                    _af1_bs = self.panel_bus.belief_store.current_belief(
                        _af1_mid, concept_id, self.panel_bus.use_case)
                    if _af1_bs is not None:
                        positions[_af1_mid]["confidence"] = _af1_bs.posterior

        for round_idx in range(max_rounds):
            prev_keys = {mid: self._position_key(positions[mid]) for mid in member_ids}
            last_snp_id: str | None = None

            # Record NegotiationRound at start with current position snapshot
            _ring_round_id = f"{self.panel_bus._negotiation_id}:ring:round:{round_idx}"
            _ring_round = NegotiationRound(
                round_id=_ring_round_id,
                proposal_id=self.panel_bus._proposal_id(round_idx, member_ids[0] if member_ids else "ring"),
                participants=list(member_ids),
                individual_positions={mid: self._confidence(positions[mid]) for mid in member_ids},
            )
            self.panel_bus.round_store.record(_ring_round)

            for i in range(n):
                sender_id = member_ids[i]
                receiver_id = member_ids[(i + 1) % n]
                sender_pos = positions[sender_id]
                receiver_pos = positions[receiver_id]

                sender_conf = self._confidence(sender_pos)
                receiver_conf = self._confidence(receiver_pos)
                sender_key = self._position_key(sender_pos)
                receiver_key = self._position_key(receiver_pos)

                neg_utt = self._utterance(sender_id, sender_pos, "negotiate")
                snp_neg = self.panel_bus.emit_negotiate(
                    sender=sender_id,
                    receiver=receiver_id,
                    utterance=neg_utt,
                    turn=round_idx,
                    confidence=sender_conf,
                    parent_snp_id=last_snp_id,
                    epistemic_state=EpistemicState.TASKWORK if round_idx == 0 else EpistemicState.TEAM_PROCESS,
                )
                last_snp_id = snp_neg["message"]["id"]
                _neg_prop_id = _get_part(snp_neg, "snp").get("proposal_id") or snp_neg["message"]["id"]
                _neg_msg = NegotiationMessage(
                    negotiation_id=self.panel_bus._negotiation_id,
                    proposal_id=_neg_prop_id,
                    sender=sender_id,
                    receiver=receiver_id,
                    operation=NegotiationOperation.NEGOTIATE,
                    content=sender_pos if isinstance(sender_pos, dict) else {},
                    timestamp_sec=int(time.time()),
                )
                self.panel_bus.negotiation_store.record(_neg_msg)
                self.panel_bus.negotiation_index.record(_neg_msg)
                _ring_round.messages.append(_neg_msg)

                if self.panel_bus.tom_engine is not None:
                    listener_belief = self.panel_bus.tom_engine.agent(receiver_id).belief()
                    sender_agent = self.panel_bus.tom_engine.agent(sender_id)
                    if hasattr(sender_agent, "predict_peer_response"):
                        raw = sender_agent.predict_peer_response(
                            receiver_id, neg_utt, task_goal,
                        )
                        listener_belief = {**listener_belief, "tom_prediction": {
                            "predicted_confidence": raw.get("predicted_alignment", 0.5),
                            "reliability": raw.get("confidence", 0.1),
                        }}
                else:
                    listener_belief = (agent_beliefs or {}).get(receiver_id, {})

                # Determine B's actual response before verifying grounding.
                # Fix A: use BeliefState.posterior for the receiver so the Bayesian
                # chain closes: inject_prior → grounding revisions → posterior → decision.
                if self.panel_bus.belief_store is not None:
                    _bs_recv = self.panel_bus.belief_store.current_belief(
                        receiver_id, concept_id, self.panel_bus.use_case
                    )
                    receiver_conf_for_decision = _bs_recv.posterior if _bs_recv is not None else receiver_conf
                else:
                    receiver_conf_for_decision = receiver_conf
                same_position = sender_key == receiver_key
                sender_dominates = sender_conf >= receiver_conf_for_decision + accept_threshold
                if same_position or sender_dominates:
                    operation = NegotiationOperation.ACCEPT
                    if sender_dominates and not same_position:
                        positions[receiver_id] = sender_pos
                    decision_utt = self._utterance(receiver_id, positions[receiver_id], "accept")
                else:
                    operation = NegotiationOperation.REJECT
                    decision_utt = self._utterance(receiver_id, receiver_pos, "reject")

                snp_dec = self.panel_bus.emit_decision(
                    sender=receiver_id,
                    receiver=sender_id,
                    utterance=decision_utt,
                    operation=operation,
                    turn=round_idx,
                    confidence=self._confidence(positions[receiver_id]),
                    ie_request_message_id=snp_neg["message"]["id"],
                    parent_snp_id=last_snp_id,
                    ctrl_position_key=sender_key,
                    ctrl_conf=sender_conf,
                    accept_threshold=accept_threshold,
                )
                last_snp_id = snp_dec["message"]["id"]
                _dec_msg = NegotiationMessage(
                    negotiation_id=self.panel_bus._negotiation_id,
                    proposal_id=_neg_prop_id,
                    sender=receiver_id,
                    receiver=sender_id,
                    operation=operation,
                    content=positions[receiver_id] if isinstance(positions[receiver_id], dict) else {},
                    timestamp_sec=int(time.time()),
                )
                self.panel_bus.negotiation_store.record(_dec_msg)
                self.panel_bus.negotiation_index.record(_dec_msg)
                _ring_round.messages.append(_dec_msg)

                # Post-response bilateral grounding verification using B's actual response
                self.panel_bus._verify_grounding_bilateral(
                    utterance_a=neg_utt,
                    response_b=decision_utt,
                    snp_message_id=snp_neg["message"]["id"],
                    task_goal=task_goal,
                    speaker=sender_id,
                    listener=receiver_id,
                    listener_actual_confidence=self._confidence(positions[receiver_id]),
                    listener_belief=listener_belief,
                    concept_id=concept_id,
                    forced_accept=sender_dominates and not same_position,
                    speaker_epistemic=snp_neg.get("epistemic"),
                    listener_epistemic=snp_dec.get("epistemic"),
                )

            result = self._check_termination(positions, n, accept_threshold=accept_threshold)
            if result:
                resolution_label = result
                break

            new_keys = {mid: self._position_key(positions[mid]) for mid in member_ids}
            if new_keys == prev_keys:
                stale_rounds += 1
                if stale_rounds >= 2:
                    resolution_label = "stale_majority"
                    break
            else:
                stale_rounds = 0

        winning_position = self._leading_position(positions)
        win_key = self._position_key(winning_position)

        if self.panel_bus.convergence_store is not None:
            # GAR: fraction of agents whose posterior moved in same direction as grounded argument
            if self.panel_bus.belief_store is not None:
                _ring_cons_conf = self._confidence(winning_position)
                _consistent = 0
                _total = len(member_ids)
                for _gid in member_ids:
                    _bs = self.panel_bus.belief_store.current_belief(
                        _gid, concept_id, self.panel_bus.use_case
                    )
                    if _bs is not None:
                        _ip = initial_priors.get(_gid, 0.5)
                        if (_bs.posterior - _ip) * (_ring_cons_conf - 0.5) >= 0:
                            _consistent += 1
                    else:
                        _consistent += 1
                gar = round(_consistent / _total, 4) if _total > 0 else 1.0
            else:
                # Fallback: direction-of-movement consistency with consensus direction
                _ring_cons_conf = self._confidence(winning_position)
                _ring_genuine = sum(
                    1 for mid in member_ids
                    if (self._confidence(positions[mid]) >= _ring_cons_conf)
                    == (_ring_cons_conf >= initial_priors.get(mid, 0.5))
                )
                gar = round(_ring_genuine / len(member_ids), 4) if member_ids else 1.0

            # Posteriors from BeliefState if wired
            if self.panel_bus.belief_store is not None:
                final_posteriors = {}
                for mid in member_ids:
                    bs = self.panel_bus.belief_store.current_belief(mid, concept_id, self.panel_bus.use_case)
                    final_posteriors[mid] = bs.posterior if bs is not None else self._confidence(positions[mid])
                all_scrs = []
                for mid in member_ids:
                    bs = self.panel_bus.belief_store.current_belief(mid, concept_id, self.panel_bus.use_case)
                    if bs is not None:
                        all_scrs.append(bs.social_compliance_ratio)
                scr = round(sum(all_scrs) / len(all_scrs), 4) if all_scrs else 0.0
            else:
                final_posteriors = {mid: self._confidence(positions[mid]) for mid in member_ids}
                scr = 0.0

            mpc = round(sum(final_posteriors.values()) / len(final_posteriors), 4) if final_posteriors else 0.5
            outcome_map = {
                "consensus": "accept", "majority": "accept",
                "timeout_majority": "accept", "stale_majority": "deferred",
            }
            formed_at = int(time.time() * 1000)
            truth = TeamGroundedTruth(
                concept_id=win_key,
                use_case=self.panel_bus.use_case,
                episode_id=self.panel_bus._episode_id(),
                participant_ids=list(member_ids),
                individual_priors=dict(initial_priors),
                individual_posteriors=final_posteriors,
                consensus_posterior=mpc,
                genuine_agreement_ratio=gar,
                social_compliance_ratio=scr,
                common_ground_ids=list(self.panel_bus._common_ground_ids),
                outcome=outcome_map.get(resolution_label, "deferred"),
                formed_at_ms=formed_at,
            )
            self.panel_bus.convergence_store.record(truth)

            # Spec §4.9: emit convergence_emitted to each participant individually.
            _ring_sender = member_ids[0] if member_ids else "ring"
            # One commit:converged — ring_bus is a shared observable bus.
            _ring_conv_proposal_id = f"convergence-{self.panel_bus._negotiation_id[:8]}"
            _ring_conv_utterance = (
                f"SNP ring convergence: {win_key} → {truth.outcome}"
                f" posterior={truth.consensus_posterior:.4f}"
                f" gar={truth.genuine_agreement_ratio:.4f}"
                f" scr={truth.social_compliance_ratio:.4f}"
            )
            _ring_snp_convergence = {
                "profile": "semantic_negotiation",
                "operation": NegotiationOperation.ACCEPT,
                "participant_ids": list(truth.participant_ids),
                "mpc": truth.consensus_posterior,
                "gar": truth.genuine_agreement_ratio,
                "scr": truth.social_compliance_ratio,
                "episode_id": truth.episode_id,
            }
            convergence_header = build_snp_l9_header(
                operation=NegotiationOperation.ACCEPT,
                use_case=self.panel_bus.use_case,
                sender=_ring_sender,
                receiver=None,
                timestamp_ms=formed_at,
                proposal_id=_ring_conv_proposal_id,
                utterance=_ring_conv_utterance,
                episode_id=truth.episode_id,
                kind_override="commit:converged",
                payload_parts=[
                    {"type": "utterance", "location": "inline", "content": _ring_conv_utterance},
                    {"type": "snp-convergence", "location": "inline", "content": _ring_snp_convergence},
                ],
            )
            self.panel_bus.ie_bus.messages.append(convergence_header)

            # C10: push consensus_posterior into each participant's AgentTOM and BeliefState.
            # Use URN concept_id (matching inject_prior's lookup key) not bare win_key.
            _conv_concept_id = f"urn:concept:{self.panel_bus.use_case}:{win_key}"
            if self.panel_bus.tom_engine is not None:
                for _pid in truth.participant_ids:
                    _agent = self.panel_bus.tom_engine.agent(_pid)
                    _prev = truth.consensus_posterior
                    pass  # _belief removed
                    if self.panel_bus.belief_store is not None:
                        _crev = BeliefRevision(
                            revision_id=str(uuid.uuid4()),
                            timestamp_ms=truth.formed_at_ms,
                            episode_id=truth.episode_id,
                            message_id=convergence_header["message"]["id"],
                            confidence_before=_prev,
                            confidence_after=truth.consensus_posterior,
                            cause="new_evidence",
                            caused_by_agent=None,
                            argument_concept_ids=[_conv_concept_id],
                        )
                        self.panel_bus.belief_store.record_revision(
                            _pid, _conv_concept_id, self.panel_bus.use_case, truth.episode_id, _crev,
                            new_status="asserted", new_public_confidence=truth.consensus_posterior,
                        )

            if self.panel_bus.semantic_rule_store is not None and truth.outcome == "accept":
                provenance_weight = round(
                    (1.0 - truth.social_compliance_ratio) * truth.genuine_agreement_ratio, 4
                )
                rule = SemanticRule(
                    concept_id=_conv_concept_id,
                    use_case=self.panel_bus.use_case,
                    confidence=truth.consensus_posterior,
                    provenance_weight=provenance_weight,
                    source_episode_id=truth.episode_id,
                    payload={
                        "participant_ids": truth.participant_ids,
                        "individual_priors": truth.individual_priors,
                        "individual_posteriors": truth.individual_posteriors,
                        "gar": truth.genuine_agreement_ratio,
                        "scr": truth.social_compliance_ratio,
                    },
                    recorded_at_ms=formed_at,
                    description=f"Team converged: {win_key} at posterior={truth.consensus_posterior:.2f}",
                )
                self.panel_bus.semantic_rule_store.record(rule)
                # Emit rule_update (kind=knowledge) on the panel SNP trace
                _ring_sender = member_ids[0] if member_ids else "ring-controller"
                _rule_utterance_r = (
                    f"rule_update:{win_key}"
                    f":posterior={truth.consensus_posterior:.4f}"
                    f":gar={truth.genuine_agreement_ratio:.4f}"
                    f":scr={truth.social_compliance_ratio:.4f}"
                    f":provenance_weight={provenance_weight:.4f}"
                )
                _rule_header_r = build_snp_l9_header(
                    operation=NegotiationOperation.ACCEPT,
                    use_case=self.panel_bus.use_case,
                    sender=_ring_sender,
                    receiver=None,
                    timestamp_ms=truth.formed_at_ms + 1,
                    proposal_id=f"rule-{self.panel_bus._negotiation_id[:8]}",
                    utterance=_rule_utterance_r,
                    episode_id=truth.episode_id,
                    kind_override="knowledge",
                    topic=f"urn:concept:{self.panel_bus.use_case}:{win_key}",
                    epistemic=make_epistemic_block(
                        speech_act=SpeechAct.ASSERTION,
                        epistemic_state=EpistemicState.TASKWORK,
                    ),
                    payload_parts=[
                        {"type": "utterance", "location": "inline", "content": _rule_utterance_r},
                    ],
                )
                self.panel_bus.ie_bus.messages.append(_rule_header_r)

        # Fix 4: batch-promote accumulated ArgumentOutcomes and write-back to AgentEpistemicStore
        if self.panel_bus.peer_interaction_store is not None:
            for (agent_a, agent_b), _outcomes in self.panel_bus._pending_arg_outcomes.items():
                self.panel_bus.peer_interaction_store.promote_outcomes_for_pair(
                    agent_a, agent_b,
                    use_case=self.panel_bus.use_case,
                    episode_id=self.panel_bus._episode_id(),
                    argument_outcomes=_outcomes,
                    prediction_records=[],
                )
                rec = self.panel_bus.peer_interaction_store.get_peer_record(
                    agent_a, agent_b, self.panel_bus.use_case
                )
                if rec is not None and self.panel_bus.tom_engine is not None:
                    try:
                        _tom_a = self.panel_bus.tom_engine.agent(agent_a)
                        _persisted = _tom_a._epistemic_store.load_peer_model(agent_b) or {}
                        _persisted.update({
                            "argument_types_that_move": rec.argument_types_that_move,
                            "argument_types_ignored":   rec.argument_types_ignored,
                            "evidence_weights":         rec.evidence_weights,
                            "predictive_accuracy":      rec.predictive_accuracy,
                        })
                        _tom_a._epistemic_store.save_peer_model(agent_b, _persisted)
                    except Exception:
                        pass
            self.panel_bus._pending_arg_outcomes.clear()

        if self.panel_bus.persistence_path:
            self.panel_bus._save_cross_episode_state(self.panel_bus.persistence_path)

        return winning_position, resolution_label, list(self.panel_bus.snp_trace)


__all__ = [
    "IERepairExhausted",
    "PanelBus",
    "StarNegotiation",
    "RingNegotiation",
]

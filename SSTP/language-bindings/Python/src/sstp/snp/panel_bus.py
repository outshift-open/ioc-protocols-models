# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/snp/panel_bus.py — Domain-agnostic SNP + IE dual-protocol panel negotiation bus.

Three classes:
  PanelBus          — shared message bus; use_case and tenant_id are constructor params
  StarNegotiation   — hub-and-spoke: controller proposes → N members respond → commit
  RingNegotiation   — ring: each member proposes to the next → rotate until convergence

Every pairwise exchange emits simultaneously:
  1. An SNP L9 header (build_snp_l9_header) → snp_trace
  2. An IE L9 envelope (AgentBus.emit_request / emit_response) → agent message stream

Ported from app/healthcare_ie_snp/panel_negotiation_bus.py; only use_case / tenant_id
hardcodes and the soid format have been parameterised.
"""
from __future__ import annotations

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
from sstp.tomcore.tom_channel import TOMPairChannel
from sstp.epistemic import (
    SpeechAct, TaskPhase, BeliefStatus,
    make_epistemic_block, infer_snp_epistemic,
)
from sstp.epistemic.stores import CommonGround, PeerInteractionStore, TeamGroundedTruth

if TYPE_CHECKING:
    from sstp.ie.agent_bus import AgentBus
    from sstp.ie.epistemic_store import EpistemicStore
    from sstp.ie.tom import TheoryOfMindEngineBase

LOGGER = logging.getLogger(__name__)


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
    use_case:   domain label written into L9 headers and soid
    tenant_id:  tenant written into IE L9 headers via ie_bus
    """

    def __init__(
        self,
        panel_name: str,
        ie_bus: "AgentBus",
        use_case: str,
        tenant_id: str = "",
        tom_engine: "TheoryOfMindEngineBase | None" = None,
        repair_fn: "Callable[[str, str, str, str, Dict, str | None, int], str] | None" = None,
        peer_store: Optional[PeerInteractionStore] = None,
        epistemic_store: "Optional[EpistemicStore]" = None,
    ) -> None:
        self.panel_name = panel_name
        self.ie_bus = ie_bus
        self.use_case = use_case
        self.tenant_id = tenant_id
        self.tom_engine = tom_engine
        self.repair_fn = repair_fn
        self.peer_store = peer_store
        self.epistemic_store = epistemic_store
        self.snp_trace: List[Dict[str, Any]] = []
        self._negotiation_id: str = str(uuid.uuid4())
        self._common_ground_ids: List[str] = []

    def reset(self, negotiation_id: str | None = None) -> None:
        self.snp_trace = []
        self._common_ground_ids = []
        self._negotiation_id = negotiation_id or str(uuid.uuid4())

    def _state_object_id(self) -> str:
        return f"urn:ioc:{self.use_case}:panel:{self.panel_name}:{self._negotiation_id}"

    def _proposal_id(self, turn: int, sender: str) -> str:
        return f"panel-{self.panel_name}-{self._negotiation_id[:8]}-t{turn}-{sender}"

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
    ) -> Tuple[str, List[Dict[str, Any]]]:
        acc: List[Dict[str, Any]] = _accumulated if _accumulated is not None else []

        if self.tom_engine is None:
            return utterance, acc

        channel = TOMPairChannel(sender, listener, self.tom_engine)
        result = channel.assess_utterance(
            utterance, task_goal, speaker=sender, listener=listener
        )

        if result.get("aligned", True):
            return utterance, acc

        derailment_cause: str | None = result.get("derailment_cause")

        if ie_depth > max_ie_depth:
            raise IERepairExhausted(snp_message_id, ie_depth, derailment_cause)

        ts = int(time.time() * 1000)
        child_state_id = f"{self._state_object_id()}:ie:{ie_depth}"

        repair_required_header = build_l9_header(
            use_case=self.use_case,
            event_type="repair_required",
            sender=listener,
            receiver=sender,
            timestamp_ms=ts,
            tenant_id=self.tenant_id,
            sensitivity="confidential",
            utterance=utterance,
            parent_ids=[snp_message_id],
            turn_depth=ie_depth,
            state_object_id=child_state_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.HELP_REQUEST,
                task_phase=TaskPhase.INTERPERSONAL,
                belief_status=BeliefStatus.DEFERRED,
            ),
        )
        self.ie_bus.messages.append(
            {"type": "repair_required", "l9_header": repair_required_header,
             "utterance": utterance, "derailment_cause": derailment_cause}
        )
        acc.append(repair_required_header)

        if self.repair_fn is not None:
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
            tenant_id=self.tenant_id,
            sensitivity="confidential",
            utterance=repaired,
            parent_ids=[repair_required_header["message_id"]],
            turn_depth=ie_depth,
            state_object_id=child_state_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.BELIEF_ASSERTION,
                task_phase=TaskPhase.INTERPERSONAL,
                belief_status=BeliefStatus.REVISED,
            ),
        )
        self.ie_bus.messages.append(
            {"type": "repair_applied", "l9_header": repair_applied_header,
             "utterance": repaired}
        )
        acc.append(repair_applied_header)

        if self.epistemic_store is not None:
            ground = CommonGround(
                holder_id=sender,
                confirmer_id=listener,
                concept_id=task_goal or "task_alignment",
                use_case=self.use_case,
                episode_id=child_state_id,
                grounding_confidence=0.8,
                holder_confidence=0.8,
                confirmer_confidence=0.8,
                contingency_verified=True,
                speech_acts=["help_request", "belief_assertion"],
                grounding_message_ids=[
                    repair_required_header["message_id"],
                    repair_applied_header["message_id"],
                ],
                formed_at_ms=int(time.time() * 1000),
            )
            self.epistemic_store.record_common_ground(ground)
            self._common_ground_ids.append(child_state_id)

        return self._ie_gate(
            repaired, repair_applied_header["message_id"], task_goal,
            sender, listener, listener_belief,
            ie_depth + 1, max_ie_depth, acc,
        )

    def emit_negotiate(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        turn: int,
        confidence: float,
        parent_snp_id: str | None = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        proposal_id = self._proposal_id(turn, sender)
        ts = int(time.time() * 1000)
        epistemic_block = make_epistemic_block(
            speech_act=SpeechAct.BELIEF_ASSERTION,
            task_phase=TaskPhase.ACTION,
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
            turn_depth=turn,
            utterance=utterance,
            parent_ids=[parent_snp_id] if parent_snp_id else None,
            confidence_score=confidence,
            risk_score=round(1.0 - confidence, 4),
            state_object_id=self._state_object_id(),
            epistemic=epistemic_block,
        )
        self.snp_trace.append(snp_header)
        ie_header = self.ie_bus.emit_request(
            sender=sender,
            receiver=receiver,
            utterance=utterance,
            confidence_score=confidence,
            state_object_id=f"{self._state_object_id()}:ie:{proposal_id}",
            turn_depth=turn + 1,
            epistemic=epistemic_block,
        )
        return snp_header, ie_header

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
        speech_act, task_phase = infer_snp_epistemic(
            operation=op_str,
            ctrl_position_key=ctrl_position_key,
            member_position_key=ctrl_position_key,
            ctrl_conf=ctrl_conf,
            member_conf=confidence,
            accept_threshold=accept_threshold,
        )
        belief_status = BeliefStatus.DEFERRED if speech_act == SpeechAct.DELIBERATION_PASS else BeliefStatus.ASSERTED
        epistemic_block = make_epistemic_block(
            speech_act=speech_act,
            task_phase=task_phase,
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
            turn_depth=turn,
            utterance=utterance,
            parent_ids=[parent_snp_id] if parent_snp_id else None,
            confidence_score=confidence,
            risk_score=round(1.0 - confidence, 4),
            state_object_id=self._state_object_id(),
            epistemic=epistemic_block,
        )
        self.snp_trace.append(snp_header)
        ie_header = self.ie_bus.emit_response(
            sender=sender,
            receiver=receiver,
            utterance=utterance,
            parent_id=ie_request_message_id,
            confidence_score=confidence,
            state_object_id=f"{self._state_object_id()}:ie:{proposal_id}",
            turn_depth=turn + 1,
            epistemic=epistemic_block,
        )
        return snp_header, ie_header


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
        epistemic_block = make_epistemic_block(
            speech_act=SpeechAct.BELIEF_ASSERTION,
            task_phase=TaskPhase.TRANSITION,
            belief_status=BeliefStatus.ASSERTED,
            uncertainty=round(1.0 - conf, 4),
            scope=supporting_ev,
        )
        snp_header = build_snp_l9_header(
            operation=NegotiationOperation.PROPOSE,
            use_case=self.panel_bus.use_case,
            sender=controller,
            receiver=specialist,
            timestamp_ms=ts,
            proposal_id=proposal_id,
            turn_depth=turn,
            utterance=utterance,
            confidence_score=conf,
            risk_score=round(1.0 - conf, 4),
            state_object_id=self.panel_bus._state_object_id(),
            epistemic=epistemic_block,
        )
        snp_header["snp_payload"] = build_snp_payload(
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
        self.panel_bus.snp_trace.append(snp_header)
        ie_header = self.panel_bus.ie_bus.emit_request(
            sender=controller,
            receiver=specialist,
            utterance=utterance,
            confidence_score=conf,
            state_object_id=f"{self.panel_bus._state_object_id()}:ie:{proposal_id}",
            turn_depth=turn + 1,
            epistemic=epistemic_block,
        )
        return snp_header, ie_header

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
        conf = self._confidence(position)
        key = self._position_key(position)
        verb = "accepts" if operation == NegotiationOperation.ACCEPT else "counter-proposes"
        utterance = f"{specialist} {verb} {key} confidence={conf:.2f}"
        proposal_id = self.panel_bus._proposal_id(turn, specialist)
        ts = int(time.time() * 1000)
        op_str = operation.value if hasattr(operation, "value") else str(operation)
        speech_act, task_phase = infer_snp_epistemic(
            operation=op_str,
            ctrl_position_key=ctrl_position_key,
            member_position_key=key,
            ctrl_conf=ctrl_conf,
            member_conf=conf,
            accept_threshold=accept_threshold,
        )
        belief_status = BeliefStatus.DEFERRED if speech_act == SpeechAct.DELIBERATION_PASS else BeliefStatus.ASSERTED
        pos_dict = position if isinstance(position, dict) else {}
        addresses_ev: List[str] | None = pos_dict.get("addresses_evidence")
        if addresses_ev is None and operation == NegotiationOperation.COUNTER_PROPOSAL:
            addresses_ev = [ctrl_position_key] if ctrl_position_key else None
        epistemic_block = make_epistemic_block(
            speech_act=speech_act,
            task_phase=task_phase,
            belief_status=belief_status,
            uncertainty=round(1.0 - conf, 4),
            addresses_evidence=addresses_ev,
        )
        snp_header = build_snp_l9_header(
            operation=operation,
            use_case=self.panel_bus.use_case,
            sender=specialist,
            receiver=controller,
            timestamp_ms=ts,
            proposal_id=proposal_id,
            turn_depth=turn,
            utterance=utterance,
            confidence_score=conf,
            risk_score=round(1.0 - conf, 4),
            state_object_id=self.panel_bus._state_object_id(),
            epistemic=epistemic_block,
        )
        snp_header["snp_payload"] = build_snp_payload(
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
        )
        self.panel_bus.snp_trace.append(snp_header)
        ie_header = self.panel_bus.ie_bus.emit_response(
            sender=specialist,
            receiver=controller,
            utterance=utterance,
            parent_id=ie_request_message_id,
            confidence_score=conf,
            state_object_id=f"{self.panel_bus._state_object_id()}:ie:{proposal_id}",
            turn_depth=turn + 1,
            epistemic=epistemic_block,
        )
        return snp_header, ie_header

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
            speech_act_v: SpeechAct = SpeechAct.DELIBERATION_PASS
            task_phase_v: TaskPhase = TaskPhase.INTERPERSONAL
            belief_status_v: BeliefStatus = BeliefStatus.DEFERRED
        else:
            speech_act_v = SpeechAct.BELIEF_ASSERTION
            task_phase_v = TaskPhase.ACTION
            belief_status_v = BeliefStatus.ASSERTED
        epistemic_block = make_epistemic_block(
            speech_act=speech_act_v,
            task_phase=task_phase_v,
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
            turn_depth=turn,
            utterance=utterance,
            confidence_score=conf,
            risk_score=round(1.0 - conf, 4),
            state_object_id=self.panel_bus._state_object_id(),
            epistemic=epistemic_block,
        )
        self.panel_bus.snp_trace.append(snp_header)
        ie_header = self.panel_bus.ie_bus.emit_response(
            sender=controller,
            receiver=specialist,
            utterance=utterance,
            parent_id=ie_request_message_id,
            confidence_score=conf,
            state_object_id=f"{self.panel_bus._state_object_id()}:ie:{proposal_id}",
            turn_depth=turn + 1,
            epistemic=epistemic_block,
        )
        return snp_header, ie_header

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
        initial_priors = {mid: self._confidence(specialist_positions[mid]) for mid in member_ids}
        initial_priors[controller_id] = self._confidence(controller_position)

        for round_idx in range(max_rounds):
            tom_predictions: Dict[str, Dict] = {}
            if self.panel_bus.peer_store is not None:
                from sstp.epistemic.tom import predict_belief
                ctrl_key_for_tom = self._position_key(ctrl_pos)
                ctrl_evidence = (ctrl_pos if isinstance(ctrl_pos, dict) else {}).get(
                    "supporting_evidence"
                ) or [ctrl_key_for_tom]
                for mid in member_ids:
                    tom_predictions[mid] = predict_belief(
                        self.panel_bus.peer_store,
                        observer_id=controller_id,
                        subject_id=mid,
                        use_case=self.panel_bus.use_case,
                        concept_id=ctrl_key_for_tom,
                        new_evidence=ctrl_evidence,
                    )

            accept_count = 0
            proposal_ie_ids: Dict[str, str] = {}

            for member_id in member_ids:
                snp_hdr, ie_hdr = self._emit_propose(controller_id, member_id, ctrl_pos, round_idx)
                proposal_ie_ids[member_id] = ie_hdr["message_id"]
                listener_belief = (agent_beliefs or {}).get(member_id, {})
                if member_id in tom_predictions:
                    listener_belief = {**listener_belief, "tom_prediction": tom_predictions[member_id]}
                prop_utt = f"{controller_id} proposes {self._position_key(ctrl_pos)} confidence={self._confidence(ctrl_pos):.2f}"
                self.panel_bus._ie_gate(
                    prop_utt, snp_hdr["message_id"], task_goal,
                    controller_id, member_id, listener_belief,
                )

            countering: List[str] = []
            for member_id in member_ids:
                member_pos = specialist_positions[member_id]
                ctrl_conf = self._confidence(ctrl_pos)
                ctrl_key = self._position_key(ctrl_pos)
                member_key = self._position_key(member_pos)

                tom_pred = tom_predictions.get(member_id, {})
                spec_threshold = accept_threshold
                if tom_pred.get("reliability", 0.0) > 0.3 and tom_pred.get("predicted_confidence", 0.5) < 0.4:
                    spec_threshold = max(0.02, accept_threshold - 0.04)

                same = ctrl_key == member_key
                ctrl_dominates = ctrl_conf >= self._confidence(member_pos) + spec_threshold

                if same or ctrl_dominates:
                    operation = NegotiationOperation.ACCEPT
                    specialist_positions[member_id] = ctrl_pos
                    accept_count += 1
                else:
                    operation = NegotiationOperation.COUNTER_PROPOSAL
                    countering.append(member_id)

                self._emit_specialist_response(
                    specialist=member_id,
                    controller=controller_id,
                    position=specialist_positions[member_id],
                    operation=operation,
                    turn=round_idx,
                    ie_request_message_id=proposal_ie_ids[member_id],
                    ctrl_position_key=ctrl_key,
                    ctrl_conf=ctrl_conf,
                    accept_threshold=accept_threshold,
                )

            if accept_count == n:
                resolution_label = "consensus"
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

        final_turn = max_rounds
        pre_final_positions = dict(specialist_positions)
        winning_position = self._leading_position(specialist_positions)
        win_key = self._position_key(winning_position)
        genuine_accept_count = 0
        for member_id in member_ids:
            _, ie_propose = self._emit_propose(controller_id, member_id, winning_position, final_turn)
            if self._position_key(pre_final_positions.get(member_id, winning_position)) == win_key:
                genuine_accept_count += 1
            self._emit_final_decision(
                controller=controller_id,
                specialist=member_id,
                position=winning_position,
                turn=final_turn,
                ie_request_message_id=ie_propose["message_id"],
                specialist_position=pre_final_positions.get(member_id),
                accept_threshold=accept_threshold,
            )

        if self.panel_bus.epistemic_store is not None:
            snp_trace_snap = list(self.panel_bus.snp_trace)
            total_msgs = len(snp_trace_snap)
            compliance_count = sum(
                1 for h in snp_trace_snap
                if (h.get("epistemic") or {}).get("social_compliance", False)
            )
            scr = round(compliance_count / total_msgs, 4) if total_msgs > 0 else 0.0
            gar = round(genuine_accept_count / len(member_ids), 4) if member_ids else 1.0
            final_posteriors = {mid: self._confidence(specialist_positions[mid]) for mid in member_ids}
            final_posteriors[controller_id] = self._confidence(winning_position)
            mpc = round(sum(final_posteriors.values()) / len(final_posteriors), 4)
            outcome_map = {
                "consensus": "accept", "majority": "accept",
                "timeout_majority": "accept", "stale_majority": "deferred",
            }
            truth = TeamGroundedTruth(
                concept_id=win_key,
                use_case=self.panel_bus.use_case,
                episode_id=self.panel_bus._state_object_id(),
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
            self.panel_bus.epistemic_store.record_convergence(truth)

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
    def _check_termination(positions: Dict[str, Any], n: int) -> str | None:
        keys = [RingNegotiation._position_key(p) for p in positions.values()]
        counts = Counter(keys)
        top_count = counts.most_common(1)[0][1]
        if top_count == n:
            return "consensus"
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
        stale_rounds = 0
        resolution_label = "timeout_majority"

        for round_idx in range(max_rounds):
            prev_keys = {mid: self._position_key(positions[mid]) for mid in member_ids}
            last_snp_id: str | None = None

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
                snp_neg, ie_neg = self.panel_bus.emit_negotiate(
                    sender=sender_id,
                    receiver=receiver_id,
                    utterance=neg_utt,
                    turn=round_idx,
                    confidence=sender_conf,
                    parent_snp_id=last_snp_id,
                )
                last_snp_id = snp_neg["message_id"]

                listener_belief = (agent_beliefs or {}).get(receiver_id, {})
                neg_utt, _ = self.panel_bus._ie_gate(
                    neg_utt, snp_neg["message_id"], task_goal,
                    sender_id, receiver_id, listener_belief,
                )

                same_position = sender_key == receiver_key
                sender_dominates = sender_conf >= receiver_conf + accept_threshold
                if same_position or sender_dominates:
                    operation = NegotiationOperation.ACCEPT
                    if sender_dominates and not same_position:
                        positions[receiver_id] = sender_pos
                    decision_utt = self._utterance(receiver_id, positions[receiver_id], "accept")
                else:
                    operation = NegotiationOperation.REJECT
                    decision_utt = self._utterance(receiver_id, receiver_pos, "reject")

                snp_dec, _ = self.panel_bus.emit_decision(
                    sender=receiver_id,
                    receiver=sender_id,
                    utterance=decision_utt,
                    operation=operation,
                    turn=round_idx,
                    confidence=self._confidence(positions[receiver_id]),
                    ie_request_message_id=ie_neg["message_id"],
                    parent_snp_id=last_snp_id,
                    ctrl_position_key=sender_key,
                    ctrl_conf=sender_conf,
                    accept_threshold=accept_threshold,
                )
                last_snp_id = snp_dec["message_id"]

            result = self._check_termination(positions, n)
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
        return winning_position, resolution_label, list(self.panel_bus.snp_trace)


# Aliases for backward compatibility with existing app code
PanelNegotiationBus = PanelBus
PanelNegotiationStar = StarNegotiation
PanelNegotiationRing = RingNegotiation


__all__ = [
    "IERepairExhausted",
    "PanelBus",
    "StarNegotiation",
    "RingNegotiation",
    # backward-compat aliases
    "PanelNegotiationBus",
    "PanelNegotiationStar",
    "PanelNegotiationRing",
]

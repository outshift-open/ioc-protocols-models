# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
siep/src/negotiation.py — SNP negotiation round-loop engines.

StarNegotiator  — hub-and-spoke: controller proposes → N members respond → commit
RingNegotiator  — ring: each member proposes to the next → rotate until convergence

All wire-message construction is delegated to the emit_* helpers in builder.py.
Each negotiator takes two objects:
  context : NegotiationContext — debate state (stores, IDs, ToM, persistence)
  network : NetworkHandle      — transport (appends headers to network.messages)
"""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from SSTP.subprotocol.siep.src.builder import (
    NegotiationOperation,
    build_snp_l9_header,
    emit_propose,
    emit_specialist_response,
    emit_final_decision,
    emit_negotiate,
    emit_decision,
)
from SSTP.subprotocol.siep.src.epistemic.vocabulary import (
    SpeechAct, EpistemicState, BeliefStatus, make_epistemic_block,
)
from SSTP.subprotocol.siep.src.epistemic.stores import (
    NegotiationMessage,
    NegotiationRound,
    SemanticRule,
    TeamGroundedTruth,
)
from SSTP.subprotocol.cip.src.message import get_part as _get_part
from SSTP.subprotocol.cip.src.grounding import verify_grounding_bilateral


# ── Shared position/confidence helpers ────────────────────────────────────────

def _position_key(pos: Any) -> str:
    if isinstance(pos, dict):
        return str(pos.get("likely_cause") or pos.get("risk_bucket") or pos.get("decision_key") or pos)
    return str(pos)


def _confidence(pos: Any) -> float:
    if isinstance(pos, dict):
        return float(pos.get("confidence") or pos.get("roi_score") or 0.5)
    return 0.5


def _position_utterance(agent_id: str, verb: str, pos: Any) -> str:
    return f"{agent_id} {verb} {_position_key(pos)} confidence={_confidence(pos):.2f}"


def _leading_position(positions: Dict[str, Any]) -> Any:
    by_key: Dict[str, List[Any]] = {}
    for pos in positions.values():
        by_key.setdefault(_position_key(pos), []).append(pos)
    best_key = max(
        by_key,
        key=lambda k: (
            len(by_key[k]),
            round(sum(_confidence(p) for p in by_key[k]) / len(by_key[k]), 4),
            k,
        ),
    )
    return max(by_key[best_key], key=_confidence)


# ── Internal round-state dataclasses ─────────────────────────────────────────

@dataclass
class _HandlerResult:
    agent_id: str
    operation: str
    position: Dict[str, Any]
    exchange_header: Dict[str, Any]
    prop_wire_id: str
    listener_belief: Dict[str, Any]
    forced_accept: bool


@dataclass
class _RoundCtx:
    controller_id: str
    ctrl_pos: Dict[str, Any]
    specialist_positions: Dict[str, Any]
    task_goal: str
    tom_predictions: Dict[str, Any]
    round_idx: int
    accept_threshold: float
    is_tp_panel: bool
    intent_msg_id: str
    prop_headers: Dict[str, Any]


# ── StarNegotiator ────────────────────────────────────────────────────────────

class StarNegotiator:
    """Hub-and-spoke SNP negotiation: controller proposes → N members respond → commit."""

    def __init__(
        self,
        context: Any,
        network: Any,
        panel_name: str,
        pivot_fn: Optional[Callable] = None,
        specialist_l9s: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.context = context
        self.network = network
        self.panel_name = panel_name
        self._pivot_fn = pivot_fn
        self._round_ctx: Optional[_RoundCtx] = None
        self._specialist_l9s: Dict[str, Any] = (
            specialist_l9s if specialist_l9s is not None
            else getattr(network, "specialist_l9s", {})
        )

    def _make_handler(self, member_id: str) -> Callable:
        def _handler(propose_header: Dict[str, Any]) -> _HandlerResult:
            ctx = self._round_ctx
            assert ctx is not None
            ctrl_pos = ctx.ctrl_pos
            member_pos = ctx.specialist_positions[member_id]
            ctrl_key = _position_key(ctrl_pos)
            ctrl_conf = _confidence(ctrl_pos)
            member_key = _position_key(member_pos)

            if self.context.tom_engine is not None:
                listener_belief: Dict[str, Any] = self.context.tom_engine.agent(member_id).belief()
            else:
                listener_belief = {}
            tom_pred = ctx.tom_predictions.get(member_id, {})
            if tom_pred:
                listener_belief = {**listener_belief, "tom_prediction": tom_pred}

            member_conf_for_decision = _confidence(member_pos)
            spec_threshold = ctx.accept_threshold
            if tom_pred.get("reliability", 0.0) > 0.3 and tom_pred.get("predicted_confidence", 0.5) < 0.4:
                spec_threshold = max(0.02, ctx.accept_threshold - 0.04)

            tom_ctx: Dict[str, Any] = {}
            if tom_pred.get("predicted_contingency") == "repair_content":
                tom_ctx["controller_preempts_objection"] = str(tom_pred.get("predicted_response", ""))
            if tom_pred.get("predicted_derailment"):
                tom_ctx["high_derailment_risk"] = True

            prop_wire_id = propose_header["message"]["id"]

            specialist_l9 = self._specialist_l9s.get(member_id)
            if specialist_l9 is not None:
                # Specialist owns its own accept/counter decision via on_debate_round hook.
                from SSTP.subprotocol.siep.src.panel import DebateRoundContext
                debate_ctx = DebateRoundContext(
                    negotiation=self,
                    controller_id=ctx.controller_id,
                    turn=ctx.round_idx,
                    ie_request_message_id=prop_wire_id,
                    ctrl_position_key=ctrl_key,
                    ctrl_conf=ctrl_conf,
                    accept_threshold=ctx.accept_threshold,
                    member_pos=member_pos,
                    ctrl_pos=ctrl_pos,
                    task_goal=ctx.task_goal,
                    tom_ctx=tom_ctx,
                )
                round_ep = specialist_l9.dispatch_debate_round(debate_ctx)
                operation = NegotiationOperation(round_ep.operation) if round_ep.operation else NegotiationOperation.ACCEPT
                updated_pos = round_ep.position if round_ep.position is not None else ctrl_pos
                resp_debate = round_ep.exchange_header or emit_specialist_response(
                    self.context, self.network,
                    specialist=member_id, controller=ctx.controller_id,
                    position=updated_pos, operation=str(operation.value if hasattr(operation, "value") else operation),
                    turn=ctx.round_idx, ie_request_message_id=prop_wire_id,
                    ctrl_position_key=ctrl_key, ctrl_conf=ctrl_conf,
                    accept_threshold=ctx.accept_threshold,
                )
                forced_accept = False
            else:
                # No specialist L9 registered — fall back to confidence heuristic.
                same = ctrl_key == member_key
                ctrl_dominates = ctrl_conf >= member_conf_for_decision + spec_threshold
                if same or ctrl_dominates:
                    operation = NegotiationOperation.ACCEPT
                    updated_pos = ctrl_pos
                else:
                    operation = NegotiationOperation.COUNTER_PROPOSAL
                    updated_pos = member_pos
                forced_accept = ctrl_dominates and not same
                resp_debate = emit_specialist_response(
                    self.context, self.network,
                    specialist=member_id, controller=ctx.controller_id,
                    position=updated_pos, operation=str(operation.value if hasattr(operation, "value") else operation),
                    turn=ctx.round_idx, ie_request_message_id=prop_wire_id,
                    ctrl_position_key=ctrl_key, ctrl_conf=ctrl_conf,
                    accept_threshold=ctx.accept_threshold,
                )

            return _HandlerResult(
                agent_id=member_id,
                operation=operation,
                position=updated_pos,
                exchange_header=resp_debate,
                prop_wire_id=prop_wire_id,
                listener_belief=listener_belief,
                forced_accept=forced_accept or ctx.is_tp_panel,
            )

        return _handler

    def _run_handler(self, member_id: str, propose_header: Dict[str, Any]) -> _HandlerResult:
        handler = self.network.get_handler(member_id)
        if handler is None:
            raise RuntimeError(f"No handler registered for {member_id}")
        return handler(propose_header)

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
    ) -> Tuple[Any, str]:
        n = len(member_ids)
        ctrl_pos = dict(controller_position)
        resolution_label = "timeout_majority"

        _tp_terms = ctrl_pos.get("team_process_terms")
        if _tp_terms:
            _debate_fmt = _tp_terms.get("debate_format", "")
            task_goal = (
                f"Agree team-process governance terms for this session "
                f"(debate format, contingency rules, role assignments). "
                f"{_debate_fmt[:120] if _debate_fmt else ''}".strip()
            )

        ctrl_key_init = _position_key(ctrl_pos)
        concept_id = f"urn:concept:{self.context.use_case}:{ctrl_key_init}"

        _panel_episode_id = self.context._episode_id()
        _all_panel_ids = [controller_id] + list(member_ids)
        _intent_utterance = f"panel:open concept={ctrl_key_init} participants={_all_panel_ids}"
        _ctrl_conf = _confidence(controller_position)
        _intent_rationale = (
            f"Opening SIEP panel on concept '{ctrl_key_init}' with {len(member_ids)} specialists. "
            f"Controller's opening position: '{ctrl_key_init}' at confidence {_ctrl_conf:.2f}. "
            f"Each specialist will respond with their taskwork-declared prior."
        )
        _intent_thought = (
            f"Panel opened on '{ctrl_key_init}'; {len(member_ids)} specialists will now state or challenge this position."
        )
        _intent_utt_part: Dict[str, Any] = {
            "type": "utterance", "location": "inline", "content": _intent_utterance,
            "rationale": _intent_rationale, "thought_summary": _intent_thought,
        }
        _intent_payload_parts: List[Dict[str, Any]] = [_intent_utt_part]
        if controller_position.get("team_process_terms"):
            _intent_payload_parts.append({
                "type": "team_process",
                "location": "inline",
                "content": controller_position["team_process_terms"],
            })
        _intent_header = build_snp_l9_header(
            operation=NegotiationOperation.PROPOSE,
            use_case=self.context.use_case,
            sender=controller_id,
            receiver=None,
            timestamp_ms=int(time.time() * 1000),
            proposal_id=f"intent-{self.context._debate_id[:8]}",
            utterance=_intent_utterance,
            episode_id=_panel_episode_id,
            kind_override="intent",
            payload_parts=_intent_payload_parts,
            recipients=_all_panel_ids,
        )
        self.network.messages.append(_intent_header)

        initial_priors = {mid: _confidence(specialist_positions[mid]) for mid in member_ids}
        initial_priors[controller_id] = _confidence(controller_position)

        _is_tp_panel = bool(ctrl_pos.get("team_process_terms"))
        _intent_msg_id = _intent_header["message"]["id"]

        for _mid in member_ids:
            self.network.register_handler(_mid, self._make_handler(_mid))

        for round_idx in range(max_rounds):
            _round_id = f"{self.context._debate_id}:star:round:{round_idx}"
            _round_positions = {
                **{mid: _confidence(specialist_positions[mid]) for mid in member_ids},
                controller_id: _confidence(ctrl_pos),
            }
            _neg_round = NegotiationRound(
                round_id=_round_id,
                proposal_id=self.context._proposal_id(round_idx, controller_id),
                participants=[controller_id] + list(member_ids),
                individual_positions=_round_positions,
            )
            self.context.round_store.record(_neg_round)

            prop_utt = _position_utterance(controller_id, "proposes", ctrl_pos)
            tom_predictions: Dict[str, Dict] = {}
            if self.context.tom_engine is not None:
                ctrl_agent = self.context.tom_engine.agent(controller_id)
                for mid in member_ids:
                    if hasattr(ctrl_agent, "predict_peer_response"):
                        raw = ctrl_agent.predict_peer_response(mid, prop_utt, task_goal)
                        tom_predictions[mid] = {
                            "predicted_confidence": raw.get("predicted_alignment", 0.5),
                            "reliability": raw.get("confidence", 0.1),
                            "predicted_derailment": raw.get("predicted_derailment", False),
                            "predicted_contingency": raw.get("predicted_contingency", "normal"),
                        }
                    else:
                        from SSTP.subprotocol.siep.src.epistemic.tom import predict_belief
                        ctrl_key_for_tom = _position_key(ctrl_pos)
                        ctrl_evidence = (ctrl_pos if isinstance(ctrl_pos, dict) else {}).get(
                            "supporting_evidence"
                        ) or [ctrl_key_for_tom]
                        tom_predictions[mid] = predict_belief(
                            ctrl_agent,
                            subject_id=mid,
                            concept_id=ctrl_key_for_tom,
                            new_evidence=ctrl_evidence,
                            peer_interaction_store=None,
                        )

            accept_count = 0
            countering: List[str] = []

            propose_headers: Dict[str, Dict[str, Any]] = {}
            for member_id in member_ids:
                if _is_tp_panel:
                    propose_headers[member_id] = _intent_header
                else:
                    debate_hdr = emit_propose(self.context, self.network, controller_id, member_id, ctrl_pos, round_idx)
                    propose_headers[member_id] = debate_hdr
                _prop_id = self.context._proposal_id(round_idx, controller_id)
                _prop_msg = NegotiationMessage(
                    negotiation_id=self.context._debate_id,
                    proposal_id=_prop_id,
                    sender=controller_id,
                    receiver=member_id,
                    operation=NegotiationOperation.PROPOSE,
                    content=ctrl_pos if isinstance(ctrl_pos, dict) else {},
                    timestamp_sec=int(time.time()),
                )
                self.context.debate_store.record(_prop_msg)
                self.context.debate_index.record(_prop_msg)
                _neg_round.messages.append(_prop_msg)

            self._round_ctx = _RoundCtx(
                controller_id=controller_id,
                ctrl_pos=dict(ctrl_pos),
                specialist_positions=dict(specialist_positions),
                task_goal=task_goal,
                tom_predictions=tom_predictions,
                round_idx=round_idx,
                accept_threshold=accept_threshold,
                is_tp_panel=_is_tp_panel,
                intent_msg_id=_intent_msg_id,
                prop_headers=propose_headers,
            )

            handler_results: Dict[str, _HandlerResult] = {}
            with ThreadPoolExecutor(max_workers=len(member_ids)) as _pool:
                _futs = {
                    _pool.submit(self._run_handler, mid, propose_headers[mid]): mid
                    for mid in member_ids
                }
                for _fut, _mid in ((f, _futs[f]) for f in _futs):
                    handler_results[_mid] = _fut.result()

            _prop_id_for_post = self.context._proposal_id(round_idx, controller_id)
            for member_id in member_ids:
                res = handler_results[member_id]
                specialist_positions[member_id] = res.position
                if res.operation == NegotiationOperation.ACCEPT:
                    accept_count += 1
                else:
                    countering.append(member_id)
                _resp_msg = NegotiationMessage(
                    negotiation_id=self.context._debate_id,
                    proposal_id=_prop_id_for_post,
                    sender=member_id,
                    receiver=controller_id,
                    operation=res.operation,
                    content=res.position if isinstance(res.position, dict) else {},
                    timestamp_sec=int(time.time()),
                    status="pending",
                )
                self.context.debate_store.record(_resp_msg)
                self.context.debate_index.record(_resp_msg)
                _neg_round.messages.append(_resp_msg)

            for member_id in member_ids:
                res = handler_results[member_id]
                verb = "accepts" if res.operation == NegotiationOperation.ACCEPT else "counter-proposes"
                response_utt = _position_utterance(member_id, verb, res.position)
                _grounding_hdr = propose_headers[member_id]
                verify_grounding_bilateral(
                    utterance_a=prop_utt,
                    response_b=response_utt,
                    debate_message_id=_grounding_hdr["message"]["id"],
                    task_goal=task_goal,
                    speaker=controller_id,
                    listener=member_id,
                    listener_actual_confidence=_confidence(res.position),
                    listener_belief=res.listener_belief,
                    concept_id=concept_id,
                    forced_accept=res.forced_accept,
                    speaker_epistemic=_grounding_hdr.get("epistemic"),
                    listener_epistemic=res.exchange_header.get("epistemic"),
                    tom_engine=self.context.tom_engine,
                    use_case=self.context.use_case,
                    episode_id=self.context._episode_id(),
                    message_bus=self.network,
                    common_ground_ids=self.context._common_ground_ids,
                )

            if accept_count == n:
                resolution_label = "consensus"
                break
            _all_confs = [_confidence(specialist_positions[mid]) for mid in member_ids]
            _all_confs.append(_confidence(ctrl_pos))
            _mpc_now = sum(_all_confs) / len(_all_confs)
            _max_dev = max(abs(c - _mpc_now) for c in _all_confs)
            if _max_dev <= 0.15:
                resolution_label = "consensus" if accept_count == n else "majority"
                break
            if accept_count > n / 2:
                resolution_label = "majority"
                break
            if not countering:
                resolution_label = "consensus"
                break

            counter_pos_map = {mid: specialist_positions[mid] for mid in countering}
            leading_counter = _leading_position(counter_pos_map)
            leading_counter_key = _position_key(leading_counter)
            leading_counter_count = sum(
                1 for mid in countering
                if _position_key(specialist_positions[mid]) == leading_counter_key
            )
            if leading_counter_count > accept_count:
                if self._pivot_fn is not None:
                    counter_list = [
                        {"agent_id": mid, **specialist_positions[mid]}
                        for mid in countering
                    ]
                    accept_list = [
                        specialist_positions[mid]
                        for mid in member_ids if mid not in countering
                    ]
                    try:
                        ctrl_pos = self._pivot_fn(dict(ctrl_pos), counter_list, accept_list, task_goal)
                    except Exception:
                        ctrl_pos = leading_counter
                else:
                    ctrl_pos = leading_counter

        if resolution_label == "timeout_majority":
            all_positions = {**specialist_positions, controller_id: ctrl_pos}
            keys = [_position_key(p) for p in all_positions.values()]
            top_count = max(Counter(keys).values())
            if top_count > n / 2:
                resolution_label = "timeout_majority"

        winning_position = _leading_position(specialist_positions)
        win_key = _position_key(winning_position)

        if self.context.convergence_store is not None:
            _cons_conf = _confidence(winning_position)
            _star_all = [controller_id] + list(member_ids)
            _star_final = {**{mid: specialist_positions[mid] for mid in member_ids},
                           controller_id: ctrl_pos}
            _genuine = sum(
                1 for _gid in _star_all
                if (_confidence(_star_final[_gid]) >= _cons_conf)
                == (_cons_conf >= initial_priors.get(_gid, 0.5))
            )
            gar = round(_genuine / len(_star_all), 4) if _star_all else 1.0
            final_posteriors = {mid: _confidence(specialist_positions[mid]) for mid in member_ids}
            final_posteriors[controller_id] = _confidence(winning_position)
            scr = 0.0
            mpc = round(sum(final_posteriors.values()) / len(final_posteriors), 4)
            outcome_map = {
                "consensus": "accept", "majority": "accept",
                "timeout_majority": "accept", "stale_majority": "deferred",
                "deferred_to_human": "deferred_to_human", "casting_vote": "casting_vote",
            }
            truth = TeamGroundedTruth(
                concept_id=win_key,
                use_case=self.context.use_case,
                episode_id=self.context._episode_id(),
                participant_ids=[controller_id] + list(member_ids),
                individual_priors=dict(initial_priors),
                individual_posteriors=final_posteriors,
                consensus_posterior=mpc,
                genuine_agreement_ratio=gar,
                social_compliance_ratio=scr,
                common_ground_ids=list(self.context._common_ground_ids),
                outcome=outcome_map.get(resolution_label, "deferred"),
                formed_at_ms=int(time.time() * 1000),
            )
            self.context.convergence_store.record(truth)

            _conv_proposal_id = f"convergence-{self.context._debate_id[:8]}"
            _conv_utterance = (
                f"SIEP convergence: {win_key} → {truth.outcome}"
                f" posterior={truth.consensus_posterior:.4f}"
                f" gar={truth.genuine_agreement_ratio:.4f}"
                f" scr={truth.social_compliance_ratio:.4f}"
            )
            _gar_interp = (
                "unanimous genuine agreement" if truth.genuine_agreement_ratio >= 0.99
                else f"genuine agreement ratio {truth.genuine_agreement_ratio:.2f}"
            )
            _scr_interp = (
                "no social compliance detected" if truth.social_compliance_ratio < 0.05
                else f"social compliance ratio {truth.social_compliance_ratio:.2f} — some deference present"
            )
            _conv_rationale = (
                f"SIEP panel converged on '{win_key}' (outcome: {truth.outcome}) with "
                f"posterior={truth.consensus_posterior:.4f} across {len(truth.participant_ids)} participants. "
                f"GAR={truth.genuine_agreement_ratio:.4f} ({_gar_interp}); "
                f"SCR={truth.social_compliance_ratio:.4f} ({_scr_interp}). "
                f"This becomes the team-grounded consensus posterior for this concept."
            )
            _conv_thought = (
                f"Panel closed: '{win_key}' accepted at posterior {truth.consensus_posterior:.4f} "
                f"with GAR={truth.genuine_agreement_ratio:.4f}, SCR={truth.social_compliance_ratio:.4f}."
            )
            _conv_utt_part: Dict[str, Any] = {
                "type": "utterance", "location": "inline", "content": _conv_utterance,
                "rationale": _conv_rationale, "thought_summary": _conv_thought,
            }
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
                use_case=self.context.use_case,
                sender=controller_id,
                receiver=None,
                timestamp_ms=truth.formed_at_ms,
                proposal_id=_conv_proposal_id,
                utterance=_conv_utterance,
                episode_id=truth.episode_id,
                kind_override="commit:converged",
                payload_parts=[
                    _conv_utt_part,
                    {"type": "snp-convergence", "location": "inline", "content": _snp_convergence},
                ],
                recipients=list(truth.participant_ids),
            )
            self.network.messages.append(convergence_header)

            _conv_concept_id = f"urn:concept:{self.context.use_case}:{win_key}"

            if (
                self.context.semantic_rule_store is not None
                and truth.outcome == "accept"
            ):
                provenance_weight = round(
                    (1.0 - truth.social_compliance_ratio) * truth.genuine_agreement_ratio, 4
                )
                rule = SemanticRule(
                    concept_id=_conv_concept_id,
                    use_case=self.context.use_case,
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
                self.context.semantic_rule_store.record(rule)
                _rule_utterance = (
                    f"team agreed: {win_key} "
                    f"(posterior={truth.consensus_posterior:.2f}, "
                    f"gar={truth.genuine_agreement_ratio:.2f}, "
                    f"scr={truth.social_compliance_ratio:.2f})"
                )
                _rule_header = build_snp_l9_header(
                    operation=NegotiationOperation.ACCEPT,
                    use_case=self.context.use_case,
                    sender=controller_id,
                    receiver=None,
                    timestamp_ms=truth.formed_at_ms + 1,
                    proposal_id=f"rule-{self.context._debate_id[:8]}",
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
                self.network.messages.append(_rule_header)

        if self.context.persistence_path:
            self.context._save_cross_episode_state(self.context.persistence_path)

        return winning_position, resolution_label


# ── RingNegotiator ────────────────────────────────────────────────────────────

class RingNegotiator:
    """Ring-topology semantic negotiation among N panel members."""

    def __init__(self, context: Any, network: Any, panel_name: str) -> None:
        self.context = context
        self.network = network
        self.panel_name = panel_name

    @staticmethod
    def _check_termination(positions: Dict[str, Any], n: int, accept_threshold: float = 0.6) -> Optional[str]:
        keys = [_position_key(p) for p in positions.values()]
        counts = Counter(keys)
        top_count = counts.most_common(1)[0][1]
        if top_count == n:
            return "consensus"
        _confs = [_confidence(p) for p in positions.values()]
        _frac_above = sum(1 for c in _confs if c >= accept_threshold) / len(_confs) if _confs else 0.0
        if _frac_above >= accept_threshold:
            return "majority"
        if top_count > n / 2:
            return "majority"
        return None

    def run(
        self,
        member_ids: List[str],
        initial_positions: Dict[str, Any],
        accept_threshold: float = 0.1,
        max_rounds: int = 3,
        task_goal: str = "",
        agent_beliefs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, str]:
        n = len(member_ids)
        positions = dict(initial_positions)
        stale_rounds = 0
        resolution_label = "timeout_majority"

        first_init_key = _position_key(initial_positions[member_ids[0]]) if member_ids else ""
        concept_id = f"urn:concept:{self.context.use_case}:{first_init_key}"

        _ring_episode_id = self.context._episode_id()
        _ring_intent_utterance = f"panel:open concept={first_init_key} participants={list(member_ids)}"
        _ring_intent_header = build_snp_l9_header(
            operation=NegotiationOperation.NEGOTIATE,
            use_case=self.context.use_case,
            sender=member_ids[0] if member_ids else "ring",
            receiver=None,
            timestamp_ms=int(time.time() * 1000),
            proposal_id=f"intent-{self.context._debate_id[:8]}",
            utterance=_ring_intent_utterance,
            episode_id=_ring_episode_id,
            kind_override="intent",
            payload_parts=[{"type": "utterance", "location": "inline", "content": _ring_intent_utterance}],
        )
        self.network.messages.append(_ring_intent_header)

        initial_priors = {mid: _confidence(initial_positions[mid]) for mid in member_ids}

        for round_idx in range(max_rounds):
            prev_keys = {mid: _position_key(positions[mid]) for mid in member_ids}
            last_debate_id: Optional[str] = None

            _ring_round_id = f"{self.context._debate_id}:ring:round:{round_idx}"
            _ring_round = NegotiationRound(
                round_id=_ring_round_id,
                proposal_id=self.context._proposal_id(round_idx, member_ids[0] if member_ids else "ring"),
                participants=list(member_ids),
                individual_positions={mid: _confidence(positions[mid]) for mid in member_ids},
            )
            self.context.round_store.record(_ring_round)

            for i in range(n):
                sender_id = member_ids[i]
                receiver_id = member_ids[(i + 1) % n]
                sender_pos = positions[sender_id]
                receiver_pos = positions[receiver_id]

                sender_conf = _confidence(sender_pos)
                receiver_conf = _confidence(receiver_pos)
                sender_key = _position_key(sender_pos)
                receiver_key = _position_key(receiver_pos)

                neg_utt = _position_utterance(sender_id, "proposes", sender_pos)
                debate_neg = emit_negotiate(
                    self.context,
                    self.network,
                    sender=sender_id,
                    receiver=receiver_id,
                    utterance=neg_utt,
                    turn=round_idx,
                    confidence=sender_conf,
                    parent_debate_id=last_debate_id,
                    epistemic_state=EpistemicState.TASKWORK if round_idx == 0 else EpistemicState.TEAM_PROCESS,
                )
                last_debate_id = debate_neg["message"]["id"]
                _neg_prop_id = _get_part(debate_neg, "snp").get("proposal_id") or debate_neg["message"]["id"]
                _neg_msg = NegotiationMessage(
                    negotiation_id=self.context._debate_id,
                    proposal_id=_neg_prop_id,
                    sender=sender_id,
                    receiver=receiver_id,
                    operation=NegotiationOperation.NEGOTIATE,
                    content=sender_pos if isinstance(sender_pos, dict) else {},
                    timestamp_sec=int(time.time()),
                )
                self.context.debate_store.record(_neg_msg)
                self.context.debate_index.record(_neg_msg)
                _ring_round.messages.append(_neg_msg)

                if self.context.tom_engine is not None:
                    listener_belief = self.context.tom_engine.agent(receiver_id).belief()
                    sender_agent = self.context.tom_engine.agent(sender_id)
                    if hasattr(sender_agent, "predict_peer_response"):
                        raw = sender_agent.predict_peer_response(receiver_id, neg_utt, task_goal)
                        listener_belief = {**listener_belief, "tom_prediction": {
                            "predicted_confidence": raw.get("predicted_alignment", 0.5),
                            "reliability": raw.get("confidence", 0.1),
                        }}
                else:
                    listener_belief = (agent_beliefs or {}).get(receiver_id, {})

                same_position = sender_key == receiver_key
                sender_dominates = sender_conf >= receiver_conf + accept_threshold
                if same_position or sender_dominates:
                    operation = NegotiationOperation.ACCEPT
                    if sender_dominates and not same_position:
                        positions[receiver_id] = sender_pos
                    decision_utt = _position_utterance(receiver_id, "accepts", positions[receiver_id])
                else:
                    operation = NegotiationOperation.REJECT
                    decision_utt = _position_utterance(receiver_id, "rejects", receiver_pos)

                debate_dec = emit_decision(
                    self.context,
                    self.network,
                    sender=receiver_id,
                    receiver=sender_id,
                    utterance=decision_utt,
                    operation=operation,
                    turn=round_idx,
                    confidence=_confidence(positions[receiver_id]),
                    ie_request_message_id=debate_neg["message"]["id"],
                    parent_debate_id=last_debate_id,
                    ctrl_position_key=sender_key,
                    ctrl_conf=sender_conf,
                    accept_threshold=accept_threshold,
                )
                last_debate_id = debate_dec["message"]["id"]
                _dec_msg = NegotiationMessage(
                    negotiation_id=self.context._debate_id,
                    proposal_id=_neg_prop_id,
                    sender=receiver_id,
                    receiver=sender_id,
                    operation=operation,
                    content=positions[receiver_id] if isinstance(positions[receiver_id], dict) else {},
                    timestamp_sec=int(time.time()),
                )
                self.context.debate_store.record(_dec_msg)
                self.context.debate_index.record(_dec_msg)
                _ring_round.messages.append(_dec_msg)

                verify_grounding_bilateral(
                    utterance_a=neg_utt,
                    response_b=decision_utt,
                    debate_message_id=debate_neg["message"]["id"],
                    task_goal=task_goal,
                    speaker=sender_id,
                    listener=receiver_id,
                    listener_actual_confidence=_confidence(positions[receiver_id]),
                    listener_belief=listener_belief,
                    concept_id=concept_id,
                    forced_accept=sender_dominates and not same_position,
                    speaker_epistemic=debate_neg.get("epistemic"),
                    listener_epistemic=debate_dec.get("epistemic"),
                    tom_engine=self.context.tom_engine,
                    use_case=self.context.use_case,
                    episode_id=self.context._episode_id(),
                    message_bus=self.network,
                    common_ground_ids=self.context._common_ground_ids,
                )

            result = self._check_termination(positions, n, accept_threshold=accept_threshold)
            if result:
                resolution_label = result
                break

            new_keys = {mid: _position_key(positions[mid]) for mid in member_ids}
            if new_keys == prev_keys:
                stale_rounds += 1
                if stale_rounds >= 2:
                    resolution_label = "stale_majority"
                    break
            else:
                stale_rounds = 0

        winning_position = _leading_position(positions)
        win_key = _position_key(winning_position)

        if self.context.convergence_store is not None:
            _ring_cons_conf = _confidence(winning_position)
            _ring_genuine = sum(
                1 for mid in member_ids
                if (_confidence(positions[mid]) >= _ring_cons_conf)
                == (_ring_cons_conf >= initial_priors.get(mid, 0.5))
            )
            gar = round(_ring_genuine / len(member_ids), 4) if member_ids else 1.0
            final_posteriors = {mid: _confidence(positions[mid]) for mid in member_ids}
            scr = 0.0
            mpc = round(sum(final_posteriors.values()) / len(final_posteriors), 4) if final_posteriors else 0.5
            outcome_map = {
                "consensus": "accept", "majority": "accept",
                "timeout_majority": "accept", "stale_majority": "deferred",
            }
            formed_at = int(time.time() * 1000)
            truth = TeamGroundedTruth(
                concept_id=win_key,
                use_case=self.context.use_case,
                episode_id=self.context._episode_id(),
                participant_ids=list(member_ids),
                individual_priors=dict(initial_priors),
                individual_posteriors=final_posteriors,
                consensus_posterior=mpc,
                genuine_agreement_ratio=gar,
                social_compliance_ratio=scr,
                common_ground_ids=list(self.context._common_ground_ids),
                outcome=outcome_map.get(resolution_label, "deferred"),
                formed_at_ms=formed_at,
            )
            self.context.convergence_store.record(truth)

            _ring_sender = member_ids[0] if member_ids else "ring"
            _ring_conv_proposal_id = f"convergence-{self.context._debate_id[:8]}"
            _ring_conv_utterance = (
                f"SIEP ring convergence: {win_key} → {truth.outcome}"
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
                use_case=self.context.use_case,
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
            self.network.messages.append(convergence_header)

            _conv_concept_id = f"urn:concept:{self.context.use_case}:{win_key}"

            if self.context.semantic_rule_store is not None and truth.outcome == "accept":
                provenance_weight = round(
                    (1.0 - truth.social_compliance_ratio) * truth.genuine_agreement_ratio, 4
                )
                rule = SemanticRule(
                    concept_id=_conv_concept_id,
                    use_case=self.context.use_case,
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
                self.context.semantic_rule_store.record(rule)
                _ring_sender = member_ids[0] if member_ids else "ring-controller"
                _rule_utterance_r = (
                    f"team agreed: {win_key} "
                    f"(posterior={truth.consensus_posterior:.2f}, "
                    f"gar={truth.genuine_agreement_ratio:.2f}, "
                    f"scr={truth.social_compliance_ratio:.2f})"
                )
                _rule_header_r = build_snp_l9_header(
                    operation=NegotiationOperation.ACCEPT,
                    use_case=self.context.use_case,
                    sender=_ring_sender,
                    receiver=None,
                    timestamp_ms=truth.formed_at_ms + 1,
                    proposal_id=f"rule-{self.context._debate_id[:8]}",
                    utterance=_rule_utterance_r,
                    episode_id=truth.episode_id,
                    kind_override="knowledge",
                    topic=f"urn:concept:{self.context.use_case}:{win_key}",
                    epistemic=make_epistemic_block(
                        speech_act=SpeechAct.ASSERTION,
                        epistemic_state=EpistemicState.TASKWORK,
                    ),
                    payload_parts=[
                        {"type": "utterance", "location": "inline", "content": _rule_utterance_r},
                    ],
                )
                self.network.messages.append(_rule_header_r)

        if self.context.persistence_path:
            self.context._save_cross_episode_state(self.context.persistence_path)

        return winning_position, resolution_label


__all__ = [
    "StarNegotiator",
    "RingNegotiator",
]

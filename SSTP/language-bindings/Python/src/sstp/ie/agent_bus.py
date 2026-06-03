# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/ie/agent_bus.py — Domain-agnostic per-episode L9 message bus.

AgentBus is parameterised at construction with use_case and sensitivity
so any application can instantiate it without subclassing.

All interactions are peer-wise peer_turn events.  There is no privileged
coordinator role in IE.  Task delegation uses speech_act=task_handoff at
epistemic_state=grounding; results use speech_act=belief_assertion at
epistemic_state=taskwork; errors use speech_act=help_request at
epistemic_state=grounding.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sstp.epistemic import SpeechAct, EpistemicState, BeliefStatus, make_epistemic_block
from sstp.epistemic.vocabulary import RepairReason
from sstp.ie.grounding import diagnose_repair_reason
from sstp.ie.l9 import build_l9_header


class AgentBus:
    """Per-episode L9 message bus shared by all agents in a session.

    Parameters
    ----------
    use_case:    domain label written into every L9 header (e.g. "healthcare")
    sensitivity: sensitivity label; defaults to "internal"
    """

    def __init__(
        self,
        run_id: str,
        conversation_id: str,
        use_case: str,
        sensitivity: str = "internal",
    ) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.use_case = use_case
        self.sensitivity = sensitivity
        self.messages: List[Dict[str, Any]] = []
        self._seq_counters: Dict[str, int] = {}
        self._current_phase: str = "taskwork"   # taskwork | grounding | team_process
        self._taskwork_store: Optional[Any] = None   # TaskworkStore; injected by app

    def _next_sequence(self, actor_id: str) -> Dict[str, Any]:
        n = self._seq_counters.get(actor_id, 0)
        self._seq_counters[actor_id] = n + 1
        return {"counter": n, "actor_id": actor_id}

    def emit_peer_turn(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        speech_act: SpeechAct,
        epistemic_state: EpistemicState,
        parent_id: str | None = None,
        episode_id: str | None = None,
        turn_depth: int | None = None,
        kind_override: str | None = None,
        error: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """Emit a peer_turn with explicit epistemic annotation.

        All agent-to-agent interactions are peer_turns.  The speech_act and
        epistemic_state carries the role of this turn — delegation, result, error,
        or social repair — without privileging either party.
        """
        header = build_l9_header(
            use_case=self.use_case,
            event_type="peer_turn",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=utterance,
            parent_ids=[parent_id] if parent_id else None,
            episode_id=episode_id,
            turn_depth=turn_depth,
            kind_override=kind_override,
            epistemic=make_epistemic_block(
                speech_act=speech_act,
                epistemic_state=epistemic_state,
            ),
            state_sequence=self._next_sequence(sender),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": utterance},
            ],
        )
        if error is not None:
            header["error"] = error
        self.messages.append(header)
        return header

    def emit_request(self, *, sender: str, receiver: str, utterance: str,
                     episode_id: str | None = None, turn_depth: int | None = None,
                     epistemic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   episode_id=episode_id, turn_depth=turn_depth)

    def emit_response(self, *, sender: str, receiver: str, utterance: str,
                      parent_id: str | None = None, episode_id: str | None = None,
                      turn_depth: int | None = None,
                      epistemic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   parent_id=parent_id, episode_id=episode_id, turn_depth=turn_depth)

    def emit_error(self, *, sender: str, receiver: str, error_type: str, error_message: str,
                   traceback: str | None = None, parent_id: str | None = None,
                   epistemic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        error_record: Dict[str, Any] = {"type": error_type, "message": error_message}
        if traceback is not None:
            error_record["traceback"] = traceback
        return self.emit_peer_turn(sender=sender, receiver=receiver,
                                   utterance=f"error:{error_type}",
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   parent_id=parent_id, error=error_record)

    def emit_semantic_repair(
        self,
        *,
        sender: str,
        receiver: str,
        target_message_id: str,
        repair_reason: RepairReason,
        target_epistemic: Optional[Dict[str, Any]] = None,
        episode_id: str | None = None,
        turn_depth: int | None = None,
    ) -> Dict[str, Any]:
        repair_concept_id = (target_epistemic or {}).get("concept_id")
        _utterance = f"repair_required:reason={repair_reason.value}:target={target_message_id}"
        header = build_l9_header(
            use_case=self.use_case,
            event_type="repair_required",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            parent_ids=[target_message_id],
            episode_id=episode_id,
            turn_depth=turn_depth,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                belief_status=BeliefStatus.CHALLENGED,
                concept_id=repair_concept_id,
            ),
            state_sequence=self._next_sequence(sender),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
            ],
        )
        header["repair"] = {
            "target_message_id": target_message_id,
            "repair_reason": repair_reason.value,
        }
        self.messages.append(header)
        return header

    def check_and_repair(
        self,
        *,
        sender: str,
        prior_message_epistemic: Optional[Dict[str, Any]],
        response_epistemic: Optional[Dict[str, Any]],
        response_message_id: str,
        episode_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        reason = diagnose_repair_reason(prior_message_epistemic, response_epistemic)
        if reason is None:
            return None
        return self.emit_semantic_repair(
            sender=sender,
            receiver=response_message_id,
            target_message_id=response_message_id,
            repair_reason=reason,
            target_epistemic=prior_message_epistemic,
            episode_id=episode_id,
        )

    def emit_epistemic_clarification(
        self,
        *,
        sender: str,
        receiver: str,
        target_message_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        _utterance = f"epistemic_clarification:{reason}"
        header = build_l9_header(
            use_case=self.use_case,
            event_type="epistemic_clarification",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            parent_ids=[target_message_id],
            state_sequence=self._next_sequence(sender),
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                belief_status=BeliefStatus.DEFERRED,
            ),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
            ],
        )
        self.messages.append(header)
        return header



    def advance_phase(self, new_phase: str, episode_id: str = "") -> None:
        """Advance the epistemic phase. Progression is one-way: taskwork→grounding→team_process.

        On taskwork→grounding transition, locks all TaskworkState entries for the episode.
        """
        _ORDER = ("taskwork", "grounding", "team_process")
        if new_phase not in _ORDER:
            raise ValueError(f"Unknown phase: {new_phase!r}")
        if _ORDER.index(new_phase) <= _ORDER.index(self._current_phase):
            raise ValueError(
                f"Cannot regress phase from {self._current_phase!r} to {new_phase!r}"
            )
        if self._current_phase == "taskwork" and new_phase == "grounding":
            if self._taskwork_store is not None and episode_id:
                for state in self._taskwork_store.all_for_episode(episode_id):
                    last_msg = self.messages[-1]["message"]["id"] if self.messages else ""
                    self._taskwork_store.lock(
                        state.agent_id, state.concept_id, episode_id, last_msg
                    )
        self._current_phase = new_phase

    def emit_initial_prior(
        self,
        *,
        sender: str,
        receiver: str,
        taskwork_state: Any,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Emit a initial_prior turn carrying independent taskwork reasoning.

        Uses IEPayload with taskwork=IETaskworkBlock(...) — same payload type
        as peer_turn, distinguished by epistemic_state=taskwork in the L9 header
        and the presence of the taskwork block. grounding is empty (no peer to
        be contingent on for a prior declaration).
        """
        from sstp.ie.message import IEPayload, IEUtteranceBlock, IEGroundingBlock, IEBeliefBlock, IETaskworkBlock
        payload = IEPayload(
            utterance=IEUtteranceBlock(
                content=f"prior:{taskwork_state.concept_id}:{taskwork_state.posterior:.4f}",
                evidence=[taskwork_state.concept_id],
                addresses_evidence=[],
                inferred_intent="initial_prior",
                turn_depth=0,
            ),
            grounding=IEGroundingBlock(),
            belief=IEBeliefBlock(
                prior=taskwork_state.prior,
                posterior=taskwork_state.posterior,
                revision_cause="semantic_memory",
            ),
            taskwork=IETaskworkBlock(
                findings=[
                    {"finding_id": f.finding_id, "value": f.value, "source": f.source}
                    for f in (taskwork_state.findings or [])
                ],
                likelihoods=list(taskwork_state.likelihoods or []),
                reasoning_summary=taskwork_state.reasoning_summary or "",
            ),
        )
        header = build_l9_header(
            use_case=self.use_case,
            event_type="initial_prior",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=payload.utterance.content,
            episode_id=episode_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TASKWORK,
                concept_id=taskwork_state.concept_id,
            ),
            state_sequence=self._next_sequence(sender),
            payload_parts=[
                {"type": "utterance", "location": "inline",
                 "content": payload.utterance.content},
                {"type": "ie", "location": "inline",
                 "content": payload.to_dict()},
            ],
        )
        self.messages.append(header)
        return header

    def emit_process_proposal(
        self,
        *,
        sender: str,
        receiver: str,
        agreement: Any,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Emit a process_proposed turn carrying a team process agreement.

        Payload is a ProcessPayload — coordinator, participants, role assignments.
        No IEPayload here: process negotiation precedes grounding; it is not grounding.
        """
        from sstp.ie.message import ProcessPayload
        payload = ProcessPayload(
            coordinator_id=agreement.coordinator_id,
            participant_ids=list(agreement.participant_ids),
            role_assignments=[
                {"agent_id": ra.agent_id, "role": ra.role, "responsible_for": list(ra.responsible_for)}
                for ra in agreement.role_assignments
            ],
        )
        content = f"process_proposal:coordinator={agreement.coordinator_id}"
        header = build_l9_header(
            use_case=self.use_case,
            event_type="process_proposed",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=content,
            episode_id=episode_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TEAM_PROCESS,
            ),
            state_sequence=self._next_sequence(sender),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": content},
                {"type": "process", "location": "inline", "content": payload.to_dict()},
            ],
        )
        self.messages.append(header)
        return header

    def emit_process_acceptance(
        self,
        *,
        sender: str,
        receiver: str,
        parent_id: str,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Emit a process_accepted peer_turn acknowledging a role assignment."""
        _utterance = f"process_accepted:by={sender}"
        header = build_l9_header(
            use_case=self.use_case,
            event_type="process_accepted",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            parent_ids=[parent_id],
            episode_id=episode_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TEAM_PROCESS,
            ),
            state_sequence=self._next_sequence(sender),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
            ],
        )
        self.messages.append(header)
        return header

    def emit_process_challenge(
        self,
        *,
        sender: str,
        receiver: str,
        parent_id: str,
        reason: str,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Emit a process_challenged peer_turn disputing a role assignment."""
        _utterance = f"process_challenged:reason={reason}"
        header = build_l9_header(
            use_case=self.use_case,
            event_type="process_challenged",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            parent_ids=[parent_id],
            episode_id=episode_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.CHALLENGE,
                epistemic_state=EpistemicState.TEAM_PROCESS,
            ),
            state_sequence=self._next_sequence(sender),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
            ],
        )
        self.messages.append(header)
        return header

    def receive_peer_turn(
        self,
        envelope: Dict[str, Any],
        *,
        replica: Optional[Any] = None,
        belief_store: Optional[Any] = None,
        common_ground_store: Optional[Any] = None,
        use_case: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Process an incoming peer_turn: verify grounding, update stores, flag repair.

        1. Extract the IE payload from the envelope.
        2. Run contingency_check() against the prior turn's concept_ids.
        3. Write contingency_verified + contingency_score back into the payload.
        4. Apply the (updated) header + payload to the replica.
        5. If verified:  write BeliefRevision to belief_store; write CommonGround record.
        6. If not verified: emit repair_required; return the repair header.

        Returns None if grounding verified; returns the repair_required header if not.
        """
        from sstp.ie.grounding import contingency_check, diagnose_repair_reason
        from sstp.epistemic.vocabulary import RepairReason
        from sstp.ie.message import get_part

        header = {k: v for k, v in envelope.items() if k != "payload"}
        ie_content = get_part(envelope, "ie")

        grounding = ie_content.get("grounding") or {}
        utterance = ie_content.get("utterance") or {}
        belief = ie_content.get("belief") or {}

        # Build epistemic dicts for contingency_check
        prior_turn_mid = grounding.get("responds_to")
        prior_epistemic: Optional[Dict[str, Any]] = None
        prior_ie_concept_ids: List[str] = []
        prior_ie_addresses_evidence: List[str] = []
        if prior_turn_mid and replica is not None:
            for e in getattr(replica, "_entries", []):
                if e.message_id == prior_turn_mid:
                    prior_epistemic = e.epistemic or {}
                    prior_ie_concept_ids = list(getattr(e, "ie_concept_ids", []))
                    prior_ie_addresses_evidence = list(getattr(e, "ie_addresses_evidence", []))
                    break

        current_ie_concept_ids = list(utterance.get("evidence") or utterance.get("concept_ids") or [])
        current_ie_addresses_evidence = list(utterance.get("addresses_evidence") or [])
        current_epistemic = (header.get("epistemic") or {})

        # Run grounding check using payload concept fields (with header fallback)
        verified, score = contingency_check(
            prior_epistemic, current_epistemic,
            a_ie_concept_ids=prior_ie_concept_ids,
            a_ie_addresses_evidence=prior_ie_addresses_evidence,
            b_ie_concept_ids=current_ie_concept_ids,
            b_ie_addresses_evidence=current_ie_addresses_evidence,
        )

        # Write result back into IE content grounding block
        ie_content = dict(ie_content)
        ie_content["grounding"] = {
            **grounding,
            "contingency_verified": verified,
            "contingency_score": score,
        }

        # Apply to replica
        if replica is not None:
            replica.apply(header, payload=ie_content)

        if verified:
            # concept_id is in the L9 header epistemic block (not in belief)
            ep_concept_id = (header.get("epistemic") or {}).get("concept_id", "")
            # Update BeliefState
            if belief_store is not None and ep_concept_id:
                from sstp.epistemic.stores import BeliefRevision
                sender = (header.get("actors") or [{}])[0].get("id", "unknown")
                ep_id = (header.get("message") or {}).get("episode", "")
                revision = BeliefRevision(
                    cause=belief.get("revision_cause") or "grounded_argument",
                    confidence_before=float(belief.get("prior", 0.5)),
                    confidence_after=float(belief.get("posterior", 0.5)),
                    caused_by_agent=None,
                    argument_concept_ids=list(utterance.get("evidence") or utterance.get("concept_ids", [])),
                    episode_id=ep_id,
                )
                belief_store.record_revision(
                    sender,
                    ep_concept_id,
                    use_case or self.use_case,
                    ep_id,
                    revision,
                    new_status="asserted",
                    new_public_confidence=float(belief.get("posterior", 0.5)),
                )

            # Write CommonGround
            if common_ground_store is not None:
                from sstp.epistemic.stores import CommonGround
                sender = (header.get("actors") or [{}])[0].get("id", "unknown")
                ep = header.get("epistemic") or {}
                prior_sender = ""
                if prior_epistemic and prior_turn_mid and replica is not None:
                    for e in getattr(replica, "_entries", []):
                        if e.message_id == prior_turn_mid:
                            prior_sender = e.sender
                            break
                cg = CommonGround(
                    holder_id=prior_sender,
                    confirmer_id=sender,
                    concept_id=ep_concept_id,
                    use_case=use_case or self.use_case,
                    episode_id=(header.get("message") or {}).get("episode", ""),
                    grounding_confidence=score,
                    holder_confidence=float(belief.get("prior", 0.5)),
                    confirmer_confidence=float(belief.get("posterior", 0.5)),
                    contingency_verified=True,
                    speech_acts=[ep.get("speech_act", "")],
                    grounding_message_ids=[prior_turn_mid or "", header["message"]["id"]],
                    formed_at_ms=int(time.time() * 1000),
                )
                common_ground_store.record(cg)
            return None

        else:
            # Emit repair_required
            repair_reason = diagnose_repair_reason(prior_epistemic, current_epistemic)
            if repair_reason is None:
                repair_reason = RepairReason.GROUNDING_FAILURE
            sender_id = self.run_id  # the receiving agent emits the repair
            return self.emit_semantic_repair(
                sender=sender_id,
                receiver=(header.get("actors") or [{}])[0].get("id", "unknown"),
                target_message_id=header["message"]["id"],
                repair_reason=repair_reason,
                target_epistemic=current_epistemic,
                episode_id=(header.get("message") or {}).get("episode"),
            )


__all__ = ["AgentBus"]

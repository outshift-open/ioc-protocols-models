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
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

from sstp.epistemic import SpeechAct, EpistemicState, BeliefStatus, make_epistemic_block
from sstp.epistemic.vocabulary import RepairReason
from sstp.ie.grounding import diagnose_repair_reason
from sstp.ie.l9 import build_l9_header


class ProtocolViolation(RuntimeError):
    """Raised when application code attempts to emit a lifecycle kind directly.

    ``intent`` and ``commit:*`` messages may only be emitted by the
    subprotocol layer (IE Episode API, SNP panel bus, TaskSession).
    Use the appropriate high-level method instead of passing
    ``kind_override`` to ``emit_peer_turn``.
    """


def get_ie_repair(header: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the ie-repair payload content from an L9 header, or None."""
    for part in header.get("payload") or []:
        if part.get("type") == "ie-repair":
            return part.get("content")
    return None


def _is_lifecycle_kind(kind_override: str) -> bool:
    """Return True if *kind_override* is a protected lifecycle kind."""
    base = kind_override.split(":")[0]
    return base in ("intent", "commit")


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
        self._current_phase: str = "taskwork"   # taskwork | grounding | team_process
        self._taskwork_store: Optional[Any] = None   # TaskworkStore; injected by app
        self._protocol_context: bool = False  # True only inside _lifecycle_emit()

    @contextmanager
    def _lifecycle_emit(self) -> Generator[None, None, None]:
        """Context manager that permits lifecycle kind_overrides (intent, commit).

        Only internal subprotocol methods should use this.  Application code
        must never acquire this context directly — use the named public methods
        (open_session, close_session, emit_repair_resolved, Episode.close(), etc.).
        """
        prev = self._protocol_context
        self._protocol_context = True
        try:
            yield
        finally:
            self._protocol_context = prev

    @property
    def snp_trace(self) -> List[Dict[str, Any]]:
        """Filtered view of messages containing only SNP messages."""
        return [m for m in self.messages if m.get("subprotocol") == "SNP"]

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
        kind_override: str | None = None,
        error: Optional[Dict[str, Any]] = None,
        epistemic: Optional[Dict[str, Any]] = None,
        topic: "str | None" = None,
        ie_payload: "Any | None" = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """Emit a peer_turn with explicit epistemic annotation.

        ``epistemic`` overrides the auto-derived epistemic block.
        ``ie_payload`` is an IEPayload instance; when provided its dict is
        added as payload[type=ie] alongside the utterance part.

        Raises :exc:`ProtocolViolation` if ``kind_override`` is a lifecycle
        kind (``intent`` or ``commit:*``) and the call originates outside the
        subprotocol layer.  Use the named methods (``Episode.close()``,
        ``emit_repair_resolved()``, ``_emit_episode_open()``, etc.) instead.
        """
        if kind_override and _is_lifecycle_kind(kind_override) and not self._protocol_context:
            raise ProtocolViolation(
                f"kind_override={kind_override!r} is a lifecycle kind and may only be "
                f"set by the subprotocol layer. Use Episode.close(), emit_repair_resolved(), "
                f"or the TaskSession open/close methods instead."
            )
        _epistemic = epistemic or make_epistemic_block(
            speech_act=speech_act,
            epistemic_state=epistemic_state,
        )
        _payload_parts: List[Dict[str, Any]] = [
            {"type": "utterance", "location": "inline", "content": utterance},
        ]
        if ie_payload is not None:
            _payload_parts.append(
                {"type": "ie", "location": "inline", "content": ie_payload.to_dict()}
            )
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
            kind_override=kind_override,
            epistemic=_epistemic,
            topic=topic,
            payload_parts=_payload_parts,
        )
        if error is not None:
            header["error"] = error
        self.messages.append(header)
        return header

    def emit_request(self, *, sender: str, receiver: str, utterance: str,
                     episode_id: str | None = None,
                     epistemic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   episode_id=episode_id)

    def emit_response(self, *, sender: str, receiver: str, utterance: str,
                      parent_id: str | None = None, episode_id: str | None = None,
                      epistemic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.emit_peer_turn(sender=sender, receiver=receiver, utterance=utterance,
                                   speech_act=SpeechAct.ASSERTION, epistemic_state=EpistemicState.GROUNDING,
                                   parent_id=parent_id, episode_id=episode_id)

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
        repair_reason: "RepairReason | str",
        target_epistemic: Optional[Dict[str, Any]] = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        from sstp.ie.l9 import get_topic
        _repair_topic = get_topic({"topic": None, "epistemic": target_epistemic}) if target_epistemic else None
        _reason_str = repair_reason.value if isinstance(repair_reason, RepairReason) else str(repair_reason)
        _utterance = f"repair_required:reason={_reason_str}:target={target_message_id}"
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
            topic=_repair_topic,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                belief_status=BeliefStatus.CHALLENGED,
            ),

            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
            ],
        )
        header["payload"].append({
            "type": "ie-repair",
            "location": "inline",
            "content": {
                "target_message_id": target_message_id,
                "repair_reason": _reason_str,
            },
        })
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
        concept_id: str,
        prior: float,
        posterior: float,
        evidence: "List[str] | None" = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Emit an initial_prior turn declaring the sender's independent belief.

        Carries IEPayload (utterance + grounding + belief) only.
        Taskwork internals (findings, likelihoods) are agent-internal state
        and do not appear on the wire.
        """
        from sstp.ie.message import IEPayload, IEUtteranceBlock, IEGroundingBlock, IEBeliefBlock
        _utterance = f"initial_prior:{concept_id}:{posterior:.4f}"
        payload = IEPayload(
            utterance=IEUtteranceBlock(
                evidence=list(evidence or [concept_id]),
                addresses_evidence=[],
                turn_depth=0,
            ),
            grounding=IEGroundingBlock(),
            belief=IEBeliefBlock(
                prior=prior,
                posterior=posterior,
                revision_cause="semantic_memory",
            ),
        )
        header = build_l9_header(
            use_case=self.use_case,
            event_type="initial_prior",
            sender=sender,
            receiver=receiver,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            episode_id=episode_id,
            topic=concept_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TASKWORK,
            ),

            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
                {"type": "ie", "location": "inline", "content": payload.to_dict()},
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
        # The message being responded to is in L9 message.parents (not in IE grounding)
        parents = (header.get("message") or {}).get("parents") or []
        prior_turn_mid = parents[0] if parents else None
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
            from sstp.ie.l9 import get_topic
            ep_concept_id = get_topic(header) or ""
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
                    speech_acts=[ep.get("message_act", "")],
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


    # ── Semantic high-level emit methods ─────────────────────────────────────
    # These hide all protocol mechanics from the application.
    # The app passes domain arguments; the bus derives kind, subkind,
    # speech_act, state, belief_status, and payload structure.

    def emit_task_assignment(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        parent_id: str | None = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Orchestrator assigns a task to an agent.

        kind=exchange, subprotocol=IE, state=team_process, speech_act=assertion.
        """
        return self.emit_peer_turn(
            sender=sender,
            receiver=receiver,
            utterance=utterance,
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.TEAM_PROCESS,
            parent_id=parent_id,
            episode_id=episode_id,
        )

    def emit_taskwork_result(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        concept_id: str | None = None,
        posterior: float | None = None,
        parent_id: str | None = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Agent returns its independent taskwork result to the orchestrator.

        kind=exchange, subprotocol=IE, state=taskwork, speech_act=assertion.
        Carries concept_id and uncertainty derived from posterior.
        """
        from sstp.epistemic.vocabulary import make_epistemic_block, BeliefStatus
        _uncertainty = round(1.0 - posterior, 4) if posterior is not None else 0.5
        epistemic = make_epistemic_block(
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.TASKWORK,
            belief_status=BeliefStatus.ASSERTED,
            uncertainty=_uncertainty,
        )
        return self.emit_peer_turn(
            sender=sender,
            receiver=receiver,
            utterance=utterance,
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.TASKWORK,
            parent_id=parent_id,
            episode_id=episode_id,
            epistemic=epistemic,
            topic=concept_id,
        )

    def _emit_episode_open(
        self,
        *,
        coordinator: str,
        subject: str,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Open a coordination session with an intent message.

        kind=intent, subprotocol=IE, state=team_process.
        Internal — call via TaskSession.open_session() or Episode.open().
        """
        _utterance = f"session:open subject={subject}"
        with self._lifecycle_emit():
            return self.emit_peer_turn(
                sender=coordinator,
                receiver=coordinator,
                utterance=_utterance,
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TEAM_PROCESS,
                kind_override="intent",
                episode_id=episode_id,
            )

    def _emit_episode_close(
        self,
        *,
        coordinator: str,
        subject: str,
        accepted: bool,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Close a coordination session.

        kind=commit, subkind=converged (accepted=True) or rejected (accepted=False).
        Internal — call via TaskSession.close_session() or Episode.close().
        """
        _outcome = "commit:converged" if accepted else "commit:rejected"
        _utterance = f"session:close subject={subject} accepted={accepted}"
        with self._lifecycle_emit():
            return self.emit_peer_turn(
                sender=coordinator,
                receiver=coordinator,
                utterance=_utterance,
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TEAM_PROCESS,
                kind_override=_outcome,
                episode_id=episode_id,
            )

    def emit_repair_resolved(
        self,
        *,
        sender: str,
        receiver: str,
        utterance: str,
        parent_id: str | None = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Emit a commit:resolved closing a contingency branch after repair.

        The sender is the agent that verified the repair (the listener in the
        original exchange).  This is the only public path to emit commit:resolved
        from outside the Episode API.
        """
        with self._lifecycle_emit():
            return self.emit_peer_turn(
                sender=sender,
                receiver=receiver,
                utterance=utterance,
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                parent_id=parent_id,
                episode_id=episode_id,
                kind_override="commit:resolved",
            )

    def emit_knowledge_rule(
        self,
        *,
        coordinator: str,
        concept_id: str,
        posterior: float,
        gar: float,
        scr: float,
        provenance_weight: float,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Announce a new knowledge rule produced by this session.

        kind=knowledge, subprotocol=IE, state=taskwork.
        """
        from sstp.epistemic.vocabulary import make_epistemic_block, BeliefStatus
        from sstp.ie.l9 import build_l9_header as _build
        _utterance = (
            f"rule_update:{concept_id}"
            f":posterior={posterior:.4f}"
            f":gar={gar:.4f}"
            f":scr={scr:.4f}"
            f":provenance_weight={provenance_weight:.4f}"
        )
        header = _build(
            use_case=self.use_case,
            event_type="rule_update",
            sender=coordinator,
            receiver=coordinator,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            episode_id=episode_id,
            topic=concept_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TASKWORK,
                belief_status=BeliefStatus.ASSERTED,
            ),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
            ],
        )
        self.messages.append(header)
        return header

    def emit_grounding_turn(
        self,
        *,
        speaker: str,
        listener: str,
        utterance: str,
        concept_id: str | None = None,
        prior: float = 0.5,
        posterior: float = 0.5,
        revision_cause: str = "grounded_argument",
        evidence: "List[str] | None" = None,
        addresses_evidence: "List[str] | None" = None,
        turn_depth: int = 0,
        parent_id: str | None = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """Agent asserts a position in a pairwise IE grounding exchange.

        kind=exchange, subprotocol=IE, state=grounding.
        Constructs IEPayload internally — the app passes domain values only.
        """
        from sstp.ie.message import IEPayload, IEUtteranceBlock, IEGroundingBlock, IEBeliefBlock
        from sstp.epistemic.vocabulary import make_epistemic_block, BeliefStatus
        ie_payload = IEPayload(
            utterance=IEUtteranceBlock(
                evidence=list(evidence or []),
                addresses_evidence=list(addresses_evidence or []),
                turn_depth=turn_depth,
            ),
            grounding=IEGroundingBlock(),
            belief=IEBeliefBlock(
                prior=prior,
                posterior=posterior,
                revision_cause=revision_cause,
            ),
        )
        epistemic = make_epistemic_block(
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.GROUNDING,
            belief_status=BeliefStatus.ASSERTED,
            uncertainty=round(1.0 - posterior, 4),
        )
        return self.emit_peer_turn(
            sender=speaker,
            receiver=listener,
            utterance=utterance,
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.GROUNDING,
            parent_id=parent_id,
            episode_id=episode_id,
            topic=concept_id,
            epistemic=epistemic,
            ie_payload=ie_payload,
        )


    # ── L9 Episode private protocol emitters ─────────────────────────────────
    # Called by sstp.l9.episode — not part of the public AgentBus API.

    def _emit_intent(
        self,
        *,
        sender: str,
        receiver: "str | None",
        subject: str,
        episode_id: str | None = None,
        team_prior: "Dict[str, Any] | None" = None,
    ) -> Dict[str, Any]:
        """kind=intent — open a coordination episode (L9 episode API)."""
        _utterance = f"episode:open subject={subject}"
        payload_parts: List[Dict[str, Any]] = [
            {"type": "utterance", "location": "inline", "content": _utterance},
        ]
        if team_prior:
            payload_parts.append({"type": "team_prior", "location": "inline", "content": team_prior})
        from sstp.ie.l9 import build_l9_header as _build
        from sstp.epistemic.vocabulary import make_epistemic_block, BeliefStatus
        with self._lifecycle_emit():
            header = _build(
                use_case=self.use_case,
                event_type="peer_turn",
                sender=sender,
                receiver=receiver or sender,
                timestamp_ms=int(time.time() * 1000),
                sensitivity=self.sensitivity,
                utterance=_utterance,
                episode_id=episode_id,
                kind_override="intent",
                epistemic=make_epistemic_block(
                    speech_act=SpeechAct.ASSERTION,
                    epistemic_state=EpistemicState.TEAM_PROCESS,
                    belief_status=BeliefStatus.ASSERTED,
                ),
                payload_parts=payload_parts,
            )
        self.messages.append(header)
        return header

    def _emit_exchange_ready(
        self,
        *,
        speaker: str,
        listener: "str | None",
        utterance: str,
        posterior: float,
        concept_id: str | None = None,
        evidence: "List[str] | None" = None,
        addresses_evidence: "List[str] | None" = None,
        parent_id: str | None = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """kind=exchange with subkind=ready — final argument + done signal."""
        from sstp.epistemic.vocabulary import make_epistemic_block, BeliefStatus
        epistemic = make_epistemic_block(
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.GROUNDING,
            belief_status=BeliefStatus.ASSERTED,
            uncertainty=round(1.0 - posterior, 4),
        )
        return self.emit_peer_turn(
            sender=speaker,
            receiver=listener or speaker,
            utterance=utterance,
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.GROUNDING,
            parent_id=parent_id,
            episode_id=episode_id,
            kind_override="exchange:ready",
            topic=concept_id,
            epistemic=epistemic,
        )

    def _emit_ready(
        self,
        *,
        sender: str,
        receiver: "str | None",
        posterior: float,
        concept_id: str | None = None,
        parent_id: str | None = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """kind=commit, subkind=ready — standalone done signal, no further content."""
        from sstp.epistemic.vocabulary import make_epistemic_block, BeliefStatus
        _utterance = f"ready posterior={posterior:.4f}"
        epistemic = make_epistemic_block(
            speech_act=SpeechAct.ASSERTION,
            epistemic_state=EpistemicState.GROUNDING,
            belief_status=BeliefStatus.ASSERTED,
            uncertainty=round(1.0 - posterior, 4),
        )
        with self._lifecycle_emit():
            return self.emit_peer_turn(
                sender=sender,
                receiver=receiver or sender,
                utterance=_utterance,
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.GROUNDING,
                parent_id=parent_id,
                episode_id=episode_id,
                kind_override="commit:ready",
                topic=concept_id,
                epistemic=epistemic,
            )

    def _emit_knowledge_announcement(
        self,
        *,
        sender: str,
        concept_id: str,
        posterior: float,
        gar: float,
        scr: float,
        provenance_weight: float,
        parent_id: str | None = None,
        episode_id: str | None = None,
    ) -> Dict[str, Any]:
        """kind=knowledge — announce a convergence result (L9 episode API)."""
        from sstp.epistemic.vocabulary import make_epistemic_block, BeliefStatus
        from sstp.ie.l9 import build_l9_header as _build
        _utterance = (
            f"knowledge:{concept_id}"
            f":posterior={posterior:.4f}"
            f":gar={gar:.4f}"
            f":scr={scr:.4f}"
            f":provenance_weight={provenance_weight:.4f}"
        )
        header = _build(
            use_case=self.use_case,
            event_type="peer_turn",
            sender=sender,
            receiver=sender,
            timestamp_ms=int(time.time() * 1000),
            sensitivity=self.sensitivity,
            utterance=_utterance,
            parent_ids=[parent_id] if parent_id else None,
            episode_id=episode_id,
            kind_override="knowledge",
            topic=concept_id,
            epistemic=make_epistemic_block(
                speech_act=SpeechAct.ASSERTION,
                epistemic_state=EpistemicState.TASKWORK,
                belief_status=BeliefStatus.ASSERTED,
                uncertainty=round(1.0 - posterior, 4),
            ),
            payload_parts=[
                {"type": "utterance", "location": "inline", "content": _utterance},
                {"type": "knowledge", "location": "inline", "content": {
                    "concept_id": concept_id,
                    "posterior": posterior,
                    "gar": gar,
                    "scr": scr,
                    "provenance_weight": provenance_weight,
                }},
            ],
        )
        self.messages.append(header)
        return header


__all__ = ["AgentBus"]

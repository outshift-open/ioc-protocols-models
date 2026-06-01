from __future__ import annotations

import time
from typing import Any, Dict, List

from sstp.ie.l9 import build_l9_header


class InteractionProtocolAdapter:
    PROTOCOL_NAME = "interaction_engine_protocol"
    VERSION = "1.0.0"

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_receiver_from_utterance(utterance: str) -> str | None:
        if not utterance or "," not in utterance:
            return None
        receiver = utterance.split(",", 1)[0].strip()
        if not receiver or " " in receiver:
            return None
        return receiver

    @classmethod
    def _normalize_contingency(cls, value: Any) -> str:
        allowed = {
            "normal_alignment",
            "repair_alignment",
            "expedite_decision",
            "cost_tradeoff",
            "none",
        }
        candidate = str(value) if value is not None else "none"
        if candidate not in allowed:
            return "none"
        return candidate

    @classmethod
    def _normalize_alignment(cls, value: Any, fallback_task_goal: str | None = None) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {
                "task_goal": fallback_task_goal,
                "aligned": None,
                "alignment_score": None,
                "disagreement_score": None,
                "rationale": None,
            }

        aligned = value.get("aligned")
        if not isinstance(aligned, bool):
            aligned = None

        alignment_score = cls._as_float(value.get("alignment_score"))
        if alignment_score is not None:
            alignment_score = max(0.0, min(1.0, alignment_score))

        disagreement_score = cls._as_float(value.get("disagreement_score"))
        if disagreement_score is None:
            disagreement_score = cls._as_float(value.get("price_sensitivity_disagreement"))
        if disagreement_score is None:
            disagreement_score = cls._as_float(value.get("cost_disagreement"))
        if disagreement_score is not None:
            disagreement_score = max(0.0, min(1.0, disagreement_score))

        rationale = value.get("rationale")
        if rationale is not None:
            rationale = str(rationale)

        task_goal = value.get("task_goal", fallback_task_goal)
        if task_goal is not None:
            task_goal = str(task_goal)

        return {
            "task_goal": task_goal,
            "aligned": aligned,
            "alignment_score": alignment_score,
            "disagreement_score": disagreement_score,
            "rationale": rationale,
        }

    @classmethod
    def _normalize_tom_snapshot(cls, value: Any) -> Dict[str, Any]:
        source = value if isinstance(value, dict) else {}

        trust = cls._as_float(source.get("trust"))
        urgency = cls._as_float(source.get("urgency"))
        safety_focus = cls._as_float(source.get("safety_focus"))
        budget_confidence = cls._as_float(source.get("budget_confidence"))

        sensitivity = cls._as_float(source.get("price_or_cost_sensitivity"))
        if sensitivity is None:
            sensitivity = cls._as_float(source.get("price_sensitivity"))
        if sensitivity is None:
            sensitivity = cls._as_float(source.get("cost_sensitivity"))

        intent_follow = cls._as_float(source.get("intent_or_follow_through"))
        if intent_follow is None:
            intent_follow = cls._as_float(source.get("intent_buy_prob"))
        if intent_follow is None:
            intent_follow = cls._as_float(source.get("follow_through_prob"))

        return {
            "trust": trust,
            "urgency": urgency,
            "safety_focus": safety_focus,
            "budget_confidence": budget_confidence,
            "price_or_cost_sensitivity": sensitivity,
            "intent_or_follow_through": intent_follow,
        }

    @classmethod
    def _build_event(
        cls,
        *,
        domain: str,
        run_id: str,
        conversation_id: str,
        phase: str,
        event_type: str,
        sender: str,
        receiver: str | None,
        turn_depth: int | None,
        utterance: str,
        inferred_intent: str,
        contingency_mode: str,
        out_of_bound: bool,
        repaired: bool,
        derailment_cause: str | None,
        alignment: Dict[str, Any] | None,
        repair_required: bool,
        repair_strategy: str | None,
        trigger_message_id: str | None,
        tom_snapshot: Dict[str, Any] | None,
        timestamp_ms: int,
        l9_header: Dict[str, Any] | None = None,
        extra: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        normalized_alignment = alignment
        if normalized_alignment is None:
            normalized_alignment = {
                "task_goal": None,
                "aligned": None,
                "alignment_score": None,
                "disagreement_score": None,
                "rationale": None,
            }

        l9 = l9_header if isinstance(l9_header, dict) else build_l9_header(
            use_case=domain,
            event_type=event_type,
            sender=sender,
            receiver=receiver,
            timestamp_ms=max(0, timestamp_ms),
            turn_depth=turn_depth,
            utterance=utterance,
        )

        ie_payload: Dict[str, Any] = {
            "run_id": run_id,
            "conversation_id": conversation_id,
            "domain": domain,
            "protocol": cls.PROTOCOL_NAME,
            "phase": phase,
            "event_type": event_type,
            "sender": sender,
            "receiver": receiver,
            "message": {
                "turn_depth": turn_depth,
                "utterance": utterance,
                "inferred_intent": inferred_intent,
                "contingency_mode": cls._normalize_contingency(contingency_mode),
                "out_of_bound": out_of_bound,
                "repaired": repaired,
                "derailment_cause": derailment_cause,
            },
            "alignment": normalized_alignment,
            "repair": {
                "required": repair_required,
                "strategy": repair_strategy,
                "trigger_message_id": trigger_message_id,
            },
            "tom_snapshot": tom_snapshot
            if tom_snapshot is not None
            else {
                "trust": None,
                "urgency": None,
                "safety_focus": None,
                "budget_confidence": None,
                "price_or_cost_sensitivity": None,
                "intent_or_follow_through": None,
            },
            "timestamp_ms": max(0, timestamp_ms),
        }

        if extra:
            ie_payload.update(extra)

        return {**l9, "payload": ie_payload}

    @classmethod
    def _find_out_of_bound_event(
        cls,
        out_of_bound_events: List[Dict[str, Any]],
        *,
        depth: int | None,
        speaker: str,
        listener: str | None,
        utterance: str,
    ) -> Dict[str, Any] | None:
        for candidate in out_of_bound_events:
            if not isinstance(candidate, dict):
                continue
            candidate_depth = cls._as_int(candidate.get("depth"))
            if depth is not None and candidate_depth is not None and candidate_depth != depth:
                continue
            if str(candidate.get("speaker", "")) != speaker:
                continue
            if listener is not None and str(candidate.get("listener", "")) != listener:
                continue
            if str(candidate.get("utterance", "")) != utterance:
                continue
            return candidate
        return None

    @classmethod
    def adapt_episode(
        cls,
        *,
        use_case: str,
        episode: Any,
        run_id: str | None = None,
        conversation_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        normalized = str(use_case).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "health_care": "healthcare",
            "healthcare2": "healthcare",
            "hospital3": "healthcare",
            "hospital_3": "healthcare",
            "hospital_tom": "healthcare",
            "travel_agent": "travel",
            "collective_validated_truth": "travel",
        }
        normalized = aliases.get(normalized, normalized)

        if normalized == "healthcare":
            return cls.adapt_healthcare_episode(episode, run_id=run_id, conversation_id=conversation_id)

        if normalized == "fmc":
            return cls.adapt_fmc_episode(episode, run_id=run_id, conversation_id=conversation_id)

        if normalized == "travel":
            events = cls.adapt_travel_episode(episode, conversation_id=conversation_id)
            if run_id:
                for event in events:
                    event["run_id"] = run_id
            return events

        if normalized in {"semantic_negotiation", "snp", "negotiation"}:
            # episode is expected to be a dict with an "sstp_message_trace" key,
            # or an object with that attribute.
            trace = (
                episode.get("sstp_message_trace")
                if isinstance(episode, dict)
                else getattr(episode, "sstp_message_trace", [])
            )
            session_id = (
                episode.get("session_id")
                if isinstance(episode, dict)
                else getattr(episode, "session_id", "unknown")
            ) or "unknown"
            return cls.adapt_snp_session(
                sstp_message_trace=trace or [],
                session_id=session_id,
                use_case=normalized,
                run_id=run_id,
                conversation_id=conversation_id,
            )

        raise ValueError(
            "Unsupported use_case for InteractionProtocolAdapter.adapt_episode: "
            f"{use_case}. Supported use cases: healthcare, fmc, travel, semantic_negotiation"
        )

    @classmethod
    def adapt_snp_session(
        cls,
        *,
        sstp_message_trace: List[Dict[str, Any]],
        session_id: str = "unknown",
        use_case: str = "semantic_negotiation",
        run_id: str | None = None,
        conversation_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Convert an SNP negotiation's SSTP message trace into IE event dicts.

        Iterates *sstp_message_trace* (the chronological list of serialised
        ``SSTPNegotiateMessage``, ``QueryMessage``, ``DelegationMessage``, and
        ``SSTPCommitMessage`` dicts produced by ``BatchCallbackRunner``) and
        maps each entry to a fully-structured Interaction Engine event.

        Mapping rules
        -------------
        - ``kind="negotiate"`` server→agent (``origin.actor_id="negotiation-server"``)
          → ``phase="peer_dialogue"``, ``event_type="peer_turn"``
        - ``kind="negotiate"`` agent→server (all other origins or no origin)
          → ``phase="peer_dialogue"``, ``event_type="peer_turn"``
        - ``kind="contingency"``
          → ``phase="peer_dialogue"``, ``event_type="repair_required"``
        - ``kind="commit"``
          → ``phase="peer_dialogue"``, ``event_type="repair_applied"``
        - ``kind="convergence"``
          → ``phase="coordination"``, ``event_type="decision_emitted"``
        - ``kind="query"`` (legacy)
          → ``phase="peer_dialogue"``, ``event_type="repair_required"``
        - ``kind="delegation"`` (legacy)
          → ``phase="peer_dialogue"``, ``event_type="repair_applied"``
        - IE protocol dicts (``protocol="interaction_engine_protocol"``)
          → passed through as-is (already adapted by the pipeline)
        - First message in trace (the ``/initiate`` request, if present)
          → ``phase="ingest"``, ``event_type="turn_ingested"``

        Parameters
        ----------
        sstp_message_trace:
            List of message dicts as stored in
            ``NegotiationSession.sstp_message_trace`` or
            ``NegotiationResult.sstp_message_trace``.
        session_id:
            The negotiation session identifier.
        use_case:
            Domain label for the IE events (default: ``"semantic_negotiation"``).
        run_id:
            Optional run identifier.  Defaults to ``"snp-<session_id>"``.
        conversation_id:
            Optional conversation identifier.  Defaults to *session_id*.
        """
        _run_id = run_id or f"snp-{session_id}"
        _conv_id = conversation_id or session_id
        _ts_base = int(time.time() * 1000)
        _seq = 0

        def _next_ts() -> int:
            nonlocal _seq
            _seq += 1
            return _ts_base + _seq

        _KIND_TO_PHASE_EVENT = {
            # New 5-value vocabulary
            "contingency": ("peer_dialogue", "repair_required"),
            "commit:converged": ("peer_dialogue", "repair_applied"),
            "commit:abort":     ("peer_dialogue", "repair_applied"),
            "convergence": ("coordination", "decision_emitted"),
            # Legacy kinds (backward compat)
            "query":       ("peer_dialogue", "repair_required"),
            "delegation":  ("peer_dialogue", "repair_applied"),
        }

        events: List[Dict[str, Any]] = []

        for idx, msg in enumerate(sstp_message_trace):
            if not isinstance(msg, dict):
                continue

            # Pass-through: already a fully-structured IE event.
            # Detected by the presence of "phase" in the payload (all IE events
            # carry a phase; raw SNP trace messages do not).
            _payload = msg.get("payload")
            if (
                isinstance(_payload, dict) and "phase" in _payload
            ) or msg.get("protocol") == "interaction_engine_protocol":
                events.append(msg)
                continue

            kind = msg.get("kind", "negotiate")
            origin = msg.get("origin") or {}
            actor_id = origin.get("actor_id", "") if isinstance(origin, dict) else ""
            payload = msg.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            action = payload.get("action", "")
            round_num = payload.get("round")
            participant_id = payload.get("participant_id", actor_id or "unknown")
            sem_ctx = msg.get("semantic_context") or {}
            if not isinstance(sem_ctx, dict):
                sem_ctx = {}

            # Determine utterance: summarise offer or action.
            offer = payload.get("current_offer") or payload.get("offer")
            if offer and isinstance(offer, dict):
                utterance = "offer:" + ",".join(f"{k}={v}" for k, v in sorted(offer.items()))
            elif action:
                utterance = action
            else:
                utterance = kind

            # First message is the ingest event (the /initiate request).
            if idx == 0 and kind == "negotiate" and not actor_id.startswith("negotiation"):
                phase, event_type = "ingest", "turn_ingested"
            elif kind in _KIND_TO_PHASE_EVENT:
                phase, event_type = _KIND_TO_PHASE_EVENT[kind]
            else:
                # negotiate — outbound or reply
                phase, event_type = "peer_dialogue", "peer_turn"

            # Derive sender/receiver from origin and payload.
            if actor_id == "negotiation-server":
                sender = "negotiation-server"
                receiver = participant_id or None
            else:
                sender = participant_id or actor_id or "unknown"
                receiver = "negotiation-server"

            # Extract existing l9_header from the message if present.
            existing_l9 = msg.get("l9_header")

            events.append(
                cls._build_event(
                    domain=use_case,
                    run_id=_run_id,
                    conversation_id=_conv_id,
                    phase=phase,
                    event_type=event_type,
                    sender=sender,
                    receiver=receiver,
                    turn_depth=None,
                    utterance=utterance,
                    inferred_intent=action or kind,
                    contingency_mode="none",
                    out_of_bound=(event_type == "repair_required"),
                    repaired=(event_type == "repair_applied"),
                    derailment_cause=None,
                    alignment=None,
                    repair_required=(event_type == "repair_required"),
                    repair_strategy=None,
                    trigger_message_id=None,
                    tom_snapshot=None,
                    timestamp_ms=_next_ts(),
                    l9_header=existing_l9 if isinstance(existing_l9, dict) else None,
                    extra={"snp_payload": payload} if payload else None,
                )
            )

        return events

    @classmethod
    def adapt_healthcare_episode(
        cls,
        episode: Any,
        run_id: str | None = None,
        conversation_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        episode_id = str(getattr(episode, "episode_id", "unknown"))
        run_identifier = run_id or f"health-{episode_id}"
        conversation_identifier = conversation_id or str(getattr(episode, "patient_id", episode_id))

        turns = list(getattr(episode, "turns", []))
        peer_interactions = list(getattr(episode, "peer_interactions", []))
        inter_agent_tom = getattr(episode, "inter_agent_tom", {})
        if not isinstance(inter_agent_tom, dict):
            inter_agent_tom = {}

        tom_trace = list(getattr(episode, "tom_trace", []))
        final_tom = cls._normalize_tom_snapshot(tom_trace[-1] if tom_trace else {})

        unix_ts = cls._as_int(getattr(episode, "timestamp_unix", None)) or int(time.time())
        base_ts = unix_ts * 1000
        fallback_step = 0

        def next_ts() -> int:
            nonlocal fallback_step
            fallback_step += 1
            return base_ts + fallback_step

        events: List[Dict[str, Any]] = []

        peer_message_numbers = {
            cls._as_int(item.get("message_number"))
            for item in peer_interactions
            if isinstance(item, dict)
        }
        peer_message_numbers.discard(None)

        last_peer_turn_message_id: str | None = None

        for turn in turns:
            turn_msg_num = cls._as_int(getattr(turn, "message_number", None))
            if turn_msg_num is not None and turn_msg_num in peer_message_numbers:
                continue

            events.append(
                cls._build_event(
                    domain="healthcare",
                    run_id=run_identifier,
                    conversation_id=conversation_identifier,
                    phase="ingest",
                    event_type="turn_ingested",
                    sender=str(getattr(turn, "speaker", "unknown")),
                    receiver=None,
                    turn_depth=None,
                    utterance=str(getattr(turn, "utterance", "")),
                    inferred_intent=str(getattr(turn, "inferred_intent", "unknown")),
                    contingency_mode="none",
                    out_of_bound=False,
                    repaired=bool(getattr(turn, "repaired", False)),
                    derailment_cause=None,
                    alignment=None,
                    repair_required=False,
                    repair_strategy=None,
                    trigger_message_id=None,
                    tom_snapshot=final_tom,
                    timestamp_ms=cls._as_int(getattr(turn, "timestamp_ms", None)) or next_ts(),
                )
            )

        for interaction in peer_interactions:
            if not isinstance(interaction, dict):
                continue

            # Support new wire format {**l9_header, "payload": {...app_fields...}} and
            # old flat format {...app_fields..., "l9_header": header} transparently.
            _p = interaction["payload"] if isinstance(interaction.get("payload"), dict) else interaction
            _l9 = (
                {k: v for k, v in interaction.items() if k != "payload"}
                if "payload" in interaction
                else (interaction.get("l9_header") or None)
            )

            interaction_type = str(_p.get("type", ""))

            if interaction_type == "peer_turn":
                alignment = cls._normalize_alignment(_p.get("alignment"), _p.get("task_goal"))
                events.append(
                    cls._build_event(
                        domain="healthcare",
                        run_id=run_identifier,
                        conversation_id=conversation_identifier,
                        phase="peer_dialogue",
                        event_type="peer_turn",
                        sender=str(_p.get("speaker", "unknown")),
                        receiver=str(_p.get("listener", "")) or None,
                        turn_depth=cls._as_int(_p.get("depth")),
                        utterance=str(_p.get("utterance", "")),
                        inferred_intent="peer_message",
                        contingency_mode=str(_p.get("contingency", "none")),
                        out_of_bound=bool(_p.get("out_of_bound", False)),
                        repaired=False,
                        derailment_cause=(
                            str(_p.get("derailment_cause"))
                            if _p.get("derailment_cause") is not None
                            else None
                        ),
                        alignment=alignment,
                        repair_required=bool(_p.get("repair_required", False)),
                        repair_strategy=None,
                        trigger_message_id=None,
                        tom_snapshot=final_tom,
                        timestamp_ms=next_ts(),
                        l9_header=_l9,
                    )
                )
                last_peer_turn_message_id = events[-1]["message_id"]

            elif interaction_type == "repair_required":
                trigger = _p.get("trigger", {})
                if not isinstance(trigger, dict):
                    trigger = {}
                events.append(
                    cls._build_event(
                        domain="healthcare",
                        run_id=run_identifier,
                        conversation_id=conversation_identifier,
                        phase="peer_dialogue",
                        event_type="repair_required",
                        sender=str(_p.get("speaker", "unknown")),
                        receiver=str(_p.get("listener", "")) or None,
                        turn_depth=cls._as_int(_p.get("depth")),
                        utterance=str(trigger.get("utterance", "")),
                        inferred_intent="repair_required",
                        contingency_mode=str(trigger.get("contingency", "repair_alignment")),
                        out_of_bound=True,
                        repaired=False,
                        derailment_cause=(
                            str(trigger.get("derailment_cause"))
                            if trigger.get("derailment_cause") is not None
                            else None
                        ),
                        alignment=None,
                        repair_required=True,
                        repair_strategy=(
                            str(_p.get("repair_strategy"))
                            if _p.get("repair_strategy") is not None
                            else None
                        ),
                        trigger_message_id=last_peer_turn_message_id,
                        tom_snapshot=final_tom,
                        timestamp_ms=next_ts(),
                        l9_header=_l9,
                    )
                )

            elif interaction_type == "peer_repair":
                triggered_by = _p.get("triggered_by", {})
                if not isinstance(triggered_by, dict):
                    triggered_by = {}
                events.append(
                    cls._build_event(
                        domain="healthcare",
                        run_id=run_identifier,
                        conversation_id=conversation_identifier,
                        phase="peer_dialogue",
                        event_type="repair_applied",
                        sender=str(_p.get("speaker", "unknown")),
                        receiver=str(_p.get("listener", "")) or None,
                        turn_depth=cls._as_int(_p.get("depth")),
                        utterance=str(_p.get("utterance", "")),
                        inferred_intent="repair",
                        contingency_mode="repair_alignment",
                        out_of_bound=False,
                        repaired=True,
                        derailment_cause=(
                            str(_p.get("derailment_cause"))
                            if _p.get("derailment_cause") is not None
                            else None
                        ),
                        alignment=cls._normalize_alignment(_p.get("alignment"), _p.get("task_goal")),
                        repair_required=False,
                        repair_strategy=(
                            str(_p.get("repair_strategy"))
                            if _p.get("repair_strategy") is not None
                            else None
                        ),
                        trigger_message_id=triggered_by.get("message_id") or last_peer_turn_message_id,
                        tom_snapshot=final_tom,
                        timestamp_ms=next_ts(),
                        l9_header=_l9,
                    )
                )

        # Insert agent-bus L9 messages (agent_request / agent_response) emitted
        # during node execution.  These are already fully-formed IEP envelopes
        # produced by HealthcareAgentBus, so they are passed through as-is.
        agent_messages = list(getattr(episode, "agent_messages", []) or [])
        for msg in agent_messages:
            if isinstance(msg, dict):
                events.append(msg)

        care_plan = getattr(episode, "care_plan", None)
        fused_alignment = inter_agent_tom.get("fused_alignment") if isinstance(inter_agent_tom, dict) else {}
        events.append(
            cls._build_event(
                domain="healthcare",
                run_id=run_identifier,
                conversation_id=conversation_identifier,
                phase="coordination",
                event_type="decision_emitted",
                sender="coordinator",
                receiver=None,
                turn_depth=None,
                utterance=str(getattr(care_plan, "primary_action", "")),
                inferred_intent="decision",
                contingency_mode="none",
                out_of_bound=False,
                repaired=False,
                derailment_cause=None,
                alignment=cls._normalize_alignment(fused_alignment),
                repair_required=False,
                repair_strategy=None,
                trigger_message_id=None,
                tom_snapshot=final_tom,
                timestamp_ms=base_ts,
                extra={
                    "decision": {
                        "accepted_route": bool(getattr(episode, "accepted_route", False)),
                        "rejection_reason": (
                            str(getattr(episode, "rejection_reason"))
                            if getattr(episode, "rejection_reason", None) is not None
                            else None
                        ),
                        "specialist": str(getattr(getattr(care_plan, "specialist", None), "specialty", "")) or None,
                        "optimization_score": cls._as_float(getattr(care_plan, "optimization_score", None)),
                    }
                },
            )
        )

        events.append(
            cls._build_event(
                domain="healthcare",
                run_id=run_identifier,
                conversation_id=conversation_identifier,
                phase="persist",
                event_type="episode_persisted",
                sender="memory_service",
                receiver=None,
                turn_depth=None,
                utterance=f"episode:{episode_id}",
                inferred_intent="persist",
                contingency_mode="none",
                out_of_bound=False,
                repaired=False,
                derailment_cause=None,
                alignment=None,
                repair_required=False,
                repair_strategy=None,
                trigger_message_id=None,
                tom_snapshot=final_tom,
                timestamp_ms=base_ts + 1,
                extra={"decision": {"stored": True, "episode_id": episode_id}},
            )
        )

        # Events are already in causal insertion order: the loop above appends
        # them in trace sequence and terminal events (decision_emitted,
        # episode_persisted) are appended after the loop.
        return events

    @classmethod
    def adapt_fmc_episode(
        cls,
        episode: Any,
        run_id: str | None = None,
        conversation_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        episode_id = str(getattr(episode, "episode_id", "unknown"))
        run_identifier = run_id or f"fmc-{episode_id}"
        conversation_identifier = conversation_id or str(getattr(episode, "customer_id", episode_id))

        turns = list(getattr(episode, "turns", []))
        peer_interactions = [item for item in getattr(episode, "peer_interactions", []) if isinstance(item, dict)]
        inter_agent_tom = getattr(episode, "inter_agent_tom", {})
        if not isinstance(inter_agent_tom, dict):
            inter_agent_tom = {}

        if peer_interactions:
            peer_turn_like_count = sum(
                1
                for item in peer_interactions
                if str(item.get("type", "")) in {"peer_turn", "peer_repair"}
            )
            ingest_turns = turns[: max(0, len(turns) - peer_turn_like_count)]
            peer_turns: List[Any] = []
        else:
            peer_turn_count = cls._as_int(inter_agent_tom.get("peer_turn_count")) or 0
            if peer_turn_count < 0 or peer_turn_count > len(turns):
                peer_turn_count = 0

            ingest_turns = turns[:-peer_turn_count] if peer_turn_count else turns
            peer_turns = turns[-peer_turn_count:] if peer_turn_count else []

        peer_alignment_events = inter_agent_tom.get("peer_alignment_events", [])
        if not isinstance(peer_alignment_events, list):
            peer_alignment_events = []

        out_of_bound_events = inter_agent_tom.get("out_of_bound_events", [])
        if not isinstance(out_of_bound_events, list):
            out_of_bound_events = []

        tom_trace = list(getattr(episode, "tom_trace", []))
        final_tom = cls._normalize_tom_snapshot(tom_trace[-1] if tom_trace else {})

        unix_ts = cls._as_int(getattr(episode, "timestamp_unix", None)) or int(time.time())
        base_ts = unix_ts * 1000
        fallback_step = 0

        def next_ts() -> int:
            nonlocal fallback_step
            fallback_step += 1
            return base_ts + fallback_step

        events: List[Dict[str, Any]] = []

        for turn in ingest_turns:
            events.append(
                cls._build_event(
                    domain="fmc",
                    run_id=run_identifier,
                    conversation_id=conversation_identifier,
                    phase="ingest",
                    event_type="turn_ingested",
                    sender=str(getattr(turn, "speaker", "unknown")),
                    receiver=None,
                    turn_depth=None,
                    utterance=str(getattr(turn, "utterance", "")),
                    inferred_intent=str(getattr(turn, "inferred_intent", "unknown")),
                    contingency_mode="none",
                    out_of_bound=False,
                    repaired=bool(getattr(turn, "repaired", False)),
                    derailment_cause=None,
                    alignment=None,
                    repair_required=False,
                    repair_strategy=None,
                    trigger_message_id=None,
                    tom_snapshot=final_tom,
                    timestamp_ms=cls._as_int(getattr(turn, "timestamp_ms", None)) or next_ts(),
                )
            )

        last_peer_turn_message_id: str | None = None
        if peer_interactions:
            for interaction in peer_interactions:
                # Support new wire format {**l9_header, "payload": {...app_fields...}} and
                # old flat format {...app_fields..., "l9_header": header} transparently.
                _p = interaction["payload"] if isinstance(interaction.get("payload"), dict) else interaction
                _l9 = (
                    {k: v for k, v in interaction.items() if k != "payload"}
                    if "payload" in interaction
                    else (interaction.get("l9_header") or None)
                )

                interaction_type = str(_p.get("type", ""))

                if interaction_type == "peer_turn":
                    events.append(
                        cls._build_event(
                            domain="fmc",
                            run_id=run_identifier,
                            conversation_id=conversation_identifier,
                            phase="peer_dialogue",
                            event_type="peer_turn",
                            sender=str(_p.get("speaker", "unknown")),
                            receiver=str(_p.get("listener", "")) or None,
                            turn_depth=cls._as_int(_p.get("depth")),
                            utterance=str(_p.get("utterance", "")),
                            inferred_intent="peer_message",
                            contingency_mode=str(_p.get("contingency", "none")),
                            out_of_bound=bool(_p.get("out_of_bound", False)),
                            repaired=False,
                            derailment_cause=(
                                str(_p.get("derailment_cause"))
                                if _p.get("derailment_cause") is not None
                                else None
                            ),
                            alignment=cls._normalize_alignment(_p.get("alignment"), _p.get("task_goal")),
                            repair_required=bool(_p.get("repair_required", False)),
                            repair_strategy=None,
                            trigger_message_id=None,
                            tom_snapshot=final_tom,
                            timestamp_ms=next_ts(),
                            l9_header=_l9,
                        )
                    )
                    last_peer_turn_message_id = events[-1]["message_id"]

                elif interaction_type == "repair_required":
                    trigger = _p.get("trigger", {})
                    if not isinstance(trigger, dict):
                        trigger = {}
                    events.append(
                        cls._build_event(
                            domain="fmc",
                            run_id=run_identifier,
                            conversation_id=conversation_identifier,
                            phase="peer_dialogue",
                            event_type="repair_required",
                            sender=str(_p.get("speaker", "unknown")),
                            receiver=str(_p.get("listener", "")) or None,
                            turn_depth=cls._as_int(_p.get("depth")),
                            utterance=str(trigger.get("utterance", "")),
                            inferred_intent="repair_required",
                            contingency_mode=str(trigger.get("contingency", "repair_alignment")),
                            out_of_bound=True,
                            repaired=False,
                            derailment_cause=(
                                str(trigger.get("derailment_cause"))
                                if trigger.get("derailment_cause") is not None
                                else None
                            ),
                            alignment=None,
                            repair_required=True,
                            repair_strategy=(
                                str(_p.get("repair_strategy"))
                                if _p.get("repair_strategy") is not None
                                else "re-anchor_to_budget_margin_timeline"
                            ),
                            trigger_message_id=last_peer_turn_message_id,
                            tom_snapshot=final_tom,
                            timestamp_ms=next_ts(),
                            l9_header=_l9,
                        )
                    )

                elif interaction_type == "peer_repair":
                    triggered_by = _p.get("triggered_by", {})
                    if not isinstance(triggered_by, dict):
                        triggered_by = {}
                    events.append(
                        cls._build_event(
                            domain="fmc",
                            run_id=run_identifier,
                            conversation_id=conversation_identifier,
                            phase="peer_dialogue",
                            event_type="repair_applied",
                            sender=str(_p.get("speaker", "unknown")),
                            receiver=str(_p.get("listener", "")) or None,
                            turn_depth=cls._as_int(_p.get("depth")),
                            utterance=str(_p.get("utterance", "")),
                            inferred_intent="repair",
                            contingency_mode="repair_alignment",
                            out_of_bound=False,
                            repaired=True,
                            derailment_cause=(
                                str(_p.get("derailment_cause"))
                                if _p.get("derailment_cause") is not None
                                else None
                            ),
                            alignment=cls._normalize_alignment(_p.get("alignment"), _p.get("task_goal")),
                            repair_required=False,
                            repair_strategy=(
                                str(_p.get("repair_strategy"))
                                if _p.get("repair_strategy") is not None
                                else "re-anchor_to_budget_margin_timeline"
                            ),
                            trigger_message_id=triggered_by.get("message_id") or last_peer_turn_message_id,
                            tom_snapshot=final_tom,
                            timestamp_ms=next_ts(),
                            l9_header=_l9,
                        )
                    )
        else:
            alignment_index = 0
            for turn in peer_turns:
                repaired = bool(getattr(turn, "repaired", False))
                utterance = str(getattr(turn, "utterance", ""))
                sender = str(getattr(turn, "speaker", "unknown"))
                ts_value = cls._as_int(getattr(turn, "timestamp_ms", None)) or next_ts()

                if repaired:
                    events.append(
                        cls._build_event(
                            domain="fmc",
                            run_id=run_identifier,
                            conversation_id=conversation_identifier,
                            phase="peer_dialogue",
                            event_type="repair_applied",
                            sender=sender,
                            receiver=cls._extract_receiver_from_utterance(utterance),
                            turn_depth=None,
                            utterance=utterance,
                            inferred_intent="repair",
                            contingency_mode="repair_alignment",
                            out_of_bound=False,
                            repaired=True,
                            derailment_cause=None,
                            alignment=None,
                            repair_required=False,
                            repair_strategy="re-anchor_to_budget_margin_timeline",
                            trigger_message_id=last_peer_turn_message_id,
                            tom_snapshot=final_tom,
                            timestamp_ms=ts_value,
                        )
                    )
                    continue

                alignment_event: Dict[str, Any] = {}
                if alignment_index < len(peer_alignment_events):
                    candidate = peer_alignment_events[alignment_index]
                    if isinstance(candidate, dict):
                        alignment_event = candidate
                    alignment_index += 1

                listener = str(alignment_event.get("listener", "")) or cls._extract_receiver_from_utterance(utterance)
                depth = cls._as_int(alignment_event.get("depth"))
                out_event = cls._find_out_of_bound_event(
                    out_of_bound_events,
                    depth=depth,
                    speaker=sender,
                    listener=listener,
                    utterance=utterance,
                )
                out_of_bound = out_event is not None
                derailment_cause = alignment_event.get("derailment_cause")
                if derailment_cause is None and isinstance(out_event, dict):
                    derailment_cause = out_event.get("derailment_cause")

                events.append(
                    cls._build_event(
                        domain="fmc",
                        run_id=run_identifier,
                        conversation_id=conversation_identifier,
                        phase="peer_dialogue",
                        event_type="peer_turn",
                        sender=sender,
                        receiver=listener,
                        turn_depth=depth,
                        utterance=utterance,
                        inferred_intent=str(getattr(turn, "inferred_intent", "peer_message")),
                        contingency_mode=str(alignment_event.get("contingency", "none")),
                        out_of_bound=out_of_bound,
                        repaired=False,
                        derailment_cause=str(derailment_cause) if derailment_cause is not None else None,
                        alignment=cls._normalize_alignment(alignment_event.get("alignment"), alignment_event.get("task_goal")),
                        repair_required=out_of_bound,
                        repair_strategy=None,
                        trigger_message_id=None,
                        tom_snapshot=final_tom,
                        timestamp_ms=ts_value,
                    )
                )

                last_peer_turn_message_id = events[-1]["message_id"]

                if out_of_bound:
                    events.append(
                        cls._build_event(
                            domain="fmc",
                            run_id=run_identifier,
                            conversation_id=conversation_identifier,
                            phase="peer_dialogue",
                            event_type="repair_required",
                            sender=sender,
                            receiver=listener,
                            turn_depth=depth,
                            utterance=utterance,
                            inferred_intent="repair_required",
                            contingency_mode="repair_alignment",
                            out_of_bound=True,
                            repaired=False,
                            derailment_cause=str(derailment_cause) if derailment_cause is not None else None,
                            alignment=None,
                            repair_required=True,
                            repair_strategy="re-anchor_to_budget_margin_timeline",
                            trigger_message_id=last_peer_turn_message_id,
                            tom_snapshot=final_tom,
                            timestamp_ms=ts_value,
                        )
                    )

        inter_alignment = inter_agent_tom.get("fmc_sfdc") if isinstance(inter_agent_tom, dict) else {}
        offer = getattr(episode, "offer", None)
        events.append(
            cls._build_event(
                domain="fmc",
                run_id=run_identifier,
                conversation_id=conversation_identifier,
                phase="coordination",
                event_type="decision_emitted",
                sender="orchestrator",
                receiver=None,
                turn_depth=None,
                utterance=(
                    f"final_offer vin={getattr(offer, 'vin', '')} final_price={getattr(offer, 'final_price_eur', '')}"
                ),
                inferred_intent="decision",
                contingency_mode="none",
                out_of_bound=False,
                repaired=False,
                derailment_cause=None,
                alignment=cls._normalize_alignment(inter_alignment, inter_agent_tom.get("task_goal")),
                repair_required=False,
                repair_strategy=None,
                trigger_message_id=None,
                tom_snapshot=final_tom,
                timestamp_ms=base_ts,
                extra={
                    "decision": {
                        "accepted": bool(getattr(episode, "accepted", False)),
                        "vin": str(getattr(offer, "vin", "")) or None,
                        "final_price_eur": cls._as_float(getattr(offer, "final_price_eur", None)),
                        "discount_pct": cls._as_float(getattr(offer, "discount_pct", None)),
                    }
                },
            )
        )

        events.append(
            cls._build_event(
                domain="fmc",
                run_id=run_identifier,
                conversation_id=conversation_identifier,
                phase="persist",
                event_type="episode_persisted",
                sender="memory_service",
                receiver=None,
                turn_depth=None,
                utterance=f"episode:{episode_id}",
                inferred_intent="persist",
                contingency_mode="none",
                out_of_bound=False,
                repaired=False,
                derailment_cause=None,
                alignment=None,
                repair_required=False,
                repair_strategy=None,
                trigger_message_id=None,
                tom_snapshot=final_tom,
                timestamp_ms=base_ts + 1,
                extra={"decision": {"stored": True, "episode_id": episode_id}},
            )
        )

        return events

    @classmethod
    def adapt_travel_episode(
        cls,
        episode: Any,
        conversation_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        run_identifier = str(getattr(episode, "run_id", "travel-run"))
        conversation_identifier = conversation_id or run_identifier

        turns = list(getattr(episode, "turns", []))
        peer_interactions = list(getattr(episode, "peer_interactions", []))
        tom_trace = list(getattr(episode, "tom_trace", []))
        final_tom = cls._normalize_tom_snapshot(tom_trace[-1] if tom_trace else {})

        unix_ts = cls._as_int(getattr(episode, "timestamp_unix", None)) or int(time.time())
        base_ts = unix_ts * 1000
        fallback_step = 0

        def next_ts() -> int:
            nonlocal fallback_step
            fallback_step += 1
            return base_ts + fallback_step

        peer_turn_like_count = sum(
            1
            for item in peer_interactions
            if isinstance(item, dict) and str(item.get("type", "")) in {"peer_turn", "peer_repair"}
        )
        ingest_count = max(0, len(turns) - peer_turn_like_count)
        ingest_turns = turns[:ingest_count]

        events: List[Dict[str, Any]] = []
        last_peer_turn_message_id: str | None = None

        for turn in ingest_turns:
            events.append(
                cls._build_event(
                    domain="travel",
                    run_id=run_identifier,
                    conversation_id=conversation_identifier,
                    phase="ingest",
                    event_type="turn_ingested",
                    sender=str(getattr(turn, "speaker", "proxy")),
                    receiver=None,
                    turn_depth=None,
                    utterance=str(getattr(turn, "utterance", "")),
                    inferred_intent=str(getattr(turn, "inferred_intent", "coordination")),
                    contingency_mode="none",
                    out_of_bound=False,
                    repaired=bool(getattr(turn, "repaired", False)),
                    derailment_cause=None,
                    alignment=None,
                    repair_required=False,
                    repair_strategy=None,
                    trigger_message_id=None,
                    tom_snapshot=final_tom,
                    timestamp_ms=cls._as_int(getattr(turn, "timestamp_ms", None)) or next_ts(),
                )
            )

        for interaction in peer_interactions:
            if not isinstance(interaction, dict):
                continue

            interaction_type = str(interaction.get("type", ""))

            if interaction_type == "peer_turn":
                events.append(
                    cls._build_event(
                        domain="travel",
                        run_id=run_identifier,
                        conversation_id=conversation_identifier,
                        phase="peer_dialogue",
                        event_type="peer_turn",
                        sender=str(interaction.get("speaker", "unknown")),
                        receiver=str(interaction.get("listener", "")) or None,
                        turn_depth=cls._as_int(interaction.get("depth")),
                        utterance=str(interaction.get("utterance", "")),
                        inferred_intent="peer_message",
                        contingency_mode=str(interaction.get("contingency", "none")),
                        out_of_bound=bool(interaction.get("out_of_bound", False)),
                        repaired=False,
                        derailment_cause=(
                            str(interaction.get("derailment_cause"))
                            if interaction.get("derailment_cause") is not None
                            else None
                        ),
                        alignment=cls._normalize_alignment(interaction.get("alignment"), interaction.get("task_goal")),
                        repair_required=bool(interaction.get("repair_required", False)),
                        repair_strategy=None,
                        trigger_message_id=None,
                        tom_snapshot=final_tom,
                        timestamp_ms=next_ts(),
                        l9_header=interaction.get("l9_header") if isinstance(interaction.get("l9_header"), dict) else None,
                    )
                )
                last_peer_turn_message_id = events[-1]["message_id"]

            elif interaction_type == "repair_required":
                events.append(
                    cls._build_event(
                        domain="travel",
                        run_id=run_identifier,
                        conversation_id=conversation_identifier,
                        phase="peer_dialogue",
                        event_type="repair_required",
                        sender=str(interaction.get("speaker", "unknown")),
                        receiver=str(interaction.get("listener", "")) or None,
                        turn_depth=cls._as_int(interaction.get("depth")),
                        utterance="",
                        inferred_intent="repair_required",
                        contingency_mode="repair_alignment",
                        out_of_bound=True,
                        repaired=False,
                        derailment_cause=None,
                        alignment=None,
                        repair_required=True,
                        repair_strategy=(
                            str(interaction.get("repair_strategy"))
                            if interaction.get("repair_strategy") is not None
                            else "re-anchor_to_constraints_and_governance"
                        ),
                        trigger_message_id=last_peer_turn_message_id,
                        tom_snapshot=final_tom,
                        timestamp_ms=next_ts(),
                        l9_header=interaction.get("l9_header") if isinstance(interaction.get("l9_header"), dict) else None,
                    )
                )

            elif interaction_type == "peer_repair":
                events.append(
                    cls._build_event(
                        domain="travel",
                        run_id=run_identifier,
                        conversation_id=conversation_identifier,
                        phase="peer_dialogue",
                        event_type="repair_applied",
                        sender=str(interaction.get("speaker", "unknown")),
                        receiver=str(interaction.get("listener", "")) or None,
                        turn_depth=cls._as_int(interaction.get("depth")),
                        utterance=str(interaction.get("utterance", "")),
                        inferred_intent="repair",
                        contingency_mode="repair_alignment",
                        out_of_bound=False,
                        repaired=True,
                        derailment_cause=None,
                        alignment=cls._normalize_alignment(interaction.get("alignment"), interaction.get("task_goal")),
                        repair_required=False,
                        repair_strategy=(
                            str(interaction.get("repair_strategy"))
                            if interaction.get("repair_strategy") is not None
                            else "re-anchor_to_constraints_and_governance"
                        ),
                        trigger_message_id=last_peer_turn_message_id,
                        tom_snapshot=final_tom,
                        timestamp_ms=next_ts(),
                        l9_header=interaction.get("l9_header") if isinstance(interaction.get("l9_header"), dict) else None,
                    )
                )

        accepted_count = cls._as_int(getattr(episode, "accepted_count", None)) or 0
        rejected_count = cls._as_int(getattr(episode, "rejected_count", None)) or 0
        governance_mode = str(getattr(episode, "governance_mode", "majority_vote"))

        events.append(
            cls._build_event(
                domain="travel",
                run_id=run_identifier,
                conversation_id=conversation_identifier,
                phase="coordination",
                event_type="decision_emitted",
                sender="decision_engine",
                receiver="validated_truth_store",
                turn_depth=None,
                utterance=f"approved={accepted_count} rejected={rejected_count}",
                inferred_intent="decision",
                contingency_mode="none",
                out_of_bound=False,
                repaired=False,
                derailment_cause=None,
                alignment=None,
                repair_required=False,
                repair_strategy=None,
                trigger_message_id=None,
                tom_snapshot=final_tom,
                timestamp_ms=base_ts,
                extra={
                    "decision": {
                        "accepted_count": accepted_count,
                        "rejected_count": rejected_count,
                        "governance_mode": governance_mode,
                    }
                },
            )
        )

        episode_id = str(getattr(episode, "episode_id", "unknown"))
        events.append(
            cls._build_event(
                domain="travel",
                run_id=run_identifier,
                conversation_id=conversation_identifier,
                phase="persist",
                event_type="episode_persisted",
                sender="memory_service",
                receiver=None,
                turn_depth=None,
                utterance=f"episode:{episode_id}",
                inferred_intent="persist",
                contingency_mode="none",
                out_of_bound=False,
                repaired=False,
                derailment_cause=None,
                alignment=None,
                repair_required=False,
                repair_strategy=None,
                trigger_message_id=None,
                tom_snapshot=final_tom,
                timestamp_ms=base_ts + 1,
                extra={"decision": {"stored": True, "episode_id": episode_id}},
            )
        )

        return events

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
app/hcpanel/orchestration.py — Joint clinical debate orchestrator.

Runs the SIEP star negotiation with inline CIP contingency gating.
Team-process preamble and taskwork episodes are included for protocol
correctness. Every CIP exchange is assessed through ToM (assess_utterance).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from SSTP.examples.hcpanel.panel_bus import PanelBus, StarNegotiation
from SSTP.subprotocol.siep.src.epistemic.stores import AgentBeliefStore, BeliefRevision

from SSTP.examples.hcpanel.agent_bus import BeliefStoreProxy
from SSTP.examples.hcpanel.domain import ClinicalDebateOutcome, SpecialistOpinion
from SSTP.l9.episode import L9, Episode as L9Episode

if TYPE_CHECKING:
    from SSTP.examples.hcpanel.specialists import PharmacologyController, PhysicianController, SpecialistAgent
    from SSTP.examples.hcpanel.memory import HCPanelMemory
    from SSTP.examples.hcpanel.domain import PatientProfile

LOGGER = logging.getLogger("hcpanel")

_CONTROLLER_ID = "diagnostics-controller"
_TASK_GOAL = (
    "joint clinical debate: patient symptom assessment, drug interaction risk, "
    "drug change proposals, and joint recommendation"
)

_ROLE_DESCRIPTIONS: Dict[str, str] = {
    "internal_medicine": "board-certified internist performing broad differential diagnosis",
    "clinical_pharmacology": "clinical pharmacologist specialising in drug-drug interactions",
    "cardiology": "cardiologist assessing cardiovascular manifestations of medication use",
    "neurology": "neurologist assessing CNS drug effects and neurotoxicity",
    "immunology": "immunologist assessing hypersensitivity and immune-mediated adverse events",
    "pharmacokinetics": "pharmacokineticist assessing ADME and PK drug-drug interactions",
    "pharmacodynamics": "pharmacodynamicist assessing receptor pharmacology and synergistic effects",
    "clinical_pharmacy": "clinical pharmacist applying guideline-based therapy and formulary evidence",
    "drug_safety": "drug safety specialist monitoring adverse events and contraindications",
    "clinical_toxicology": "clinical toxicologist assessing toxicity risk and high-risk combinations",
}


def _build_role_assignments(
    all_specialists: List["SpecialistAgent"],
) -> List[Dict[str, Any]]:
    concept_map = {
        "physician": ["concept:drug_interaction", "concept:symptom_assessment"],
        "pharmacology": ["concept:drug_interaction", "concept:drug_change_proposal"],
    }
    return [
        {
            "agent_id": a.agent_id,
            "role": a.role,
            "responsible_for": concept_map.get(a.panel, ["concept:drug_interaction"]),
        }
        for a in all_specialists
    ]


def _extract_convergence_metrics(snp_trace: List[Dict[str, Any]]) -> Dict[str, float]:
    for msg in reversed(snp_trace):
        for part in msg.get("payload") or []:
            if part.get("type") == "snp-convergence":
                content = part.get("content") or {}
                return {
                    "gar": float(content.get("gar", 0.0)),
                    "scr": float(content.get("scr", 0.0)),
                    "mpc": float(content.get("mpc", 0.5)),
                }
    return {"gar": 0.0, "scr": 0.0, "mpc": 0.5}


def _positions_to_opinions(
    specialist_positions: Dict[str, Any],
    all_specialists: List["SpecialistAgent"],
) -> List[SpecialistOpinion]:
    specialist_map = {a.agent_id: a for a in all_specialists}
    opinions = []
    for agent_id, pos in specialist_positions.items():
        agent = specialist_map.get(agent_id)
        if agent is None:
            continue
        opinions.append(SpecialistOpinion(
            specialist_id=agent_id,
            specialty=agent.role,
            panel=agent.panel,
            symptom_assessment=str(pos.get("reasoning_summary") or pos.get("rationale") or ""),
            drug_change_proposal=str(pos.get("drug_change_proposal") or ""),
            confidence=float(pos.get("confidence") or 0.5),
            reasoning=str(pos.get("reasoning_summary") or ""),
            likely_cause=str(pos.get("likely_cause") or "drug_interaction"),
            posterior=float(pos.get("posterior") or pos.get("confidence") or 0.5),
            supporting_evidence=list(pos.get("supporting_evidence") or []),
        ))
    return opinions


def _flatten_rationale(value: Any) -> str:
    """Return a plain-text string from a rationale that may be a dict, list, or str.

    The Haiku LLM occasionally returns rationale as a nested JSON object with
    keys like 'primary_reasoning'. Extract prose in that case rather than repr.
    """
    if isinstance(value, dict):
        for key in ("primary_reasoning", "reasoning", "summary", "rationale", "text"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # fall back: join all string values
        parts = [str(v) for v in value.values() if isinstance(v, str) and str(v).strip()]
        return " ".join(parts).strip()
    if isinstance(value, list):
        return " ".join(str(x) for x in value if str(x).strip()).strip()
    return str(value).strip()


def _utterance_from_pos(agent: "SpecialistAgent", pos: Dict[str, Any]) -> str:
    """Return the natural-language utterance for a taskwork result."""
    raw = pos.get("rationale") or pos.get("reasoning_summary")
    if raw:
        utterance = _flatten_rationale(raw)
        if utterance:
            return utterance
    cause = pos.get("likely_cause", "?")
    conf = float(pos.get("confidence", 0.5))
    return f"{cause} confidence={conf:.2f}"


def _thought_from_pos(pos: Dict[str, Any]) -> str:
    """Return the thought_summary from a position dict if present."""
    return str(pos.get("thought_summary") or "").strip()


class DebateOrchestrator:
    """Runs the joint panel negotiation for one patient episode."""

    def __init__(
        self,
        physician_ctrl: "PhysicianController",
        pharmacy_ctrl: "PharmacologyController",
        memory: "HCPanelMemory",
        ie_bus: Any,
        tom_engine: Optional[Any] = None,
        repair_fn: Optional[Any] = None,
    ) -> None:
        self.physician_ctrl = physician_ctrl
        self.pharmacy_ctrl = pharmacy_ctrl
        self.memory = memory
        self.ie_bus = ie_bus
        self.tom_engine = tom_engine
        self.repair_fn = repair_fn

    def _tom_assess(
        self,
        utterance: str,
        speaker: str,
        listener: str,
        prior_utterance: str = "",
        belief_store: Any = None,
        concept_id: str = "",
    ) -> Dict[str, Any]:
        """Call assess_utterance on the listener's ToM agent after a CIP exchange.

        Returns the assessment dict so callers can act on ambiguity/grounding_failure.
        Returns {} when tom_engine is not set or on error.
        """
        if self.tom_engine is None:
            return {}
        # TEAM_PROCESS coordination tokens have no clinical content — skip the judge.
        if utterance.startswith(("process_proposal:", "process_accepted:", "process_challenged:")):
            return {}
        try:
            listener_tom = self.tom_engine.agent(listener)
            return listener_tom.assess_utterance(
                utterance=utterance,
                task_goal=_TASK_GOAL,
                speaker=speaker,
                listener=listener,
                listener_prior_utterance=prior_utterance or None,
                belief_store=belief_store,
                concept_id=concept_id,
                use_case="healthcare",
            )
        except Exception as exc:
            LOGGER.warning("tom.assess_utterance failed speaker=%s listener=%s err=%s",
                           speaker, listener, exc)
            return {}

    def _handle_taskwork_contingency(
        self,
        agent: Any,
        pos: Dict[str, Any],
        assessment: Dict[str, Any],
        original_msg_id: str,
        episode_id: str,
        concept_id: str,
    ) -> None:
        """Open a contingency sub-episode when ToM detects ambiguity or grounding failure.

        Emits: epistemic_clarification (kind=contingency) → clarification response
        (kind=exchange) → commit:resolved. The clarification content is derived from
        the agent's supporting_evidence and drug_change_proposal fields.
        """
        ambiguity_score = float(assessment.get("ambiguity_score", 0.0))
        critique = str(assessment.get("critique", ""))
        clarification_request = (
            f"Clarification requested for {agent.agent_id} assertion on {concept_id}: "
            f"ambiguity_score={ambiguity_score:.2f} critique={critique or 'grounding_failure'}"
        )

        clarif_hdr = self.ie_bus.emit_epistemic_clarification(
            sender=_CONTROLLER_ID,
            receiver=agent.agent_id,
            target_message_id=original_msg_id,
            reason=f"ambiguous_taskwork:score={ambiguity_score:.2f}",
            episode_id=episode_id,
        )

        # Specialist responds with a clarified rationale
        evidence = pos.get("supporting_evidence") or []
        drug_changes = pos.get("drug_change_proposal") or pos.get("proposed_changes") or ""
        clarification_text = (
            str(pos.get("rationale") or pos.get("reasoning_summary") or "")
            + (f" Supporting evidence: {', '.join(str(e) for e in evidence[:3])}." if evidence else "")
            + (f" Proposed changes: {drug_changes}." if drug_changes else "")
        ).strip()
        if not clarification_text:
            clarification_text = f"Reaffirming: {pos.get('likely_cause','?')} posterior={float(pos.get('posterior') or pos.get('confidence') or 0.5):.2f}"

        clarif_response_hdr = self.ie_bus.emit_taskwork_result(
            sender=agent.agent_id,
            receiver=_CONTROLLER_ID,
            utterance=clarification_text,
            concept_id=concept_id,
            posterior=float(pos.get("posterior") or pos.get("confidence") or 0.5),
            episode_id=episode_id,
        )

        # Re-assess clarification through ToM before closing
        clarif_assessment = self._tom_assess(
            utterance=clarification_text,
            speaker=agent.agent_id,
            listener=_CONTROLLER_ID,
            prior_utterance=clarification_request,
            belief_store=agent.belief_store,
            concept_id=concept_id,
        )

        resolution = "resolved" if clarif_assessment.get("aligned") or not clarif_assessment.get("grounding_failure") else "partial"
        self.ie_bus.emit_repair_resolved(
            sender=_CONTROLLER_ID,
            receiver=agent.agent_id,
            utterance=f"contingency_resolved:{concept_id}:{resolution}",
            parent_id=clarif_hdr["message"]["id"],
            episode_id=episode_id,
        )
        LOGGER.debug(
            "taskwork.contingency_resolved agent=%s concept=%s resolution=%s aligned=%s",
            agent.agent_id, concept_id, resolution,
            clarif_assessment.get("aligned"),
        )

    def run_joint_panel(
        self,
        patient: "PatientProfile",
        episode_id: str,
        physician_positions: Dict[str, Dict[str, Any]],
        pharmacy_positions: Dict[str, Dict[str, Any]],
    ) -> ClinicalDebateOutcome:
        from collections import Counter
        from SSTP.subprotocol.siep.src.epistemic.stores import TeamProcessAgreement, RoleAssignment

        all_specialists = (
            self.physician_ctrl.specialists + self.pharmacy_ctrl.specialists
        )
        all_ids = [a.agent_id for a in all_specialists]
        all_positions = {**physician_positions, **pharmacy_positions}

        # BeliefStoreProxy — routes all PanelBus belief reads/writes to the
        # owning agent's private AgentBeliefStore.
        # The controller gets its own private store (not shared with any specialist).
        controller_belief_store = AgentBeliefStore()
        agent_store_map = {agent.agent_id: agent.belief_store for agent in all_specialists}
        agent_store_map[_CONTROLLER_ID] = controller_belief_store
        belief_proxy = BeliefStoreProxy(agent_store_map)

        # Seed ToM engine with specialist roles so predict_peer_response has
        # a non-empty peer model from round 1 onward.
        if self.tom_engine is not None:
            session_ctx = {
                "patient_id": patient.patient_id,
                "task_goal": _TASK_GOAL,
                "symptoms": patient.symptoms,
                "medications": patient.current_medications,
            }
            for agent in all_specialists:
                role_desc = _ROLE_DESCRIPTIONS.get(agent.role, agent.role)
                try:
                    ctrl_tom = self.tom_engine.agent(_CONTROLLER_ID)
                    ctrl_tom.seed_peer(agent.agent_id, role_desc, session_ctx)
                    agent_tom = self.tom_engine.agent(agent.agent_id)
                    agent_tom.seed_peer(_CONTROLLER_ID,
                                        "diagnostics coordinator driving joint clinical debate",
                                        session_ctx)
                except Exception as exc:
                    LOGGER.warning("tom.seed_peer failed agent=%s err=%s", agent.agent_id, exc)

        episode_tp = f"{episode_id}:tp"
        episode_tw = f"{episode_id}:tw"

        # L9 entry point for the controller — wraps the bus for episode A and B.
        ctrl_l9 = L9(self.ie_bus, agent_id=_CONTROLLER_ID)

        # ── EPISODE A: team process ──────────────────────────────────────
        role_assignments = _build_role_assignments(all_specialists)
        agreement = TeamProcessAgreement(
            episode_id=episode_tp,
            round_id=str(uuid.uuid4()),
            coordinator_id=_CONTROLLER_ID,
            participant_ids=list(all_ids),
            role_assignments=[
                RoleAssignment(
                    agent_id=ra["agent_id"],
                    role=ra["role"],
                    responsible_for=list(ra.get("responsible_for", [])),
                    assigned_at_ms=int(time.time() * 1000),
                    agreed=False,
                )
                for ra in role_assignments
            ],
            formed_at_ms=int(time.time() * 1000),
        )

        tp_episode = ctrl_l9.open(
            concept_id=patient.patient_id,
            group=all_ids,
            episode_id=episode_tp,
            rationale=f"Opening team process for patient {patient.patient_id}: assigning roles to {len(all_ids)} specialists.",
            thought_summary=f"Initiating team formation before taskwork; {len(all_ids)} specialists need role assignments.",
        )

        for specialist_id in all_ids:
            prop_hdr = self.ie_bus.emit_process_proposal(
                sender=_CONTROLLER_ID,
                receiver=specialist_id,
                agreement=agreement,
                episode_id=episode_tp,
            )
            prop_utterance = (
                (prop_hdr.get("payload") or [{}])[0].get("content", "")
                or prop_hdr.get("utterance", "")
            )
            self._tom_assess(
                utterance=prop_utterance,
                speaker=_CONTROLLER_ID,
                listener=specialist_id,
            )

            acc_hdr = self.ie_bus.emit_process_acceptance(
                sender=specialist_id,
                receiver=_CONTROLLER_ID,
                parent_id=prop_hdr["message"]["id"],
                episode_id=episode_tp,
            )
            acc_utterance = (
                (acc_hdr.get("payload") or [{}])[0].get("content", "")
                or acc_hdr.get("utterance", "")
            )
            self._tom_assess(
                utterance=acc_utterance,
                speaker=specialist_id,
                listener=_CONTROLLER_ID,
                prior_utterance=prop_utterance,
            )
            tp_episode._record_done(specialist_id, 1.0)

        tp_episode.close(
            rationale=(
                f"All {len(all_ids)} specialists acknowledged their role assignments. "
                f"Team structure is confirmed — taskwork gate is now open."
            ),
            thought_summary=(
                f"{len(all_ids)} role assignments accepted; team process converged, proceeding to taskwork."
            ),
        )

        # ── EPISODE B: taskwork assessments ─────────────────────────────
        tw_episode = ctrl_l9.open(
            concept_id=patient.patient_id,
            group=all_ids,
            episode_id=episode_tw,
            team_process={
                "symptoms": patient.symptoms,
                "medications": patient.current_medications,
                "chat_history": patient.chat_history,
            },
            rationale=f"Opening taskwork for patient {patient.patient_id}: collecting independent priors from {len(all_ids)} specialists.",
            thought_summary=f"Each specialist must declare their prior before peer exchange begins.",
        )

        for agent in all_specialists:
            pos = all_positions.get(agent.agent_id, {})
            utterance = _utterance_from_pos(agent, pos)
            thought = _thought_from_pos(pos)
            concept_id = f"urn:concept:healthcare:{pos.get('likely_cause', '?')}"
            posterior = float(pos.get("posterior") or pos.get("confidence") or 0.5)

            # Seed agent's prior into their own belief_store before ToM assessment.
            if not agent.belief_store.current_belief(agent.agent_id, concept_id, "healthcare"):
                agent.belief_store.set_prior(agent.agent_id, concept_id, "healthcare",
                                             posterior, 1.0)
                agent.belief_store.record_revision(
                    agent.agent_id, concept_id, "healthcare",
                    episode_tw,
                    BeliefRevision(
                        revision_id=str(uuid.uuid4()),
                        timestamp_ms=int(time.time() * 1000),
                        episode_id=episode_tw,
                        message_id=None,
                        confidence_before=posterior,
                        confidence_after=posterior,
                        cause="semantic_memory",
                        caused_by_agent=None,
                        argument_concept_ids=[concept_id],
                    ),
                    new_status="held",
                    new_public_confidence=posterior,
                )

            # Each specialist uses Episode directly to say() their prior.
            agent_episode = L9Episode(
                bus=self.ie_bus,
                agent_id=agent.agent_id,
                concept_id=concept_id,
                episode_id=episode_tw,
                initiator=False,
            )
            tw_msg_id = agent_episode.say(
                utterance=utterance,
                posterior=posterior,
                rationale=utterance,
                thought_summary=thought,
            )

            assessment = self._tom_assess(
                utterance=utterance,
                speaker=agent.agent_id,
                listener=_CONTROLLER_ID,
                belief_store=agent.belief_store,
                concept_id=concept_id,
            )

            if assessment.get("ambiguous") or assessment.get("grounding_failure"):
                self._handle_taskwork_contingency(
                    agent=agent,
                    pos=pos,
                    assessment=assessment,
                    original_msg_id=tw_msg_id,
                    episode_id=episode_tw,
                    concept_id=concept_id,
                )

            tw_episode._record_done(agent.agent_id, posterior)

        tw_episode.close(
            rationale=(
                f"Independent priors declared by all {len(all_ids)} specialists for patient "
                f"{patient.patient_id}. Each agent has stated its position before peer exchange — "
                f"baseline beliefs are on record."
            ),
            thought_summary=(
                f"All {len(all_ids)} prior declarations received; taskwork baseline established, proceeding to panel debate."
            ),
        )

        # ── EPISODE C: SNP panel negotiation (PanelBus-managed URN) ─────
        panel_bus = PanelBus(
            panel_name="hcpanel",
            ie_bus=self.ie_bus,
            use_case="healthcare",
            tom_engine=self.tom_engine,
            repair_fn=self.repair_fn,
            convergence_store=self.memory.convergence_store,
            semantic_rule_store=self.memory.semantic_rule_store,
            belief_store=belief_proxy,
            peer_interaction_store=self.memory.peer_interaction_store,
        )

        # Derive controller position from physician plurality
        cause_counts: Counter = Counter(
            str(pos.get("likely_cause", "drug_interaction"))
            for pos in physician_positions.values()
        )
        leading_cause = cause_counts.most_common(1)[0][0] if cause_counts else "drug_interaction"
        physician_confs = [
            float(pos.get("confidence", 0.5))
            for pos in physician_positions.values()
            if str(pos.get("likely_cause")) == leading_cause
        ]
        ctrl_confidence = round(
            sum(physician_confs) / len(physician_confs) if physician_confs else 0.65, 4
        )
        controller_position: Dict[str, Any] = {
            "likely_cause": leading_cause,
            "confidence": ctrl_confidence,
            "posterior": ctrl_confidence,
            "supporting_evidence": [leading_cause],
            "reasoning_summary": (
                f"Physician plurality: {leading_cause} "
                f"({len(physician_confs)}/{len(physician_positions)})"
            ),
            "rationale": f"Physician panel plurality position: {leading_cause}",
        }

        LOGGER.info(
            "debate.panel_open episode=%s controller_position=%s confidence=%.4f members=%d",
            episode_id, leading_cause, ctrl_confidence, len(all_ids),
        )

        star = StarNegotiation(panel_bus, panel_name="hcpanel")
        winning_position, resolution_label, snp_trace = star.run(
            controller_id=_CONTROLLER_ID,
            member_ids=all_ids,
            controller_position=controller_position,
            specialist_positions=all_positions,
            task_goal=_TASK_GOAL,
            accept_threshold=0.1,
            max_rounds=2,
        )

        panel_episode_id = panel_bus._episode_id()
        metrics = _extract_convergence_metrics(snp_trace)
        opinions = _positions_to_opinions(all_positions, all_specialists)

        win_key = str(
            winning_position.get("likely_cause")
            if isinstance(winning_position, dict)
            else winning_position
        )
        win_conf = float(
            winning_position.get("confidence", metrics["mpc"])
            if isinstance(winning_position, dict)
            else metrics["mpc"]
        )

        proposed_changes: List[str] = []
        for pos in pharmacy_positions.values():
            changes = pos.get("proposed_changes") or pos.get("drug_change_proposal") or []
            if isinstance(changes, list):
                proposed_changes.extend(changes)
            elif isinstance(changes, str) and changes:
                proposed_changes.append(changes)
        proposed_changes = list(dict.fromkeys(proposed_changes))

        joint_recommendation = (
            f"Panel converged ({resolution_label}): {win_key} "
            f"posterior={win_conf:.2f} GAR={metrics['gar']:.2f} SCR={metrics['scr']:.2f}"
        )

        LOGGER.info(
            "debate.panel_close episode=%s resolution=%s cause=%s gar=%.4f scr=%.4f mpc=%.4f",
            episode_id, resolution_label, win_key,
            metrics["gar"], metrics["scr"], metrics["mpc"],
        )

        return ClinicalDebateOutcome(
            patient_id=patient.patient_id,
            symptom_conclusion=win_key,
            drug_interaction_risk=win_conf,
            proposed_drug_changes=proposed_changes,
            joint_recommendation=joint_recommendation,
            gar=metrics["gar"],
            scr=metrics["scr"],
            mpc=metrics["mpc"],
            resolution_label=resolution_label,
            specialist_opinions=opinions,
            snp_trace=snp_trace,
            panel_episode_id=panel_episode_id,
        )

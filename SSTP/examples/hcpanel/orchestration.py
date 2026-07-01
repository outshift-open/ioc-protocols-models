# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
app/hcpanel/orchestration.py — Joint clinical debate orchestrator.

Runs three L9 episode phases in sequence:
  A. team process   — open_team_process → run → close
  B. taskwork       — open_taskwork     → run → close
  C. SIEP task      — open_task        → run → announce

All protocol mechanics (belief seeding, ToM assessment, contingency repair,
proposal/acceptance loops, SIEP star negotiation) are encapsulated inside
the Episode API. The orchestrator handles domain data extraction and
dependency injection only.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from SSTP.examples.hcpanel.agent_bus import BeliefStoreProxy
from SSTP.examples.hcpanel.domain import ClinicalDebateOutcome, SpecialistOpinion
from SSTP.examples.hcpanel.episode import L9, TaskworkParticipant
from SSTP.subprotocol.siep.src.epistemic.stores import AgentBeliefStore

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
    """Return a plain-text string from a rationale that may be a dict, list, or str."""
    if isinstance(value, dict):
        for key in ("primary_reasoning", "reasoning", "summary", "rationale", "text"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
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

        # BeliefStoreProxy — routes PanelBus belief reads/writes to each
        # specialist's private AgentBeliefStore.
        controller_belief_store = AgentBeliefStore()
        agent_store_map = {agent.agent_id: agent.belief_store for agent in all_specialists}
        agent_store_map[_CONTROLLER_ID] = controller_belief_store
        belief_proxy = BeliefStoreProxy(agent_store_map)

        # Seed ToM engine with specialist roles.
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
                    agent_tom.seed_peer(
                        _CONTROLLER_ID,
                        "diagnostics coordinator driving joint clinical debate",
                        session_ctx,
                    )
                except Exception as exc:
                    LOGGER.warning("tom.seed_peer failed agent=%s err=%s", agent.agent_id, exc)

        episode_tp = f"{episode_id}:tp"
        episode_tw = f"{episode_id}:tw"

        # Controller L9 entry point — tom_engine and task_goal wired in once.
        ctrl_l9 = L9(
            self.ie_bus,
            agent_id=_CONTROLLER_ID,
            tom_engine=self.tom_engine,
            task_goal=_TASK_GOAL,
        )

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

        tp_episode = ctrl_l9.open_team_process(
            concept_id=patient.patient_id,
            group=all_ids,
            episode_id=episode_tp,
            agreement=agreement,
            task_goal=_TASK_GOAL,
            rationale=f"Opening team process for patient {patient.patient_id}: assigning roles to {len(all_ids)} specialists.",
            thought_summary=f"Initiating team formation before taskwork; {len(all_ids)} specialists need role assignments.",
        )
        tp_episode.run()
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
        participants = [
            TaskworkParticipant(
                agent_id=agent.agent_id,
                utterance=_utterance_from_pos(agent, all_positions.get(agent.agent_id, {})),
                posterior=float(
                    all_positions.get(agent.agent_id, {}).get("posterior")
                    or all_positions.get(agent.agent_id, {}).get("confidence")
                    or 0.5
                ),
                concept_id=f"urn:concept:healthcare:{all_positions.get(agent.agent_id, {}).get('likely_cause', '?')}",
                belief_store=agent.belief_store,
                thought_summary=_thought_from_pos(all_positions.get(agent.agent_id, {})),
            )
            for agent in all_specialists
        ]

        tw_episode = ctrl_l9.open_taskwork(
            concept_id=patient.patient_id,
            group=all_ids,
            episode_id=episode_tw,
            participants=participants,
            task_goal=_TASK_GOAL,
            coordinator_id=_CONTROLLER_ID,
            team_process={
                "symptoms": patient.symptoms,
                "medications": patient.current_medications,
                "chat_history": patient.chat_history,
            },
            rationale=f"Opening taskwork for patient {patient.patient_id}: collecting independent priors from {len(all_ids)} specialists.",
            thought_summary=f"Each specialist must declare their prior before peer exchange begins.",
        )
        tw_episode.run()
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

        # ── EPISODE C: SIEP panel negotiation ───────────────────────────
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

        task_ep = ctrl_l9.open_task(
            concept_id=f"urn:concept:healthcare:{leading_cause}",
            group=all_ids,
            convergence_store=self.memory.convergence_store,
            semantic_rule_store=self.memory.semantic_rule_store,
            peer_interaction_store=self.memory.peer_interaction_store,
            belief_store=belief_proxy,
            tom_engine=self.tom_engine,
            repair_fn=self.repair_fn,
            task_name="hcpanel",
        )
        task_ep.run(
            controller_position=controller_position,
            specialist_positions=all_positions,
            task_goal=_TASK_GOAL,
            accept_threshold=0.1,
            max_rounds=2,
        )
        task_ep.announce(
            concept_id=task_ep.winning_position_key,
            posterior=task_ep.mpc,
            gar=task_ep.gar,
            scr=task_ep.scr,
        )

        snp_trace = task_ep.snp_trace
        winning_position = task_ep.winning_position
        resolution_label = task_ep.resolution_label or "timeout_majority"
        task_episode_id = task_ep.episode_id
        metrics = {"gar": task_ep.gar, "scr": task_ep.scr, "mpc": task_ep.mpc}
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
            panel_episode_id=task_episode_id,
        )

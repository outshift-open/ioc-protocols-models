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
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from SSTP.subprotocol.siep.src.panel import NetworkHandle
from SSTP.examples.hcpanel.domain import ClinicalDebateOutcome, SpecialistOpinion
from SSTP.l9 import L9, TaskworkParticipant


if TYPE_CHECKING:
    from SSTP.examples.hcpanel.specialists import SpecialistAgent
    from SSTP.examples.hcpanel.memory import HCPanelMemory
    from SSTP.examples.hcpanel.domain import PatientProfile

from SSTP.examples.hcpanel.specialists import ROLE_DESCRIPTIONS

LOGGER = logging.getLogger("hcpanel")

_CONTROLLER_ID = "diagnostics-controller"


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


class DebateOrchestrator:
    """Runs the joint panel negotiation for one patient episode."""

    def __init__(
        self,
        specialists: 'List["SpecialistAgent"]',
        memory: "HCPanelMemory",
        message_bus: NetworkHandle,
        llm_factory: Optional[Any] = None,
        repair_fn: Optional[Any] = None,
        llm: Optional[Any] = None,
    ) -> None:
        self.specialists = specialists
        self.memory = memory
        self.message_bus = message_bus
        self._llm_factory = llm_factory
        self.repair_fn = repair_fn
        self.llm = llm

    def run_joint_panel(
        self,
        patient: "PatientProfile",
        episode_id: str,
    ) -> ClinicalDebateOutcome:
        all_specialists = self.specialists
        specialist_map = {a.agent_id: a for a in all_specialists}
        all_ids = [a.agent_id for a in all_specialists]

        # ── TP-1: case-specific session objective and role assignments ───
        case_frame: Dict[str, Any] = {}
        if self.llm is not None:
            try:
                case_frame = self.llm.complete_json("tp_case_frame", {
                    "caller_id": _CONTROLLER_ID,
                    "patient_id": patient.patient_id,
                    "symptoms": patient.symptoms,
                    "health_history": patient.health_history,
                    "current_medications": patient.current_medications,
                    "available_specialists": [
                        {"agent_id": a.agent_id, "role": a.role, "panel": a.panel}
                        for a in all_specialists
                    ],
                })
            except Exception as exc:
                LOGGER.warning("tp_case_frame failed: %s", exc)

        session_objective: str = case_frame.get(
            "session_objective",
            "joint clinical debate: patient symptom assessment, drug interaction risk, "
            "drug change proposals, and joint recommendation",
        )
        primary_question: str = case_frame.get("primary_question", "")
        responsible_for: Dict[str, List[str]] = case_frame.get("responsible_for") or {}

        case_brief = {
            "symptoms": patient.symptoms,
            "medications": patient.current_medications,
        }

        episode_tp = f"{episode_id}:tp"
        episode_tw = f"{episode_id}:tw"

        # Build peer-description map for L9 ToM seeding — role descriptions
        # are domain knowledge; L9 handles all seed_peer calls internally.
        peer_descriptions = {
            a.agent_id: ROLE_DESCRIPTIONS.get(a.role, a.role)
            for a in all_specialists
        }

        # Controller L9 — tom_engine and peer_descriptions are wired in here so
        # all ToM seeding and assessment happen inside the episode API.
        # Neither specialists nor orchestration logic ever touch tom_engine directly.
        ctrl_l9 = L9(
            self.message_bus,
            agent_id=_CONTROLLER_ID,
            llm_factory=self._llm_factory,
            task_goal=session_objective,
            peer_descriptions=peer_descriptions,
        )

        # ── EPISODE A: team process ──────────────────────────────────────
        # TP-2: SNP callbacks for TeamProcessEpisode governance debate
        current_team_process: Dict[str, Any] = {
                "session_objective": session_objective,
                "primary_question": primary_question,
                "prior_establishment": (
                    "Before debate, each specialist independently declares a taskwork prior: "
                    "their initial likelihood estimate for the primary question based on their "
                    "domain expertise alone, without peer influence. Priors are collected in a "
                    "dedicated taskwork episode so that baseline beliefs are on record before "
                    "any exchange occurs."
                ),
                "debate_format": (
                    "Debate is a structured negotiation protocol (SNP). The coordinator "
                    "synthesises all priors into a controller position and opens a panel. "
                    "Each specialist may accept or counter the controller position with a "
                    "competing proposal. Rounds continue until consensus is reached or the "
                    "maximum round limit is exhausted."
                ),
                "contingency_rules": {
                    "description": (
                        "A contingency is raised when a specialist's counter-proposal cannot "
                        "be resolved within the current exchange round. The contingency episode "
                        "captures the unresolved disagreement and triggers a repair pass. If "
                        "the repair pass produces agreement the session resumes; if not, the "
                        "contingency escalates to the deadlock rule below."
                    ),
                    "deadlock_rule": "casting_vote",
                    "casting_vote_holder": _CONTROLLER_ID,
                    "human_escalation_threshold": 0.6,
                },
                "no_convergence_handling": (
                    f"If the panel fails to reach full consensus after all SNP rounds, "
                    f"the session resolves by majority rule: the position held by the "
                    f"largest coalition of specialists is adopted. If no majority exists "
                    f"(tie), the casting vote of {_CONTROLLER_ID} is applied. "
                    f"If the winning position's confidence remains below "
                    f"{0.6} after casting vote, the case is flagged for human escalation "
                    f"and the session closes with resolution_label=human_escalation."
                ),
        }

        def _tp_pivot_fn(
            ctrl_pos: Dict[str, Any],
            counter_list: List[Dict[str, Any]],
            accept_list: List[Dict[str, Any]],
            task_goal: str,
        ) -> Dict[str, Any]:
            if self.llm is None:
                return ctrl_pos
            try:
                result = self.llm.complete_json("tp_debate_pivot_synthesis", {
                    "governance_terms": ctrl_pos.get("team_process_terms", {}),
                    "counter_proposals": [
                        {"agent_id": c.get("agent_id"), "concerns": c.get("rationale", "")}
                        for c in counter_list
                    ],
                    "task_goal": task_goal,
                })
                return {
                    **ctrl_pos,
                    "team_process_terms": result.get(
                        "revised_governance_terms",
                        ctrl_pos.get("team_process_terms", {}),
                    ),
                    "confidence": float(result.get("confidence", 0.9)),
                    "rationale": result.get("rationale", ""),
                }
            except Exception as exc:
                LOGGER.warning("tp_debate_pivot_synthesis failed: %s", exc)
                return ctrl_pos

        def _tp_commit_fn(winning_position: Dict[str, Any], resolution_label: str) -> None:
            final_terms = winning_position.get("team_process_terms", current_team_process)
            for sid in all_ids:
                agent = specialist_map.get(sid)
                if agent is not None:
                    agent.set_process_params({
                        "session_objective": final_terms.get("session_objective", session_objective),
                        "debate_format": final_terms.get("debate_format", ""),
                        "contingency_rules": final_terms.get("contingency_rules", {}),
                        "no_convergence_handling": final_terms.get("no_convergence_handling", ""),
                        "role_assignment": responsible_for.get(sid, []),
                        "governance_resolution": resolution_label,
                    })

        ctrl_l9.run_team_process(
            concept_id=patient.patient_id,
            group=all_ids,
            episode_id=episode_tp,
            task_goal=session_objective,
            rationale=(
                f"Opening team process for patient {patient.patient_id}: "
                f"governance debate with {len(all_ids)} specialists."
            ),
            thought_summary=(
                f"SNP governance debate: {len(all_ids)} specialists converge on team process."
            ),
            team_process=current_team_process,
            pivot_fn=_tp_pivot_fn,
            commit_fn=_tp_commit_fn,
            convergence_store=self.memory.convergence_store,
            semantic_rule_store=self.memory.semantic_rule_store,
            close_rationale=(
                f"Team process governance converged for patient {patient.patient_id}. "
                f"All {len(all_ids)} specialists have agreed process terms."
            ),
            close_thought_summary="Governance SNP complete; proceeding to taskwork.",
        )

        # ── EPISODE B: taskwork assessments ─────────────────────────────
        coordinator_framing = (
            f"{session_objective}: {primary_question}" if primary_question
            else session_objective
        )

        for a in all_specialists:
            a.set_patient(patient)

        participants = [
            TaskworkParticipant(
                agent_id=a.agent_id,
                utterance="",
                posterior=0.5,
                concept_id=f"urn:concept:healthcare:{patient.patient_id}",
                role=a.role,
            )
            for a in all_specialists
        ]

        tw_result = ctrl_l9.run_taskwork(
            concept_id=patient.patient_id,
            group=all_ids,
            episode_id=episode_tw,
            participants=participants,
            task_goal=session_objective,
            coordinator_id=_CONTROLLER_ID,
            team_process={
                "symptoms": patient.symptoms,
                "medications": patient.current_medications,
                "chat_history": patient.chat_history,
            },
            rationale=(
                f"Opening taskwork for patient {patient.patient_id}: "
                f"collecting independent priors from {len(all_ids)} specialists."
            ),
            thought_summary="Each specialist must declare their prior before peer exchange begins.",
            coordinator_framing=coordinator_framing,
            close_rationale=(
                f"Independent priors declared by all {len(all_ids)} specialists for patient "
                f"{patient.patient_id}. Each agent has stated its position before peer exchange — "
                f"baseline beliefs are on record."
            ),
            close_thought_summary=(
                f"All {len(all_ids)} prior declarations received; "
                f"taskwork baseline established, proceeding to panel debate."
            ),
        )

        # Collect positions from participants updated by assess_fn
        all_positions: Dict[str, Any] = {
            p.agent_id: {
                "likely_cause": p.likely_cause or "drug_interaction",
                "confidence": p.posterior,
                "posterior": p.posterior,
                "rationale": p.rationale,
                "supporting_evidence": p.evidence or [],
                "reasoning_summary": p.rationale,
                "thought_summary": p.thought_summary,
            }
            for p in tw_result.participants
        }

        # ── EPISODE C: SIEP panel negotiation ───────────────────────────
        # TW-5: controller synthesis from all declarations via LLM
        controller_position: Dict[str, Any] = {}
        if self.llm is not None:
            try:
                synthesis = self.llm.complete_json("debate_controller_synthesis", {
                    "declarations": [
                        {
                            "agent_id": p.agent_id,
                            "likely_cause": p.likely_cause or "drug_interaction",
                            "confidence": p.posterior,
                            "rationale": p.rationale,
                            "panel": specialist_map[p.agent_id].panel,
                        }
                        for p in tw_result.participants
                    ],
                    "session_objective": session_objective,
                    "case_brief": case_brief,
                })
                controller_position = {
                    "likely_cause": synthesis["proposed_concept"],
                    "confidence": float(synthesis["confidence"]),
                    "posterior": float(synthesis["confidence"]),
                    "supporting_evidence": synthesis.get("supporting_evidence", []),
                    "rationale": synthesis.get("rationale", ""),
                    "addresses_evidence": synthesis.get("addresses_counterevidence", []),
                    "reasoning_summary": synthesis.get("rationale", ""),
                }
            except Exception as exc:
                LOGGER.warning("debate_controller_synthesis failed: %s", exc)

        if not controller_position:
            # Fallback: plurality of likely_cause across all specialists
            from collections import Counter as _Counter
            cause_counts = _Counter(p.likely_cause or "drug_interaction" for p in tw_result.participants)
            leading_cause = cause_counts.most_common(1)[0][0]
            all_confs = [
                p.posterior for p in tw_result.participants
                if (p.likely_cause or "drug_interaction") == leading_cause
            ]
            ctrl_conf = round(sum(all_confs) / len(all_confs) if all_confs else 0.65, 4)
            controller_position = {
                "likely_cause": leading_cause,
                "confidence": ctrl_conf,
                "posterior": ctrl_conf,
                "supporting_evidence": [leading_cause],
                "rationale": f"Plurality position: {leading_cause} ({len(all_confs)}/{len(all_ids)})",
                "reasoning_summary": f"Plurality position: {leading_cause}",
            }

        LOGGER.info(
            "debate.panel_open episode=%s controller_position=%s confidence=%.4f members=%d",
            episode_id, controller_position.get("likely_cause"), controller_position.get("confidence"), len(all_ids),
        )

        def _pivot_fn(
            ctrl_pos: Dict[str, Any],
            counter_list: List[Dict[str, Any]],
            accept_list: List[Dict[str, Any]],
            task_goal: str,
        ) -> Dict[str, Any]:
            if self.llm is None:
                return ctrl_pos
            try:
                result = self.llm.complete_json("debate_pivot_synthesis", {
                    "original_position": ctrl_pos,
                    "counter_proposals": counter_list,
                    "accept_positions": accept_list,
                    "task_goal": task_goal,
                })
                return {
                    "likely_cause": result["revised_concept"],
                    "confidence": float(result["revised_confidence"]),
                    "posterior": float(result["revised_confidence"]),
                    "rationale": result.get("rationale", ""),
                    "supporting_evidence": result.get("supporting_evidence", []),
                    "addresses_evidence": result.get("addresses_evidence", []),
                    "reasoning_summary": result.get("rationale", ""),
                }
            except Exception as exc:
                LOGGER.warning("debate_pivot_synthesis failed: %s", exc)
                return ctrl_pos

        task_result = ctrl_l9.run_task(
            concept_id=f"urn:concept:healthcare:{controller_position.get('likely_cause', 'unknown')}",
            group=all_ids,
            controller_position=controller_position,
            specialist_positions=all_positions,
            task_goal=session_objective,
            accept_threshold=0.1,
            max_rounds=2,
            convergence_store=self.memory.convergence_store,
            semantic_rule_store=self.memory.semantic_rule_store,
            repair_fn=self.repair_fn,
            task_name="hcpanel",
            pivot_fn=_pivot_fn,
        )

        winning_position = task_result.winning_position
        resolution_label = task_result.resolution_label
        task_episode_id = task_result.episode_id
        metrics = {"gar": task_result.gar, "scr": task_result.scr, "mpc": task_result.mpc}
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
        for pos in all_positions.values():
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
            panel_episode_id=task_episode_id,
        )

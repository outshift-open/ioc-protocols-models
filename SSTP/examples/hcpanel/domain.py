from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict


@dataclass
class PatientProfile:
    patient_id: str
    locality: str
    symptoms: List[str]
    health_history: List[str]
    current_medications: List[str]
    medication_allergies: List[str]
    insurance_plan: str
    chat_history: List[str]
    calendar_slots_day_offsets: List[int]


@dataclass
class SpecialistOpinion:
    specialist_id: str
    specialty: str
    panel: str                   # "physician" | "pharmacology"
    symptom_assessment: str
    drug_change_proposal: str
    confidence: float
    reasoning: str
    likely_cause: str = "drug_interaction"
    posterior: float = 0.5
    supporting_evidence: List[str] = field(default_factory=list)


@dataclass
class ClinicalDebateOutcome:
    patient_id: str
    symptom_conclusion: str
    drug_interaction_risk: float
    proposed_drug_changes: List[str]
    joint_recommendation: str
    gar: float                   # genuine agreement ratio from SIEP convergence
    scr: float                   # social compliance ratio
    mpc: float                   # mean position confidence
    resolution_label: str        # "consensus" | "majority" | "timeout_majority"
    specialist_opinions: List[SpecialistOpinion] = field(default_factory=list)
    debate_log: List[str] = field(default_factory=list)
    panel_episode_id: str = ""    # PanelBus URN — used by _node_coordination to cite the SIEP episode


@dataclass
class HealthcareEpisode:
    """Minimal episode record for hcpanel (no insurance/scheduling)."""
    episode_id: str
    patient_id: str
    outcome: Optional[ClinicalDebateOutcome]
    wire_trace: List[Dict[str, Any]] = field(default_factory=list)
    orchestration_log: List[str] = field(default_factory=list)
    llm_trace: List[Dict[str, Any]] = field(default_factory=list)
    timestamp_unix: int = 0


class DebateGraphState(TypedDict):
    patient: PatientProfile
    episode_id: str
    run_id: str
    orchestration_log: List[str]
    wire_trace: List[Dict[str, Any]]
    outcome: Optional[ClinicalDebateOutcome]
    error: Optional[str]

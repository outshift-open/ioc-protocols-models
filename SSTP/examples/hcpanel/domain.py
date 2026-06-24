from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict


AGENT_ROLES: Dict[str, str] = {
    "diagnostics": "Coordinate clinical assessment, evaluate patient symptoms and medication history, and route patients to appropriate specialists",
    "pharmacy": "Assess medication safety, identify drug interaction risks, and recommend dose adjustments for safe patient care",
    "insurance": "Verify insurance coverage, validate in-network providers, and assess out-of-pocket cost constraints for the patient",
    "scheduling": "Book specialist appointments, confirm availability, coordinate patient reminders, and ensure timely care delivery",
}

SNP_AGENT_ROLES: Dict[str, str] = {
    f"physician-reviewer-{i:02d}": "Review clinical case independently, provide diagnostic assessment, and contribute to panel consensus on specialist routing"
    for i in range(1, 6)
}


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
class SpecialistProvider:
    provider_id: str
    specialty: str
    locality: str
    in_network_plans: List[str]
    availability_day_offsets: List[int]


@dataclass
class DoctorAssessment:
    doctor_id: str
    likely_cause: str
    interaction_likelihood: float
    new_disease_likelihood: float
    confidence: float
    rationale: str
    review_mode: str = "independent"
    corroborated_by: List[str] = field(default_factory=list)


@dataclass
class ClinicalAssessment:
    likely_cause: str
    interaction_likelihood: float
    new_disease_likelihood: float
    confidence: float
    rationale: str
    panel_size: int = 1
    majority_size: int = 1
    vote_breakdown: Dict[str, int] = field(default_factory=dict)
    all_opinions_corroborated: bool = True
    doctor_assessments: List[DoctorAssessment] = field(default_factory=list)


@dataclass
class MedicationProposal:
    interaction_risks: List[str]
    proposed_changes: List[str]
    risk_score: float
    panel_size: int = 1
    majority_size: int = 1
    vote_breakdown: Dict[str, int] = field(default_factory=dict)
    reviewer_assessments: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class InsuranceDecision:
    in_network_only: bool
    approved_specialties: List[str]
    estimated_out_of_pocket_eur: float
    roi_score: float
    validation_note: str
    panel_size: int = 1
    majority_size: int = 1
    vote_breakdown: Dict[str, int] = field(default_factory=dict)
    reviewer_decisions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ScheduledAppointment:
    provider_id: str
    specialty: str
    day_offset: int
    reminder_plan: List[str]


@dataclass
class CarePlan:
    patient_id: str
    primary_action: str
    specialist: ScheduledAppointment
    clinical_assessment: ClinicalAssessment
    medication_proposal: MedicationProposal
    insurance_decision: InsuranceDecision
    explanation: str
    optimization_score: float
    compliant: bool


from SSTP.subprotocol.siep.src.tomcore.types import Turn  # noqa: F401 — re-exported for app consumers


@dataclass

class EpistemicProvenance:
    episode_ids: List[str]
    prior_rule_ids: List[str]
    genuine_assertion_ratio: float
    unresolved_challenge_ratio: float
    mean_panel_confidence: float
    social_compliance_ratio: float
    formation_summary: str


@dataclass
class ConceptNode:
    concept_id: str
    label: str
    aliases: List[str] = field(default_factory=list)


@dataclass
class ConceptEdge:
    source: str
    relation: str
    target: str
    weight: float = 1.0


@dataclass
class ConceptGraph:
    nodes: Dict[str, ConceptNode] = field(default_factory=dict)
    edges: List[ConceptEdge] = field(default_factory=list)

    def activate(self, presenting_concepts: List[str]) -> List[str]:
        """BFS from presenting concepts over edges → reachable concept_ids."""
        if not self.edges:
            return list(presenting_concepts)
        visited: set = set(presenting_concepts)
        frontier = list(presenting_concepts)
        while frontier:
            current = frontier.pop()
            for edge in self.edges:
                if edge.source == current and edge.target not in visited:
                    visited.add(edge.target)
                    frontier.append(edge.target)
        return list(visited)


@dataclass
class KnowledgeRule:
    rule_id: str
    description: str
    support: int
    confidence: float
    provenance: Optional[EpistemicProvenance] = None
    supported_by: List[str] = field(default_factory=list)
    against: List[str] = field(default_factory=list)
    hypothesis_tags: List[str] = field(default_factory=list)


@dataclass
class LikelihoodEntry:
    finding_id: str
    hypothesis_id: str
    specialist_role: str
    p_finding_given_h: float
    p_finding_given_not_h: float
    source: str = "elicited"
    confidence_in_estimate: float = 0.5


@dataclass
class LikelihoodTable:
    role: str
    entries: List["LikelihoodEntry"] = field(default_factory=list)
    last_calibrated_episode: Optional[str] = None

    def likelihood_ratio(self, finding_id: str, hypothesis_id: str) -> float:
        """P(finding|H) / P(finding|¬H). Returns 1.0 (neutral) if unknown."""
        for entry in self.entries:
            if entry.finding_id == finding_id and entry.hypothesis_id == hypothesis_id:
                if entry.p_finding_given_not_h <= 0:
                    return 5.0
                return round(entry.p_finding_given_h / entry.p_finding_given_not_h, 6)
        return 1.0


class HealthcareGraphState(TypedDict, total=False):
    patient: PatientProfile
    providers: List[SpecialistProvider]
    hard_max_out_of_pocket_eur: float
    semantic_rules: List[KnowledgeRule]

    turns: List[Turn]
    next_message_number: int
    peer_turns: List[Turn]
    peer_interactions: List[Dict[str, Any]]
    llm_trace: List[Dict[str, Any]]
    orchestration_log: List[str]
    tom_trace: List[Dict[str, float]]
    customer_alignment: List[Dict[str, Any]]
    peer_alignment_events: List[Dict[str, Any]]
    pairwise_agent_tom: Dict[str, Any]
    patient_belief: Dict[str, Any]
    out_of_bound_events: List[Dict[str, Any]]
    conversation_terminated: bool
    conversation_error: Dict[str, Any]
    coordination_summary: Dict[str, Any]

    diagnostics: ClinicalAssessment
    pharmacy: MedicationProposal
    insurance: InsuranceDecision
    scheduling: ScheduledAppointment
    care_plan: CarePlan
    inter_agent_tom: Dict[str, Any]
    accepted_route: bool
    rejection_reason: str | None

    tom_task_description: str
    peer_task_description: str
    inter_agent_task_description: str
    agent_messages: List[Dict[str, Any]]
    snp_trace: List[Dict[str, Any]]
    panel_snapshots: Dict[str, Any]

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
    snp_trace: List[Dict[str, Any]] = field(default_factory=list)
    panel_episode_id: str = ""    # PanelBus URN — used by _node_coordination to cite the SNP episode


@dataclass
class HealthcareEpisode:
    """Minimal episode record for hcpanel (no insurance/scheduling)."""
    episode_id: str
    patient_id: str
    outcome: Optional[ClinicalDebateOutcome]
    agent_messages: List[Dict[str, Any]] = field(default_factory=list)
    snp_trace: List[Dict[str, Any]] = field(default_factory=list)
    orchestration_log: List[str] = field(default_factory=list)
    llm_trace: List[Dict[str, Any]] = field(default_factory=list)
    timestamp_unix: int = 0


class DebateGraphState(TypedDict):
    patient: PatientProfile
    episode_id: str
    run_id: str
    orchestration_log: List[str]
    agent_messages: List[Dict[str, Any]]
    snp_trace: List[Dict[str, Any]]
    outcome: Optional[ClinicalDebateOutcome]
    error: Optional[str]
    # Passed from orchestrate → joint_panel
    physician_positions: Dict[str, Any]
    pharmacy_positions: Dict[str, Any]

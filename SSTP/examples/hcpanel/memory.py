from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

from SSTP.examples.hcpanel.domain import ConceptGraph, EpistemicProvenance, HealthcareEpisode, KnowledgeRule, LikelihoodEntry, LikelihoodTable
from SSTP.examples.hcpanel.interaction_semantics import canonicalize_interaction_entries
from SSTP.subprotocol.siep.src.epistemic.stores import (
    AgentBeliefStore, ArgumentOutcome, BeliefRevision, BeliefState,
    ConvergenceStore, PeerInteractionRecord, PeerInteractionStore,
    PredictionRecord, SemanticRule, SemanticRuleStore,
    TaskworkStore,
)
from SSTP.subprotocol.siep.src.epistemic.stores import TeamProcessStore

LOGGER = logging.getLogger("healthcare2")


def _episode_from_dict(data: Dict[str, Any]) -> HealthcareEpisode:
    from SSTP.examples.hcpanel.domain import (
        CarePlan,
        ClinicalAssessment,
        DoctorAssessment,
        InsuranceDecision,
        MedicationProposal,
        ScheduledAppointment,
        Turn,
    )

    care_plan_data = data.get("care_plan", {}) if isinstance(data.get("care_plan"), dict) else {}
    specialist_data = care_plan_data.get("specialist", {}) if isinstance(care_plan_data.get("specialist"), dict) else {}
    clinical_data = care_plan_data.get("clinical_assessment", {}) if isinstance(care_plan_data.get("clinical_assessment"), dict) else {}
    medication_data = care_plan_data.get("medication_proposal", {}) if isinstance(care_plan_data.get("medication_proposal"), dict) else {}
    insurance_data = care_plan_data.get("insurance_decision", {}) if isinstance(care_plan_data.get("insurance_decision"), dict) else {}
    doctor_assessments_data = clinical_data.get("doctor_assessments", []) if isinstance(clinical_data.get("doctor_assessments"), list) else []
    doctor_assessments = [
        DoctorAssessment(
            doctor_id=str(item.get("doctor_id", f"doctor-{index + 1:02d}")),
            likely_cause=str(item.get("likely_cause", clinical_data.get("likely_cause", "drug_interaction"))),
            interaction_likelihood=float(item.get("interaction_likelihood", clinical_data.get("interaction_likelihood", 0.5))),
            new_disease_likelihood=float(item.get("new_disease_likelihood", clinical_data.get("new_disease_likelihood", 0.5))),
            confidence=float(item.get("confidence", clinical_data.get("confidence", 0.5))),
            rationale=str(item.get("rationale", "")),
            review_mode=str(item.get("review_mode", "independent")),
            corroborated_by=[str(member) for member in item.get("corroborated_by", [])],
        )
        for index, item in enumerate(doctor_assessments_data)
        if isinstance(item, dict)
    ]
    vote_breakdown = (
        {str(key): int(value) for key, value in clinical_data.get("vote_breakdown", {}).items()}
        if isinstance(clinical_data.get("vote_breakdown"), dict)
        else {}
    )
    panel_size_value = clinical_data.get("panel_size")
    majority_size_value = clinical_data.get("majority_size")
    panel_size = int(panel_size_value) if isinstance(panel_size_value, (int, float)) else (len(doctor_assessments) or 1)
    majority_size = (
        int(majority_size_value)
        if isinstance(majority_size_value, (int, float))
        else (max(vote_breakdown.values()) if vote_breakdown else panel_size)
    )
    if not vote_breakdown and panel_size > 0:
        vote_breakdown = {str(clinical_data.get("likely_cause", "drug_interaction")): majority_size}

    medication_vote_breakdown = (
        {str(key): int(value) for key, value in medication_data.get("vote_breakdown", {}).items()}
        if isinstance(medication_data.get("vote_breakdown"), dict)
        else {}
    )
    medication_panel_size = int(medication_data.get("panel_size", 1))
    medication_majority_size = int(medication_data.get("majority_size", medication_panel_size))
    reviewer_assessments = [
        item
        for item in medication_data.get("reviewer_assessments", [])
        if isinstance(item, dict)
    ]

    insurance_vote_breakdown = (
        {str(key): int(value) for key, value in insurance_data.get("vote_breakdown", {}).items()}
        if isinstance(insurance_data.get("vote_breakdown"), dict)
        else {}
    )
    insurance_panel_size = int(insurance_data.get("panel_size", 1))
    insurance_majority_size = int(insurance_data.get("majority_size", insurance_panel_size))
    reviewer_decisions = [
        item
        for item in insurance_data.get("reviewer_decisions", [])
        if isinstance(item, dict)
    ]

    care_plan = CarePlan(
        patient_id=str(care_plan_data.get("patient_id", data.get("patient_id", "unknown"))),
        primary_action=str(care_plan_data.get("primary_action", "route_patient")),
        specialist=ScheduledAppointment(
            provider_id=str(specialist_data.get("provider_id", "waitlist")),
            specialty=str(specialist_data.get("specialty", "general_medicine")),
            day_offset=int(specialist_data.get("day_offset", 7)),
            reminder_plan=[str(item) for item in specialist_data.get("reminder_plan", [])],
        ),
        clinical_assessment=ClinicalAssessment(
            likely_cause=str(clinical_data.get("likely_cause", "drug_interaction")),
            interaction_likelihood=float(clinical_data.get("interaction_likelihood", 0.5)),
            new_disease_likelihood=float(clinical_data.get("new_disease_likelihood", 0.5)),
            confidence=float(clinical_data.get("confidence", 0.5)),
            rationale=str(clinical_data.get("rationale", "")),
            panel_size=panel_size,
            majority_size=majority_size,
            vote_breakdown=vote_breakdown,
            all_opinions_corroborated=bool(
                clinical_data.get(
                    "all_opinions_corroborated",
                    not doctor_assessments or all(len(assessment.corroborated_by) >= 1 for assessment in doctor_assessments),
                )
            ),
            doctor_assessments=doctor_assessments,
        ),
        medication_proposal=MedicationProposal(
            interaction_risks=[str(item) for item in medication_data.get("interaction_risks", [])],
            proposed_changes=[str(item) for item in medication_data.get("proposed_changes", [])],
            risk_score=float(medication_data.get("risk_score", 0.0)),
            panel_size=medication_panel_size,
            majority_size=medication_majority_size,
            vote_breakdown=medication_vote_breakdown,
            reviewer_assessments=reviewer_assessments,
        ),
        insurance_decision=InsuranceDecision(
            in_network_only=bool(insurance_data.get("in_network_only", True)),
            approved_specialties=[str(item) for item in insurance_data.get("approved_specialties", [])],
            estimated_out_of_pocket_eur=float(insurance_data.get("estimated_out_of_pocket_eur", 0.0)),
            roi_score=float(insurance_data.get("roi_score", 0.0)),
            validation_note=str(insurance_data.get("validation_note", "")),
            panel_size=insurance_panel_size,
            majority_size=insurance_majority_size,
            vote_breakdown=insurance_vote_breakdown,
            reviewer_decisions=reviewer_decisions,
        ),
        explanation=str(care_plan_data.get("explanation", "")),
        optimization_score=float(care_plan_data.get("optimization_score", 0.0)),
        compliant=bool(care_plan_data.get("compliant", True)),
    )

    turns = [
        Turn(
            speaker=str(item.get("speaker", "unknown")),
            utterance=str(item.get("utterance", "")),
            inferred_intent=str(item.get("inferred_intent", "clinical_context")),
            timestamp_ms=int(item.get("timestamp_ms", 0)),
            message_number=int(item.get("message_number", 0)),
            repaired=bool(item.get("repaired", False)),
        )
        for item in data.get("turns", [])
        if isinstance(item, dict)
    ]

    raw_rejection_reason = data.get("rejection_reason")
    rejection_reason = str(raw_rejection_reason) if raw_rejection_reason not in (None, "") else None
    panel_snapshots = data.get("panel_snapshots", {})
    if not isinstance(panel_snapshots, dict):
        panel_snapshots = {}

    return HealthcareEpisode(
        episode_id=str(data.get("episode_id", str(uuid.uuid4()))),
        patient_id=str(data.get("patient_id", "unknown")),
        locality=str(data.get("locality", "unknown")),
        initial_patient_request=str(data.get("initial_patient_request", "")),
        accepted_route=bool(data.get("accepted_route", False)),
        care_plan=care_plan,
        turns=turns,
        peer_interactions=[item for item in data.get("peer_interactions", []) if isinstance(item, dict)],
        agent_messages=[item for item in data.get("agent_messages", []) if isinstance(item, dict)],
        snp_trace=[item for item in data.get("snp_trace", []) if isinstance(item, dict)],
        llm_trace=[item for item in data.get("llm_trace", []) if isinstance(item, dict)],
        tom_trace=[row for row in data.get("tom_trace", []) if isinstance(row, dict)],
        orchestration_log=[str(item) for item in data.get("orchestration_log", [])],
        inter_agent_tom=data.get("inter_agent_tom", {}) if isinstance(data.get("inter_agent_tom"), dict) else {},
        discovered_interactions=canonicalize_interaction_entries(
            [str(item) for item in data.get("discovered_interactions", [])]
        ),
        semantic_rules_applied=[item for item in data.get("semantic_rules_applied", []) if isinstance(item, dict)],
        specialist_routed=str(data.get("specialist_routed", care_plan.specialist.specialty)),
        timestamp_unix=int(data.get("timestamp_unix", int(time.time()))),
        rejection_reason=rejection_reason,
        panel_snapshots=panel_snapshots,
        episode_findings=[str(item) for item in data.get("episode_findings", []) if isinstance(item, str)],
    )


def _provenance_from_dict(data: Any) -> EpistemicProvenance | None:
    if not isinstance(data, dict):
        return None
    return EpistemicProvenance(
        episode_ids=[str(x) for x in data.get("episode_ids", [])],
        prior_rule_ids=[str(x) for x in data.get("prior_rule_ids", [])],
        genuine_assertion_ratio=float(data.get("genuine_assertion_ratio", 0.0)),
        unresolved_challenge_ratio=float(data.get("unresolved_challenge_ratio", 0.0)),
        mean_panel_confidence=float(data.get("mean_panel_confidence", 0.0)),
        social_compliance_ratio=float(data.get("social_compliance_ratio", 0.0)),
        formation_summary=str(data.get("formation_summary", "")),
    )


def _rule_from_dict(data: Dict[str, Any]) -> KnowledgeRule:
    return KnowledgeRule(
        rule_id=str(data.get("rule_id", "rule-unknown")),
        description=str(data.get("description", "")),
        support=int(data.get("support", 0)),
        confidence=float(data.get("confidence", 0.0)),
        provenance=_provenance_from_dict(data.get("provenance")),
        hypothesis_tags=[str(t) for t in data.get("hypothesis_tags", []) if isinstance(t, str)],
    )


class EpisodicMemory:
    def __init__(self) -> None:
        self.episodes: List[HealthcareEpisode] = []

    def add(self, episode: HealthcareEpisode) -> None:
        self.episodes.append(episode)

    def recent(self, n: int = 100) -> List[HealthcareEpisode]:
        return self.episodes[-n:]


class KnowledgeMemory:
    def __init__(self) -> None:
        self.rules: List[KnowledgeRule] = []
        self.discovered_interactions: List[str] = []
        self.specialist_network_notes: List[str] = []

    def refresh_from_episodes(
        self,
        episodes: List[HealthcareEpisode],
        semantic_rule_store: Any = None,
        use_case: str = "healthcare",
    ) -> None:
        if not episodes:
            return

        interaction_counts: Dict[str, int] = {}
        specialist_counts: Dict[str, int] = {}
        acceptance_rate = mean(1.0 if episode.accepted_route else 0.0 for episode in episodes)

        for episode in episodes:
            specialist_counts[episode.specialist_routed] = specialist_counts.get(episode.specialist_routed, 0) + 1
            for interaction in canonicalize_interaction_entries(episode.discovered_interactions):
                interaction_counts[interaction] = interaction_counts.get(interaction, 0) + 1

        # Compute epistemic signals from panel_snapshots
        episode_ids = [e.episode_id for e in episodes]
        prior_rule_ids = [r.rule_id for r in self.rules]

        taskwork_total = 0
        taskwork_assertions = 0
        interp_delib_passes = 0
        interp_accepts_total = 0
        unresolved_episodes = 0
        panel_confidences: List[float] = []

        for episode in episodes:
            for snap_data in episode.panel_snapshots.values():
                if isinstance(snap_data, dict):
                    ds = snap_data.get("derived_state", {})
                    phase_counts = ds.get("phase_counts", {})
                    tw = phase_counts.get("taskwork", 0)
                    taskwork_total += tw
                    tir = ds.get("taskwork_independence_ratio", 1.0)
                    taskwork_assertions += int(round(tir * tw))
                    scr = ds.get("social_compliance_ratio", 0.0)
                    ip = phase_counts.get("interpersonal", 0)
                    if ip > 0:
                        interp_delib_passes += int(round(scr * ip))
                        interp_accepts_total += ip
                    conf = ds.get("epistemic_strength")
                    if isinstance(conf, float):
                        panel_confidences.append(conf)
            snp_msgs = episode.snp_trace or []
            ep_unresolved = any(
                isinstance(m, dict) and
                isinstance(m.get("epistemic"), dict) and
                m["epistemic"].get("belief_status") == "unresolved"
                for m in snp_msgs
            )
            if ep_unresolved:
                unresolved_episodes += 1

        genuine_assertion_ratio = taskwork_assertions / taskwork_total if taskwork_total > 0 else 1.0
        social_compliance_ratio = interp_delib_passes / interp_accepts_total if interp_accepts_total > 0 else 0.0
        unresolved_challenge_ratio = unresolved_episodes / len(episodes) if episodes else 0.0
        mean_panel_confidence = mean(panel_confidences) if panel_confidences else acceptance_rate

        def _make_provenance(rule_id: str, n: int) -> EpistemicProvenance:
            return EpistemicProvenance(
                episode_ids=episode_ids,
                prior_rule_ids=[rid for rid in prior_rule_ids if rid != rule_id],
                genuine_assertion_ratio=round(genuine_assertion_ratio, 4),
                unresolved_challenge_ratio=round(unresolved_challenge_ratio, 4),
                mean_panel_confidence=round(mean_panel_confidence, 4),
                social_compliance_ratio=round(social_compliance_ratio, 4),
                formation_summary=(
                    f"Derived from {n} episodes. "
                    f"Taskwork assertion ratio: {genuine_assertion_ratio:.2f}. "
                    f"Social compliance ratio: {social_compliance_ratio:.2f}. "
                    f"Unresolved challenges: {unresolved_challenge_ratio:.2f}. "
                    f"Informed by rules: {prior_rule_ids or 'none'}."
                ),
            )

        routing_rule_id = f"routing-acceptance-{len(episodes)}"
        rules: List[KnowledgeRule] = [
            KnowledgeRule(
                rule_id=routing_rule_id,
                description=f"Recent routing acceptance rate={acceptance_rate:.2f}",
                support=len(episodes),
                confidence=min(0.99, 0.55 + len(episodes) / 180.0),
                provenance=_make_provenance(routing_rule_id, len(episodes)),
                hypothesis_tags=[],
            )
        ]

        for interaction, support in sorted(interaction_counts.items(), key=lambda item: item[1], reverse=True):
            rule_id = f"interaction-{abs(hash(interaction)) % 100000}"
            rules.append(
                KnowledgeRule(
                    rule_id=rule_id,
                    description=f"Observed interaction pattern: {interaction}",
                    support=support,
                    confidence=min(0.99, 0.5 + support / 50.0),
                    provenance=_make_provenance(rule_id, support),
                    hypothesis_tags=["drug_interaction"],
                )
            )

        for specialty, support in sorted(specialist_counts.items(), key=lambda item: item[1], reverse=True):
            rule_id = f"specialist-{specialty}-{support}"
            rules.append(
                KnowledgeRule(
                    rule_id=rule_id,
                    description=f"Specialty routing volume: {specialty} support={support}",
                    support=support,
                    confidence=min(0.99, 0.5 + support / 60.0),
                    provenance=_make_provenance(rule_id, support),
                    hypothesis_tags=[],
                )
            )

        # AF2: blend SemanticRule convergence posteriors into KnowledgeRule confidence.
        # hypothesis_tag "drug_interaction" → concept "urn:concept:{use_case}:drug_interaction".
        # Blended 40% formula / 60% team-converged posterior so rules improve with experience.
        if semantic_rule_store is not None:
            from dataclasses import replace as _dc_replace
            for _i, _rule in enumerate(rules):
                for _tag in (_rule.hypothesis_tags or []):
                    _cid = f"urn:concept:{use_case}:{_tag}"
                    _sem = semantic_rule_store.latest(_cid, use_case)
                    if _sem is not None:
                        _blended = round(min(0.99, 0.4 * _rule.confidence + 0.6 * _sem.confidence), 4)
                        _desc_suffix = (
                            f" | converged@{_sem.confidence:.2f}: {_sem.description}"
                            if _sem.description else f" | converged@{_sem.confidence:.2f}"
                        )
                        rules[_i] = _dc_replace(
                            rules[_i],
                            confidence=_blended,
                            description=rules[_i].description + _desc_suffix,
                        )
                        break

        self.rules = rules
        self.discovered_interactions = sorted(interaction_counts.keys())
        self.specialist_network_notes = [
            f"{specialty}: routed {count} patients"
            for specialty, count in sorted(specialist_counts.items(), key=lambda item: item[1], reverse=True)
        ]


def activate_rules(
    graph: ConceptGraph,
    rules: List[KnowledgeRule],
    presenting_concepts: List[str],
) -> List[KnowledgeRule]:
    """Return rules whose supported_by concepts overlap the activated concept set."""
    if not graph.edges:
        return list(rules)
    activated = set(graph.activate(presenting_concepts))
    filtered = [r for r in rules if set(r.supported_by) & activated]
    return filtered if filtered else list(rules)


# ── Layer 7: Bayesian Confidence ─────────────────────────────────────────────

_HYPOTHESES = ["drug_interaction", "new_disease"]

_BOOTSTRAP_ENTRIES: Dict[str, List[tuple]] = {
    "internal_medicine": [
        ("dizziness",          "drug_interaction", 0.70, 0.55),
        ("dizziness",          "new_disease",      0.60, 0.45),
        ("fatigue",            "drug_interaction", 0.68, 0.50),
        ("fatigue",            "new_disease",      0.58, 0.42),
        ("nausea",             "drug_interaction", 0.65, 0.48),
        ("nausea",             "new_disease",      0.52, 0.40),
        ("palpitations",       "drug_interaction", 0.55, 0.40),
        ("palpitations",       "new_disease",      0.60, 0.38),
        ("polypharmacy",       "drug_interaction", 0.80, 0.38),
        ("polypharmacy",       "new_disease",      0.42, 0.60),
        ("known_interaction",  "drug_interaction", 0.88, 0.30),
        ("known_interaction",  "new_disease",      0.32, 0.70),
        ("anticoagulant_use",  "drug_interaction", 0.72, 0.40),
        ("anticoagulant_use",  "new_disease",      0.44, 0.58),
        ("nsaid_use",          "drug_interaction", 0.68, 0.42),
        ("nsaid_use",          "new_disease",      0.46, 0.55),
        ("cardiac_history",    "drug_interaction", 0.38, 0.62),
        ("cardiac_history",    "new_disease",      0.72, 0.35),
        ("cns_history",        "drug_interaction", 0.40, 0.58),
        ("cns_history",        "new_disease",      0.68, 0.38),
        ("allergy_history",    "drug_interaction", 0.50, 0.50),
        ("allergy_history",    "new_disease",      0.55, 0.50),
    ],
    "clinical_pharmacology": [
        ("polypharmacy",       "drug_interaction", 0.92, 0.30),
        ("polypharmacy",       "new_disease",      0.30, 0.72),
        ("known_interaction",  "drug_interaction", 0.95, 0.20),
        ("known_interaction",  "new_disease",      0.22, 0.78),
        ("anticoagulant_use",  "drug_interaction", 0.86, 0.32),
        ("anticoagulant_use",  "new_disease",      0.34, 0.66),
        ("nsaid_use",          "drug_interaction", 0.82, 0.35),
        ("nsaid_use",          "new_disease",      0.38, 0.63),
        ("dizziness",          "drug_interaction", 0.74, 0.50),
        ("dizziness",          "new_disease",      0.52, 0.48),
        ("nausea",             "drug_interaction", 0.78, 0.45),
        ("nausea",             "new_disease",      0.46, 0.55),
    ],
    "cardiology": [
        ("cardiac_history",    "new_disease",      0.88, 0.25),
        ("cardiac_history",    "drug_interaction", 0.20, 0.75),
        ("palpitations",       "new_disease",      0.80, 0.35),
        ("palpitations",       "drug_interaction", 0.35, 0.65),
        ("fatigue",            "new_disease",      0.72, 0.38),
        ("fatigue",            "drug_interaction", 0.40, 0.60),
        ("polypharmacy",       "drug_interaction", 0.52, 0.48),
        ("polypharmacy",       "new_disease",      0.55, 0.48),
        ("dizziness",          "new_disease",      0.62, 0.42),
        ("dizziness",          "drug_interaction", 0.42, 0.58),
        # Anticoagulant + NSAID co-prescription overrides cardiac-first specialty priors.
        ("anticoagulant_use",  "drug_interaction", 0.85, 0.30),
        ("anticoagulant_use",  "new_disease",      0.28, 0.72),
        ("nsaid_use",          "drug_interaction", 0.80, 0.33),
        ("nsaid_use",          "new_disease",      0.30, 0.68),
    ],
    "neurology": [
        ("cns_history",        "new_disease",      0.85, 0.28),
        ("cns_history",        "drug_interaction", 0.25, 0.72),
        ("dizziness",          "new_disease",      0.78, 0.40),
        ("dizziness",          "drug_interaction", 0.42, 0.60),
        ("fatigue",            "new_disease",      0.65, 0.42),
        ("fatigue",            "drug_interaction", 0.45, 0.55),
        ("polypharmacy",       "drug_interaction", 0.58, 0.45),
        ("polypharmacy",       "new_disease",      0.50, 0.52),
        # Anticoagulant + NSAID co-prescription overrides CNS-first specialty priors.
        ("anticoagulant_use",  "drug_interaction", 0.85, 0.30),
        ("anticoagulant_use",  "new_disease",      0.28, 0.72),
        ("nsaid_use",          "drug_interaction", 0.80, 0.33),
        ("nsaid_use",          "new_disease",      0.30, 0.68),
    ],
    "immunology": [
        ("allergy_history",    "new_disease",      0.78, 0.35),
        ("allergy_history",    "drug_interaction", 0.38, 0.62),
        ("rash",               "new_disease",      0.72, 0.32),
        ("rash",               "drug_interaction", 0.35, 0.65),
        ("nausea",             "new_disease",      0.62, 0.45),
        ("nausea",             "drug_interaction", 0.50, 0.52),
        ("polypharmacy",       "drug_interaction", 0.55, 0.48),
        ("polypharmacy",       "new_disease",      0.52, 0.50),
        # Anticoagulant + NSAID co-prescription overrides immune-first specialty priors.
        ("anticoagulant_use",  "drug_interaction", 0.85, 0.30),
        ("anticoagulant_use",  "new_disease",      0.28, 0.72),
        ("nsaid_use",          "drug_interaction", 0.80, 0.33),
        ("nsaid_use",          "new_disease",      0.30, 0.68),
    ],
}


_PHARMACY_BOOTSTRAP_ENTRIES: Dict[str, List[tuple]] = {
    "pharmacokinetics": [
        ("polypharmacy",                "high",     0.75, 0.35),
        ("polypharmacy",                "moderate", 0.60, 0.45),
        ("polypharmacy",                "low",      0.28, 0.62),
        ("anticoagulant_present",       "high",     0.65, 0.38),
        ("anticoagulant_present",       "moderate", 0.58, 0.42),
        ("anticoagulant_nsaid_overlap", "high",     0.82, 0.30),
    ],
    "pharmacodynamics": [
        ("anticoagulant_nsaid_overlap", "high",     0.88, 0.28),
        ("anticoagulant_present",       "high",     0.72, 0.35),
        ("nsaid_present",               "moderate", 0.65, 0.40),
        ("polypharmacy",                "moderate", 0.62, 0.42),
        ("allergy_history",             "moderate", 0.55, 0.45),
    ],
    "clinical_pharmacy": [
        ("polypharmacy",                "high",     0.68, 0.38),
        ("polypharmacy",                "moderate", 0.62, 0.45),
        ("anticoagulant_present",       "moderate", 0.60, 0.42),
        ("nsaid_present",               "moderate", 0.60, 0.43),
        ("anticoagulant_nsaid_overlap", "high",     0.85, 0.28),
        ("allergy_history",             "moderate", 0.58, 0.46),
        ("high_allergy_count",          "high",     0.70, 0.35),
    ],
    "drug_safety": [
        ("anticoagulant_nsaid_overlap", "high",     0.92, 0.25),
        ("anticoagulant_present",       "high",     0.78, 0.32),
        ("high_allergy_count",          "high",     0.75, 0.30),
        ("polypharmacy",                "high",     0.70, 0.38),
        ("nsaid_present",               "moderate", 0.62, 0.44),
        ("allergy_history",             "moderate", 0.60, 0.44),
    ],
    "clinical_toxicology": [
        ("anticoagulant_nsaid_overlap", "high",     0.90, 0.20),
        ("high_allergy_count",          "high",     0.72, 0.30),
        ("polypharmacy",                "high",     0.68, 0.40),
        ("anticoagulant_present",       "high",     0.75, 0.35),
        ("nsaid_present",               "moderate", 0.58, 0.48),
    ],
}


def _bootstrap_likelihood_tables() -> Dict[str, LikelihoodTable]:
    """Return bootstrapped likelihood tables for all diagnostic and pharmacy specialist roles."""
    tables: Dict[str, LikelihoodTable] = {}
    for role, raw_entries in {**_BOOTSTRAP_ENTRIES, **_PHARMACY_BOOTSTRAP_ENTRIES}.items():
        entries = [
            LikelihoodEntry(
                finding_id=f,
                hypothesis_id=h,
                specialist_role=role,
                p_finding_given_h=ph,
                p_finding_given_not_h=pnh,
                source="elicited",
                confidence_in_estimate=0.5,
            )
            for f, h, ph, pnh in raw_entries
        ]
        tables[role] = LikelihoodTable(role=role, entries=entries)
    return tables


def compute_prior(activated_rules: List[KnowledgeRule], hypothesis_id: str) -> float:
    """Compute prior P(H) from activated semantic memory rules tagged with hypothesis_id.

    Falls back to 0.5 when no rules are tagged for this hypothesis.
    """
    if not activated_rules:
        return 0.5
    weights: List[float] = []
    for rule in activated_rules:
        prov = rule.provenance
        if prov is None:
            w = rule.confidence
        else:
            gar = getattr(prov, "genuine_agreement_ratio", 1.0) or 1.0
            scr = getattr(prov, "social_compliance_ratio", 0.0) or 0.0
            w = rule.confidence * max(0.0, (1.0 - scr) * gar)
        if hypothesis_id in rule.hypothesis_tags:
            weights.append(w)
    if not weights:
        return 0.5
    return round(min(0.95, max(0.05, sum(weights) / len(weights))), 4)


class LikelihoodStore:
    def __init__(self) -> None:
        self._tables: Dict[str, LikelihoodTable] = _bootstrap_likelihood_tables()

    def get(self, role: str) -> LikelihoodTable:
        return self._tables.get(role, LikelihoodTable(role=role))

    def all_roles(self) -> List[str]:
        return list(self._tables.keys())

    def update_entry(
        self,
        role: str,
        finding_id: str,
        hypothesis_id: str,
        p_finding_given_h: float,
        p_finding_given_not_h: float,
        source: str = "calibrated",
        confidence_in_estimate: float = 0.5,
    ) -> None:
        if role not in self._tables:
            self._tables[role] = LikelihoodTable(role=role)
        table = self._tables[role]
        for entry in table.entries:
            if entry.finding_id == finding_id and entry.hypothesis_id == hypothesis_id:
                entry.p_finding_given_h = p_finding_given_h
                entry.p_finding_given_not_h = p_finding_given_not_h
                entry.source = source
                entry.confidence_in_estimate = confidence_in_estimate
                return
        table.entries.append(LikelihoodEntry(
            finding_id=finding_id,
            hypothesis_id=hypothesis_id,
            specialist_role=role,
            p_finding_given_h=p_finding_given_h,
            p_finding_given_not_h=p_finding_given_not_h,
            source=source,
            confidence_in_estimate=confidence_in_estimate,
        ))


def _extract_argument_outcomes(
    snp_trace: List[Dict[str, Any]],
    episode_id: str,
    controller_id: str,
) -> Dict[Tuple[str, str], List[ArgumentOutcome]]:
    """Extract (controller, specialist) argument outcomes from an SNP trace."""
    pending: Dict[Tuple[int, str], Dict[str, Any]] = {}
    outcomes: Dict[Tuple[str, str], List[ArgumentOutcome]] = {}

    from SSTP.subprotocol.cip.src.message import get_part as _gp
    for msg in snp_trace:
        snp_payload = _gp(msg, "snp") or msg.get("snp_payload", {})
        operation = snp_payload.get("operation", "")
        actors = (msg.get("participants") or {}).get("actors") or msg.get("actors") or []
        sender = (actors[0].get("id", "") if actors else "") or msg.get("origin", {}).get("actor_id", "")
        receiver = snp_payload.get("receiver", "")
        ring_round = int(snp_payload.get("ring_round") or 0)

        if operation == "propose":
            pending[(ring_round, receiver)] = msg
        elif operation in ("accept", "counter_proposal"):
            proposal = pending.get((ring_round, sender))
            if proposal is None:
                continue
            prop_ep = proposal.get("epistemic", {})
            resp_ep = msg.get("epistemic", {})
            prop_scope = set(prop_ep.get("scope", []))
            resp_scope = set(resp_ep.get("scope", []) + resp_ep.get("addresses_evidence", []))

            moved = operation == "accept"
            contingent = bool(prop_scope & resp_scope)
            speech_act = resp_ep.get("message_act", "")
            if speech_act in ("compliance", "deliberation_pass"):
                move_cause = "social_compliance"
            elif moved and contingent:
                move_cause = "grounded_argument"
            else:
                move_cause = "no_move"

            prop_scope_list = prop_ep.get("scope", [])
            argument_type = prop_scope_list[0] if prop_scope_list else "unknown"
            prop_snp = proposal.get("snp_payload", {})
            subject_confidence = float(
                prop_snp.get("proposal_payload", {}).get("posterior", 0.5)
            )
            resp_snp = msg.get("snp_payload", {})
            subject_confidence_after = float(
                resp_snp.get("proposal_payload", {}).get("posterior")
                or subject_confidence
            )

            key = (controller_id, sender)
            outcomes.setdefault(key, []).append(
                ArgumentOutcome(
                    episode_id=episode_id,
                    message_id=str(msg.get("message_id", "")),
                    epistemic_state=str(resp_ep.get("state") or resp_ep.get("epistemic_state", "team_process")),
                    argument_concept_id=argument_type,
                    argument_type=argument_type,
                    subject_confidence_before=subject_confidence,
                    subject_confidence_after=subject_confidence_after,
                    contingent=contingent,
                    moved=moved,
                    move_cause=move_cause,
                )
            )

    return outcomes


_CONTINGENT_PEER_STATES = frozenset({"normal_alignment", "expedite_decision"})


def _extract_peer_dialogue_outcomes(
    peer_alignment_events: List[Dict[str, Any]],
    episode_id: str,
) -> Dict[Tuple[str, str], List[ArgumentOutcome]]:
    """Convert peer_alignment_events from execute_recursive_peer_dialogue() into ArgumentOutcomes.

    argument_concept_id uses task_goal as a URI proxy — not a real concept URI.
    """
    outcomes: Dict[Tuple[str, str], List[ArgumentOutcome]] = {}
    for evt in peer_alignment_events:
        speaker = evt.get("speaker", "")
        listener = evt.get("listener", "")
        if not speaker or not listener:
            continue
        alignment = evt.get("alignment") or {}
        if isinstance(alignment, dict):
            alignment_score = float(alignment.get("alignment_score", 0.5))
        else:
            alignment_score = float(alignment)
        contingency_str = evt.get("contingency", "")
        derailment_cause = evt.get("derailment_cause")
        task_goal = evt.get("task_goal", "")
        contingent = contingency_str in _CONTINGENT_PEER_STATES
        moved = alignment_score > 0.6
        if derailment_cause:
            move_cause = "social_compliance"
        elif moved and contingent:
            move_cause = "grounded_argument"
        else:
            move_cause = "no_move"
        key = (speaker, listener)
        outcomes.setdefault(key, []).append(
            ArgumentOutcome(
                episode_id=episode_id,
                message_id=f"{speaker}->{listener}:{evt.get('depth', 0)}",
                epistemic_state="taskwork",
                argument_concept_id=task_goal,
                argument_type=task_goal,
                subject_confidence_before=0.5,
                subject_confidence_after=alignment_score,
                contingent=contingent,
                moved=moved,
                move_cause=move_cause,
            )
        )
    return outcomes


class HealthcareMemoryService:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.episodic = EpisodicMemory()
        self.knowledge = KnowledgeMemory()
        self.concept_graph: ConceptGraph = ConceptGraph()
        # Layer 6: cross-episode epistemic stores (soid-free, persistent)
        self.belief_store = AgentBeliefStore()
        self.peer_store = PeerInteractionStore()
        self.convergence_store = ConvergenceStore()
        self.semantic_rule_store = SemanticRuleStore()
        # Layer 6: per-episode taskwork and team process state
        self.taskwork_store = TaskworkStore()
        self.team_process_store = TeamProcessStore()
        # Layer 7: Bayesian likelihood tables
        self.likelihood_store = LikelihoodStore()
        # ToM snapshots loaded from disk — applied via restore_tom_state()
        self._loaded_tom_snapshots: Dict[str, Any] = {}

    def store_episode(self, episode: HealthcareEpisode) -> None:
        self.episodic.add(episode)

    def calibrate_from_outcome(
        self,
        episode_id: str,
        outcome: str,
        team_epistemic_agent: Any = None,
    ) -> None:
        """Record a ground-truth outcome against a stored episode.

        Stamps ``ground_truth_outcome`` on the episode record and, if
        ``team_epistemic_agent`` is supplied, writes a knowledge announcement
        so TeamEpistemicMemory is updated for the relevant concept.

        outcome: free-text label, e.g. ``"drug_interaction"`` or ``"new_disease"``
        """
        ep = next((e for e in self.episodic.episodes if e.episode_id == episode_id), None)
        if ep is None:
            return
        from dataclasses import replace as _dc_replace
        updated = _dc_replace(ep, ground_truth_outcome=outcome)
        idx = self.episodic.episodes.index(ep)
        self.episodic.episodes[idx] = updated

        if team_epistemic_agent is not None:
            concept_id = f"concept:{outcome}"
            envelope = {
                "kind": "knowledge",
                "semantic": {"ontology_ref": concept_id},
                "message": {"id": episode_id, "parents": [], "episode": episode_id},
                "payload": [{"type": "knowledge", "location": "inline", "content": {
                    "concept_id": concept_id,
                    "posterior": 1.0,
                    "gar": 1.0,
                    "scr": 0.0,
                    "provenance_weight": 1.0,
                }}],
            }
            team_epistemic_agent.handle_knowledge(envelope)

    def close_episode(
        self,
        episode: HealthcareEpisode,
        panel_snp_traces: Dict[str, Tuple[str, List[Dict[str, Any]]]],
        peer_alignment_events: List[Dict[str, Any]] | None = None,
    ) -> None:
        """Store episode and promote SNP + peer-dialogue argument outcomes into cross-episode peer model."""
        self.episodic.add(episode)
        for _panel_name, (controller_id, snp_trace) in panel_snp_traces.items():
            outcomes_by_pair = _extract_argument_outcomes(snp_trace, episode.episode_id, controller_id)
            for (observer_id, subject_id), outcomes in outcomes_by_pair.items():
                self.peer_store.promote_outcomes_for_pair(
                    observer_id=observer_id,
                    subject_id=subject_id,
                    use_case="healthcare",
                    episode_id=episode.episode_id,
                    argument_outcomes=outcomes,
                    prediction_records=[],
                )
        if peer_alignment_events:
            peer_outcomes = _extract_peer_dialogue_outcomes(peer_alignment_events, episode.episode_id)
            for (observer_id, subject_id), outcomes in peer_outcomes.items():
                self.peer_store.promote_outcomes_for_pair(
                    observer_id=observer_id,
                    subject_id=subject_id,
                    use_case="healthcare",
                    episode_id=episode.episode_id,
                    argument_outcomes=outcomes,
                    prediction_records=[],
                )

    def inject_prior(
        self,
        agent_id: str,
        concept_id: str,
        prior: float,
        episode_id: str,
        use_case: str = "healthcare",
        prior_weight: float = 1.0,
        message_id: str | None = None,
    ) -> None:
        """Record a semantic-memory prior injection for an agent at episode open."""
        revision = BeliefRevision(
            revision_id=str(uuid.uuid4()),
            timestamp_ms=int(time.time() * 1000),
            episode_id=episode_id,
            message_id=message_id,
            confidence_before=prior,
            confidence_after=prior,
            cause="semantic_memory",
            caused_by_agent=None,
            argument_concept_ids=[concept_id],
        )
        self.belief_store.record_revision(
            agent_id=agent_id,
            concept_id=concept_id,
            use_case=use_case,
            episode_id=episode_id,
            revision=revision,
            new_status="held",
            new_public_confidence=prior,
        )
        self.belief_store.set_prior(
            agent_id=agent_id,
            concept_id=concept_id,
            use_case=use_case,
            prior=prior,
            prior_weight=prior_weight,
        )

    def calibrate_likelihood_tables(self, min_episodes: int = 10) -> None:
        """Update likelihood tables from episode outcome feedback.

        Requires at least min_episodes with episode_findings populated.
        Uses Beta pseudo-count: p_h = (hits+1)/(total+2).
        """
        episodes = [e for e in self.episodic.episodes if e.episode_findings]
        if len(episodes) < min_episodes:
            return
        for role, table in self.likelihood_store._tables.items():
            for entry in list(table.entries):
                hits = sum(
                    1 for e in episodes
                    if e.care_plan.clinical_assessment.likely_cause == entry.hypothesis_id
                    and entry.finding_id in e.episode_findings
                )
                total = sum(1 for e in episodes if entry.finding_id in e.episode_findings)
                if total == 0:
                    continue
                p_h = (hits + 1) / (total + 2)
                confidence = min(0.95, 0.5 + total / 40.0)
                self.likelihood_store.update_entry(
                    role=role,
                    finding_id=entry.finding_id,
                    hypothesis_id=entry.hypothesis_id,
                    p_finding_given_h=round(p_h, 6),
                    p_finding_given_not_h=round(max(0.01, 1.0 - p_h), 6),
                    source="calibrated",
                    confidence_in_estimate=round(confidence, 4),
                )

    def refresh_knowledge(self, limit: int = 200) -> None:
        self.knowledge.refresh_from_episodes(
            self.episodic.recent(limit),
            semantic_rule_store=self.semantic_rule_store,
            use_case="healthcare",
        )

    def load(self) -> None:
        if not self.store_path.exists():
            return
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return

        semantic_payload = payload.get("semantic") if isinstance(payload.get("semantic"), dict) else {}
        knowledge_payload = payload.get("knowledge") if isinstance(payload.get("knowledge"), dict) else {}
        memory_payload = semantic_payload if semantic_payload else knowledge_payload

        episodes = [_episode_from_dict(item) for item in payload.get("episodic", []) if isinstance(item, dict)]
        rules = [_rule_from_dict(item) for item in memory_payload.get("rules", []) if isinstance(item, dict)]

        self.episodic.episodes = episodes
        self.knowledge.rules = rules
        self.knowledge.discovered_interactions = [
            str(item) for item in memory_payload.get("discovered_interactions", [])
        ]
        self.knowledge.specialist_network_notes = [
            str(item) for item in memory_payload.get("specialist_network_notes", [])
        ]

        for record_data in payload.get("peer_store", []):
            if not isinstance(record_data, dict):
                continue
            argument_outcomes = [
                ArgumentOutcome(**o) for o in record_data.get("argument_outcomes", [])
                if isinstance(o, dict)
            ]
            prediction_history = [
                PredictionRecord(**p) for p in record_data.get("prediction_history", [])
                if isinstance(p, dict)
            ]
            rec = PeerInteractionRecord(
                observer_id=str(record_data.get("observer_id", "")),
                subject_id=str(record_data.get("subject_id", "")),
                use_case=str(record_data.get("use_case", "")),
                argument_outcomes=argument_outcomes,
                prediction_history=prediction_history,
                predictive_accuracy=float(record_data.get("predictive_accuracy", 0.5)),
                argument_types_that_move=list(record_data.get("argument_types_that_move", [])),
                argument_types_ignored=list(record_data.get("argument_types_ignored", [])),
                evidence_weights={str(k): float(v) for k, v in record_data.get("evidence_weights", {}).items()},
                confidence_accuracy_correlation=float(record_data.get("confidence_accuracy_correlation", 0.0)),
                episode_count=int(record_data.get("episode_count", 0)),
                last_episode=str(record_data.get("last_episode", "")),
            )
            key = self.peer_store._key(rec.observer_id, rec.subject_id, rec.use_case)
            self.peer_store._store[key] = rec

        for role, table_data in payload.get("likelihood_tables", {}).items():
            if not isinstance(table_data, dict):
                continue
            entries = [
                LikelihoodEntry(**e) for e in table_data.get("entries", [])
                if isinstance(e, dict)
            ]
            self.likelihood_store._tables[str(role)] = LikelihoodTable(
                role=str(table_data.get("role", role)),
                entries=entries,
                last_calibrated_episode=table_data.get("last_calibrated_episode"),
            )

        for bs_data in payload.get("belief_store", []):
            if not isinstance(bs_data, dict):
                continue
            revision_history = [
                BeliefRevision(**r) for r in bs_data.get("revision_history", [])
                if isinstance(r, dict)
            ]
            bs = BeliefState(
                agent_id=str(bs_data.get("agent_id", "")),
                concept_id=str(bs_data.get("concept_id", "")),
                current_confidence=float(bs_data.get("current_confidence", 0.5)),
                public_confidence=float(bs_data.get("public_confidence", 0.5)),
                status=str(bs_data.get("status", "held")),
                use_case=str(bs_data.get("use_case", "")),
                first_formed_episode=str(bs_data.get("first_formed_episode", "")),
                last_revised_episode=str(bs_data.get("last_revised_episode", "")),
                prior=float(bs_data.get("prior", 0.5)),
                prior_weight=float(bs_data.get("prior_weight", 1.0)),
                likelihoods=[tuple(pair) for pair in bs_data.get("likelihoods", [])],
                revision_history=revision_history,
                social_compliance_ratio=float(bs_data.get("social_compliance_ratio", 0.0)),
                revision_count=int(bs_data.get("revision_count", 0)),
                confidence_variance=float(bs_data.get("confidence_variance", 0.0)),
            )
            key = self.belief_store._key(bs.agent_id, bs.concept_id, bs.use_case)
            self.belief_store._store[key] = bs

        from SSTP.subprotocol.siep.src.epistemic.stores import TeamGroundedTruth
        for t_data in payload.get("convergence_store", []):
            if not isinstance(t_data, dict):
                continue
            try:
                truth = TeamGroundedTruth(**{k: v for k, v in t_data.items()
                                             if k in TeamGroundedTruth.__dataclass_fields__})
                self.convergence_store.record(truth)
            except Exception:
                pass

        for r_data in payload.get("semantic_rule_store", []):
            if not isinstance(r_data, dict):
                continue
            try:
                rule = SemanticRule(**{k: v for k, v in r_data.items()
                                       if k in SemanticRule.__dataclass_fields__})
                self.semantic_rule_store.record(rule)
            except Exception:
                pass

        tom_data = payload.get("tom_snapshots", {})
        if isinstance(tom_data, dict):
            self._loaded_tom_snapshots = tom_data

    def restore_tom_state(self, tom_engine: Any) -> None:
        """Restore AgentEpistemicStore peer_models and prediction_logs from disk."""
        if not self._loaded_tom_snapshots:
            return
        for agent_id, snap in self._loaded_tom_snapshots.items():
            if not isinstance(snap, dict):
                continue
            agent_tom = tom_engine._agent_toms.get(agent_id)
            if agent_tom is None:
                continue
            for peer_id, model in snap.get("peer_models", {}).items():
                if isinstance(model, dict):
                    agent_tom._epistemic_store.save_peer_model(peer_id, model)
            for peer_id, logs in snap.get("prediction_logs", {}).items():
                if isinstance(logs, list):
                    agent_tom._epistemic_store._prediction_logs[peer_id] = list(logs)
            cg_records = snap.get("common_ground", [])
            if cg_records:
                agent_tom._epistemic_store._common_ground._restore_flat(cg_records)

    def save(self, tom_engine: Any = None) -> None:
        semantic_block = {
            "rules": [asdict(rule) for rule in self.knowledge.rules],
            "discovered_interactions": self.knowledge.discovered_interactions,
            "specialist_network_notes": self.knowledge.specialist_network_notes,
        }

        def _belief_state_to_dict(bs: BeliefState) -> Dict[str, Any]:
            d = asdict(bs)
            d["likelihoods"] = [list(pair) for pair in bs.likelihoods]
            return d

        payload = {
            "version": 1,
            "updated_unix": int(time.time()),
            "episodic": [asdict(episode) for episode in self.episodic.episodes],
            "semantic": semantic_block,
            "knowledge": semantic_block,
            "peer_store": [asdict(r) for r in self.peer_store._store.values()],
            "likelihood_tables": {
                role: asdict(table)
                for role, table in self.likelihood_store._tables.items()
            },
            "belief_store": [_belief_state_to_dict(bs) for bs in self.belief_store._store.values()],
            "convergence_store": [asdict(t) for t in self.convergence_store._store.values()],
            "semantic_rule_store": [asdict(r) for r in sum(self.semantic_rule_store._store.values(), [])],
            "tom_snapshots": {
                agent_id: {
                    "peer_models": dict(agent_tom._epistemic_store._peer_models),
                    "prediction_logs": {
                        k: list(v)
                        for k, v in agent_tom._epistemic_store._prediction_logs.items()
                    },
                    "common_ground": agent_tom._epistemic_store._common_ground._store_flat(),
                }
                for agent_id, agent_tom in (tom_engine._agent_toms.items() if tom_engine is not None else {}.items())
            },
        }
        self.store_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

class HCPanelMemory:
    """Team-level memory for hcpanel.

    Owns only convergence output and team-level knowledge.
    Per-agent stores (AgentBeliefStore, PeerInteractionStore, TaskworkStore,
    AgentEpistemicStore) are owned exclusively by each SpecialistAgent.
    PanelBus receives a BeliefStoreProxy that routes reads/writes to the right
    agent's private store. peer_interaction_store here is the controller-level
    cross-episode view used by predict_belief() — not an agent's private store.
    """

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.episodic = EpisodicMemory()
        # Team-level convergence and rule stores
        self.convergence_store = ConvergenceStore()
        self.semantic_rule_store = SemanticRuleStore()
        # Shared likelihood tables (read-only by agents via LLM priors)
        self.likelihood_store = LikelihoodStore()
        # Controller-level peer interaction store — tracks cross-episode argument
        # outcomes from the controller's perspective (used by predict_belief)
        self.peer_interaction_store = PeerInteractionStore()

    def store_episode(self, episode: HealthcareEpisode) -> None:
        self.episodic.add(episode)

    def load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict):
            return

        for t_data in payload.get("convergence_store", []):
            if not isinstance(t_data, dict):
                continue
            try:
                truth = TeamGroundedTruth(**{
                    k: v for k, v in t_data.items()
                    if k in TeamGroundedTruth.__dataclass_fields__
                })
                self.convergence_store.record(truth)
            except Exception:
                pass

        for r_data in payload.get("semantic_rule_store", []):
            if not isinstance(r_data, dict):
                continue
            try:
                rule = SemanticRule(**{
                    k: v for k, v in r_data.items()
                    if k in SemanticRule.__dataclass_fields__
                })
                self.semantic_rule_store.record(rule)
            except Exception:
                pass

    def save(self) -> None:
        payload: Dict[str, Any] = {
            "version": 1,
            "updated_unix": int(time.time()),
            "convergence_store": [
                asdict(t) for t in self.convergence_store._store.values()
            ],
            "semantic_rule_store": [
                asdict(r)
                for rules in self.semantic_rule_store._store.values()
                for r in rules
            ],
        }
        self.store_path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

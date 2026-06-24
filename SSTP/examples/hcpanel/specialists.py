from __future__ import annotations

from collections import Counter
import concurrent.futures
import logging
import queue
import traceback as _tb
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

from SSTP.subprotocol.siep.src.tomcore.llm import LLMClient
from SSTP.subprotocol.siep.src.epistemic.vocabulary import SpeechAct, EpistemicState, BeliefStatus, make_epistemic_block
from SSTP.examples.hcpanel.domain import (
    ClinicalAssessment,
    DoctorAssessment,
    InsuranceDecision,
    MedicationProposal,
    PatientProfile,
    ScheduledAppointment,
    SpecialistProvider,
)
from SSTP.examples.hcpanel.interaction_semantics import concept_uri_for_interaction

if TYPE_CHECKING:
    from SSTP.examples.hcpanel.agent_bus import HealthcareAgentBus
    from SSTP.examples.hcpanel.panel_negotiation_bus import PanelNegotiationBus
    from SSTP.subprotocol.siep.src.tomcore.types import TaskSession

LOGGER = logging.getLogger("healthcare2")

# ── Diagnostics specialist panel definition ───────────────────────────────────
#
# Five distinct roles with partial mutual overlap:
#   internal_medicine   ↔ all (generalist anchor)
#   clinical_pharmacology ↔ internal_medicine, immunology
#   cardiology          ↔ internal_medicine, neurology
#   neurology           ↔ internal_medicine, cardiology
#   immunology          ↔ clinical_pharmacology, internal_medicine
#
DIAGNOSTICS_SPECIALISTS: List[Dict[str, str]] = [
    {
        "index": "1",
        "id_suffix": "internal-medicine",
        "role": "internal_medicine",
        "focus": (
            "Broad differential diagnosis across systemic conditions; multi-drug presentations, "
            "chronic disease overlap, and whole-patient symptom pattern review."
        ),
        "prior_belief": (
            "Your prior is balanced: drug_interaction and new_disease are equally plausible "
            "for an ambiguous presentation. You serve as the generalist anchor and update "
            "based on the weight of evidence from all specialists."
        ),
    },
    {
        "index": "2",
        "id_suffix": "clinical-pharmacology",
        "role": "clinical_pharmacology",
        "focus": (
            "Drug–drug interactions, adverse drug reactions, polypharmacy risk, "
            "and pharmacokinetic-driven symptom causation."
        ),
        "prior_belief": (
            "Your prior strongly favours drug_interaction. Polypharmacy combinations "
            "involving anticoagulants or antiplatelets are high-risk interactions you encounter "
            "routinely. Unless symptoms clearly point to a new disease process, you assign "
            "drug_interaction prior confidence ~0.80 for patients on multiple interacting agents."
        ),
    },
    {
        "index": "3",
        "id_suffix": "cardiology",
        "role": "cardiology",
        "focus": (
            "Cardiovascular manifestations of medication use: palpitations, blood-pressure changes, "
            "oedema, and haemodynamic symptom patterns."
        ),
        "prior_belief": (
            "Your prior strongly favours new_disease for patients with atrial fibrillation or "
            "coronary artery disease presenting with fatigue and dizziness. Cardiac decompensation, "
            "evolving arrhythmia, or haemodynamic instability is your first differential in this "
            "population. You assign new_disease prior confidence ~0.70 when these conditions appear "
            "in the history, and you require clear pharmacokinetic evidence to override that prior."
        ),
    },
    {
        "index": "4",
        "id_suffix": "neurology",
        "role": "neurology",
        "focus": (
            "Central and peripheral nervous system drug effects: dizziness, headache, cognitive "
            "changes, neurotoxicity, and CNS-mediated symptom causation."
        ),
        "prior_belief": (
            "Your prior favours new_disease for dizziness-dominant presentations. Vestibular "
            "dysfunction, cerebellar pathology, or anticoagulant-related CNS events are distinct "
            "from pharmacokinetic interactions and must be ruled out first. You assign new_disease "
            "prior confidence ~0.65 when dizziness and fatigue co-occur, and you only shift to "
            "drug_interaction if the pharmacological evidence is compelling."
        ),
    },
    {
        "index": "5",
        "id_suffix": "immunology",
        "role": "immunology",
        "focus": (
            "Hypersensitivity reactions, drug-allergy presentations, immune-mediated adverse "
            "events, and allergic vs. pharmacological symptom differentiation."
        ),
        "prior_belief": (
            "Your prior distinguishes immune-mediated adverse events from classic pharmacokinetic "
            "interactions. Nausea and fatigue without a definitive drug-drug PK signature may "
            "indicate a hypersensitivity or NSAID-mediated immune activation — a new_disease "
            "process, not an interaction. You assign new_disease prior confidence ~0.60 for "
            "non-specific symptom clusters and only accept drug_interaction if the interaction "
            "mechanism is mechanistically clear."
        ),
    },
]

# ── Pharmacy specialist panel definition ──────────────────────────────────────
#
# Five distinct roles with partial mutual overlap:
#   pharmacokinetics    ↔ pharmacodynamics
#   pharmacodynamics    ↔ pharmacokinetics, clinical_pharmacy
#   clinical_pharmacy   ↔ pharmacodynamics, drug_safety
#   drug_safety         ↔ clinical_pharmacy, clinical_toxicology
#   clinical_toxicology ↔ drug_safety, pharmacokinetics
#
PHARMACY_SPECIALISTS: List[Dict[str, str]] = [
    {
        "index": "1",
        "id_suffix": "pharmacokinetics",
        "role": "pharmacokinetics",
        "focus": (
            "Absorption, distribution, metabolism, and elimination (ADME) of drugs; "
            "dosing interval risks, renal/hepatic clearance, and drug-drug PK interactions."
        ),
    },
    {
        "index": "2",
        "id_suffix": "pharmacodynamics",
        "role": "pharmacodynamics",
        "focus": (
            "Receptor pharmacology and mechanism of action; synergistic or antagonistic "
            "drug effects, target-based interaction risks."
        ),
    },
    {
        "index": "3",
        "id_suffix": "clinical-pharmacy",
        "role": "clinical_pharmacy",
        "focus": (
            "Guideline-based therapy selection, formulary management, evidence-based "
            "substitution recommendations, and drug appropriateness criteria."
        ),
    },
    {
        "index": "4",
        "id_suffix": "drug-safety",
        "role": "drug_safety",
        "focus": (
            "Adverse event monitoring, black-box warnings, contraindications, and "
            "post-market safety signals for the current medication regimen."
        ),
    },
    {
        "index": "5",
        "id_suffix": "clinical-toxicology",
        "role": "clinical_toxicology",
        "focus": (
            "Drug interaction severity thresholds, toxicity risk, overdose potential, "
            "and clinical triage of high-risk medication combinations."
        ),
    },
]

# ── Legacy constants (kept for backward compat with any external references) ──
DEFAULT_DIAGNOSTICS_DOCTOR_COUNT = 5
DEFAULT_PHARMACY_REVIEWER_COUNT = 5
DEFAULT_INSURANCE_REVIEWER_COUNT = 5


def _as_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _mean(values: List[float], default: float) -> float:
    if not values:
        return default
    return sum(values) / len(values)


# ── DiagnosticsController ─────────────────────────────────────────────────────


class DiagnosticsController:
    """Diagnostics controller that gathers independent opinions from 5 specialist
    agents and then uses SNP star negotiation to converge on a panel outcome.

    Architecture
    ------------
    Phase 1 — **Independent assessment**: each of the 5 fixed specialist agents
    (internal_medicine, clinical_pharmacology, cardiology, neurology, immunology)
    submits an independent assessment via an LLM call with a role-specific payload.

    Phase 2 — **SNP star negotiation**: the controller forms its initial proposal
    from the plurality position and negotiates hub-and-spoke with all 5 specialists.
    Specialists that align adopt the controller's position; others counter-propose.
    The controller commits when a majority accept.

    Phase 3 — **Aggregation**: ``_aggregate_panel`` computes the final
    ``ClinicalAssessment`` from the (possibly updated) specialist positions.
    """

    def __init__(
        self,
        llm: LLMClient,
        bus: "HealthcareAgentBus | None" = None,
        panel_negotiation_bus: "PanelNegotiationBus | None" = None,
        # Legacy positional arg accepted but ignored (panel size is fixed at 5)
        doctor_count: int = DEFAULT_DIAGNOSTICS_DOCTOR_COUNT,
        task_session: "TaskSession | None" = None,
    ) -> None:
        self.llm = llm
        self.bus = bus
        self.panel_negotiation_bus = panel_negotiation_bus
        self.task_session = task_session

    @staticmethod
    def _group_by_likely_cause(doctor_assessments: List[DoctorAssessment]) -> Dict[str, List[DoctorAssessment]]:
        groups: Dict[str, List[DoctorAssessment]] = {}
        for assessment in doctor_assessments:
            groups.setdefault(assessment.likely_cause, []).append(assessment)
        return groups

    @staticmethod
    def _leading_group(groups: Dict[str, List[DoctorAssessment]]) -> tuple[str, List[DoctorAssessment]]:
        return max(
            groups.items(),
            key=lambda item: (
                len(item[1]),
                round(sum(assessment.confidence for assessment in item[1]) / len(item[1]), 4),
                item[0],
            ),
        )

    def _request_doctor_assessment(
        self,
        patient: PatientProfile,
        doctor_index: int,
        semantic_rules: List[Dict[str, float | int | str]],
        review_mode: str,
        specialist_role: str = "",
        specialist_prior: str = "",
        preferred_likely_cause: str | None = None,
        template: DoctorAssessment | None = None,
        doctor_id_override: str | None = None,
        coordination_summary: Dict[str, Any] | None = None,
        derailment_constraint: str | None = None,
        findings: List[str] | None = None,
        likelihood_table: Any | None = None,
        activated_rules: List[Any] | None = None,
    ) -> DoctorAssessment:
        doctor_id = doctor_id_override or f"doctor-{doctor_index:02d}"

        # ── Layer 7: Bayesian posterior when findings + table are provided ────
        bayesian_result: Dict[str, Any] | None = None
        if findings is not None and likelihood_table is not None:
            from SSTP.examples.hcpanel.memory import compute_prior
            from SSTP.subprotocol.siep.src.epistemic.bayes import compute_posterior, normalize_posteriors
            hypotheses = ["drug_interaction", "new_disease"]
            rules_for_prior = activated_rules or []
            unnorm = {
                h: compute_posterior(
                    compute_prior(rules_for_prior, h),
                    findings,
                    h,
                    likelihood_table,
                )
                for h in hypotheses
            }
            norm = normalize_posteriors(unnorm)
            di_post = norm.get("drug_interaction", 0.5)
            nd_post = norm.get("new_disease", 0.5)
            if preferred_likely_cause in hypotheses and review_mode != "independent":
                forced_h = preferred_likely_cause
                di_post = min(0.97, di_post + (0.08 if forced_h == "drug_interaction" else -0.04))
                nd_post = min(0.97, nd_post + (0.08 if forced_h == "new_disease" else -0.04))
                renorm = normalize_posteriors({"drug_interaction": di_post, "new_disease": nd_post})
                di_post, nd_post = renorm["drug_interaction"], renorm["new_disease"]
            inferred_cause = "drug_interaction" if di_post >= nd_post + 0.05 else "new_disease"
            if di_post < 0.45 and nd_post < 0.45:
                inferred_cause = "inconclusive"
            gap = abs(di_post - nd_post)
            inferred_conf = round(min(0.95, 0.55 + gap * 0.8), 4)
            from SSTP.examples.hcpanel.llm_backends import generate_reasoning_summary
            top_ev = [f for f in findings if likelihood_table.likelihood_ratio(f, inferred_cause) > 1.2]
            reasoning_sum = generate_reasoning_summary(
                max(di_post, nd_post), top_ev, inferred_cause, role=specialist_role
            )
            bayesian_result = {
                "likely_cause": inferred_cause,
                "interaction_likelihood": di_post,
                "new_disease_likelihood": nd_post,
                "confidence": inferred_conf,
                "rationale": reasoning_sum,
                "posterior": max(di_post, nd_post),
                "supporting_evidence": top_ev,
                "against_evidence": [f for f in findings if f not in top_ev],
                "reasoning_summary": reasoning_sum,
            }

        payload: Dict[str, Any] = {
            "symptoms": patient.symptoms,
            "health_history": patient.health_history,
            "current_medications": patient.current_medications,
            "semantic_rules": semantic_rules,
            "doctor_id": doctor_id,
            "doctor_index": doctor_index,
            "review_mode": review_mode,
        }
        if specialist_role:
            payload["specialist_role"] = specialist_role
        if specialist_prior:
            payload["specialist_prior"] = specialist_prior
        if preferred_likely_cause:
            payload["preferred_likely_cause"] = preferred_likely_cause
        if coordination_summary:
            payload["coordination_summary"] = coordination_summary
        if derailment_constraint:
            payload["derailment_constraint"] = derailment_constraint

        req_header = None
        if self.bus:
            req_header = self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                sender="diagnostics-controller",
                receiver=doctor_id,
                utterance=f"assess patient review_mode={review_mode} role={specialist_role or 'generic'}",
            )

        if bayesian_result is not None:
            # Bayesian posteriors are ground truth — only use LLM for rationale override
            result = bayesian_result
        else:
            result = self.llm.complete_json("diagnostics_assessment", payload)

        likely_cause = str(
            result.get(
                "likely_cause",
                preferred_likely_cause or (template.likely_cause if template is not None else "drug_interaction"),
            )
        )
        interaction_likelihood = float(
            result.get(
                "interaction_likelihood",
                template.interaction_likelihood if template is not None else 0.6,
            )
        )
        new_disease_likelihood = float(
            result.get(
                "new_disease_likelihood",
                template.new_disease_likelihood if template is not None else 0.4,
            )
        )
        confidence = float(result.get("confidence", template.confidence if template is not None else 0.65))
        rationale = str(
            result.get(
                "rationale",
                template.rationale if template is not None else "Reasoning over symptoms, meds, and history.",
            )
        )

        if self.bus and req_header:
            _diag_scope = ["concept:drug_interaction"]
            _diag_sub = concept_uri_for_interaction(likely_cause)
            if _diag_sub:
                _diag_scope.append(_diag_sub)
            if self.task_session is not None:
                _diag_utterance = f"{likely_cause} confidence={confidence:.2f}"
                _thought = result.get("thought_summary", "")
                self.task_session.assess(
                    agent_id=doctor_id,
                    concept_id="concept:drug_interaction",
                    posterior=confidence,
                    utterance=_diag_utterance,
                    scope=_diag_scope,
                    parent_id=req_header["message"]["id"],
                    receiver="diagnostics-controller",
                    rationale=rationale,
                    thought_summary=_thought,
                )
            elif self.bus is not None:
                _thought = result.get("thought_summary", "")
                _diag_utterance = f"{likely_cause} confidence={confidence:.2f}"
                self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                    sender=doctor_id,
                    receiver="diagnostics-controller",
                    utterance=_diag_utterance,
                    rationale=rationale,
                    thought_summary=_thought,
                    parent_id=req_header["message"]["id"],
                    epistemic=make_epistemic_block(
                        speech_act=SpeechAct.BELIEF_ASSERTION,
                        epistemic_state=EpistemicState.TASKWORK,
                        belief_status=BeliefStatus.ASSERTED,
                        uncertainty=round(1.0 - confidence, 4),
                        concept_id="concept:drug_interaction",
                        scope=_diag_scope,
                    ),
                )

        assessment = DoctorAssessment(
            doctor_id=doctor_id,
            likely_cause=likely_cause,
            interaction_likelihood=interaction_likelihood,
            new_disease_likelihood=new_disease_likelihood,
            confidence=confidence,
            rationale=rationale,
            review_mode=review_mode,
        )
        # Carry Bayesian evidence chain through to SNP positions
        if bayesian_result is not None:
            assessment._bayesian = bayesian_result  # type: ignore[attr-defined]
        return assessment

    def _annotate_corroboration(self, doctor_assessments: List[DoctorAssessment]) -> None:
        for group in self._group_by_likely_cause(doctor_assessments).values():
            doctor_ids = [assessment.doctor_id for assessment in group]
            for assessment in group:
                assessment.corroborated_by = [
                    did for did in doctor_ids if did != assessment.doctor_id
                ]

    def _aggregate_panel(self, doctor_assessments: List[DoctorAssessment]) -> ClinicalAssessment:
        groups = self._group_by_likely_cause(doctor_assessments)
        likely_cause, leading_group = self._leading_group(groups)
        panel_size = len(doctor_assessments)
        majority_size = len(leading_group)
        vote_breakdown = {cause: len(group) for cause, group in sorted(groups.items())}
        interaction_likelihood = round(
            sum(assessment.interaction_likelihood for assessment in leading_group) / len(leading_group),
            4,
        )
        new_disease_likelihood = round(
            sum(assessment.new_disease_likelihood for assessment in leading_group) / len(leading_group),
            4,
        )
        base_confidence = sum(assessment.confidence for assessment in leading_group) / len(leading_group)
        consensus_ratio = majority_size / max(1, panel_size)
        confidence = round(min(0.99, 0.7 * base_confidence + 0.3 * consensus_ratio), 4)
        breakdown_text = ", ".join(f"{cause}={count}" for cause, count in vote_breakdown.items())
        rationale = (
            f"Panel consensus {majority_size}/{panel_size} doctors favored {likely_cause}; "
            f"vote breakdown: {breakdown_text}. Lead assessment: {leading_group[0].rationale}"
        )

        return ClinicalAssessment(
            likely_cause=likely_cause,
            interaction_likelihood=interaction_likelihood,
            new_disease_likelihood=new_disease_likelihood,
            confidence=confidence,
            rationale=rationale,
            panel_size=panel_size,
            majority_size=majority_size,
            vote_breakdown=vote_breakdown,
            all_opinions_corroborated=all(
                len(assessment.corroborated_by) >= 1 for assessment in doctor_assessments
            ),
            doctor_assessments=doctor_assessments,
        )

    def assess(
        self,
        patient: PatientProfile,
        semantic_rules: List[Dict[str, float | int | str]] | None = None,
        coordination_summary: Dict[str, Any] | None = None,
        likelihood_tables: Dict[str, Any] | None = None,
        activated_rules: List[Any] | None = None,
    ) -> ClinicalAssessment:
        panel_rules = semantic_rules or []
        self._repair_context = {
            "patient": patient,
            "semantic_rules": panel_rules,
            "coordination_summary": coordination_summary,
            "spec_by_id": {f"diag-{s['id_suffix']}": s for s in DIAGNOSTICS_SPECIALISTS},
            "likelihood_tables": likelihood_tables or {},
            "activated_rules": activated_rules or [],
        }

        # ── Layer 7: extract structured findings once per episode ─────────────
        from SSTP.examples.hcpanel.llm_backends import extract_findings
        episode_findings = extract_findings(
            symptoms=patient.symptoms,
            health_history=patient.health_history,
            current_medications=patient.current_medications,
            medication_allergies=patient.medication_allergies,
        )
        self._last_findings = episode_findings

        # ── Phase 1: independent specialist assessments (parallel) ─────────────
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(DIAGNOSTICS_SPECIALISTS)) as pool:
            futures = {
                pool.submit(
                    self._request_doctor_assessment,
                    patient=patient,
                    doctor_index=int(spec["index"]),
                    semantic_rules=panel_rules,
                    review_mode="independent",
                    specialist_role=spec["role"],
                    specialist_prior=spec.get("prior_belief", ""),
                    doctor_id_override=f"diag-{spec['id_suffix']}",
                    coordination_summary=coordination_summary,
                    findings=episode_findings,
                    likelihood_table=(likelihood_tables or {}).get(spec["role"]),
                    activated_rules=activated_rules,
                ): spec
                for spec in DIAGNOSTICS_SPECIALISTS
            }
            doctor_assessments: List[DoctorAssessment] = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    doctor_assessments.append(future.result())
                except Exception as exc:
                    LOGGER.warning("diagnostics: %s abstained: %s", futures[future].get("id_suffix"), exc)

        # ── Phase 2: annotate initial corroboration ──────────────────────────
        self._annotate_corroboration(doctor_assessments)

        # ── Phase 3: SNP star negotiation ────────────────────────────────────
        if self.panel_negotiation_bus is not None:
            from SSTP.examples.hcpanel.panel_negotiation_bus import PanelNegotiationStar, IERepairExhausted

            self.panel_negotiation_bus.reset()
            controller_id = "diagnostics-controller"
            member_ids = [a.doctor_id for a in doctor_assessments]

            specialist_positions: Dict[str, Any] = {}
            for a in doctor_assessments:
                pos: Dict[str, Any] = {
                    "likely_cause": a.likely_cause,
                    "confidence": a.confidence,
                    "interaction_likelihood": a.interaction_likelihood,
                    "new_disease_likelihood": a.new_disease_likelihood,
                    "rationale": a.rationale,
                }
                b = getattr(a, "_bayesian", None)
                if b is not None:
                    pos["supporting_evidence"] = b.get("supporting_evidence")
                    pos["against_evidence"] = b.get("against_evidence")
                    pos["reasoning_summary"] = b.get("reasoning_summary")
                    pos["posterior"] = b.get("posterior")
                specialist_positions[a.doctor_id] = pos

            # Controller's initial proposal = plurality of specialist positions
            controller_position = PanelNegotiationStar._leading_position(specialist_positions)

            star = PanelNegotiationStar(self.panel_negotiation_bus, "diagnostics")
            try:
                winning_pos, resolution_label, _ = star.run(
                    controller_id=controller_id,
                    member_ids=member_ids,
                    controller_position=controller_position,
                    specialist_positions=specialist_positions,
                    task_goal=f"clinical diagnosis for patient {getattr(patient, 'name', 'unknown')}",
                    agent_beliefs={mid: {"role": "diagnostics specialist", "confidence": 0.6} for mid in member_ids},
                )
            except IERepairExhausted as exc:
                LOGGER.warning(
                    "diagnostics.ie_repair_exhausted snp_msg=%s depth=%d cause=%s",
                    exc.snp_message_id, exc.ie_depth, exc.cause,
                )
                winning_pos, resolution_label = None, "ie_repair_exhausted"

            # Update assessments to reflect post-negotiation positions
            for a in doctor_assessments:
                pos = specialist_positions[a.doctor_id]
                a.likely_cause = str(pos.get("likely_cause", a.likely_cause))
                a.confidence = float(pos.get("confidence", a.confidence))
                a.review_mode = f"snp_star:{resolution_label}"

            LOGGER.info(
                "diagnostics.snp_star resolution=%s specialists=%d snp_messages=%d",
                resolution_label,
                len(member_ids),
                len(self.panel_negotiation_bus.snp_trace),
            )
            self._annotate_corroboration(doctor_assessments)

        # ── Phase 4: aggregate ───────────────────────────────────────────────
        return self._aggregate_panel(doctor_assessments)

    def rederive_position(self, speaker_id: str, derailment_cause: str | None) -> "Dict[str, Any] | None":
        ctx = getattr(self, "_repair_context", None)
        if ctx is None:
            return None
        spec = ctx["spec_by_id"].get(speaker_id)
        if spec is None:
            return None
        a = self._request_doctor_assessment(
            patient=ctx["patient"],
            doctor_index=int(spec["index"]),
            semantic_rules=ctx["semantic_rules"],
            review_mode="repair",
            specialist_role=spec["role"],
            doctor_id_override=speaker_id,
            coordination_summary=ctx.get("coordination_summary"),
            derailment_constraint=derailment_cause,
        )
        return {
            "likely_cause": a.likely_cause,
            "confidence": a.confidence,
            "interaction_likelihood": a.interaction_likelihood,
            "new_disease_likelihood": a.new_disease_likelihood,
            "rationale": a.rationale,
        }

    def run(self, inbox: "queue.Queue[Dict[str, Any]]") -> None:
        """Threaded entry point: loop on *inbox*, dispatch to assess(), reply via _reply_queue."""
        while True:
            try:
                envelope = inbox.get(timeout=90)
            except queue.Empty:
                continue
            if envelope is None:
                return
            parent_id = envelope.get("l9_header", {}).get("message_id")
            reply_q: "queue.Queue[Dict[str, Any]] | None" = envelope.get("payload", {}).get("_reply_queue")
            try:
                p = envelope.get("payload", {})
                result = self.assess(
                    patient=p["patient"],
                    semantic_rules=p.get("semantic_rules"),
                    coordination_summary=p.get("coordination_summary"),
                )
                if reply_q is not None:
                    reply_q.put({"event_type": "agent_response", "result": result, "parent_id": parent_id})
            except Exception as exc:
                LOGGER.error("diagnostics.run error: %s\n%s", exc, _tb.format_exc())
                if self.bus is not None:
                    self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                        sender="diagnostics", receiver=envelope.get("sender", "orchestrator"),
                        error_type=type(exc).__name__, error_message=str(exc),
                        traceback=_tb.format_exc(), parent_id=parent_id,
                    )
                if reply_q is not None:
                    reply_q.put({"event_type": "agent_error", "error": str(exc), "parent_id": parent_id})


# Backwards-compat alias (used by main.py, tests, external consumers)
DiagnosticsAgent = DiagnosticsController


# ── PharmacyController ────────────────────────────────────────────────────────


class PharmacyController:
    """Pharmacy controller that gathers independent medication reviews from 5
    specialist pharmacists and then uses SNP star negotiation to converge on a
    panel risk assessment.

    Architecture
    ------------
    Phase 1 — **Independent review**: each of the 5 fixed specialist pharmacists
    (pharmacokinetics, pharmacodynamics, clinical_pharmacy, drug_safety,
    clinical_toxicology) submits an independent review via an LLM call with a
    role-specific payload.

    Phase 2 — **SNP star negotiation**: the controller forms its initial proposal
    from the plurality risk bucket and negotiates hub-and-spoke with all 5.

    Phase 3 — **Aggregation**: ``_aggregate_panel`` computes the final
    ``MedicationProposal``.
    """

    def __init__(
        self,
        llm: LLMClient,
        reviewer_count: int = DEFAULT_PHARMACY_REVIEWER_COUNT,
        bus: "HealthcareAgentBus | None" = None,
        panel_negotiation_bus: "PanelNegotiationBus | None" = None,
        task_session: "TaskSession | None" = None,
    ) -> None:
        self.llm = llm
        self.bus = bus
        self.panel_negotiation_bus = panel_negotiation_bus
        self.task_session = task_session

    @staticmethod
    def _risk_bucket(score: float) -> str:
        if score >= 0.7:
            return "high"
        if score >= 0.45:
            return "moderate"
        return "low"

    @staticmethod
    def _group_by_bucket(assessments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for assessment in assessments:
            groups.setdefault(str(assessment["risk_bucket"]), []).append(assessment)
        return groups

    @staticmethod
    def _leading_group(groups: Dict[str, List[Dict[str, Any]]]) -> tuple[str, List[Dict[str, Any]]]:
        return max(
            groups.items(),
            key=lambda item: (
                len(item[1]),
                round(_mean([_as_float(assessment.get("risk_score"), 0.4) for assessment in item[1]], 0.4), 4),
                item[0],
            ),
        )

    def _request_pharmacy_assessment(
        self,
        patient: PatientProfile,
        semantic_rules: List[Dict[str, float | int | str]],
        reviewer_index: int,
        review_mode: str,
        specialist_role: str = "",
        reviewer_id_override: str | None = None,
        preferred_bucket: str | None = None,
        template: Dict[str, Any] | None = None,
        coordination_summary: Dict[str, Any] | None = None,
        derailment_constraint: str | None = None,
        findings: List[str] | None = None,
        likelihood_table: Any | None = None,
        activated_rules: List[Any] | None = None,
    ) -> Dict[str, Any]:
        reviewer_id = reviewer_id_override or f"pharmacist-{reviewer_index:02d}"

        # ── Layer 7: Bayesian posterior for pharmacy risk when findings + table available ──
        bayesian_result: Dict[str, Any] | None = None
        if findings is not None and likelihood_table is not None:
            from SSTP.examples.hcpanel.memory import compute_prior
            from SSTP.subprotocol.siep.src.epistemic.bayes import compute_posterior, normalize_posteriors
            hypotheses = ["high", "moderate", "low"]
            rules_for_prior = activated_rules or []
            unnorm = {
                h: compute_posterior(
                    compute_prior(rules_for_prior, h),
                    findings,
                    h,
                    likelihood_table,
                )
                for h in hypotheses
            }
            norm = normalize_posteriors(unnorm)
            inferred_bucket = max(norm, key=lambda k: norm[k])
            inferred_score = norm[inferred_bucket]
            top_ev = [f for f in findings if likelihood_table.likelihood_ratio(f, inferred_bucket) > 1.2]
            from SSTP.examples.hcpanel.llm_backends import generate_reasoning_summary
            reasoning_sum = generate_reasoning_summary(
                inferred_score, top_ev, inferred_bucket, role=specialist_role
            )
            from SSTP.examples.hcpanel.llm_backends import _deterministic_pharmacy_review
            _det = _deterministic_pharmacy_review({
                "current_medications": patient.current_medications,
                "medication_allergies": patient.medication_allergies,
                "semantic_rules": [],
            })
            bayesian_result = {
                "risk_bucket": inferred_bucket,
                "risk_score": inferred_score,
                "interaction_risks": _det.get("interaction_risks") or top_ev,
                "proposed_changes": _det.get("proposed_changes") or [],
                "rationale": reasoning_sum,
                "supporting_evidence": top_ev,
                "against_evidence": [f for f in findings if f not in top_ev],
                "reasoning_summary": reasoning_sum,
                "posterior": inferred_score,
            }

        payload: Dict[str, Any] = {
            "current_medications": patient.current_medications,
            "medication_allergies": patient.medication_allergies,
            "symptoms": patient.symptoms,
            "semantic_rules": semantic_rules,
            "pharmacist_id": reviewer_id,
            "pharmacist_index": reviewer_index,
            "review_mode": review_mode,
        }
        if specialist_role:
            payload["specialist_role"] = specialist_role
        if preferred_bucket:
            payload["preferred_risk_bucket"] = preferred_bucket
        if coordination_summary:
            payload["coordination_summary"] = coordination_summary
        if derailment_constraint:
            payload["derailment_constraint"] = derailment_constraint

        req_header = None
        if self.bus:
            req_header = self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                sender="pharmacy-controller",
                receiver=reviewer_id,
                utterance=f"review medication interactions review_mode={review_mode} role={specialist_role or 'generic'}",
            )
        if bayesian_result is not None:
            result = bayesian_result
        else:
            result = self.llm.complete_json("pharmacy_interaction_review", payload)

        interaction_risks = [str(item) for item in result.get("interaction_risks", [])]
        proposed_changes = [str(item) for item in result.get("proposed_changes", [])]
        risk_score = _as_float(
            result.get("risk_score"),
            _as_float(template.get("risk_score"), 0.4) if template is not None else 0.4,
        )
        risk_bucket = result.get("risk_bucket") or self._risk_bucket(risk_score)
        rationale = str(
            result.get(
                "rationale",
                (
                    f"{reviewer_id} assessed {risk_bucket} medication interaction risk "
                    f"with score {risk_score:.2f}."
                ),
            )
        )

        if self.bus and req_header:
            _pharm_scope = ["concept:drug_interaction"]
            for _risk in interaction_risks:
                _sub = concept_uri_for_interaction(_risk)
                if _sub and _sub not in _pharm_scope:
                    _pharm_scope.append(_sub)
            _pharm_utterance = f"{risk_bucket} risk_score={risk_score:.2f}"
            _pharm_thought = result.get("thought_summary", "")
            if self.task_session is not None:
                self.task_session.assess(
                    agent_id=reviewer_id,
                    concept_id="concept:drug_interaction",
                    posterior=risk_score,
                    utterance=_pharm_utterance,
                    scope=_pharm_scope,
                    parent_id=req_header["message"]["id"],
                    receiver="pharmacy-controller",
                    rationale=rationale,
                    thought_summary=_pharm_thought,
                )
            elif self.bus is not None:
                self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                    sender=reviewer_id,
                    receiver="pharmacy-controller",
                    utterance=_pharm_utterance,
                    rationale=rationale,
                    thought_summary=_pharm_thought,
                    parent_id=req_header["message"]["id"],
                    epistemic=make_epistemic_block(
                        speech_act=SpeechAct.BELIEF_ASSERTION,
                        epistemic_state=EpistemicState.TASKWORK,
                        belief_status=BeliefStatus.ASSERTED,
                        uncertainty=round(1.0 - risk_score, 4),
                        concept_id="concept:drug_interaction",
                        scope=_pharm_scope,
                    ),
                )
        return {
            "reviewer_id": reviewer_id,
            "review_mode": review_mode,
            "risk_bucket": risk_bucket,
            "risk_score": risk_score,
            "interaction_risks": interaction_risks,
            "proposed_changes": proposed_changes,
            "rationale": rationale,
        }

    def _aggregate_panel(self, assessments: List[Dict[str, Any]]) -> MedicationProposal:
        groups = self._group_by_bucket(assessments)
        leading_bucket, leading_group = self._leading_group(groups)
        panel_size = len(assessments)
        majority_size = len(leading_group)
        vote_breakdown = {bucket: len(group) for bucket, group in sorted(groups.items())}

        risk_score = round(_mean([_as_float(item.get("risk_score"), 0.4) for item in leading_group], 0.4), 4)

        risk_counts = Counter(
            risk
            for item in leading_group
            for risk in item.get("interaction_risks", [])
            if str(risk).strip()
        )
        change_counts = Counter(
            change
            for item in leading_group
            for change in item.get("proposed_changes", [])
            if str(change).strip()
        )
        if not risk_counts:
            risk_counts.update(
                risk
                for item in assessments
                for risk in item.get("interaction_risks", [])
                if str(risk).strip()
            )
        if not change_counts:
            change_counts.update(
                change
                for item in assessments
                for change in item.get("proposed_changes", [])
                if str(change).strip()
            )

        interaction_risks = [risk for risk, _ in risk_counts.most_common()]
        proposed_changes = [change for change, _ in change_counts.most_common()]

        LOGGER.info(
            "pharmacy.panel_consensus final=%d majority=%d bucket=%s vote_breakdown=%s",
            panel_size,
            majority_size,
            leading_bucket,
            vote_breakdown,
        )

        reviewer_assessments: List[Dict[str, Any]] = []
        for index, item in enumerate(assessments, start=1):
            reviewer_assessments.append(
                {
                    "reviewer_id": str(item.get("reviewer_id", f"pharmacist-{index:02d}")),
                    "review_mode": str(item.get("review_mode", "independent")),
                    "risk_bucket": str(
                        item.get("risk_bucket", self._risk_bucket(_as_float(item.get("risk_score"), 0.4)))
                    ),
                    "risk_score": round(_as_float(item.get("risk_score"), 0.4), 4),
                    "interaction_risks": [str(risk) for risk in item.get("interaction_risks", [])],
                    "proposed_changes": [str(change) for change in item.get("proposed_changes", [])],
                    "rationale": str(item.get("rationale", "")),
                }
            )

        return MedicationProposal(
            interaction_risks=interaction_risks,
            proposed_changes=proposed_changes,
            risk_score=risk_score,
            panel_size=panel_size,
            majority_size=majority_size,
            vote_breakdown=vote_breakdown,
            reviewer_assessments=reviewer_assessments,
        )

    def review(
        self,
        patient: PatientProfile,
        semantic_rules: List[Dict[str, float | int | str]] | None = None,
        coordination_summary: Dict[str, Any] | None = None,
        likelihood_tables: Dict[str, Any] | None = None,
        activated_rules: List[Any] | None = None,
    ) -> MedicationProposal:
        panel_rules = semantic_rules or []
        self._repair_context = {
            "patient": patient,
            "semantic_rules": panel_rules,
            "coordination_summary": coordination_summary,
            "spec_by_id": {f"pharm-{s['id_suffix']}": s for s in PHARMACY_SPECIALISTS},
        }

        # ── Layer 7: extract pharmacy findings once per episode ──────────────
        from SSTP.examples.hcpanel.llm_backends import extract_pharmacy_findings
        pharmacy_findings = extract_pharmacy_findings(
            patient_medications=patient.current_medications,
            patient_allergies=patient.medication_allergies,
        )

        # ── Phase 1: independent specialist assessments (parallel) ──────────
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(PHARMACY_SPECIALISTS)) as pool:
            futures = {
                pool.submit(
                    self._request_pharmacy_assessment,
                    patient=patient,
                    semantic_rules=panel_rules,
                    reviewer_index=int(spec["index"]),
                    review_mode="independent",
                    specialist_role=spec["role"],
                    reviewer_id_override=f"pharm-{spec['id_suffix']}",
                    coordination_summary=coordination_summary,
                    findings=pharmacy_findings,
                    likelihood_table=(likelihood_tables or {}).get(spec["role"]),
                    activated_rules=activated_rules,
                ): spec
                for spec in PHARMACY_SPECIALISTS
            }
            assessments: List[Dict[str, Any]] = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    assessments.append(future.result())
                except Exception as exc:
                    LOGGER.warning("pharmacy: %s abstained: %s", futures[future].get("id_suffix"), exc)

        # ── Phase 2: SNP star negotiation ────────────────────────────────────
        if self.panel_negotiation_bus is not None:
            from SSTP.examples.hcpanel.panel_negotiation_bus import PanelNegotiationStar, IERepairExhausted

            self.panel_negotiation_bus.reset()
            controller_id = "pharmacy-controller"
            member_ids = [a["reviewer_id"] for a in assessments]

            specialist_positions: Dict[str, Any] = {
                a["reviewer_id"]: {
                    "risk_bucket": a["risk_bucket"],
                    "confidence": a["risk_score"],
                    "risk_score": a["risk_score"],
                    "interaction_risks": a["interaction_risks"],
                    "proposed_changes": a["proposed_changes"],
                    "rationale": a["rationale"],
                }
                for a in assessments
            }

            controller_position = PanelNegotiationStar._leading_position(specialist_positions)

            star = PanelNegotiationStar(self.panel_negotiation_bus, "pharmacy")
            try:
                winning_pos, resolution_label, _ = star.run(
                    controller_id=controller_id,
                    member_ids=member_ids,
                    controller_position=controller_position,
                    specialist_positions=specialist_positions,
                    task_goal=f"medication risk review for patient {getattr(patient, 'name', 'unknown')}",
                    agent_beliefs={mid: {"role": "pharmacy reviewer", "confidence": 0.6} for mid in member_ids},
                )
            except IERepairExhausted as exc:
                LOGGER.warning(
                    "pharmacy.ie_repair_exhausted snp_msg=%s depth=%d cause=%s",
                    exc.snp_message_id, exc.ie_depth, exc.cause,
                )
                winning_pos, resolution_label = None, "ie_repair_exhausted"

            for a in assessments:
                pos = specialist_positions[a["reviewer_id"]]
                a["risk_bucket"] = str(pos.get("risk_bucket", a["risk_bucket"]))
                a["risk_score"] = float(pos.get("risk_score", a["risk_score"]))
                a["review_mode"] = f"snp_star:{resolution_label}"

            LOGGER.info(
                "pharmacy.snp_star resolution=%s specialists=%d snp_messages=%d",
                resolution_label,
                len(member_ids),
                len(self.panel_negotiation_bus.snp_trace),
            )

        return self._aggregate_panel(assessments)

    def rederive_position(self, speaker_id: str, derailment_cause: str | None) -> "Dict[str, Any] | None":
        ctx = getattr(self, "_repair_context", None)
        if ctx is None:
            return None
        spec = ctx["spec_by_id"].get(speaker_id)
        if spec is None:
            return None
        return self._request_pharmacy_assessment(
            patient=ctx["patient"],
            semantic_rules=ctx["semantic_rules"],
            reviewer_index=int(spec["index"]),
            review_mode="repair",
            specialist_role=spec["role"],
            reviewer_id_override=speaker_id,
            coordination_summary=ctx.get("coordination_summary"),
            derailment_constraint=derailment_cause,
        )

    def run(self, inbox: "queue.Queue[Dict[str, Any]]") -> None:
        """Threaded entry point: loop on *inbox*, dispatch to review(), reply via _reply_queue."""
        while True:
            try:
                envelope = inbox.get(timeout=90)
            except queue.Empty:
                continue
            if envelope is None:
                return
            parent_id = envelope.get("l9_header", {}).get("message_id")
            reply_q: "queue.Queue[Dict[str, Any]] | None" = envelope.get("payload", {}).get("_reply_queue")
            try:
                p = envelope.get("payload", {})
                result = self.review(
                    patient=p["patient"],
                    semantic_rules=p.get("semantic_rules"),
                    coordination_summary=p.get("coordination_summary"),
                )
                if reply_q is not None:
                    reply_q.put({"event_type": "agent_response", "result": result, "parent_id": parent_id})
            except Exception as exc:
                LOGGER.error("pharmacy.run error: %s\n%s", exc, _tb.format_exc())
                if self.bus is not None:
                    self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                        sender="pharmacy", receiver=envelope.get("sender", "orchestrator"),
                        error_type=type(exc).__name__, error_message=str(exc),
                        traceback=_tb.format_exc(), parent_id=parent_id,
                    )
                if reply_q is not None:
                    reply_q.put({"event_type": "agent_error", "error": str(exc), "parent_id": parent_id})


# Backwards-compat alias
PharmacyAgent = PharmacyController


# ── InsuranceAgent (unchanged) ────────────────────────────────────────────────


class InsuranceAgent:
    def __init__(
        self,
        llm: LLMClient,
        reviewer_count: int = DEFAULT_INSURANCE_REVIEWER_COUNT,
        bus: "HealthcareAgentBus | None" = None,
        panel_negotiation_bus: "PanelNegotiationBus | None" = None,
        task_session: "TaskSession | None" = None,
    ) -> None:
        self.llm = llm
        self.reviewer_count = max(1, reviewer_count)
        self.bus = bus
        self.panel_negotiation_bus = panel_negotiation_bus
        self.task_session = task_session

    @staticmethod
    def _canonical_approved(specialties: List[str]) -> Tuple[str, ...]:
        return tuple(sorted({str(item) for item in specialties if str(item).strip()}))

    @staticmethod
    def _decision_key(decision: Dict[str, Any]) -> Tuple[bool, Tuple[str, ...]]:
        return bool(decision.get("in_network_only", True)), tuple(decision.get("approved_specialties", ()))

    @staticmethod
    def _group_by_decision(decisions: List[Dict[str, Any]]) -> Dict[Tuple[bool, Tuple[str, ...]], List[Dict[str, Any]]]:
        groups: Dict[Tuple[bool, Tuple[str, ...]], List[Dict[str, Any]]] = {}
        for decision in decisions:
            groups.setdefault(InsuranceAgent._decision_key(decision), []).append(decision)
        return groups

    @staticmethod
    def _leading_group(
        groups: Dict[Tuple[bool, Tuple[str, ...]], List[Dict[str, Any]]]
    ) -> tuple[Tuple[bool, Tuple[str, ...]], List[Dict[str, Any]]]:
        return max(
            groups.items(),
            key=lambda item: (
                len(item[1]),
                round(_mean([_as_float(decision.get("roi_score"), 0.5) for decision in item[1]], 0.5), 4),
                item[0],
            ),
        )

    def _request_insurance_decision(
        self,
        patient: PatientProfile,
        providers: List[SpecialistProvider],
        requested_specialties: List[str],
        reviewer_index: int,
        review_mode: str,
        preferred_in_network: bool | None = None,
        preferred_approved: Tuple[str, ...] | None = None,
        template: Dict[str, Any] | None = None,
        coordination_summary: Dict[str, Any] | None = None,
        derailment_constraint: str | None = None,
    ) -> Dict[str, Any]:
        payload = {
            "insurance_plan": patient.insurance_plan,
            "requested_specialties": requested_specialties,
            "providers": [
                {
                    "provider_id": provider.provider_id,
                    "specialty": provider.specialty,
                    "in_network_plans": provider.in_network_plans,
                }
                for provider in providers
            ],
            "reviewer_id": f"insurance-reviewer-{reviewer_index:02d}",
            "reviewer_index": reviewer_index,
            "review_mode": review_mode,
        }
        if preferred_approved is not None:
            payload["preferred_approved_specialties"] = list(preferred_approved)
        if preferred_in_network is not None:
            payload["preferred_in_network_only"] = preferred_in_network
        if coordination_summary:
            payload["coordination_summary"] = coordination_summary
        if derailment_constraint:
            payload["derailment_constraint"] = derailment_constraint

        reviewer_id = payload["reviewer_id"]
        req_header = None
        if self.bus:
            req_header = self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                sender="insurance",
                receiver=reviewer_id,
                utterance=f"validate coverage for {requested_specialties} review_mode={review_mode}",
            )
        result = self.llm.complete_json("insurance_coverage_review", payload)

        in_network_only = bool(
            result.get(
                "in_network_only",
                bool(template.get("in_network_only", True)) if template is not None else True,
            )
        )
        approved_from_result: List[str] = [str(item) for item in result.get("approved_specialties", [])]
        approved_fallback: List[str] = [str(item) for item in template.get("approved_specialties", ())] if template is not None else []
        approved_specialties = self._canonical_approved(approved_from_result or approved_fallback)
        estimated_out_of_pocket_eur = _as_float(
            result.get("estimated_out_of_pocket_eur"),
            _as_float(template.get("estimated_out_of_pocket_eur"), 250.0) if template is not None else 250.0,
        )
        roi_score = _as_float(
            result.get("roi_score"),
            _as_float(template.get("roi_score"), 0.5) if template is not None else 0.5,
        )
        validation_note = str(
            result.get(
                "validation_note",
                template.get("validation_note", "Coverage validated.") if template is not None else "Coverage validated.",
            )
        )

        if (
            review_mode != "independent"
            and template is not None
            and preferred_approved is not None
            and preferred_in_network is not None
            and (approved_specialties != preferred_approved or in_network_only != preferred_in_network)
        ):
            approved_specialties = preferred_approved
            in_network_only = preferred_in_network
            estimated_out_of_pocket_eur = _as_float(template.get("estimated_out_of_pocket_eur"), estimated_out_of_pocket_eur)
            roi_score = max(0.0, min(1.0, _as_float(template.get("roi_score"), roi_score) - 0.01))
            validation_note = (
                f"Targeted panel {review_mode.replace('_', ' ')} corroborated in-network specialty approvals. "
                f"{template.get('validation_note', validation_note)}"
            )

        if req_header:
            approved_str = ",".join(approved_specialties) if approved_specialties else "none"
            _ins_utterance = f"approved={approved_str} in_network={in_network_only}"
            _ins_thought = result.get("thought_summary", "")
            if self.task_session is not None:
                self.task_session.assess(
                    agent_id=reviewer_id,
                    concept_id="concept:coverage_decision",
                    posterior=roi_score,
                    utterance=_ins_utterance,
                    parent_id=req_header["message"]["id"],
                    receiver="insurance",
                    rationale=validation_note,
                    thought_summary=_ins_thought,
                )
            elif self.bus is not None:
                self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                    sender=reviewer_id,
                    receiver="insurance",
                    utterance=_ins_utterance,
                    rationale=validation_note,
                    thought_summary=_ins_thought,
                    parent_id=req_header["message"]["id"],
                    epistemic=make_epistemic_block(
                        speech_act=SpeechAct.BELIEF_ASSERTION,
                        epistemic_state=EpistemicState.TASKWORK,
                        belief_status=BeliefStatus.ASSERTED,
                        uncertainty=round(1.0 - roi_score, 4),
                        concept_id="concept:coverage_decision",
                    ),
                )
        return {
            "reviewer_id": reviewer_id,
            "review_mode": review_mode,
            "in_network_only": in_network_only,
            "approved_specialties": approved_specialties,
            "estimated_out_of_pocket_eur": estimated_out_of_pocket_eur,
            "roi_score": roi_score,
            "validation_note": validation_note,
        }

    def _expand_panel(
        self,
        patient: PatientProfile,
        providers: List[SpecialistProvider],
        requested_specialties: List[str],
        decisions: List[Dict[str, Any]],
        coordination_summary: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        next_reviewer_index = len(decisions) + 1

        initial_groups = list(self._group_by_decision(decisions).items())
        for decision_key, members in initial_groups:
            if len(members) != 1:
                continue
            preferred_in_network, preferred_approved = decision_key
            decisions.append(
                self._request_insurance_decision(
                    patient=patient,
                    providers=providers,
                    requested_specialties=requested_specialties,
                    reviewer_index=next_reviewer_index,
                    review_mode="corroboration_review",
                    preferred_in_network=preferred_in_network,
                    preferred_approved=preferred_approved,
                    template=members[0],
                    coordination_summary=coordination_summary,
                )
            )
            next_reviewer_index += 1

        groups = self._group_by_decision(decisions)
        while True:
            leading_key, leading_group = self._leading_group(groups)
            if len(leading_group) > len(decisions) / 2:
                break

            preferred_in_network, preferred_approved = leading_key
            template = max(leading_group, key=lambda item: _as_float(item.get("roi_score"), 0.0))
            decisions.append(
                self._request_insurance_decision(
                    patient=patient,
                    providers=providers,
                    requested_specialties=requested_specialties,
                    reviewer_index=next_reviewer_index,
                    review_mode="majority_review",
                    preferred_in_network=preferred_in_network,
                    preferred_approved=preferred_approved,
                    template=template,
                    coordination_summary=coordination_summary,
                )
            )
            next_reviewer_index += 1
            groups = self._group_by_decision(decisions)

        return decisions

    def _aggregate_panel(self, decisions: List[Dict[str, Any]]) -> InsuranceDecision:
        groups = self._group_by_decision(decisions)
        leading_key, leading_group = self._leading_group(groups)
        in_network_only, approved_specialties = leading_key
        panel_size = len(decisions)
        majority_size = len(leading_group)

        estimated_out_of_pocket_eur = round(
            _mean([_as_float(item.get("estimated_out_of_pocket_eur"), 250.0) for item in leading_group], 250.0),
            2,
        )
        roi_score = round(_mean([_as_float(item.get("roi_score"), 0.5) for item in leading_group], 0.5), 4)
        vote_breakdown = {
            f"in_network={key[0]}|approved={','.join(key[1]) or 'none'}": len(group)
            for key, group in groups.items()
        }
        validation_note = (
            f"Panel consensus {majority_size}/{panel_size} reviewers; "
            f"{leading_group[0].get('validation_note', 'Coverage validated.')}"
        )

        LOGGER.info(
            "insurance.panel_consensus initial=%d final=%d majority=%d vote_breakdown=%s",
            self.reviewer_count,
            panel_size,
            majority_size,
            vote_breakdown,
        )

        reviewer_decisions: List[Dict[str, Any]] = []
        for index, item in enumerate(decisions, start=1):
            approved = item.get("approved_specialties", ())
            reviewer_decisions.append(
                {
                    "reviewer_id": str(item.get("reviewer_id", f"insurance-reviewer-{index:02d}")),
                    "review_mode": str(item.get("review_mode", "independent")),
                    "in_network_only": bool(item.get("in_network_only", True)),
                    "approved_specialties": [str(specialty) for specialty in approved],
                    "estimated_out_of_pocket_eur": round(_as_float(item.get("estimated_out_of_pocket_eur"), 250.0), 2),
                    "roi_score": round(_as_float(item.get("roi_score"), 0.5), 4),
                    "validation_note": str(item.get("validation_note", "Coverage validated.")),
                }
            )

        return InsuranceDecision(
            in_network_only=in_network_only,
            approved_specialties=list(approved_specialties),
            estimated_out_of_pocket_eur=estimated_out_of_pocket_eur,
            roi_score=roi_score,
            validation_note=validation_note,
            panel_size=panel_size,
            majority_size=majority_size,
            vote_breakdown=vote_breakdown,
            reviewer_decisions=reviewer_decisions,
        )

    def validate(
        self,
        patient: PatientProfile,
        providers: List[SpecialistProvider],
        requested_specialties: List[str],
        coordination_summary: Dict[str, Any] | None = None,
    ) -> InsuranceDecision:
        self._repair_context = {
            "patient": patient,
            "providers": providers,
            "requested_specialties": requested_specialties,
            "coordination_summary": coordination_summary,
            "reviewer_by_id": {f"insurance-reviewer-{i:02d}": i for i in range(1, self.reviewer_count + 1)},
        }
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.reviewer_count) as pool:
            futures = {
                pool.submit(
                    self._request_insurance_decision,
                    patient=patient,
                    providers=providers,
                    requested_specialties=requested_specialties,
                    reviewer_index=reviewer_index,
                    review_mode="independent",
                    coordination_summary=coordination_summary,
                ): reviewer_index
                for reviewer_index in range(1, self.reviewer_count + 1)
            }
            decisions: List[Dict[str, Any]] = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    decisions.append(future.result())
                except Exception as exc:
                    LOGGER.warning("insurance: reviewer-%02d abstained: %s", futures[future], exc)

        if len(decisions) > 1:
            decisions = self._expand_panel(patient, providers, requested_specialties, decisions, coordination_summary=coordination_summary)

        if len(decisions) > 1 and self.panel_negotiation_bus is not None:
            from SSTP.examples.hcpanel.panel_negotiation_bus import PanelNegotiationRing, IERepairExhausted

            self.panel_negotiation_bus.reset()
            member_ids = [d["reviewer_id"] for d in decisions]
            initial_positions = {
                d["reviewer_id"]: {
                    "decision_key": f"net={d['in_network_only']}|{','.join(d['approved_specialties'])}",
                    "confidence": d["roi_score"],
                    "in_network_only": d["in_network_only"],
                    "approved_specialties": d["approved_specialties"],
                    "estimated_out_of_pocket_eur": d["estimated_out_of_pocket_eur"],
                    "roi_score": d["roi_score"],
                    "validation_note": d["validation_note"],
                }
                for d in decisions
            }
            ring = PanelNegotiationRing(self.panel_negotiation_bus, "insurance")
            try:
                winning_pos, resolution_label, _ = ring.run(
                    member_ids,
                    initial_positions,
                    task_goal=f"insurance coverage decision for patient {getattr(patient, 'name', 'unknown')}",
                    agent_beliefs={mid: {"role": "insurance reviewer", "confidence": 0.6} for mid in member_ids},
                )
            except IERepairExhausted as exc:
                LOGGER.warning(
                    "insurance.ie_repair_exhausted snp_msg=%s depth=%d cause=%s",
                    exc.snp_message_id, exc.ie_depth, exc.cause,
                )
                winning_pos, resolution_label = None, "ie_repair_exhausted"
            for d in decisions:
                pos = initial_positions[d["reviewer_id"]]
                d["in_network_only"] = pos["in_network_only"]
                d["approved_specialties"] = pos["approved_specialties"]
                d["roi_score"] = PanelNegotiationRing._confidence(pos)
                d["review_mode"] = f"snp_negotiation:{resolution_label}"
            LOGGER.info(
                "insurance.snp_negotiation resolution=%s members=%d snp_messages=%d",
                resolution_label,
                len(member_ids),
                len(self.panel_negotiation_bus.snp_trace),
            )

        return self._aggregate_panel(decisions)

    def rederive_position(self, speaker_id: str, derailment_cause: str | None) -> "Dict[str, Any] | None":
        ctx = getattr(self, "_repair_context", None)
        if ctx is None:
            return None
        reviewer_index = ctx["reviewer_by_id"].get(speaker_id)
        if reviewer_index is None:
            return None
        return self._request_insurance_decision(
            patient=ctx["patient"],
            providers=ctx["providers"],
            requested_specialties=ctx["requested_specialties"],
            reviewer_index=reviewer_index,
            review_mode="repair",
            coordination_summary=ctx.get("coordination_summary"),
            derailment_constraint=derailment_cause,
        )

    def run(self, inbox: "queue.Queue[Dict[str, Any]]") -> None:
        """Threaded entry point: loop on *inbox*, dispatch to validate(), reply via _reply_queue."""
        while True:
            try:
                envelope = inbox.get(timeout=90)
            except queue.Empty:
                continue
            if envelope is None:
                return
            parent_id = envelope.get("l9_header", {}).get("message_id")
            reply_q: "queue.Queue[Dict[str, Any]] | None" = envelope.get("payload", {}).get("_reply_queue")
            try:
                p = envelope.get("payload", {})
                result = self.validate(
                    patient=p["patient"],
                    providers=p["providers"],
                    requested_specialties=p.get("requested_specialties", []),
                    coordination_summary=p.get("coordination_summary"),
                )
                if reply_q is not None:
                    reply_q.put({"event_type": "agent_response", "result": result, "parent_id": parent_id})
            except Exception as exc:
                LOGGER.error("insurance.run error: %s\n%s", exc, _tb.format_exc())
                if self.bus is not None:
                    self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                        sender="insurance", receiver=envelope.get("sender", "orchestrator"),
                        error_type=type(exc).__name__, error_message=str(exc),
                        traceback=_tb.format_exc(), parent_id=parent_id,
                    )
                if reply_q is not None:
                    reply_q.put({"event_type": "agent_error", "error": str(exc), "parent_id": parent_id})


# ── SchedulingAgent (unchanged) ───────────────────────────────────────────────


class SchedulingAgent:
    def __init__(self, llm: LLMClient, bus: "HealthcareAgentBus | None" = None) -> None:
        self.llm = llm
        self.bus = bus

    def schedule(
        self,
        patient: PatientProfile,
        providers: List[SpecialistProvider],
        approved_specialties: List[str],
        coordination_summary: Dict[str, Any] | None = None,
    ) -> ScheduledAppointment:
        filtered = [
            provider
            for provider in providers
            if provider.specialty in approved_specialties and patient.insurance_plan in provider.in_network_plans
        ]
        payload = {
            "patient_slots": patient.calendar_slots_day_offsets,
            "candidate_providers": [
                {
                    "provider_id": provider.provider_id,
                    "specialty": provider.specialty,
                    "availability_day_offsets": provider.availability_day_offsets,
                }
                for provider in filtered
            ],
        }
        if coordination_summary:
            payload["coordination_summary"] = coordination_summary
        result = self.llm.complete_json("scheduling_route", payload)
        return ScheduledAppointment(
            provider_id=str(result.get("provider_id", "waitlist")),
            specialty=str(result.get("specialty", approved_specialties[0] if approved_specialties else "general_medicine")),
            day_offset=int(result.get("day_offset", 7)),
            reminder_plan=[str(item) for item in result.get("reminder_plan", ["reminder_24h"])],
        )

    def run(self, inbox: "queue.Queue[Dict[str, Any]]") -> None:
        """Threaded entry point: loop on *inbox*, dispatch to schedule(), reply via _reply_queue."""
        while True:
            try:
                envelope = inbox.get(timeout=90)
            except queue.Empty:
                continue
            if envelope is None:
                return
            parent_id = envelope.get("l9_header", {}).get("message_id")
            reply_q: "queue.Queue[Dict[str, Any]] | None" = envelope.get("payload", {}).get("_reply_queue")
            try:
                p = envelope.get("payload", {})
                result = self.schedule(
                    patient=p["patient"],
                    providers=p["providers"],
                    approved_specialties=p.get("approved_specialties", []),
                    coordination_summary=p.get("coordination_summary"),
                )
                if reply_q is not None:
                    reply_q.put({"event_type": "agent_response", "result": result, "parent_id": parent_id})
            except Exception as exc:
                LOGGER.error("scheduling.run error: %s\n%s", exc, _tb.format_exc())
                if self.bus is not None:
                    self.bus.emit_peer_turn(speech_act=SpeechAct.BELIEF_ASSERTION, epistemic_state=EpistemicState.TASKWORK,
                        sender="scheduling", receiver=envelope.get("sender", "orchestrator"),
                        error_type=type(exc).__name__, error_message=str(exc),
                        traceback=_tb.format_exc(), parent_id=parent_id,
                    )
                if reply_q is not None:
                    reply_q.put({"event_type": "agent_error", "error": str(exc), "parent_id": parent_id})


def requested_specialties_from_assessment(
    diagnostics: ClinicalAssessment,
    pharmacy: MedicationProposal,
) -> List[str]:
    if diagnostics.likely_cause == "drug_interaction" or pharmacy.risk_score >= 0.5:
        return ["clinical_pharmacology", "internal_medicine"]
    return ["internal_medicine"]


def summarize_interaction_signals(patient: PatientProfile, pharmacy: MedicationProposal) -> Dict[str, float]:
    symptom_pressure = min(1.0, len(patient.symptoms) / 8.0)
    medication_load = min(1.0, len(patient.current_medications) / 6.0)
    risk = min(1.0, 0.5 * pharmacy.risk_score + 0.3 * symptom_pressure + 0.2 * medication_load)
    return {
        "symptom_pressure": round(symptom_pressure, 4),
        "medication_load": round(medication_load, 4),
        "interaction_risk": round(risk, 4),
    }

class SpecialistAgent:
    """A single specialist in the debate panel.

    Owns all per-agent epistemic state. No store references are shared
    with any other agent. State is exported only through L9 message payloads.
    """

    def __init__(
        self,
        agent_id: str,
        role: str,
        focus: str,
        prior_belief: str,
        panel: str,                     # "physician" | "pharmacology"
        llm: LLMClient,
        bus: Optional["HCPanelAgentBus"] = None,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.focus = focus
        self.prior_belief = prior_belief
        self.panel = panel
        self.llm = llm
        self.bus = bus

        # Per-agent stores — owned exclusively by this instance
        self.belief_store = AgentBeliefStore()
        self.peer_store = PeerInteractionStore()
        self.taskwork_store = TaskworkStore()
        self.epistemic_store = AgentEpistemicStore(agent_id)

    def assess_patient(
        self,
        patient: PatientProfile,
        episode_id: str,
        likelihood_store: Optional[LikelihoodStore] = None,
        semantic_rules: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Produce an independent prior-driven position for this agent.

        Returns a position dict compatible with StarNegotiation.run():
        {likely_cause, confidence, posterior, supporting_evidence,
         against_evidence, reasoning_summary, rationale}
        """
        rules = semantic_rules or []

        # Extract structured findings from patient data
        findings = extract_findings(
            patient.symptoms,
            patient.health_history,
            patient.current_medications,
        )

        # Bayesian posterior only for simulated backends (deterministic tables).
        # Real LLM backends should reason directly from patient data.
        use_bayes = isinstance(self.llm, SimulatedHealthcareLLMClient)
        likelihood_table = (likelihood_store.get(self.role) if likelihood_store else None) if use_bayes else None
        thought_summary = ""
        if likelihood_table is not None and findings:
            from SSTP.subprotocol.siep.src.epistemic.bayes import compute_posterior, normalize_posteriors
            hypotheses = ["drug_interaction", "new_disease"]
            unnorm = {
                h: compute_posterior(
                    compute_prior(rules, h),
                    findings,
                    h,
                    likelihood_table,
                )
                for h in hypotheses
            }
            norm = normalize_posteriors(unnorm)
            di_post = norm.get("drug_interaction", 0.5)
            nd_post = norm.get("new_disease", 0.5)
            inferred_cause = (
                "drug_interaction" if di_post >= nd_post + 0.05 else "new_disease"
            )
            if di_post < 0.45 and nd_post < 0.45:
                inferred_cause = "inconclusive"
            gap = abs(di_post - nd_post)
            confidence = round(min(0.95, 0.55 + gap * 0.8), 4)
            posterior = max(di_post, nd_post)
            top_ev = [
                f for f in findings
                if likelihood_table.likelihood_ratio(f, inferred_cause) > 1.2
            ]
            against_ev = [f for f in findings if f not in top_ev]
            from SSTP.examples.hcpanel.llm_backends import generate_reasoning_summary
            rationale = generate_reasoning_summary(posterior, top_ev, inferred_cause, role=self.role)
        else:
            # Fallback: use LLM directly
            payload = {
                "symptoms": patient.symptoms,
                "health_history": patient.health_history,
                "current_medications": patient.current_medications,
                "specialist_role": self.role,
                "specialist_prior": self.prior_belief,
                "review_mode": "independent",
            }
            result = self.llm.complete_json("diagnostics_assessment", payload)
            inferred_cause = str(result.get("likely_cause", "drug_interaction"))
            confidence = float(result.get("confidence", 0.65))
            posterior = confidence
            top_ev = findings
            against_ev = []
            raw_rationale = result.get("rationale", "")
            # rationale may be a dict with sub-keys — flatten to prose
            if isinstance(raw_rationale, dict):
                rationale = " ".join(
                    str(v) for v in raw_rationale.values()
                    if isinstance(v, str) and str(v).strip()
                ).strip() or str(raw_rationale)
            else:
                rationale = str(raw_rationale)
            thought_summary = str(result.get("thought_summary", ""))

        position: Dict[str, Any] = {
            "likely_cause": inferred_cause,
            "confidence": confidence,
            "posterior": posterior,
            "supporting_evidence": top_ev,
            "against_evidence": against_ev,
            "reasoning_summary": rationale,
            "rationale": rationale,
            "thought_summary": thought_summary,
        }

        # Emit taskwork assertion on the bus — suppressed when episode_id is None
        # (caller passes None during _node_orchestrate to compute positions without emitting;
        # run_joint_panel() re-emits inside the open taskwork episode via emit_taskwork_result)
        if self.bus is not None and episode_id is not None:
            self.bus.emit_peer_turn(
                speech_act=SpeechAct.BELIEF_ASSERTION,
                epistemic_state=EpistemicState.TASKWORK,
                sender=self.agent_id,
                receiver="diagnostics-controller",
                utterance=f"{inferred_cause} confidence={confidence:.2f}",
                rationale=rationale,
                episode_id=episode_id,
                epistemic=make_epistemic_block(
                    speech_act=SpeechAct.BELIEF_ASSERTION,
                    epistemic_state=EpistemicState.TASKWORK,
                    belief_status=BeliefStatus.ASSERTED,
                    uncertainty=round(1.0 - confidence, 4),
                ),
            )

        LOGGER.debug(
            "specialist.assess agent=%s cause=%s confidence=%.4f",
            self.agent_id, inferred_cause, confidence,
        )
        return position

    def promote_peer_outcomes(
        self,
        episode_id: str,
        argument_outcomes: Optional[List[ArgumentOutcome]] = None,
        prediction_records: Optional[List[PredictionRecord]] = None,
        peer_id: Optional[str] = None,
    ) -> None:
        """Write observed argument outcomes to this agent's own PeerInteractionStore."""
        if not argument_outcomes:
            return
        obs = peer_id or "diagnostics-controller"
        self.peer_store.promote_outcomes_for_pair(
            observer_id=self.agent_id,
            subject_id=obs,
            use_case="healthcare",
            episode_id=episode_id,
            argument_outcomes=argument_outcomes,
            prediction_records=prediction_records or [],
        )


class PhysicianController:
    """Pure orchestrator for the physician panel. Owns no epistemic stores."""

    def __init__(
        self,
        llm: LLMClient,
        bus: Optional["HCPanelAgentBus"] = None,
    ) -> None:
        self.llm = llm
        self.bus = bus
        self.specialists: List[SpecialistAgent] = [
            SpecialistAgent(
                agent_id=f"physician-{s['id_suffix']}",
                role=s["role"],
                focus=s["focus"],
                prior_belief=s.get("prior_belief", ""),
                panel="physician",
                llm=llm,
                bus=bus,
            )
            for s in DIAGNOSTICS_SPECIALISTS
        ]

    @property
    def agent_ids(self) -> List[str]:
        return [a.agent_id for a in self.specialists]

    def assess_all(
        self,
        patient: PatientProfile,
        episode_id: str,
        likelihood_store: Optional[LikelihoodStore] = None,
        semantic_rules: Optional[List[Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        return {
            agent.agent_id: agent.assess_patient(
                patient, episode_id, likelihood_store, semantic_rules
            )
            for agent in self.specialists
        }


class PharmacologyController:
    """Pure orchestrator for the pharmacology panel. Owns no epistemic stores."""

    def __init__(
        self,
        llm: LLMClient,
        bus: Optional["HCPanelAgentBus"] = None,
    ) -> None:
        self.llm = llm
        self.bus = bus
        self.specialists: List[SpecialistAgent] = [
            SpecialistAgent(
                agent_id=f"pharmacologist-{s['id_suffix']}",
                role=s["role"],
                focus=s["focus"],
                prior_belief=s.get("prior_belief", ""),
                panel="pharmacology",
                llm=llm,
                bus=bus,
            )
            for s in PHARMACY_SPECIALISTS
        ]

    @property
    def agent_ids(self) -> List[str]:
        return [a.agent_id for a in self.specialists]

    def assess_all(
        self,
        patient: PatientProfile,
        episode_id: str,
        likelihood_store: Optional[LikelihoodStore] = None,
        semantic_rules: Optional[List[Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        return {
            agent.agent_id: agent.assess_patient(
                patient, episode_id, likelihood_store, semantic_rules
            )
            for agent in self.specialists
        }

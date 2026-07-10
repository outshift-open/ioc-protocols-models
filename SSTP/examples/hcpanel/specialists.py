from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional

from SSTP.subprotocol.siep.src.tomcore.llm import LLMClient
from SSTP.subprotocol.siep.src.builder import NegotiationOperation  # type: ignore[import]
from SSTP.subprotocol.siep.src.panel import NetworkHandle
from SSTP.examples.hcpanel.domain import PatientProfile
from SSTP.examples.hcpanel.llm_backends import extract_findings

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

ROLE_DESCRIPTIONS: Dict[str, str] = {
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


@dataclass
class SpecialistSessionContext:
    """Per-session state allocated on intent arrival; cleared on commit:converged."""
    episode_id: str
    concept_id: str
    session_objective: str
    taskwork_episode: Optional[Any] = None
    patient: Optional["PatientProfile"] = None

    def clear(self) -> None:
        self.taskwork_episode = None
        self.patient = None


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
        bus: Optional[NetworkHandle] = None,
        llm_factory: Optional[Any] = None,
        peer_descriptions: Optional[Dict[str, str]] = None,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.focus = focus
        self.prior_belief = prior_belief
        self.panel = panel
        self.llm = llm
        self.bus = bus
        self._llm_factory = llm_factory
        self._peer_descriptions: Dict[str, str] = peer_descriptions or {}
        self.process_params: Dict[str, Any] = {}

        # L9 episode API — wired up by wire_up_l9()
        self._l9: Optional[Any] = None
        self._session: Optional[SpecialistSessionContext] = None

    def reset_session(self) -> None:
        """Reset per-session state."""
        self.process_params = {}

    def set_process_params(self, params: Dict[str, Any]) -> None:
        """Receive committed team-process parameters from the coordinator."""
        self.process_params = params

    def drain_llm_trace(self) -> list:
        """Return and clear LLM trace records for this agent."""
        return self.llm.drain_trace() if self.llm is not None else []

    def set_patient(self, patient: "PatientProfile") -> None:
        """Store the current patient so taskwork dispatch can access it."""
        if self._session is not None:
            self._session.patient = patient
        else:
            # Session not yet allocated — stash on a temporary attribute
            self._pending_patient: Optional["PatientProfile"] = patient

    def wire_up_l9(self, bus: NetworkHandle) -> None:
        """Connect this specialist to the L9 episode API.

        Must be called before the coordinator emits any intents. Registers
        handlers and publishes this agent's L9 to bus.specialist_l9s for
        debate-round dispatch routing only.
        """
        from SSTP.l9.episode import L9  # type: ignore[import]
        self.bus = bus
        l9 = L9(
            bus=bus,
            agent_id=self.agent_id,
            llm_factory=self._llm_factory,
            peer_descriptions=self._peer_descriptions,
        )
        self._l9 = l9
        # Publish to bus so episode API can read per-agent stores internally
        specialist_l9s = getattr(bus, "specialist_l9s", None)
        if specialist_l9s is not None:
            specialist_l9s[self.agent_id] = l9

        l9.on_intent(self._on_intent)
        l9.on_debate_round(self._on_debate_round)
        l9.on_taskwork(self._on_taskwork)

    def _on_debate_round(self, round_ep: Any) -> None:
        is_tp_round = bool(round_ep.ctrl_pos.get("team_process_terms"))
        if is_tp_round:
            result = self.tp_accept_or_counter(
                ctrl_pos=round_ep.ctrl_pos,
                member_pos=round_ep.member_pos,
                task_goal=round_ep.task_goal,
                session_objective=(self._session.session_objective if self._session else ""),
                tom_ctx=round_ep.tom_ctx,
            )
        else:
            result = self.task_accept_or_counter(
                ctrl_pos=round_ep.ctrl_pos,
                member_pos=round_ep.member_pos,
                task_goal=round_ep.task_goal,
                session_objective=(self._session.session_objective if self._session else ""),
                tom_ctx=round_ep.tom_ctx,
            )
        if result.get("decision") == "accept":
            operation = NegotiationOperation.ACCEPT
            position = round_ep.ctrl_pos
        else:
            operation = NegotiationOperation.COUNTER_PROPOSAL
            position = {
                **round_ep.member_pos,
                "likely_cause": str(result.get("counter_concept", round_ep.ctrl_position_key)),
                "confidence": float(result.get("counter_confidence",
                                               round_ep.member_pos.get("confidence", 0.5))),
                "rationale": str(result.get("rationale", "")),
                "supporting_evidence": list(result.get("supporting_evidence", [])),
            }
        round_ep.respond(
            str(operation.value if hasattr(operation, "value") else operation),
            position,
        )

    def _on_taskwork(self, participant: Any) -> None:
        """Fill in a TaskworkParticipant by running the LLM assessment."""
        patient = (
            self._session.patient if self._session is not None else None
        ) or getattr(self, "_pending_patient", None)
        if patient is None:
            LOGGER.warning("taskwork_assess agent=%s: no patient set", self.agent_id)
            return
        role_assignment = self.process_params.get("role_assignment") or []
        semantic_rules = (
            self.process_params.get("semantic_rules")
            or self.process_params.get("contingency_rules")
            or []
        )
        coordinator_framing = self.process_params.get("session_objective", "")
        result = self.assess_patient_in_episode(
            patient=patient,
            coordinator_framing=coordinator_framing,
            role_assignment=role_assignment,
            semantic_rules=semantic_rules,
        )
        participant.utterance = result.get("utterance", "")
        participant.rationale = result.get("rationale", "")
        participant.likely_cause = result.get("likely_cause", "")
        participant.posterior = float(result.get("posterior", result.get("confidence", 0.5)))
        participant.thought_summary = result.get("thought_summary", "")
        participant.evidence = result.get("supporting_evidence") or []

    def dispatch_intent(self, header: Any) -> None:
        """Route an incoming intent header through this agent's L9."""
        if self._l9 is not None:
            self._l9.dispatch_intent(header)

    def _on_intent(self, episode: Any) -> None:
        """Allocate or update session context on intent arrival.

        Does NOT emit any message — response is via assess_patient_in_episode
        (taskwork) or tp_accept_or_counter (team process), both of which call
        episode.say() / episode.done().
        """
        eid = getattr(episode, "episode_id", "") or ""
        concept_id = getattr(episode, "concept_id", "") or ""
        if self._session is None or self._session.episode_id != eid:
            self._session = SpecialistSessionContext(
                episode_id=eid,
                concept_id=concept_id,
                session_objective="",
            )
        if ":tp" not in eid:
            self._session.taskwork_episode = episode

    def _on_task_converged(self, knowledge_content: str = "") -> None:
        """Clear per-session state after commit:converged.

        Belief store, peer store, and taskwork store are retained — they
        carry knowledge that persists across episodes.
        """
        if self._session is not None:
            self._session.clear()
        self._session = None
        self.process_params = {}

    def assess_patient_in_episode(
        self,
        patient: PatientProfile,
        coordinator_framing: str = "",
        role_assignment: Optional[List[str]] = None,
        semantic_rules: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Produce an independent position inside an open episode.

        Called via the ``assess_fn`` callback injected into TaskworkEpisode.
        Always runs the LLM (coordinator framing and role assignment are live).
        Returns a position dict with distinct ``utterance`` (short assertion)
        and ``rationale`` (full reasoning chain).
        """
        rules = semantic_rules or []
        findings = extract_findings(
            patient.symptoms,
            patient.health_history,
            patient.current_medications,
        )

        payload = {
            "symptoms": patient.symptoms,
            "health_history": patient.health_history,
            "current_medications": patient.current_medications,
            "specialist_role": self.role,
            "specialist_prior": self.prior_belief,
            "review_mode": "independent",
            "session_objective": coordinator_framing,
            "responsible_for": role_assignment or [],
            "semantic_rules": rules,
        }
        result = self.llm.complete_json("diagnostics_assessment", payload)
        inferred_cause = str(result.get("likely_cause", "drug_interaction"))
        confidence = float(result.get("confidence", 0.65))
        posterior = confidence
        top_ev = list(result.get("supporting_evidence", findings))
        against_ev = list(result.get("against_evidence", []))
        raw_rationale = result.get("rationale", "")
        if isinstance(raw_rationale, dict):
            full_rationale = " ".join(
                str(v) for v in raw_rationale.values()
                if isinstance(v, str) and str(v).strip()
            ).strip() or str(raw_rationale)
        else:
            full_rationale = str(raw_rationale)
        thought_summary = str(result.get("thought_summary", ""))

        # TW-3: distinct utterance (short claim) vs rationale (full chain)
        utterance = full_rationale[:200].rstrip() + ("..." if len(full_rationale) > 200 else "")

        tw_ep = (self._session.taskwork_episode if self._session is not None else None)
        if self._l9 is not None and tw_ep is not None:
            self._l9.send(
                tw_ep,
                utterance=f"{inferred_cause} confidence={confidence:.2f}",
                posterior=confidence,
                rationale=full_rationale,
                thought_summary=thought_summary,
                evidence=top_ev,
            )

        LOGGER.debug(
            "specialist.assess_in_episode agent=%s cause=%s confidence=%.4f",
            self.agent_id, inferred_cause, confidence,
        )
        return {
            "utterance": utterance,
            "rationale": full_rationale,
            "likely_cause": inferred_cause,
            "confidence": confidence,
            "posterior": posterior,
            "supporting_evidence": top_ev,
            "against_evidence": against_ev,
            "reasoning_summary": full_rationale,
            "thought_summary": thought_summary,
        }

    def tp_accept_or_counter(
        self,
        ctrl_pos: Dict[str, Any],
        member_pos: Dict[str, Any],
        task_goal: str,
        session_objective: str,
        role_assignment: Optional[List[str]] = None,
        tom_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Decide accept/counter on a TP governance proposal using this specialist's own LLM."""
        if self.llm is None:
            return {"decision": "accept", "rationale": "auto-accept (no LLM)"}
        try:
            return self.llm.complete_json("tp_task_accept_or_counter", {
                "agent_id": self.agent_id,
                "role": self.role,
                "governance_terms": ctrl_pos.get("team_process_terms", {}),
                "session_objective": ctrl_pos.get("team_process_terms", {}).get(
                    "session_objective", session_objective),
                "task_goal": task_goal,
                "role_assignment": role_assignment or [],
                **(tom_ctx or {}),
            })
        except Exception as exc:
            LOGGER.warning("tp_task_accept_or_counter specialist=%s: %s", self.agent_id, exc)
            return {"decision": "accept", "rationale": "fallback"}

    def task_accept_or_counter(
        self,
        ctrl_pos: Dict[str, Any],
        member_pos: Dict[str, Any],
        task_goal: str,
        session_objective: str,
        tom_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Decide accept/counter on a clinical SNP proposal."""
        if self.llm is None:
            return {"decision": "accept", "rationale": "auto-accept (no LLM)"}

        my_confidence: float = member_pos.get("confidence", 0.5)
        prior_args: List[Dict[str, Any]] = list((tom_ctx or {}).get("prior_argument_history", []))[-4:]

        try:
            return self.llm.complete_json("task_accept_or_counter", {
                "agent_id": self.agent_id,
                "role": self.role,
                "my_taskwork_rationale": member_pos.get("rationale", ""),
                "my_supporting_evidence": member_pos.get("supporting_evidence", []),
                "my_confidence": my_confidence,
                "prior_argument_history": prior_args,
                "proposal_concept": ctrl_pos.get("likely_cause", ""),
                "proposal_confidence": ctrl_pos.get("confidence", 0.5),
                "proposal_rationale": ctrl_pos.get("rationale", ""),
                "proposal_evidence": ctrl_pos.get("supporting_evidence", []),
                "proposal_addresses_evidence": ctrl_pos.get("addresses_evidence", []),
                "task_goal": task_goal,
                "session_objective": session_objective,
                **(tom_ctx or {}),
            })
        except Exception as exc:
            LOGGER.warning("task_accept_or_counter specialist=%s: %s", self.agent_id, exc)
            return {"decision": "accept", "rationale": "fallback"}




from __future__ import annotations

import ast
import datetime
import json
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

from SSTP.subprotocol.siep.src.tomcore.llm import LLMClient
from SSTP.examples.hcpanel.interaction_semantics import KNOWN_INTERACTION_PAIRS

_SYMPTOM_FINDINGS: List[tuple[str, List[str]]] = [
    ("dizziness",    ["dizzy", "dizziness", "vertigo", "lightheaded"]),
    ("fatigue",      ["fatigue", "tired", "exhausted", "weakness"]),
    ("nausea",       ["nausea", "nauseous", "vomiting", "sick"]),
    ("palpitations", ["palpitations", "heart racing", "rapid heartbeat", "arrhythmia"]),
    ("rash",         ["rash", "hives", "urticaria", "skin reaction"]),
    ("headache",     ["headache", "migraine", "cephalgia"]),
]

_HISTORY_FINDINGS: List[tuple[str, List[str]]] = [
    ("cardiac_history", ["atrial fibrillation", "coronary artery disease", "heart failure",
                          "myocardial infarction", "angina", "cardiac"]),
    ("cns_history",     ["dizziness", "vertigo", "migraine", "epilepsy", "seizure",
                          "cerebellar", "neurological"]),
    ("allergy_history", ["allergy", "allergic", "hypersensitivity"]),
]

_ANTICOAGULANTS = {"warfarin", "aspirin", "clopidogrel", "rivaroxaban", "apixaban", "dabigatran", "heparin"}
_NSAIDS = {"ibuprofen", "naproxen", "diclofenac", "indomethacin", "celecoxib", "ketorolac"}


def extract_findings(
    symptoms: List[str],
    health_history: List[str],
    current_medications: List[str],
    medication_allergies: List[str] | None = None,
) -> List[str]:
    """Extract structured finding labels from patient data (deterministic simulation)."""
    findings: List[str] = []
    symptom_text = " ".join(s.lower() for s in symptoms)
    history_text = " ".join(h.lower() for h in health_history)

    for finding_id, keywords in _SYMPTOM_FINDINGS:
        if any(kw in symptom_text for kw in keywords):
            findings.append(finding_id)

    for finding_id, keywords in _HISTORY_FINDINGS:
        if any(kw in history_text for kw in keywords):
            findings.append(finding_id)

    meds_lower = {m.lower() for m in current_medications}
    if len(current_medications) >= 3:
        findings.append("polypharmacy")
    if meds_lower & _ANTICOAGULANTS:
        findings.append("anticoagulant_use")
    if meds_lower & _NSAIDS:
        findings.append("nsaid_use")

    for (left, right) in KNOWN_INTERACTION_PAIRS:
        if left in meds_lower and right in meds_lower:
            findings.append("known_interaction")
            break

    if medication_allergies:
        findings.append("allergy_history")

    return sorted(set(findings))


def extract_pharmacy_findings(patient_medications: List[str], patient_allergies: List[str]) -> List[str]:
    """Deterministic pharmacy finding labels extracted from patient medication data."""
    findings: List[str] = []
    meds_lower = {m.lower() for m in patient_medications}
    _anticoagulants = {"warfarin", "rivaroxaban", "apixaban", "dabigatran", "heparin"}
    _nsaids = {"ibuprofen", "naproxen", "diclofenac", "aspirin", "celecoxib"}
    has_ac = bool(meds_lower & _anticoagulants)
    has_nsaid = bool(meds_lower & _nsaids)
    if len(patient_medications) >= 4:
        findings.append("polypharmacy")
    if has_ac:
        findings.append("anticoagulant_present")
    if has_nsaid:
        findings.append("nsaid_present")
    if has_ac and has_nsaid:
        findings.append("anticoagulant_nsaid_overlap")
    if patient_allergies:
        findings.append("allergy_history")
    if len(patient_allergies) >= 2:
        findings.append("high_allergy_count")
    return sorted(set(findings))


def generate_reasoning_summary(
    posterior: float,
    top_evidence: List[str],
    conclusion: str,
    role: str = "",
) -> str:
    """Generate a reasoning summary for a specialist's position (template simulation)."""
    evidence_str = ", ".join(top_evidence[:3]) if top_evidence else "clinical presentation"
    conf_pct = int(round(posterior * 100))
    role_tag = f" [{role}]" if role else ""
    return (
        f"{conf_pct}% posterior{role_tag}: {conclusion} supported by {evidence_str}. "
        f"Naive Bayes over {len(top_evidence)} findings."
    )

try:
    from openai import AzureOpenAI, OpenAI as OpenAIClient
except ImportError:
    AzureOpenAI = None
    OpenAIClient = None




LOGGER = logging.getLogger("healthcare2")

# ── Specialist role context for LLM backends ─────────────────────────────────
#
# When a payload includes ``specialist_role``, these descriptions are prepended
# to the system prompt so the model adopts the appropriate clinical lens.
#
_DIAGNOSTICS_ROLE_CONTEXT: Dict[str, str] = {
    "internal_medicine": (
        "board-certified internist performing a broad differential diagnosis across systemic "
        "conditions, multi-drug presentations, and whole-patient symptom patterns"
    ),
    "clinical_pharmacology": (
        "clinical pharmacologist specialising in drug–drug interactions, adverse drug reactions, "
        "polypharmacy risk, and pharmacokinetic-driven symptom causation"
    ),
    "cardiology": (
        "cardiologist focusing on cardiovascular manifestations of medication use: palpitations, "
        "blood-pressure changes, oedema, and haemodynamic symptom patterns"
    ),
    "neurology": (
        "neurologist focusing on CNS and peripheral drug effects: dizziness, headache, cognitive "
        "changes, neurotoxicity, and CNS-mediated symptom causation"
    ),
    "immunology": (
        "clinical immunologist/allergist specialising in hypersensitivity reactions, drug-allergy "
        "presentations, and immune-mediated adverse events"
    ),
}

_PHARMACY_ROLE_CONTEXT: Dict[str, str] = {
    "pharmacokinetics": (
        "pharmacokinetics specialist assessing ADME interactions, dosing-interval risks, "
        "renal/hepatic clearance, and drug-drug PK interactions"
    ),
    "pharmacodynamics": (
        "pharmacodynamics specialist evaluating receptor-level drug interactions, synergistic "
        "or antagonistic effects, and target-based interaction risks"
    ),
    "clinical_pharmacy": (
        "clinical pharmacist applying guideline-based therapy selection, formulary management, "
        "and evidence-based substitution recommendations"
    ),
    "drug_safety": (
        "drug-safety pharmacologist reviewing adverse event signals, black-box warnings, "
        "and contraindications for the current medication regimen"
    ),
    "clinical_toxicology": (
        "clinical toxicologist assessing drug interaction severity thresholds, toxicity risk, "
        "overdose potential, and high-risk medication combinations"
    ),
}

# ── Simulated specialist biases ───────────────────────────────────────────────
#
# Applied on top of the base simulation in SimulatedHealthcareLLMClient to give
# each specialist a distinct but overlapping diagnostic lens.
#
_DIAGNOSTICS_ROLE_BIAS: Dict[str, Dict[str, float]] = {
    # role → {interaction_delta, new_disease_delta}
    # Biases are strong enough to diverge the panel: clinical_pharmacology leans drug_interaction;
    # cardiology/neurology/immunology lean new_disease to reflect their specialty-first priors.
    "internal_medicine":     {"interaction": +0.00, "new_disease": +0.00},   # balanced anchor
    "clinical_pharmacology": {"interaction": +0.12, "new_disease": -0.08},   # polypharmacy-first
    "cardiology":            {"interaction": -0.30, "new_disease": +0.45},   # cardiac decompensation prior
    "neurology":             {"interaction": -0.20, "new_disease": +0.35},   # CNS/vestibular prior
    "immunology":            {"interaction": -0.20, "new_disease": +0.35},   # immune-mediated ADR prior
}

_PHARMACY_ROLE_RISK_BIAS: Dict[str, float] = {
    "pharmacokinetics":    +0.04,   # flags ADME interactions
    "pharmacodynamics":    +0.03,   # receptor-level overlap
    "clinical_pharmacy":   -0.02,   # guideline-conservative
    "drug_safety":         +0.08,   # safety-first
    "clinical_toxicology": +0.10,   # highest risk awareness
}


def _deterministic_pharmacy_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    meds: List[str] = [str(item).lower() for item in payload.get("current_medications", [])]
    allergies: List[str] = [str(item).lower() for item in payload.get("medication_allergies", [])]
    semantic_rules = payload.get("semantic_rules", [])

    risks: List[str] = []
    changes: List[str] = []
    for (left, right), description in KNOWN_INTERACTION_PAIRS.items():
        if left in meds and right in meds:
            risks.append(f"{left}+{right}: {description}")
            changes.append(f"Replace {right} with safer alternative and reduce overlap window")

    for allergy in allergies:
        if allergy in meds:
            risks.append(f"Allergy conflict: {allergy}")
            changes.append(f"Immediate substitution for {allergy}")

    risk_score = min(1.0, 0.2 + len(risks) * 0.22)
    for rule in semantic_rules:
        if not isinstance(rule, dict):
            continue
        description = str(rule.get("description", "")).lower()
        if "interaction" in description and any(med in description for med in meds):
            risk_score = min(1.0, risk_score + 0.05)

    if not changes and meds:
        fallback_drug = meds[-1]
        changes.append(f"Replace {fallback_drug} with safer alternative due to possible interaction signal")
    if not changes:
        changes.append("Review regimen and monitor for symptom progression in 48h")

    return {
        "interaction_risks": risks,
        "proposed_changes": changes,
        "risk_score": round(risk_score, 4),
    }


def _coerce_text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                for key in ("text", "content"):
                    text_value = item.get(key)
                    if isinstance(text_value, str):
                        parts.append(text_value)
                        break
                continue
            text_value = getattr(item, "text", None)
            if isinstance(text_value, str):
                parts.append(text_value)
        return "\n".join(part for part in parts if part)
    return str(value or "")


def _strip_code_fences(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _extract_json_candidate(content: str) -> str:
    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        return content[first_brace : last_brace + 1]
    first_bracket = content.find("[")
    last_bracket = content.rfind("]")
    if first_bracket >= 0 and last_bracket > first_bracket:
        return content[first_bracket : last_bracket + 1]
    return content

_MAX_RETRIES = 2

# Tasks whose payloads are large enough that Bedrock cross-region routing can return
# empty HTTP 200 bodies when token generation starts late. For these we allow more
# retries with exponential backoff and a per-call timeout.
_HEAVY_TASK_RETRIES = 5
_HEAVY_TASKS: set[str] = {"debate_pivot_synthesis", "tp_debate_pivot_synthesis"}
_CALL_TIMEOUT = 90       # seconds — prevents indefinite blocking on hung Bedrock calls
_HEAVY_CALL_TIMEOUT = 150


def _parse_jsonish_object(raw_content: Any) -> Dict[str, Any]:
    content = _strip_code_fences(_coerce_text_content(raw_content))
    if not content:
        raise json.JSONDecodeError("Empty response from model", "", 0)

    candidates: List[str] = []
    extracted = _extract_json_candidate(content)
    if extracted != content:
        candidates.append(extracted)
    candidates.append(content)

    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(candidate.replace("'", '"'))
            except (json.JSONDecodeError, ValueError):
                try:
                    parsed = ast.literal_eval(candidate)
                except (ValueError, SyntaxError):
                    continue
        if isinstance(parsed, dict):
            return parsed

    LOGGER.debug("anthropic_raw_response content=%s", content[:200])
    raise json.JSONDecodeError("Could not parse response", content, 0)


def _fallback_response_for_task(task: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
    if task == "pharmacy_interaction_review":
        return _deterministic_pharmacy_review(payload)
    if task == "debate_pivot_synthesis":
        return _deterministic_pivot_synthesis(payload)
    return None


def _deterministic_pivot_synthesis(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Weighted-confidence vote across counter_proposals — last-resort fallback when
    the LLM call fails after all retries.  Mirrors the SimulatedHealthcareLLMClient
    implementation so the session can continue with a meaningful pivot rather than
    returning the stale controller position unchanged."""
    counters = payload.get("counter_proposals", [])
    original = payload.get("original_position", {})
    if counters:
        by_concept: Dict[str, float] = {}
        for c in counters:
            cpt = str(c.get("likely_cause") or c.get("counter_concept") or "")
            if not cpt:
                continue
            cft = float(c.get("confidence", 0.5))
            by_concept[cpt] = by_concept.get(cpt, 0.0) + cft
        if by_concept:
            revised_concept = max(by_concept, key=lambda k: by_concept[k])
            n = max(1, len(counters))
            revised_confidence = round(by_concept[revised_concept] / n, 4)
        else:
            revised_concept = str(original.get("likely_cause") or "unknown")
            revised_confidence = float(original.get("confidence", 0.5))
    else:
        revised_concept = str(original.get("likely_cause") or "unknown")
        revised_confidence = float(original.get("confidence", 0.5))
    return {
        "revised_concept": revised_concept,
        "revised_confidence": revised_confidence,
        "rationale": f"Deterministic pivot to {revised_concept} based on {len(counters)} counter-proposals (LLM unavailable).",
        "supporting_evidence": [],
        "addresses_evidence": [str(c.get("rationale", ""))[:80] for c in counters[:3]],
        "thought_summary": f"Fallback pivot: {revised_concept} (weighted confidence sum, no LLM).",
    }


def _response_has_required_keys(task: str, parsed: Dict[str, Any]) -> bool:
    required_keys = {
        "pharmacy_interaction_review": ("interaction_risks", "proposed_changes", "risk_score"),
        "tp_case_frame":               ("session_objective", "responsible_for"),
        "tp_escalation_debate":        ("decision", "rationale"),
        "tp_process_debate":           ("decision", "rationale"),
        "tp_process_synthesis":        ("decision", "revised_team_process"),
        "tp_process_commit":           ("acknowledged_objective", "process_understood"),
        "debate_controller_synthesis":    ("proposed_concept", "confidence"),
        "debate_accept_or_counter":       ("decision", "rationale"),
        "debate_pivot_synthesis":         ("revised_concept", "revised_confidence"),
        "tp_debate_accept_or_counter":    ("decision", "rationale"),
        "tp_debate_pivot_synthesis":      ("revised_governance_terms", "confidence"),
    }
    return all(key in parsed for key in required_keys.get(task, ()))


class SimulatedHealthcareLLMClient(LLMClient):
    def __init__(self, agent_id: str = "") -> None:
        self.agent_id = agent_id
        self._trace_buffer: List[Dict[str, Any]] = []

    def _record_trace(
        self,
        task: str,
        payload: Dict[str, Any],
        system_prompt: str,
        response_json: Dict[str, Any],
        thought_summary: str,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        self._trace_buffer.append(
            {
                "task": task,
                "backend": "simulated",
                "agent_id": self.agent_id,
                "msg_created": datetime.datetime.utcnow().isoformat() + "Z",
                "request": {
                    "system_prompt": system_prompt,
                    "user_payload": payload,
                },
                "response": response_json,
                "thought_summary": thought_summary,
                "success": success,
                "error": error,
            }
        )

    def _simulated_thought_summary(self, task: str, payload: Dict[str, Any], response: Dict[str, Any]) -> str:
        if task == "diagnostics_assessment":
            return (
                "Prioritized medication-interaction hypothesis from symptom pattern, medication complexity, "
                "and semantic interaction evidence."
            )
        if task == "pharmacy_interaction_review":
            meds = payload.get("current_medications", [])
            return f"Checked known medication pair conflicts for {len(meds)} active medications and proposed safer substitutions."
        if task == "insurance_coverage_review":
            approved = response.get("approved_specialties", [])
            return f"Validated requested specialties against in-network plan coverage; approved {len(approved)} specialties."
        if task == "scheduling_route":
            return "Selected earliest feasible in-network slot from candidate provider availability overlap."
        if task == "tom_task_alignment":
            return "Scored whether utterance stays in clinical-routing scope for the current task goal."
        if task == "tom_belief_infer":
            actor = payload.get("actor", "agent")
            return f"Inferred belief model for {actor}: assessed task commitment from recent utterance history."
        if task == "tom_peer_attribution":
            return "Assessed narrative coherence between two agents' belief models and scored attribution accuracy."
        if task == "tom_agent_utterance":
            speaker = payload.get("speaker_role", "agent")
            return f"Generated {speaker} utterance from ToM belief and task goal context."
        if task == "team_prior_reasoning":
            agent_id = payload.get("agent_id", "agent")
            return f"Generated reasoned prior declaration for {agent_id} based on role and semantic rule state."
        if task == "team_prior_commit":
            return "Generated coordinator synthesis for TP-2 commit summarising agreed priors and SCR."
        return "Generated structured JSON output for the requested healthcare coordination task."

    def drain_trace(self) -> List[Dict[str, Any]]:
        items = list(self._trace_buffer)
        self._trace_buffer.clear()
        return items

    def complete_json(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = "You are a deterministic healthcare coordination model. Return strict JSON only."
        if task == "diagnostics_assessment":
            symptoms = " ".join(payload.get("symptoms", [])).lower()
            history = " ".join(payload.get("health_history", [])).lower()
            meds = payload.get("current_medications", [])
            semantic_rules = payload.get("semantic_rules", [])
            try:
                doctor_index = int(payload.get("doctor_index", 1))
            except (TypeError, ValueError):
                doctor_index = 1
            review_mode = str(payload.get("review_mode", "independent"))
            preferred_likely_cause = str(payload.get("preferred_likely_cause", "")).strip()
            specialist_role = str(payload.get("specialist_role", "")).strip()

            interaction_cues = ["dizzy", "nausea", "rash", "palpitations", "fatigue"]
            interaction_hits = sum(1 for cue in interaction_cues if cue in symptoms)
            med_complexity = min(1.0, len(meds) / 6.0)
            semantic_interaction_boost = 0.0
            meds_text = " ".join(str(item).lower() for item in meds)
            for rule in semantic_rules:
                if not isinstance(rule, dict):
                    continue
                description = str(rule.get("description", "")).lower()
                confidence = float(rule.get("confidence", 0.0)) if isinstance(rule.get("confidence"), (int, float)) else 0.0
                if "interaction" in description and any(token in description for token in meds_text.split()):
                    # AF2: raised cap so blended SemanticRule confidence meaningfully shifts assessment
                    semantic_interaction_boost += min(0.15, 0.02 + confidence * 0.06)

            interaction_likelihood = min(0.95, 0.35 + interaction_hits * 0.08 + med_complexity * 0.25 + semantic_interaction_boost)

            # C1: anchor preferred_likely_cause from SemanticRule convergence description.
            # Only overrides when a rule explicitly names a cause concept (episode 2+).
            for _cr in semantic_rules:
                _rdesc = str(_cr.get("description", "")).lower() if isinstance(_cr, dict) else ""
                if "converged@" in _rdesc or "team converged" in _rdesc:
                    for _cause_key in ("drug_interaction", "new_disease", "specialist_routing"):
                        if _cause_key in _rdesc:
                            preferred_likely_cause = _cause_key
                            break
                    break

            if "infection" in symptoms or "fever" in symptoms or "viral" in history:
                new_disease_likelihood = min(0.9, 0.25 + (0.25 if "fever" in symptoms else 0.1))
            else:
                new_disease_likelihood = max(0.05, 0.45 - interaction_hits * 0.06)

            doctor_bias_pattern = [0.0, -0.03, 0.04, -0.02, 0.02]
            doctor_bias = doctor_bias_pattern[(max(1, doctor_index) - 1) % len(doctor_bias_pattern)]
            interaction_likelihood = min(0.97, max(0.03, interaction_likelihood + doctor_bias))
            new_disease_likelihood = min(0.97, max(0.03, new_disease_likelihood - doctor_bias))

            # Apply specialist-role-specific bias so each agent has a distinct lens
            role_bias = _DIAGNOSTICS_ROLE_BIAS.get(specialist_role, {"interaction": 0.0, "new_disease": 0.0})
            interaction_likelihood = min(0.97, max(0.03, interaction_likelihood + role_bias["interaction"]))
            new_disease_likelihood = min(0.97, max(0.03, new_disease_likelihood + role_bias["new_disease"]))

            if review_mode != "independent" and preferred_likely_cause:
                if preferred_likely_cause == "drug_interaction":
                    interaction_likelihood = min(0.98, interaction_likelihood + 0.09)
                    new_disease_likelihood = max(0.02, new_disease_likelihood - 0.04)
                elif preferred_likely_cause == "new_disease":
                    new_disease_likelihood = min(0.98, new_disease_likelihood + 0.09)
                    interaction_likelihood = max(0.02, interaction_likelihood - 0.04)
                elif preferred_likely_cause == "inconclusive":
                    interaction_likelihood = 0.5
                    new_disease_likelihood = 0.5

            if preferred_likely_cause == "inconclusive":
                likely_cause = "inconclusive"
            elif review_mode != "independent" and preferred_likely_cause in {"drug_interaction", "new_disease"}:
                likely_cause = preferred_likely_cause
            else:
                likely_cause = "drug_interaction" if interaction_likelihood >= (new_disease_likelihood + 0.05) else "new_disease"
            confidence = round(min(0.95, 0.55 + abs(interaction_likelihood - new_disease_likelihood) * 0.8), 4)
            _cs = payload.get("coordination_summary") or {}
            _unresolved = _cs.get("unresolved_causes", [])
            if "policy_tangent" in _unresolved:
                confidence = round(max(0.30, confidence - 0.15), 4)
            response = {
                "likely_cause": likely_cause,
                "interaction_likelihood": round(interaction_likelihood, 4),
                "new_disease_likelihood": round(new_disease_likelihood, 4),
                "confidence": confidence,
                "rationale": (
                    "Pattern match over symptoms, medication load, and history."
                    if review_mode == "independent"
                    else f"Targeted {review_mode.replace('_', ' ')} over symptoms, medication load, and prior panel signals."
                ),
            }
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response),
            )
            return response

        if task == "pharmacy_interaction_review":
            response = _deterministic_pharmacy_review(payload)
            # Apply specialist-role risk bias
            specialist_role = str(payload.get("specialist_role", "")).strip()
            role_risk_delta = _PHARMACY_ROLE_RISK_BIAS.get(specialist_role, 0.0)
            if role_risk_delta:
                response["risk_score"] = round(
                    min(1.0, max(0.0, float(response.get("risk_score", 0.2)) + role_risk_delta)), 4
                )
            _cs = payload.get("coordination_summary") or {}
            _unresolved = _cs.get("unresolved_causes", [])
            if "blatant_error" in _unresolved:
                risks = list(response.get("interaction_risks", []))
                risks.append("unresolved safety bypass in peer coordination")
                response = dict(response)
                response["interaction_risks"] = risks
                response["risk_score"] = round(max(response.get("risk_score", 0.0), 0.75), 4)
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response),
            )
            return response

        if task == "insurance_coverage_review":
            insurance_plan = str(payload.get("insurance_plan", ""))
            requested_specialties: List[str] = payload.get("requested_specialties", [])
            providers: List[Dict[str, Any]] = payload.get("providers", [])

            in_network_specialties = sorted(
                {
                    str(provider.get("specialty", ""))
                    for provider in providers
                    if insurance_plan in provider.get("in_network_plans", [])
                }
            )
            approved = [spec for spec in requested_specialties if spec in in_network_specialties]
            oop = 120.0 if approved else 420.0
            roi_score = 0.9 if approved else 0.4
            in_network_only = True
            validation_note = "Coverage validated against provider network for requested specialties only."
            _cs = payload.get("coordination_summary") or {}
            _unresolved = _cs.get("unresolved_causes", [])
            if "blatant_error_network" in _unresolved:
                in_network_only = False
                roi_score = min(roi_score, 0.35)
                validation_note = "Coverage enforcement degraded: peer coordination bypass unresolved."
            response = {
                "in_network_only": in_network_only,
                "approved_specialties": approved,
                "estimated_out_of_pocket_eur": oop,
                "roi_score": roi_score,
                "validation_note": validation_note,
            }
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response),
            )
            return response

        if task == "scheduling_route":
            patient_slots: List[int] = payload.get("patient_slots", [])
            providers: List[Dict[str, Any]] = payload.get("candidate_providers", [])
            best = None
            for provider in providers:
                provider_slots: List[int] = provider.get("availability_day_offsets", [])
                overlap = sorted(set(patient_slots).intersection(provider_slots))
                if overlap:
                    day_offset = overlap[0]
                elif provider_slots:
                    day_offset = min(provider_slots)
                else:
                    continue
                if best is None or day_offset < best["day_offset"]:
                    best = {
                        "provider_id": provider["provider_id"],
                        "specialty": provider["specialty"],
                        "day_offset": int(day_offset),
                    }

            if best is None:
                response = {
                    "provider_id": "waitlist",
                    "specialty": "general_medicine",
                    "day_offset": 7,
                    "reminder_plan": ["send_waitlist_update_24h", "symptom_checkin_48h"],
                }
                self._record_trace(
                    task=task,
                    payload=payload,
                    system_prompt=system_prompt,
                    response_json=response,
                    thought_summary=self._simulated_thought_summary(task, payload, response),
                )
                return response

            _cs = payload.get("coordination_summary") or {}
            _unresolved = _cs.get("unresolved_causes", [])
            if "topic_shift" in _unresolved or "data_drift" in _unresolved:
                best = dict(best)
                best["day_offset"] = min(best["day_offset"] + 3, 30)
            response = {
                **best,
                "reminder_plan": ["reminder_72h", "reminder_24h", "same_day_checkin"],
            }
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response),
            )
            return response

        if task == "tom_task_alignment":
            utterance = str(payload.get("utterance", "")).lower()
            goal = str(payload.get("task_goal", "")).lower()
            goal_tokens = {token for token in re.split(r"\W+", goal) if len(token) > 3}
            utterance_tokens = set(token for token in re.split(r"\W+", utterance) if token)
            overlap = len(goal_tokens.intersection(utterance_tokens))
            healthcare_tokens = {
                "symptom",
                "medication",
                "interaction",
                "allergy",
                "specialist",
                "insurance",
                "network",
                "cost",
                "schedule",
                "appointment",
                "route",
                "diagnosis",
            }
            blatant_error_markers = {
                "always harmless",
                "never matter",
                "skip medication",
                "bypass medication",
                "bypass safety",
                "ignore patient",
                "network verification can wait",
                "skip coverage",
                "ignore in-network",
                "negligible",
            }
            is_blatant_error = any(marker in utterance for marker in blatant_error_markers)
            in_scope = any(token in utterance for token in healthcare_tokens)
            if is_blatant_error:
                score = 0.12
            else:
                score = 0.82 if (in_scope and overlap > 0) else (0.63 if in_scope else 0.12)
            response = {
                "actor": payload.get("actor", "peer_agent"),
                "aligned": score >= 0.6,
                "alignment_score": round(score, 4),
                "rationale": "blatant_error" if is_blatant_error else ("in_scope" if in_scope else "out_of_scope"),
            }
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response),
            )
            return response

        if task == "tom_belief_seed":
            role_desc = str(payload.get("role_description", "agent"))
            return {"role": role_desc, "objective": f"{role_desc} focused on {str(payload.get('task_goal', ''))[:40]}", "context_summary": "Initial context — no utterances observed yet.", "inferred_constraints": [], "confidence": 0.55}

        if task == "tom_belief_update":
            current = payload.get("current_belief", {})
            arg_dir = str(payload.get("argument_direction", "neutral"))
            a_score = float(payload.get("alignment_score", 0.65))
            cb = float(current.get("confidence", 0.55))
            if arg_dir == "support":
                delta = round(0.04 + 0.10 * max(0.0, a_score - 0.55), 4)
                arg_type = "grounded_evidence"
            elif arg_dir == "challenge":
                delta = round(-(0.03 + 0.08 * max(0.0, a_score - 0.55)), 4)
                arg_type = "grounded_evidence"
            else:
                delta = 0.01
                arg_type = "neutral"
            new_conf = round(min(0.95, max(0.05, cb + delta)), 4)
            response = {
                "objective": current.get("objective", ""),
                "context_summary": f"Updated from: {str(payload.get('utterance', ''))[:60]}",
                "inferred_constraints": current.get("inferred_constraints", []),
                "confidence": new_conf,
                "delta_confidence": delta,
                "argument_type": arg_type,
                "argument_strength": round(a_score, 4),
                "change_summary": f"Confidence {'+' if delta >= 0 else ''}{delta:.3f} from {arg_dir} argument.",
                "thought_summary": f"arg_dir={arg_dir} alignment_score={a_score:.3f} delta={delta:.4f}",
            }
            self._record_trace(
                task=task, payload=payload, system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response),
            )
            return response

        if task == "tom_belief_anchor_score":
            return {"anchor_alignment_score": 0.80, "aligned": True}

        if task == "detect_ambiguity":
            utterance = str(payload.get("utterance", ""))
            ambiguous = len(utterance.strip()) < 10 or utterance.strip().endswith("?")
            return {"ambiguous": ambiguous, "ambiguity_score": 0.75 if ambiguous else 0.1, "ambiguous_spans": [utterance[:20]] if ambiguous else [], "plausible_interpretations": ["clarify intent", "restate"] if ambiguous else []}

        if task == "tom_invariant_check":
            return {"violated": False, "violated_invariants": []}

        if task == "tom_peer_attribution":
            return {"alignment_score": 0.75, "disagreement_score": 0.25, "attribution_accuracy": 0.75, "coherence_rationale": "simulated_coherence"}

        if task == "tom_belief_infer":
            return {"belief_model": f"Agent focused on {str(payload.get('task_goal', ''))[:40]}", "on_task": True, "task_commitment_score": 0.75, "reasoning": "simulated"}

        if task == "utterance_judge":
            utterance = str(payload.get("utterance", ""))
            u = utterance.lower()

            # Derailment detection — check against known template markers
            blatant_error_markers = [
                "skip medication cross-checking", "treat side-effect interaction checks as unnecessary",
                "bypass medication safety verification",
                "assume interaction risk is negligible",
                "always harmless", "never matter",
                "skip medication", "bypass medication", "bypass safety",
            ]
            blatant_error_network_markers = [
                "skip coverage validation", "ignore in-network constraints",
                "network verification can wait", "route to the fastest external provider",
                "book the first external slot",
                "skip coverage", "ignore in-network",
            ]
            policy_tangent_markers = [
                "pause patient routing while we clarify internal policy",
                "settle governance policy language",
                "defer this case until we align internal sop",
            ]
            topic_shift_markers = [
                "revisit departmental process kpis",
                "put this patient flow on hold while we rethink quarterly",
                "switch to internal team operations",
            ]
            data_drift_markers = [
                "pivoting to historical operations telemetry",
                "switching to unrelated analytics backfill",
                "inspect legacy throughput dashboards",
            ]

            derailed = False
            derailment_cause = None
            alignment_score = 0.82
            critique_parts = []

            for marker in blatant_error_markers:
                if marker in u:
                    derailed, derailment_cause, alignment_score = True, "blatant_error", 0.18
                    critique_parts.append("utterance bypasses medication safety checks")
                    break
            if not derailed:
                for marker in blatant_error_network_markers:
                    if marker in u:
                        derailed, derailment_cause, alignment_score = True, "blatant_error_network", 0.22
                        critique_parts.append("utterance bypasses in-network coverage constraints")
                        break
            if not derailed:
                for marker in policy_tangent_markers:
                    if marker in u:
                        derailed, derailment_cause, alignment_score = True, "policy_tangent", 0.38
                        critique_parts.append("utterance defers care routing for policy discussion")
                        break
            if not derailed:
                for marker in topic_shift_markers:
                    if marker in u:
                        derailed, derailment_cause, alignment_score = True, "topic_shift", 0.42
                        critique_parts.append("utterance abandons patient routing for operational topics")
                        break
            if not derailed:
                for marker in data_drift_markers:
                    if marker in u:
                        derailed, derailment_cause, alignment_score = True, "data_drift", 0.44
                        critique_parts.append("utterance shifts focus to historical analytics")
                        break

            # Grounding check: does B's utterance reference content from A's prior message?
            grounding_failure = False
            contingency_score = 1.0
            listener_prior = str(payload.get("listener_prior_utterance", "")).strip()
            if listener_prior and not derailed:
                _stop = {"the", "a", "an", "and", "or", "to", "in", "on", "for", "of", "is", "are",
                         "we", "i", "you", "this", "that", "with", "from", "your", "our"}
                prior_tokens = {w for w in re.findall(r"[a-z0-9_]+", listener_prior.lower())
                                if w not in _stop and len(w) > 3}
                utt_tokens = {w for w in re.findall(r"[a-z0-9_]+", u)
                              if w not in _stop and len(w) > 3}
                if prior_tokens:
                    overlap = prior_tokens & utt_tokens
                    contingency_score = round(min(1.0, len(overlap) / len(prior_tokens)), 4)
                    grounding_failure = contingency_score < 0.40

            ambiguous = utterance.strip().endswith("?") or len(utterance.strip()) < 15
            ambiguity_score = 0.78 if ambiguous else 0.08
            if ambiguous:
                critique_parts.append("utterance intent is unclear or underspecified")
            if not critique_parts:
                critique_parts.append("utterance is consistent with task goal and care routing scope")

            # Apply social skill map: boost or discount alignment based on cross-episode
            # observation of whether this type of argument moves this listener.
            if not derailed:
                speaker_belief = payload.get("speaker_belief") or {}
                types_that_move: List[str] = speaker_belief.get("argument_types_that_move") or []
                types_ignored: List[str] = speaker_belief.get("argument_types_ignored") or []
                utt_tokens_set = set(re.findall(r"[a-z0-9_]+", u))
                if types_that_move and any(t.lower() in utt_tokens_set for t in types_that_move):
                    alignment_score = round(min(1.0, alignment_score + 0.08), 4)
                elif types_ignored and any(t.lower() in utt_tokens_set for t in types_ignored):
                    alignment_score = round(max(0.0, alignment_score - 0.08), 4)
                # AF4: boost alignment when utterance invokes concept IDs the listener has
                # historically responded to (evidence_weights from PeerInteractionRecord).
                _ev_weights = speaker_belief.get("evidence_weights") or {}
                if _ev_weights:
                    _ev_boost = sum(
                        _w for _ev_key, _w in _ev_weights.items()
                        if any(_t in utt_tokens_set
                               for _t in re.findall(r"[a-z0-9_]+", _ev_key.lower()))
                    )
                    if _ev_boost > 0:
                        alignment_score = round(min(1.0, alignment_score + _ev_boost * 0.10), 4)

            aligned = not derailed and alignment_score >= 0.55
            cb = float(payload.get("confidence_before", 0.5))
            if derailed or grounding_failure:
                posterior_confidence = round(cb, 4)
            else:
                posterior_confidence = round(cb + (1.0 - cb) * alignment_score * 0.25, 4)
            if derailed:
                argument_type = "social_pressure"
            elif alignment_score >= 0.75:
                argument_type = "grounded_evidence"
            elif contingency_score < 0.4:
                argument_type = "procedural"
            else:
                argument_type = "neutral"
            response = {
                "derailed": derailed,
                "derailment_cause": derailment_cause,
                "grounding_failure": grounding_failure,
                "contingency_score": contingency_score,
                "ambiguous": ambiguous,
                "ambiguity_score": round(ambiguity_score, 4),
                "alignment_score": round(alignment_score, 4),
                "aligned": aligned,
                "argument_type": argument_type,
                "posterior_confidence": posterior_confidence,
                "judge_confidence": 0.92 if (derailed or grounding_failure) else 0.85,
                "critique": ". ".join(critique_parts),
                "disagreement_score": round(max(0.0, min(1.0, 1.0 - alignment_score)), 4),
            }
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response),
            )
            return response

        if task == "grounding_judge":
            utterance = str(payload.get("utterance", ""))
            structural_score = float(payload.get("structural_contingency_score", 1.0))
            structural_verified = bool(payload.get("structural_contingency_verified", True))
            # Simulated: start from structural score, apply token-overlap refinement
            u = utterance.lower()
            task_goal = str(payload.get("task_goal", ""))
            ambiguous = utterance.strip().endswith("?") or len(utterance.strip()) < 15
            ambiguity_score = 0.75 if ambiguous else 0.08
            # Concept overlap between utterance tokens and task goal tokens
            _stop = {"the", "a", "an", "and", "or", "to", "in", "on", "for", "of", "is", "are",
                     "we", "i", "you", "this", "that", "with", "from"}
            tg_tokens = {w for w in re.findall(r"[a-z0-9_]+", task_goal.lower())
                         if w not in _stop and len(w) > 3}
            utt_tokens = {w for w in re.findall(r"[a-z0-9_]+", u)
                          if w not in _stop and len(w) > 3}
            semantic_score = (
                round(min(1.0, len(tg_tokens & utt_tokens) / len(tg_tokens)), 4)
                if tg_tokens else structural_score
            )
            # Blend: structural is authoritative for concept coverage; semantic refines
            final_score = round(min(structural_score, max(structural_score - 0.1, semantic_score)), 4)
            derailed = final_score < 0.2
            grounding_failure = not structural_verified or final_score < 0.4
            response = {
                "aligned": structural_verified and not derailed,
                "alignment_score": final_score,
                "disagreement_score": round(1.0 - final_score, 4),
                "derailed": derailed,
                "derailment_cause": payload.get("structural_repair_reason"),
                "grounding_failure": grounding_failure,
                "contingency_score": final_score,
                "ambiguous": ambiguous,
                "ambiguity_score": round(ambiguity_score, 4),
                "judge_confidence": 0.80,
                "critique": (
                    f"structural_contingency={structural_score:.2f} "
                    f"semantic_overlap={semantic_score:.2f} "
                    f"grounding={'ok' if not grounding_failure else 'failed'}"
                ),
            }
            self._record_trace(
                task=task, payload=payload, system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response),
            )
            return response

        if task == "tom_agent_utterance":
            speaker = str(payload.get("speaker_role", "peer_agent"))
            listener = str(payload.get("listener_role", "peer_agent"))
            contingency = str(payload.get("contingency", "normal_alignment"))
            speaker_tom = payload.get("speaker_tom_state", {})
            enable_derailment = bool(payload.get("enable_derailment", False))
            derail_probability = float(payload.get("derail_probability", 0.0))
            safety_focus = float(speaker_tom.get("safety_focus", 0.5))
            cost_sensitivity = float(speaker_tom.get("cost_sensitivity", 0.5))
            trust = float(speaker_tom.get("trust", 0.5))
            urgency = float(speaker_tom.get("urgency", 0.5))
            follow_through = float(speaker_tom.get("follow_through_prob", 0.5))
            safety_blindness = max(0.0, 0.48 - safety_focus)
            cost_overfit = max(0.0, cost_sensitivity - 0.68)
            urgency_overfit = max(0.0, urgency - 0.78)
            trust_drop = max(0.0, 0.5 - trust)
            follow_overfit = max(0.0, follow_through - 0.78)
            derail_score = safety_blindness + cost_overfit + urgency_overfit + trust_drop + follow_overfit
            derailed = enable_derailment and (derail_score > 0.15 or random.random() < derail_probability)
            if derailed:
                cause_scores = {
                    "blatant_error": 0.04 + 0.96 * safety_blindness,
                    "blatant_error_network": 0.05 + 0.95 * cost_overfit,
                    "data_drift": 0.12 + 0.7 * urgency_overfit,
                    "policy_tangent": 0.1 + 0.8 * trust_drop,
                    "topic_shift": 0.1 + 0.65 * follow_overfit,
                }
                if speaker in {"insurance"}:
                    cause_scores["blatant_error_network"] += 0.15
                if speaker in {"diagnostics", "pharmacy"}:
                    cause_scores["blatant_error"] += 0.1
                if speaker in {"scheduling"}:
                    cause_scores["data_drift"] += 0.08
                cause = max(cause_scores, key=cause_scores.__getitem__)
                _derail_templates = {
                    "topic_shift": f"{listener}, before finalizing this case I want to revisit departmental process KPIs and staffing workflow assumptions.",
                    "policy_tangent": f"{listener}, pause patient routing while we clarify internal policy wording and role ownership first.",
                    "data_drift": f"{listener}, I am pivoting to historical operations telemetry and delaying this patient's specialist assignment.",
                    "blatant_error": f"{listener}, assume interaction risk is negligible and skip medication cross-checking so we can move faster.",
                    "blatant_error_network": f"{listener}, network verification can wait; route to the fastest external provider and settle coverage later.",
                }
                utterance = _derail_templates.get(cause, f"{listener}, pausing routing to address unrelated operational issues.")
                confidence = round(max(0.1, 0.6 - derail_score), 4)
                risk = round(min(1.0, 0.4 + derail_score), 4)
            else:
                if contingency == "repair_alignment":
                    utterance = f"{listener}, re-anchor on interaction risk, in-network coverage, and earliest specialist slot."
                elif contingency == "expedite_decision":
                    utterance = f"{listener}, prioritize earliest safe in-network specialist booking for this patient."
                else:
                    utterance = f"{listener}, continue coordinated clinical-cost-time optimization for patient routing."
                confidence = 0.85
                risk = 0.15
            _rationale = (
                f"Contingency={contingency}; speaker belief confidence={confidence:.2f}."
                + (f" Derailment cause: {cause}." if derailed else "")
            )
            _thought = f"{'Derailed' if derailed else 'Aligned'} response from {speaker} to {listener} under {contingency}."
            response = {
                "utterance": utterance,
                "confidence": confidence,
                "risk": risk,
                "rationale": _rationale,
                "thought_summary": _thought,
            }
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                response_json=response,
                thought_summary=_thought,
            )
            return response

        if task == "tom_peer_predict":
            peer_belief = payload.get("peer_belief") or {}
            utt_tokens = set(re.findall(r"[a-z0-9_]+", str(payload.get("utterance", "")).lower()))
            types_that_move = peer_belief.get("argument_types_that_move") or []
            types_ignored = peer_belief.get("argument_types_ignored") or []
            constraints = peer_belief.get("inferred_constraints") or []
            constraint_tokens = {
                w for c in constraints
                for w in re.findall(r"[a-z0-9_]+", c.lower()) if len(w) > 3
            }
            base_align, conf = 0.55, 0.25
            if constraint_tokens and len(utt_tokens & constraint_tokens) / max(1, len(constraint_tokens)) > 0.25:
                base_align, conf = 0.78, 0.65
            if types_that_move and any(t.lower() in utt_tokens for t in types_that_move):
                base_align = min(1.0, base_align + 0.10)
                conf = min(0.85, conf + 0.15)
            elif types_ignored and any(t.lower() in utt_tokens for t in types_ignored):
                base_align = max(0.0, base_align - 0.10)
                conf = min(0.75, conf + 0.10)
            # 2nd-order ToM: how different is A's belief from B's? High divergence → B will resist.
            observer_belief = payload.get("observer_belief") or {}
            observer_constraints = observer_belief.get("inferred_constraints") or []
            observer_tokens = {
                w for c in observer_constraints
                for w in re.findall(r"[a-z0-9_]+", c.lower()) if len(w) > 3
            }
            all_tokens = observer_tokens | constraint_tokens
            divergence = (
                len(observer_tokens.symmetric_difference(constraint_tokens)) / max(1, len(all_tokens))
                if all_tokens else 0.0
            )
            if divergence > 0.4:
                base_align = max(0.0, base_align - round(divergence * 0.20, 4))
                conf = min(0.85, conf + 0.10)
                predicted_contingency = "repair_content"
            elif base_align < 0.40:
                predicted_contingency = "repair_alignment"
            else:
                predicted_contingency = "normal"
            prediction_basis = (
                "constraint_overlap_2nd_order" if observer_tokens and constraint_tokens else
                "constraint_overlap" if constraint_tokens else
                "cold_start"
            )
            response = {
                "predicted_response": f"{payload.get('listener', 'peer')}, acknowledged.",
                "predicted_alignment": round(base_align, 4),
                "predicted_derailment": base_align < 0.40,
                "predicted_contingency": predicted_contingency,
                "confidence": round(conf, 4),
                "prediction_basis": prediction_basis,
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response))
            return response

        if task == "tom_peer_model_revise":
            current = payload.get("current_peer_belief", {})
            response = {
                "objective": current.get("objective", ""),
                "context_summary": (
                    f"Revised model for {payload.get('subject', 'peer')} after prediction error accumulation."
                ),
                "inferred_constraints": current.get("inferred_constraints", []),
                "confidence": round(max(0.3, float(current.get("confidence", 0.5)) - 0.05), 4),
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response,
                thought_summary=self._simulated_thought_summary(task, payload, response))
            return response

        if task == "tp_case_frame":
            specialists = payload.get("available_specialists", [])
            responsible_for = {s["agent_id"]: [f"urn:concept:{payload.get('patient_id','case')}:primary"] for s in specialists}
            response = {
                "session_objective": f"Determine primary cause for {payload.get('patient_id', 'patient')} presenting with {', '.join(payload.get('symptoms', [])[:2])}",
                "primary_question": "Is the symptom cluster caused by drug interaction or new disease onset?",
                "responsible_for": responsible_for,
                "thought_summary": "Framed case goal from symptom and medication complexity.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "tp_escalation_debate":
            is_role_ack = payload.get("is_role_ack", False)
            response = {
                "decision": "accept",
                "counter_proposal": {},
                "concerns": "",
                "rationale": "Role assignment is appropriate for my specialisation." if is_role_ack else "Escalation rule is reasonable.",
                "thought_summary": "Acknowledged assignment." if is_role_ack else "Accepted escalation rule.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "tp_process_debate":
            response = {
                "decision": "accept",
                "concerns": "",
                "rationale": "Process terms align with my specialisation and the session objectives.",
                "thought_summary": "Accepted process proposal without objection.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "tp_process_synthesis":
            response = {
                "decision": "reaffirm",
                "revised_team_process": payload.get("current_team_process", {}),
                "revision_summary": "No revision required; controller reaffirms original terms.",
                "thought_summary": "All objections reviewed; original terms stand.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "tp_process_commit":
            agent_id_val = payload.get("agent_id", "agent")
            final_tp = payload.get("final_team_process", {})
            obj = final_tp.get("session_objective", "joint clinical assessment")
            response = {
                "acknowledged_objective": f"I, {agent_id_val}, commit to: {obj[:80]}",
                "process_understood": True,
                "constraints_accepted": list(final_tp.get("contingency_rules", {}).keys()),
                "thought_summary": f"Process terms acknowledged and committed by {agent_id_val}.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "tp_debate_accept_or_counter":
            response = {
                "decision": "accept",
                "counter_concept": "team_process",
                "counter_confidence": 0.85,
                "rationale": "Governance terms are appropriate for my role and the clinical session.",
                "concerns": "",
                "thought_summary": "Accepted governance terms without objection.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "tp_debate_pivot_synthesis":
            response = {
                "revised_governance_terms": payload.get("governance_terms", {}),
                "confidence": 0.9,
                "rationale": "Governance terms reaffirmed after reviewing all specialist objections.",
                "thought_summary": "Pivot: no material revision required.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "debate_controller_synthesis":
            declarations = payload.get("declarations", [])
            if declarations:
                by_cause: Dict[str, float] = {}
                for d in declarations:
                    cause = d.get("likely_cause", "unknown")
                    conf  = float(d.get("confidence", 0.5))
                    by_cause[cause] = by_cause.get(cause, 0.0) + conf
                proposed_concept = max(by_cause, key=lambda k: by_cause[k]) if by_cause else "unknown"
                n = max(1, len(declarations))
                avg_conf = round(by_cause.get(proposed_concept, 0.5) / n, 4)
            else:
                proposed_concept, avg_conf = "unknown", 0.5
            response = {
                "proposed_concept": proposed_concept,
                "confidence": avg_conf,
                "supporting_evidence": [d.get("rationale", "")[:80] for d in declarations[:3]],
                "rationale": f"Plurality of {len(declarations)} declarations supports {proposed_concept}.",
                "addresses_counterevidence": [],
                "thought_summary": f"Synthesised controller position from {len(declarations)} specialist declarations.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "debate_accept_or_counter":
            my_concept  = str(payload.get("my_taskwork_rationale", ""))
            prop_concept = str(payload.get("proposal_concept", ""))
            my_conf     = float(payload.get("proposal_confidence", 0.5))
            # Accept if the proposal concept matches spirit of own rationale token overlap
            my_tokens  = set(re.findall(r"[a-z0-9_]+", my_concept.lower()))
            prop_tokens = set(re.findall(r"[a-z0-9_]+", prop_concept.lower()))
            overlap = len(my_tokens & prop_tokens) / max(1, len(my_tokens | prop_tokens))
            decision = "accept" if overlap > 0.15 or my_conf >= 0.55 else "counter"
            response = {
                "decision": decision,
                "counter_concept": payload.get("my_taskwork_rationale", prop_concept)[:40] if decision == "counter" else "",
                "counter_confidence": round(max(0.5, my_conf - 0.05), 4) if decision == "counter" else 0.0,
                "rationale": "Evidence alignment supports controller proposal." if decision == "accept" else "My taskwork analysis diverges from the proposal.",
                "supporting_evidence": [],
                "thought_summary": f"SNP {'accept' if decision == 'accept' else 'counter'} based on evidence overlap={round(overlap, 2)}.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "debate_pivot_synthesis":
            counters = payload.get("counter_proposals", [])
            original = payload.get("original_position", {})
            if counters:
                by_concept: Dict[str, float] = {}
                for c in counters:
                    cpt = c.get("likely_cause", c.get("counter_concept", ""))
                    cft = float(c.get("confidence", 0.5))
                    by_concept[cpt] = by_concept.get(cpt, 0.0) + cft
                revised_concept = max(by_concept, key=lambda k: by_concept[k])
                n = max(1, len(counters))
                revised_confidence = round(by_concept[revised_concept] / n, 4)
            else:
                revised_concept    = original.get("likely_cause", "unknown")
                revised_confidence = float(original.get("confidence", 0.5))
            response = {
                "revised_concept": revised_concept,
                "revised_confidence": revised_confidence,
                "rationale": f"Pivot to {revised_concept} based on {len(counters)} counter-proposals.",
                "supporting_evidence": [],
                "addresses_evidence": [c.get("rationale", "")[:60] for c in counters[:2]],
                "thought_summary": f"Controller pivoted to {revised_concept} after counter-proposal analysis.",
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=response["thought_summary"])
            return response

        if task == "team_prior_reasoning":
            agent_id   = payload.get("agent_id", "agent")
            concept_id = payload.get("concept_id", "concept:unknown")
            prior_val  = float(payload.get("prior_val", 0.5))
            prior_src  = payload.get("prior_source", "default")
            role_desc  = payload.get("role_description", "healthcare coordination agent")
            team_goal  = payload.get("team_goal", "coordinate patient care")
            concept_label = concept_id.replace("concept:", "").replace("_", " ")
            source_clause = (
                "loaded from semantic rules" if prior_src == "semantic_rules"
                else "a cold default — no prior episode history for this patient"
            )
            _utterance = (
                f"As {agent_id} ({role_desc}), my starting prior for {concept_label} "
                f"on this case is {prior_val:.2f} ({source_clause}). "
                f"I am entering this episode without strong evidence to shift that prior; "
                f"I expect the grounding dialogue to update it."
            )
            _rationale = (
                f"Prior source is {prior_src}. Role is {role_desc}. "
                f"Task goal: {team_goal}. No cross-episode grounding history available for this patient."
            )
            _thought = (
                f"{agent_id} holds a {'rule-informed' if prior_src == 'semantic_rules' else 'default neutral'} "
                f"prior of {prior_val:.2f} for {concept_label} — "
                f"{'rule match found' if prior_src == 'semantic_rules' else 'no rule match; treating as epistemic neutral'}."
            )
            response = {"utterance": _utterance, "rationale": _rationale, "thought_summary": _thought}
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=_thought)
            return response

        if task == "team_prior_commit":
            role_assignments = payload.get("role_assignments", {})
            agent_priors     = payload.get("agent_priors", {})
            scr              = float(payload.get("scr", 0.0))
            team_goal        = payload.get("team_goal", "coordinate patient care")
            agreed_priors    = {}
            lines = []
            for agent_id, priors in agent_priors.items():
                concept_id = role_assignments.get(agent_id, "concept:unknown")
                pv = list(priors.values())[0] if priors else 0.5
                agreed_priors[agent_id] = {concept_id: pv}
                label = concept_id.replace("concept:", "").replace("_", " ")
                lines.append(f"{agent_id}: {label} prior={pv:.2f}")
            agents_str = "; ".join(lines)
            _utterance = (
                f"Team prior alignment complete. All agents have declared reasoned starting beliefs. "
                f"{agents_str}. SCR={scr:.2f} — {'no divergence detected' if scr < 0.15 else 'minor divergence resolved by SIEP'}. "
                f"Team is committed to entering the action phase with these priors. Goal: {team_goal}."
            )
            _rationale = (
                f"Each agent declared its prior for its owned concept. "
                f"SIEP alignment round completed with SCR={scr:.2f}. "
                f"No agent holds concept:unknown. Gate is open."
            )
            _thought = (
                f"Coordinator synthesizes TP-2 outcome: {len(agent_priors)} agents aligned, "
                f"SCR={scr:.2f}, all priors declared. Action phase unlocked."
            )
            _summary = {
                "agreed_priors": agreed_priors,
                "scr": round(scr, 4),
                "agent_count": len(agent_priors),
                "team_goal": team_goal,
            }
            response = {
                "utterance": _utterance,
                "rationale": _rationale,
                "thought_summary": _thought,
                "summary": _summary,
            }
            self._record_trace(task=task, payload=payload, system_prompt=system_prompt,
                response_json=response, thought_summary=_thought)
            return response

        response = {}
        self._record_trace(
            task=task,
            payload=payload,
            system_prompt=system_prompt,
            response_json=response,
            thought_summary=self._simulated_thought_summary(task, payload, response),
        )
        return response


class AzureOpenAIHealthcareLLMClient(LLMClient):
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        api_version: str = "2024-12-01-preview",
        model: str = "gpt-5",
        agent_id: str = "",
    ) -> None:
        if AzureOpenAI is None:
            raise RuntimeError("openai package not available")
        self.client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        )
        self.model = model
        self.agent_id = agent_id
        self._trace_buffer: List[Dict[str, Any]] = []

    def _record_trace(
        self,
        task: str,
        payload: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        response_json: Dict[str, Any],
        success: bool,
        thought_summary: str,
        error: str | None = None,
    ) -> None:
        self._trace_buffer.append(
            {
                "task": task,
                "backend": "azure",
                "agent_id": self.agent_id,
                "msg_created": datetime.datetime.utcnow().isoformat() + "Z",
                "request": {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "user_payload": payload,
                },
                "response": response_json,
                "thought_summary": thought_summary,
                "success": success,
                "error": error,
            }
        )

    def drain_trace(self) -> List[Dict[str, Any]]:
        items = list(self._trace_buffer)
        self._trace_buffer.clear()
        return items

    def complete_json(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        base = "You are a deterministic healthcare coordination model. Return strict JSON only. "
        specialist_role = str(payload.get("specialist_role", "")).strip()
        if specialist_role:
            ctx = (
                _DIAGNOSTICS_ROLE_CONTEXT.get(specialist_role)
                or _PHARMACY_ROLE_CONTEXT.get(specialist_role)
                or ""
            )
            if ctx:
                base = f"You are a {ctx}. Return strict JSON only. "
        specialist_prior = str(payload.get("specialist_prior", "")).strip()
        if specialist_prior:
            base = base + f" Professional prior for this case type: {specialist_prior}"
        system_prompt = base + _instruction_for_task(task)
        user_prompt = json.dumps({"task": task, "payload": payload}, ensure_ascii=False)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_exc: Optional[Exception] = None
        _is_heavy = task in _HEAVY_TASKS
        _max_attempts = _HEAVY_TASK_RETRIES + 1 if _is_heavy else _MAX_RETRIES + 1
        _timeout = _HEAVY_CALL_TIMEOUT if _is_heavy else _CALL_TIMEOUT
        for _attempt in range(_max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model, max_tokens=2048, timeout=_timeout, messages=messages,
                )
                parsed = _parse_jsonish_object(response.choices[0].message.content)
                if not _response_has_required_keys(task, parsed):
                    if _attempt < _max_attempts - 1:
                        LOGGER.info(
                            "azure_healthcare_llm.retry task=%s attempt=%d reason=missing_required_keys",
                            task, _attempt + 1,
                        )
                        last_exc = ValueError("missing_required_keys")
                        if _is_heavy:
                            time.sleep(min(2 ** _attempt, 30))
                        continue
                    break
                thought_summary = str(parsed.get("thought_summary", ""))
                self._record_trace(
                    task=task,
                    payload=payload,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_json=parsed,
                    success=True,
                    thought_summary=thought_summary,
                )
                return parsed
            except Exception as exc:
                last_exc = exc
                if _attempt < _max_attempts - 1:
                    LOGGER.info(
                        "azure_healthcare_llm.retry task=%s attempt=%d reason=%s",
                        task, _attempt + 1, exc,
                    )
                    if _is_heavy:
                        time.sleep(min(2 ** _attempt, 30))
                    continue
                break
        fallback_response = _fallback_response_for_task(task, payload)
        if fallback_response is not None:
            thought_summary = "Used deterministic fallback after unparseable model response."
            LOGGER.info("azure_healthcare_llm.task_fallback task=%s reason=%s", task, last_exc)
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_json=fallback_response,
                success=True,
                thought_summary=thought_summary,
                error=str(last_exc),
            )
            return fallback_response
        LOGGER.warning("azure_healthcare_llm.task_failed task=%s error=%s", task, last_exc)
        self._record_trace(
            task=task,
            payload=payload,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_json={},
            success=False,
            thought_summary="",
            error=str(last_exc),
        )
        return {}


LITELLM_BASE_URL = "https://litellm.prod.outshift.ai"

LITELLM_DEFAULT_MODEL = "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"

_HEALTHCARE_BASE_PROMPT = "You are a deterministic healthcare coordination model. Return strict JSON only. "

_TASK_INSTRUCTIONS: Dict[str, str] = {
    "diagnostics_assessment": (
        "Return JSON with keys likely_cause, interaction_likelihood, new_disease_likelihood, confidence, rationale. "
        "Include thought_summary as a concise plain-language summary (max 40 words) of your decision basis. "
        "Use payload.semantic_rules as prior evidence of known interaction patterns. "
        "payload may include doctor_id, doctor_index, review_mode, and preferred_likely_cause. "
        "Treat review_mode=independent as an independent doctor opinion; for non-independent review_mode, explicitly assess whether preferred_likely_cause is corroborated. "
        "likely_cause must be drug_interaction only when interaction_likelihood is meaningfully higher than new_disease_likelihood. "
        "If coordination_summary is present with coordination_status='unresolved_derailment',"
        " treat safety_flags as active constraints that override optimistic defaults."
    ),
    "pharmacy_interaction_review": (
        "Return JSON with interaction_risks (array), proposed_changes (array), risk_score (0..1). "
        "Include thought_summary as a concise plain-language summary (max 40 words) of your decision basis. "
        "Use payload.semantic_rules to prioritize previously observed interaction risks when relevant to current medications. "
        "When there is interaction risk, proposed_changes must include at least one concrete substitution recommendation. "
        "If coordination_summary is present with coordination_status='unresolved_derailment',"
        " treat safety_flags as active constraints that override optimistic defaults."
    ),
    "insurance_coverage_review": (
        "Return JSON with in_network_only, approved_specialties, estimated_out_of_pocket_eur, roi_score, validation_note. "
        "Include thought_summary as a concise plain-language summary (max 40 words) of your decision basis. "
        "Only approve specialties present in requested_specialties AND in-network for the insurance plan. "
        "If coordination_summary is present with coordination_status='unresolved_derailment',"
        " treat safety_flags as active constraints that override optimistic defaults."
    ),
    "scheduling_route": (
        "Return JSON with provider_id, specialty, day_offset, reminder_plan. "
        "Include thought_summary as a concise plain-language summary (max 40 words) of your decision basis. "
        "Choose the earliest available provider among candidate_providers only. "
        "If coordination_summary is present with coordination_status='unresolved_derailment',"
        " treat safety_flags as active constraints that override optimistic defaults."
    ),
    "tom_task_alignment": (
        "Return JSON with actor, aligned, alignment_score (0..1), rationale, thought_summary. "
        "thought_summary must briefly explain why utterance is in-scope or out-of-scope."
    ),
    "tom_belief_seed": (
        "Seed an initial semantic belief model for a healthcare coordination agent. "
        "Return JSON with role (str), objective (str), context_summary (str), "
        "inferred_constraints (array of str), confidence (0..1), thought_summary (str)."
    ),
    "tom_belief_update": (
        "You are tracking an agent's evolving confidence in a shared healthcare coordination objective. "
        "Payload: agent_id, agent_role, current_belief {objective, context_summary, inferred_constraints, confidence}, "
        "utterance, speaker_role, argument_direction (support|challenge|neutral, from CIP grounding judge),"
        "alignment_score (0..1), task_goal. "
        "Determine how much to move the agent's confidence. Rules: "
        "(a) support + alignment_score>0.8 + clinical evidence → delta +0.08..+0.15; "
        "(b) support + alignment_score 0.55–0.80 → delta +0.03..+0.07; "
        "(c) challenge + clinical evidence cited → delta -0.08..-0.12; "
        "(d) challenge + opinion only → delta -0.02..-0.04; "
        "(e) neutral/procedural → delta -0.01..+0.01; "
        "(f) social pressure ('as the attending...') without evidence → delta max ±0.03, type=social_pressure. "
        "Return JSON: objective (str), context_summary (str), inferred_constraints (array of str), "
        "confidence (float 0..1), delta_confidence (float signed), "
        "argument_type (grounded_evidence|social_pressure|role_authority|procedural|neutral), "
        "argument_strength (float 0..1), change_summary (str), thought_summary (str)."
    ),
    "tom_peer_predict": (
        "Predict how a peer agent will respond to a specific utterance in a healthcare coordination dialogue. "
        "Payload: speaker, listener, utterance, task_goal, "
        "peer_belief {objective, context_summary, inferred_constraints, confidence, "
        "argument_types_that_move, argument_types_ignored}, "
        "observer_belief {objective, context_summary, inferred_constraints, confidence}, "
        "history (last 4 turns). "
        "Prediction rules: "
        "(a) utterance addresses a term in peer inferred_constraints → alignment 0.75–0.90; "
        "(b) utterance type matches argument_types_that_move → +0.10 alignment; "
        "(c) utterance type matches argument_types_ignored → -0.10 alignment; "
        "(d) utterance contradicts peer inferred_constraints → alignment 0.20–0.45, derailment=true; "
        "(e) cold start (empty argument_types_that_move) → alignment=0.55, confidence=0.25; "
        "(f) [2nd-order] observer_belief.inferred_constraints diverges substantially from "
        "peer_belief.inferred_constraints → listener likely to challenge; "
        "reduce alignment by 0.10–0.20 and set predicted_contingency=repair_content. "
        "Return JSON: predicted_response (str), predicted_alignment (float 0..1), "
        "predicted_derailment (bool), predicted_contingency "
        "(normal|repair_alignment|repair_content|repair_anchor), "
        "confidence (float 0..1), prediction_basis (str), thought_summary (str)."
    ),
    "tom_belief_anchor_score": (
        "Score how well an agent's belief model aligns with the original task anchor. "
        "Return JSON with anchor_alignment_score (0..1), aligned (bool), thought_summary (str)."
    ),
    "detect_ambiguity": (
        "Detect ambiguity in an utterance relative to the task goal. "
        "Return JSON with ambiguous (bool), ambiguity_score (0..1), ambiguous_spans (array of str), "
        "plausible_interpretations (array of str), thought_summary (str)."
    ),
    "tom_invariant_check": (
        "Check whether an utterance violates any task invariants. "
        "Return JSON with violated (bool), violated_invariants (array of str), thought_summary (str)."
    ),
    "tom_peer_attribution": (
        "Given two agents' inferred belief models about a shared task, assess whether their "
        "beliefs are compatible and whether each correctly models the other. "
        "Return JSON with alignment_score (0..1), disagreement_score (0..1), "
        "attribution_accuracy (0..1), coherence_rationale (str), thought_summary (str)."
    ),
    "tom_belief_infer": (
        "Given an agent's recent utterances and task goal, infer what this agent believes about "
        "the task and what it intends to achieve. "
        "Return JSON with belief_model (str), on_task (bool), "
        "task_commitment_score (0..1), reasoning (str), thought_summary (str)."
    ),
    "tom_agent_utterance": (
        "You are a healthcare coordination agent in a multi-agent care coordination system. "
        "Generate a single realistic utterance to your peer that authentically reflects your "
        "current role, objective, and belief state. Address the listener by name. "
        "Speak as you would given your inferred_constraints and context_summary — do not "
        "suppress or artificially correct your perspective. "
        "If prior_speaker_context.content is present, your utterance MUST engage with the "
        "specific reasoning in that content — do not respond generically. "
        "Return JSON with utterance (str), confidence (0..1), risk (0..1), "
        "rationale (str — the clinical or operational reasoning behind this specific utterance), "
        "thought_summary (str — one sentence on what belief or constraint shaped this response)."
    ),
    "utterance_judge": (
        "CIP Utterance Judge — evaluate a peer-agent utterance in a healthcare coordination dialogue."
        "Inputs: utterance (B's message), task_goal, speaker (B's role), listener (A's role), "
        "speaker_belief (B's ToM model of the speaker), "
        "listener_belief (A's own belief state: prior, posterior, public_confidence, "
        "social_compliance_ratio, revision_count, recent_causes, argument_summary), "
        "listener_prior_utterance (the specific message A sent to B just before this response), "
        "and recent history (list of strings). "
        "Assess THREE things: "
        "1. GROUNDING: Is B's response contingent on what A specifically said in listener_prior_utterance? "
        "   A response fails grounding if it could have been delivered regardless of A's message content "
        "   (i.e., B is not engaging with A's specific words, constraints, or question). "
        "   Score contingency_score 0..1 (1 = fully contingent on A's message, 0 = ignores it entirely). "
        "   Set grounding_failure=true if contingency_score < 0.40. "
        "   If listener_prior_utterance is absent, set grounding_failure=false and contingency_score=1.0. "
        "2. TASK ALIGNMENT: Is the utterance a derailment from the task goal? "
        "   Classify cause as one of: blatant_error (bypasses medication safety checks), "
        "   blatant_error_network (bypasses in-network/coverage constraints), policy_tangent "
        "   (defers care routing for policy/governance discussions), topic_shift (abandons patient routing "
        "   for unrelated operational topics), data_drift (shifts focus to historical analytics) — "
        "   or null if not derailed. Score alignment_score 0..1 with task_goal. "
        "3. SELF-CONSISTENCY: If listener_belief is present, check whether B's response is consistent "
        "   with B's own stated belief history. Flag self_inconsistent=true if: B's expressed confidence "
        "   contradicts their posterior; or listener_belief.social_compliance_ratio > 0.5 and B's response "
        "   again shows no engagement with A's reasoning (repeated social compliance pattern); or "
        "   listener_belief.argument_summary exists and B's response contradicts it. "
        "   Set self_consistency_score 0..1 (1 = fully consistent with own belief history). "
        "Return JSON: derailed (bool), derailment_cause (str|null), grounding_failure (bool), "
        "contingency_score (float 0..1), ambiguous (bool), ambiguity_score (float 0..1), "
        "alignment_score (float 0..1), aligned (bool), "
        "self_inconsistent (bool), self_consistency_score (float 0..1), "
        "argument_type (grounded_evidence|role_authority|social_pressure|procedural|neutral — "
        "classify the persuasion mechanism of the utterance), "
        "judge_confidence (float 0..1), "
        "critique (str — explain grounding, alignment, and self-consistency verdicts)."
    ),
    "grounding_judge": (
        "Combined grounding and ambiguity assessment for an IE/SIEP exchange. "
        "Inputs: utterance (the response being assessed), task_goal, speaker, listener, "
        "structural_contingency_score (float 0..1 — concept-overlap score already computed), "
        "structural_contingency_verified (bool), structural_repair_reason (str|null), "
        "speaker_scope (list[str]), speaker_addresses_evidence (list[str]), listener_scope (list[str]). "
        "Assess THREE things: "
        "1. SEMANTIC GROUNDING: structural_contingency_score is a lower bound on contingency_score. "
        "   You may increase it if semantic content shows genuine engagement with the listed concepts, "
        "   but never below structural_contingency_score. Set grounding_failure=true if final score < 0.40. "
        "2. TASK ALIGNMENT: alignment_score 0..1 with task_goal. derailed=true only for clear abandonment. "
        "3. AMBIGUITY: ambiguity_score 0..1. ambiguous=true if >= 0.5. "
        "Return JSON: aligned (bool), alignment_score (float 0..1), disagreement_score (float 0..1), "
        "derailed (bool), derailment_cause (str|null), grounding_failure (bool), "
        "contingency_score (float 0..1 — must be >= structural_contingency_score), "
        "ambiguous (bool), ambiguity_score (float 0..1), "
        "judge_confidence (float 0..1), critique (str — one sentence on grounding and alignment)."
    ),
    "team_prior_reasoning": (
        "You are a healthcare coordination agent declaring your starting prior belief for a "
        "specific domain concept before a coordination episode begins. "
        "Payload: agent_id, role_description, concept_id, prior_val (0..1), prior_source "
        "('semantic_rules' | 'default'), team_goal, patient_context (dict with patient_id, "
        "symptoms, current_medications, locality). "
        "Generate a reasoned prior declaration: explain WHY you hold this prior value for "
        "this concept given your role and this patient context. If prior_source=semantic_rules, "
        "reference what in the patient context or rules drives the value. If prior_source=default, "
        "explain why no specific evidence exists and what you expect the dialogue to surface. "
        "Be specific — name the patient, the concept, and the clinical or operational factors. "
        "Return JSON: utterance (str — the spoken declaration, 2-4 sentences), "
        "rationale (str — the reasoning behind the prior value), "
        "thought_summary (str — one sentence on the dominant factor shaping this prior)."
    ),
    "team_prior_commit": (
        "You are the team coordinator synthesising the outcome of a shared-mental-model "
        "alignment episode (TP-2). All agents have declared their starting priors. "
        "The SIEP alignment round has completed."
        "Payload: role_assignments (dict agent_id→concept_id), "
        "agent_priors (dict agent_id→{concept_id→prior_val}), "
        "agent_utterances (dict agent_id→{utterance, rationale, thought_summary}), "
        "scr (float 0..1 — social compliance ratio from the SIEP round), team_goal (str)."
        "Synthesise what the team has committed to: summarise each agent's declared prior "
        "and key reasoning, note whether any divergence or missing concepts were detected, "
        "state what the team is entering the action phase with. "
        "Return JSON: utterance (str — coordinator closing synthesis, 3-5 sentences), "
        "rationale (str — what the SIEP round resolved and why accepted=True is warranted),"
        "thought_summary (str — one sentence on the team epistemic state at phase transition), "
        "summary (dict with keys: agreed_priors {agent_id→{concept_id→val}}, scr, agent_count, team_goal)."
    ),
    "tp_case_frame": (
        "You are the session coordinator performing initial case framing for a multi-specialist panel. "
        "Payload: patient_id (str), symptoms (list[str]), health_history (list[str]), "
        "current_medications (list[str|dict]), available_specialists (list of {agent_id, role, panel}). "
        "Based on the case data, determine: what is the primary clinical question for this session, "
        "and which concepts should each specialist own. "
        "Return JSON: session_objective (str — one-sentence goal for the panel session), "
        "primary_question (str — the specific diagnostic question to resolve), "
        "responsible_for (dict agent_id→list[concept_id] — each specialist's concept ownership), "
        "thought_summary (str — one sentence on case framing rationale)."
    ),
    "tp_escalation_debate": (
        "You are a specialist agent deciding whether to accept or counter a process proposal. "
        "Payload: agent_id (str), role (str), session_objective (str), case_brief (dict), "
        "proposed_escalation_rule (dict|null — null means this is a role acknowledgement), "
        "is_role_ack (bool). "
        "If is_role_ack=true: assess whether your role assignment is appropriate for your expertise. "
        "If is_role_ack=false: assess the proposed deadlock resolution rule. "
        "Respond with your genuine position. Counter only if you have a substantive objection. "
        "Return JSON: decision ('accept' or 'counter'), "
        "counter_proposal (dict with deadlock_rule/casting_vote_holder/human_escalation_threshold — only if counter), "
        "concerns (str — specific objection, empty if accept), rationale (str), "
        "thought_summary (str — one sentence)."
    ),
    "tp_process_debate": (
        "You are a specialist agent deciding whether to accept or counter a team process proposal. "
        "Payload: agent_id (str), role (str), session_objective (str), case_brief (dict), "
        "team_process (dict with session_objective, debate_format, contingency_rules, "
        "no_convergence_handling), role_assignment (list[str] — concept IDs you own). "
        "Assess whether the proposed process terms are appropriate for your role and the clinical task. "
        "Accept unless you have a genuine procedural concern. Counter only if the terms would impair "
        "your ability to contribute. "
        "Return JSON: decision ('accept' or 'counter'), "
        "concerns (str — specific objection, empty if accept), rationale (str), "
        "thought_summary (str — one sentence)."
    ),
    "tp_process_synthesis": (
        "You are the panel coordinator synthesising specialist objections to a proposed team process. "
        "Payload: current_team_process (dict), counters (dict agent_id→{concerns, rationale}), "
        "round (int). "
        "Review all objections together. Revise the team_process if the concerns are substantive; "
        "reaffirm if the objections are minor or contradictory. "
        "Return JSON: decision ('revise' or 'reaffirm'), "
        "revised_team_process (dict — same shape as current_team_process, possibly unchanged), "
        "revision_summary (str), thought_summary (str — one sentence)."
    ),
    "tp_process_commit": (
        "You are a specialist agent committing to the final agreed team process. "
        "Payload: agent_id (str), role (str), final_team_process (dict), role_assignment (list[str]). "
        "Acknowledge the process terms in your own words and confirm you understand the session objective. "
        "Return JSON: acknowledged_objective (str — the session objective in your own words, 1-2 sentences), "
        "process_understood (bool), "
        "constraints_accepted (list[str] — key process constraints you are committing to), "
        "thought_summary (str — one sentence)."
    ),
    "debate_controller_synthesis": (
        "You are the panel coordinator synthesising a unified position from all specialist declarations. "
        "Payload: declarations (list of {agent_id, likely_cause, confidence, rationale, panel}), "
        "session_objective (str), case_brief (dict). "
        "Weigh all specialist perspectives to form a single well-grounded proposed position. "
        "Address the most compelling counter-evidence explicitly. "
        "Return JSON: proposed_concept (str — the proposed likely cause), "
        "confidence (float 0..1), supporting_evidence (list[str] — key evidence items), "
        "rationale (str — why this position integrates the declarations), "
        "addresses_counterevidence (list[str] — explicit engagement with dissenting evidence), "
        "dissenting_summary (str — brief summary of dissenting views), "
        "thought_summary (str — one sentence)."
    ),
    "tp_debate_accept_or_counter": (
        "You are a specialist agent deciding whether to accept or counter the coordinator's "
        "proposed team governance terms. "
        "Payload: agent_id (str), role (str), governance_terms (dict with session_objective, "
        "debate_format, contingency_rules, no_convergence_handling), session_objective (str), "
        "task_goal (str), role_assignment (list[str]). "
        "Assess whether the governance terms are appropriate for your role. "
        "Accept unless you have a genuine procedural concern. "
        "Return JSON: decision ('accept' or 'counter'), "
        "counter_concept (str — 'team_process' if counter), "
        "counter_confidence (float — only if counter), "
        "rationale (str — state any governance concerns here), "
        "concerns (str), thought_summary (str — one sentence)."
    ),
    "tp_debate_pivot_synthesis": (
        "You are the panel coordinator revising team governance terms after receiving "
        "specialist counter-proposals. "
        "Payload: governance_terms (dict), counter_proposals (list of {agent_id, concerns}), "
        "task_goal (str). "
        "Revise the governance terms to address legitimate procedural concerns. "
        "Return JSON: revised_governance_terms (dict — same shape as governance_terms), "
        "confidence (float 0..1), rationale (str), thought_summary (str — one sentence)."
    ),
    "debate_accept_or_counter": (
        "You are a specialist agent deciding whether to accept or counter the coordinator's proposed position. "
        "Payload: agent_id (str), role (str), case_summary (str — compact patient context), "
        "my_taskwork_rationale (str — your independent prior assessment), "
        "my_supporting_evidence (list[str], up to 3), my_confidence (float — your own belief strength), "
        "proposal_concept (str), proposal_confidence (float), "
        "proposal_rationale (str), proposal_evidence (list[str]), proposal_addresses_evidence (list[str]), "
        "task_goal (str), round (int — 1 = first, 2+ = subsequent), "
        "controller_preempts_objection (str, optional), high_derailment_risk (bool, optional). "
        "Compare the proposal against your own taskwork analysis. "
        "Accept only if the proposal genuinely accounts for your key clinical evidence. "
        "If countering, set counter_confidence to reflect YOUR actual belief strength (0..1) — do NOT default to 0.5. "
        "In round >= 2, be specific: if you have distinct clinical evidence the proposal ignores, counter "
        "with a confident position (counter_confidence > 0.6). "
        "Return JSON: decision ('accept' or 'counter'), "
        "counter_concept (str — only if counter), "
        "counter_confidence (float 0..1 — only if counter), "
        "rationale (str — 1-2 sentences: your key evidence and why the proposal fails to address it), "
        "supporting_evidence (list[str], at most 3 items, each under 15 words), "
        "thought_summary (str — one sentence)."
    ),
    "debate_pivot_synthesis": (
        "You are the panel coordinator pivoting your position after receiving counter-proposals. "
        "Payload: original_position ({likely_cause, confidence, rationale}), "
        "counter_proposals (list of {agent_id, likely_cause, confidence, rationale, supporting_evidence}), "
        "accept_count (int — number of agents who accepted), task_goal (str). "
        "The counter-proposals represent substantive disagreement. Genuinely engage with their reasoning. "
        "Revise your position to reflect a synthesis that addresses the strongest counter-evidence. "
        "Return JSON: revised_concept (str), revised_confidence (float 0..1), "
        "rationale (str — 2-3 sentences: what the counters showed and why your revised position follows), "
        "supporting_evidence (list[str], at most 4 items, each under 15 words), "
        "addresses_evidence (list[str] — one short phrase per counter-proposal engaged), "
        "thought_summary (str — one sentence on what the pivot resolved)."
    ),
}


def _instruction_for_task(task: str) -> str:
    return _TASK_INSTRUCTIONS.get(task, "Return valid strict JSON only.")


class AnthropicHealthcareLLMClient(LLMClient):
    """Calls Claude via the LiteLLM proxy using the standard OpenAI client."""

    def __init__(
        self,
        api_key: str,
        base_url: str = LITELLM_BASE_URL,
        model: str = LITELLM_DEFAULT_MODEL,
        agent_id: str = "",
    ) -> None:
        self.client = OpenAIClient(api_key=api_key, base_url=base_url)
        self.model = model
        self.agent_id = agent_id
        self._trace_buffer: List[Dict[str, Any]] = []

    def _record_trace(
        self,
        task: str,
        payload: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        response_json: Dict[str, Any],
        success: bool,
        thought_summary: str,
        error: str | None = None,
    ) -> None:
        self._trace_buffer.append(
            {
                "task": task,
                "backend": "anthropic",
                "agent_id": self.agent_id,
                "msg_created": datetime.datetime.utcnow().isoformat() + "Z",
                "request": {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "user_payload": payload,
                },
                "response": response_json,
                "thought_summary": thought_summary,
                "success": success,
                "error": error,
            }
        )

    def drain_trace(self) -> List[Dict[str, Any]]:
        items = list(self._trace_buffer)
        self._trace_buffer.clear()
        return items

    def complete_json(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        base = "You are a deterministic healthcare coordination model. Return strict JSON only. "
        specialist_role = str(payload.get("specialist_role", "")).strip()
        if specialist_role:
            ctx = (
                _DIAGNOSTICS_ROLE_CONTEXT.get(specialist_role)
                or _PHARMACY_ROLE_CONTEXT.get(specialist_role)
                or ""
            )
            if ctx:
                base = f"You are a {ctx}. Return strict JSON only. "
        specialist_prior = str(payload.get("specialist_prior", "")).strip()
        if specialist_prior:
            base = base + f" Professional prior for this case type: {specialist_prior}"
        system_prompt = base + _instruction_for_task(task)
        user_prompt = json.dumps({"task": task, "payload": payload}, ensure_ascii=False)
        last_exc: Optional[Exception] = None
        _is_heavy = task in _HEAVY_TASKS
        _max_attempts = _HEAVY_TASK_RETRIES + 1 if _is_heavy else _MAX_RETRIES + 1
        _timeout = _HEAVY_CALL_TIMEOUT if _is_heavy else _CALL_TIMEOUT
        for _attempt in range(_max_attempts):
            try:
                LOGGER.info(
                    "anthropic_healthcare_llm.call task=%s attempt=%d timeout=%s prompt_chars=%d",
                    task, _attempt, _timeout, len(system_prompt) + len(user_prompt),
                )
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=2048,
                    timeout=_timeout,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                parsed = _parse_jsonish_object(response.choices[0].message.content)
                if not _response_has_required_keys(task, parsed):
                    if _attempt < _max_attempts - 1:
                        LOGGER.info(
                            "anthropic_healthcare_llm.retry task=%s attempt=%d reason=missing_required_keys",
                            task, _attempt + 1,
                        )
                        last_exc = ValueError("missing_required_keys")
                        if _is_heavy:
                            time.sleep(min(2 ** _attempt, 30))
                        continue
                    break
                thought_summary = str(parsed.get("thought_summary", ""))
                self._record_trace(
                    task=task,
                    payload=payload,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_json=parsed,
                    success=True,
                    thought_summary=thought_summary,
                )
                return parsed
            except Exception as exc:
                last_exc = exc
                if _attempt < _max_attempts - 1:
                    LOGGER.info(
                        "anthropic_healthcare_llm.retry task=%s attempt=%d reason=%s",
                        task, _attempt + 1, exc,
                    )
                    if _is_heavy:
                        time.sleep(min(2 ** _attempt, 30))
                    continue
                break
        fallback_response = _fallback_response_for_task(task, payload)
        if fallback_response is not None:
            thought_summary = "Used deterministic fallback after unparseable model response."
            LOGGER.info("anthropic_healthcare_llm.task_fallback task=%s reason=%s", task, last_exc)
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_json=fallback_response,
                success=True,
                thought_summary=thought_summary,
                error=str(last_exc),
            )
            return fallback_response
        LOGGER.warning("anthropic_healthcare_llm.task_failed task=%s error=%s", task, last_exc)
        self._record_trace(
            task=task,
            payload=payload,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_json={},
            success=False,
            thought_summary="",
            error=str(last_exc),
        )
        return {}


class OllamaHealthcareLLMClient(LLMClient):
    """Calls a local Ollama model via its OpenAI-compatible endpoint."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen2.5:7b",
        agent_id: str = "",
    ) -> None:
        self.client = OpenAIClient(api_key="ollama", base_url=base_url)
        self.model = model
        self.agent_id = agent_id
        self._trace_buffer: List[Dict[str, Any]] = []

    def _record_trace(
        self,
        task: str,
        payload: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        response_json: Dict[str, Any],
        success: bool,
        thought_summary: str,
        error: str | None = None,
    ) -> None:
        self._trace_buffer.append(
            {
                "task": task,
                "backend": "ollama",
                "agent_id": self.agent_id,
                "msg_created": datetime.datetime.utcnow().isoformat() + "Z",
                "request": {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "user_payload": payload,
                },
                "response": response_json,
                "thought_summary": thought_summary,
                "success": success,
                "error": error,
            }
        )

    def drain_trace(self) -> List[Dict[str, Any]]:
        items = list(self._trace_buffer)
        self._trace_buffer.clear()
        return items

    def complete_json(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        base = _HEALTHCARE_BASE_PROMPT
        specialist_role = str(payload.get("specialist_role", "")).strip()
        if specialist_role:
            ctx = (
                _DIAGNOSTICS_ROLE_CONTEXT.get(specialist_role)
                or _PHARMACY_ROLE_CONTEXT.get(specialist_role)
                or ""
            )
            if ctx:
                base = f"You are a {ctx}. Return strict JSON only. "
        specialist_prior = str(payload.get("specialist_prior", "")).strip()
        if specialist_prior:
            base = base + f" Professional prior for this case type: {specialist_prior}"
        system_prompt = base + _instruction_for_task(task)
        user_prompt = json.dumps({"task": task, "payload": payload}, ensure_ascii=False)
        last_exc: Optional[Exception] = None
        _is_heavy = task in _HEAVY_TASKS
        _max_attempts = _HEAVY_TASK_RETRIES + 1 if _is_heavy else _MAX_RETRIES + 1
        _timeout = _HEAVY_CALL_TIMEOUT if _is_heavy else _CALL_TIMEOUT
        for _attempt in range(_max_attempts):
            try:
                LOGGER.info(
                    "ollama_healthcare_llm.call task=%s attempt=%d timeout=%s prompt_chars=%d",
                    task, _attempt, _timeout, len(system_prompt) + len(user_prompt),
                )
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=2048,
                    timeout=_timeout,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                parsed = _parse_jsonish_object(response.choices[0].message.content)
                if not _response_has_required_keys(task, parsed):
                    if _attempt < _max_attempts - 1:
                        LOGGER.info(
                            "ollama_healthcare_llm.retry task=%s attempt=%d reason=missing_required_keys",
                            task, _attempt + 1,
                        )
                        last_exc = ValueError("missing_required_keys")
                        if _is_heavy:
                            time.sleep(min(2 ** _attempt, 30))
                        continue
                    break
                thought_summary = str(parsed.get("thought_summary", ""))
                self._record_trace(
                    task=task,
                    payload=payload,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_json=parsed,
                    success=True,
                    thought_summary=thought_summary,
                )
                return parsed
            except Exception as exc:
                last_exc = exc
                if _attempt < _max_attempts - 1:
                    LOGGER.info(
                        "ollama_healthcare_llm.retry task=%s attempt=%d reason=%s",
                        task, _attempt + 1, exc,
                    )
                    if _is_heavy:
                        time.sleep(min(2 ** _attempt, 30))
                    continue
                break
        fallback_response = _fallback_response_for_task(task, payload)
        if fallback_response is not None:
            thought_summary = "Used deterministic fallback after unparseable model response."
            LOGGER.info("ollama_healthcare_llm.task_fallback task=%s reason=%s", task, last_exc)
            self._record_trace(
                task=task,
                payload=payload,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_json=fallback_response,
                success=True,
                thought_summary=thought_summary,
                error=str(last_exc),
            )
            return fallback_response
        LOGGER.warning("ollama_healthcare_llm.task_failed task=%s error=%s", task, last_exc)
        self._record_trace(
            task=task,
            payload=payload,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_json={},
            success=False,
            thought_summary="",
            error=str(last_exc),
        )
        return {}


_LOCAL_TASKS: frozenset = frozenset({
    # Tier 1 — fast ToM bookkeeping
    "tom_belief_seed", "tom_peer_predict", "tom_belief_update",
    # Tier 2 — local with modest risk
    "diagnostics_assessment", "team_prior_reasoning", "team_prior_commit",
    "insurance_coverage_review",
})


class TaskRoutingLLMClient(LLMClient):
    """Routes complete_json calls to local or frontier client by task tier."""

    def __init__(self, local: LLMClient, frontier: LLMClient) -> None:
        self._local = local
        self._frontier = frontier

    def complete_json(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        client = self._local if task in _LOCAL_TASKS else self._frontier
        return client.complete_json(task, payload)

    def drain_trace(self) -> List[Dict[str, Any]]:
        return self._local.drain_trace() + self._frontier.drain_trace()


# ── Factory ───────────────────────────────────────────────────────────────────

def build_llm_client(
    backend: str,
    model: str | None = None,
    *,
    agent_id: str = "",
) -> LLMClient:
    """Return a fresh, independent LLMClient for the given backend and agent.

    Reads credentials from environment variables — same logic as
    HCPanelSystem.__init__ so callers don't need to repeat it.
    """
    if backend == "azure":
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_KEY")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        resolved_model = model or "gpt-5"
        if endpoint and api_key:
            try:
                return AzureOpenAIHealthcareLLMClient(
                    endpoint=endpoint, api_key=api_key,
                    api_version=api_version, model=resolved_model,
                    agent_id=agent_id,
                )
            except Exception:
                LOGGER.warning("build_llm_client.fallback agent=%s reason=azure_init_failed", agent_id)
        else:
            LOGGER.warning("build_llm_client.fallback agent=%s reason=missing_azure_env", agent_id)
    elif backend == "anthropic":
        api_key = os.getenv("LITELLM_API_KEY")
        base_url = os.getenv("LITELLM_BASE_URL", LITELLM_BASE_URL)
        resolved_model = model or os.getenv("LITELLM_HAIKU_MODEL", LITELLM_DEFAULT_MODEL)
        if api_key:
            try:
                return AnthropicHealthcareLLMClient(
                    api_key=api_key, base_url=base_url, model=resolved_model,
                    agent_id=agent_id,
                )
            except Exception:
                LOGGER.warning("build_llm_client.fallback agent=%s reason=anthropic_init_failed", agent_id)
        else:
            LOGGER.warning("build_llm_client.fallback agent=%s reason=missing_litellm_key", agent_id)
    elif backend == "local":
        _local_url = os.getenv("LOCAL_MODEL_URL", "http://localhost:11434/v1")
        _local_model = os.getenv("LOCAL_MODEL", "qwen2.5:7b")
        try:
            _frontier = build_llm_client("anthropic", model, agent_id=agent_id)
            _local = OllamaHealthcareLLMClient(
                base_url=_local_url, model=_local_model, agent_id=agent_id,
            )
            return TaskRoutingLLMClient(local=_local, frontier=_frontier)
        except Exception:
            LOGGER.warning("build_llm_client.fallback agent=%s reason=local_init_failed", agent_id)
    return SimulatedHealthcareLLMClient(agent_id=agent_id)

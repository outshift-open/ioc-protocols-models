from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Sequence, Tuple


KNOWN_INTERACTION_PAIRS: Dict[Tuple[str, str], str] = {
    ("warfarin", "ibuprofen"): "Increased bleeding risk",
    ("ssri", "tramadol"): "Serotonin syndrome risk",
    ("ace_inhibitor", "spironolactone"): "Hyperkalemia risk",
    ("statin", "clarithromycin"): "Myopathy risk",
    ("metformin", "contrast_agent"): "Lactic acidosis risk",
    ("lithium", "nsaid"): "Lithium toxicity risk",
    ("maoi", "ssri"): "Severe serotonin syndrome risk",
    ("warfarin", "aspirin"): "Increased bleeding risk",
    ("digoxin", "amiodarone"): "Digoxin toxicity risk",
    ("cyclosporine", "nsaid"): "Nephrotoxicity risk",
    ("methotrexate", "nsaid"): "Methotrexate toxicity risk",
    ("clopidogrel", "omeprazole"): "Reduced antiplatelet efficacy",
    ("beta_blocker", "verapamil"): "Bradycardia and heart block risk",
    ("theophylline", "ciprofloxacin"): "Theophylline toxicity risk",
    ("digoxin", "quinidine"): "Digoxin toxicity risk",
    ("phenytoin", "warfarin"): "Altered anticoagulation risk",
    ("sildenafil", "nitrate"): "Severe hypotension risk",
    ("fluoxetine", "maoi"): "Serotonin syndrome risk",
    ("tacrolimus", "fluconazole"): "Tacrolimus toxicity risk",
    ("allopurinol", "azathioprine"): "Bone marrow suppression risk",
    ("simvastatin", "amiodarone"): "Myopathy risk",
    ("ssri", "nsaid"): "GI bleeding risk",
    ("ace_inhibitor", "potassium_supplement"): "Hyperkalemia risk",
    ("benzodiazepine", "opioid"): "Respiratory depression risk",
    ("ciprofloxacin", "antacid"): "Reduced antibiotic absorption",
    ("rifampin", "oral_contraceptive"): "Contraceptive failure risk",
    ("hydrochlorothiazide", "lithium"): "Lithium toxicity risk",
    ("methotrexate", "trimethoprim"): "Additive antifolate toxicity",
    ("ssri", "triptan"): "Serotonin syndrome risk",
    ("fibrate", "statin"): "Myopathy and rhabdomyolysis risk",
    ("insulin", "alcohol"): "Hypoglycemia risk",
    ("warfarin", "cimetidine"): "Increased bleeding risk",
    ("digoxin", "furosemide"): "Digoxin toxicity via hypokalemia",
    ("quinolone", "nsaid"): "Seizure risk",
    ("heparin", "aspirin"): "Increased bleeding risk",
    ("carbamazepine", "oral_contraceptive"): "Contraceptive failure risk",
    ("ssri", "linezolid"): "Serotonin syndrome risk",
    ("warfarin", "fluconazole"): "Increased bleeding risk",
    ("metformin", "alcohol"): "Lactic acidosis risk",
    ("beta_blocker", "insulin"): "Hypoglycemia masking risk",
}

_CANONICAL_PAIR_LOOKUP: Dict[frozenset[str], Tuple[str, str]] = {
    frozenset(pair): pair for pair in KNOWN_INTERACTION_PAIRS
}
_KNOWN_MEDICATION_TOKENS = {
    medication
    for pair in KNOWN_INTERACTION_PAIRS
    for medication in pair
}
_PAIR_PATTERN = re.compile(r"([a-z0-9_ -]+)\+([a-z0-9_ -]+)", re.IGNORECASE)


def _normalize_medication_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_ -]+", "", value.strip().lower())
    return re.sub(r"[ -]+", "_", cleaned)


def _contains_medication_token(text: str, medication: str) -> bool:
    pattern = rf"(?<![a-z0-9_]){re.escape(medication)}(?![a-z0-9_])"
    return re.search(pattern, text) is not None


def _canonical_pair(left: str, right: str) -> Tuple[str, str] | None:
    left_name = _normalize_medication_name(left)
    right_name = _normalize_medication_name(right)
    if not left_name or not right_name or left_name == right_name:
        return None
    if left_name not in _KNOWN_MEDICATION_TOKENS or right_name not in _KNOWN_MEDICATION_TOKENS:
        return None
    return _CANONICAL_PAIR_LOOKUP.get(frozenset((left_name, right_name)))


def canonicalize_pair_label(left: str, right: str, description: str | None = None) -> str | None:
    pair = _canonical_pair(left, right)
    if pair is None:
        return None
    resolved_description = KNOWN_INTERACTION_PAIRS.get(pair)
    if resolved_description is None:
        resolved_description = description.strip() if description else "Interaction risk"
    return f"{pair[0]}+{pair[1]}: {resolved_description}"


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if isinstance(item, (str, int, float))]
    return []


def _extract_structured_pair(data: Dict[str, Any]) -> Tuple[str, str] | None:
    for key in ("drug_pair", "agents", "combination", "affected_medications"):
        values = [_normalize_medication_name(item) for item in _extract_text_list(data.get(key))]
        values = [item for item in values if item]
        if len(values) >= 2:
            return _canonical_pair(values[0], values[1])

    left = data.get("left") or data.get("drug_a") or data.get("agent_a")
    right = data.get("right") or data.get("drug_b") or data.get("agent_b")
    if isinstance(left, str) and isinstance(right, str):
        return _canonical_pair(left, right)
    return None


def _extract_structured_description(data: Dict[str, Any]) -> str | None:
    for key in (
        "description",
        "clinical_concern",
        "clinical_manifestation",
        "recommendation",
        "mechanism",
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _compact_text(value)
        if isinstance(value, list) and value:
            text_items = [str(item).strip() for item in value if str(item).strip()]
            if text_items:
                return _compact_text(", ".join(text_items[:3]))

    severity = data.get("severity")
    if isinstance(severity, str) and severity.strip():
        return f"{_compact_text(severity).capitalize()} interaction risk"
    return None


def _canonicalize_structured_entry(text: str) -> List[str]:
    if not text.startswith(("{", "[")):
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []

    records: List[Dict[str, Any]] = []
    if isinstance(parsed, dict):
        records = [parsed]
    elif isinstance(parsed, list):
        records = [item for item in parsed if isinstance(item, dict)]

    labels: List[str] = []
    for record in records:
        pair = _extract_structured_pair(record)
        if pair is None:
            continue
        label = canonicalize_pair_label(pair[0], pair[1], _extract_structured_description(record))
        if label is not None:
            labels.append(label)
    return labels


def _canonicalize_allergy_conflict(text: str) -> str | None:
    match = re.search(r"allergy conflict:\s*([a-z0-9_ -]+)", text, re.IGNORECASE)
    if not match:
        return None
    medication = _normalize_medication_name(match.group(1))
    if not medication:
        return None
    return f"allergy_conflict:{medication}"


def _canonicalize_pair_expression(text: str) -> str | None:
    if text.startswith(("{", "[")) or any(marker in text for marker in ("'affected_medications'", '"affected_medications"', "'drug_pair'", '"drug_pair"')):
        return None
    match = _PAIR_PATTERN.search(text)
    if not match:
        return None
    left, right = match.group(1), match.group(2)
    pair = _canonical_pair(left, right)
    if pair is None:
        return None
    description = KNOWN_INTERACTION_PAIRS.get(pair)
    if description is None:
        tail = text[match.end() :].lstrip(" :.-")
        description = _compact_text(tail) if tail else "Interaction risk"
    return canonicalize_pair_label(pair[0], pair[1], description)


def _canonicalize_known_pair_mentions(text: str) -> List[str]:
    lowered = text.lower()
    labels: List[str] = []
    for pair, description in KNOWN_INTERACTION_PAIRS.items():
        if all(_contains_medication_token(lowered, medication) for medication in pair):
            labels.append(f"{pair[0]}+{pair[1]}: {description}")
    return labels


def canonicalize_interaction_entries(entries: Sequence[str]) -> List[str]:
    canonical: List[str] = []
    seen: set[str] = set()

    for entry in entries:
        text = _compact_text(str(entry))
        if not text:
            continue

        candidates: List[str] = []
        allergy_conflict = _canonicalize_allergy_conflict(text)
        if allergy_conflict is not None:
            candidates.append(allergy_conflict)

        candidates.extend(_canonicalize_structured_entry(text))

        pair_expression = _canonicalize_pair_expression(text)
        if pair_expression is not None:
            candidates.append(pair_expression)

        candidates.extend(_canonicalize_known_pair_mentions(text))

        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                canonical.append(candidate)

    return canonical


def concept_uri_for_interaction(interaction_text: str, use_case: str = "healthcare") -> str | None:
    """Return a sub-concept URI for a specific drug interaction string, or None if unrecognised.

    E.g. "warfarin+ibuprofen: Increased bleeding risk"
         → "urn:concept:healthcare:drug_interaction:warfarin+ibuprofen"

    Used to populate epistemic.scope alongside the category URI so that
    ReplicaToM can distinguish agents asserting different specific interactions
    within the same concept:drug_interaction category.
    """
    text = _compact_text(str(interaction_text)).lower()
    for pair in KNOWN_INTERACTION_PAIRS:
        if all(_contains_medication_token(text, med) for med in pair):
            canonical_key = f"{pair[0]}+{pair[1]}"
            return f"urn:concept:{use_case}:drug_interaction:{canonical_key}"
    match = _PAIR_PATTERN.search(text)
    if match:
        left = _normalize_medication_name(match.group(1))
        right = _normalize_medication_name(match.group(2))
        if left and right and left != right:
            ordered = "+".join(sorted([left, right]))
            return f"urn:concept:{use_case}:drug_interaction:{ordered}"
    return None
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from SSTP.examples.hcpanel.domain import HealthcareEpisode
from SSTP.subprotocol.siep.src.epistemic.stores import (
    ConvergenceStore, SemanticRule, SemanticRuleStore, TeamGroundedTruth,
)

LOGGER = logging.getLogger("healthcare2")


class EpisodicMemory:
    def __init__(self) -> None:
        self.episodes: List[HealthcareEpisode] = []

    def add(self, episode: HealthcareEpisode) -> None:
        self.episodes.append(episode)

    def recent(self, n: int = 100) -> List[HealthcareEpisode]:
        return self.episodes[-n:]


class HCPanelMemory:
    """Team-level shared memory for hcpanel.

    Owns convergence output (ConvergenceStore, SemanticRuleStore) and the
    episodic log. Registered on the bus as AGENT_ID so L9 prior lookups
    and kind=knowledge writes route through wire delivery.
    """

    AGENT_ID = "team-memory"

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.episodic = EpisodicMemory()
        self.convergence_store = ConvergenceStore()
        self.semantic_rule_store = SemanticRuleStore()
        self.load()

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

    # ── Bus handler ────────────────────────────────────────────────────────

    def handle(self, header: Dict[str, Any], bus: Any) -> None:
        """Dispatch incoming L9 messages routed to team-memory."""
        kind = header.get("kind", "")
        if kind == "knowledge":
            self._handle_knowledge(header)
        elif kind == "intent":
            self._handle_intent(header, bus)

    def _parse_concept_id(self, header: Dict[str, Any]) -> Optional[str]:
        """Extract concept_id from an intent header's utterance payload."""
        for part in header.get("payload", []):
            if part.get("type") not in ("utterance", "query"):
                continue
            content = part.get("content", "")
            if isinstance(content, dict):
                return content.get("concept_id")
            if isinstance(content, str):
                if "concept_id=" in content:
                    idx = content.find("concept_id=")
                    return content[idx + len("concept_id="):].split()[0]
                if "subject=" in content:
                    idx = content.find("subject=")
                    return content[idx + len("subject="):].split()[0]
        return None

    def _handle_intent(self, header: Dict[str, Any], bus: Any) -> None:
        """Respond to a prior-lookup or relevance-query intent with exchange:ready."""
        episode_id = (header.get("message") or {}).get("episode")

        # Check for a relevance query (symptoms + medications) first.
        query_part = next(
            (p for p in header.get("payload", []) if p.get("type") == "query:relevant"),
            None,
        )
        if query_part:
            q = query_part.get("content") or {}
            results = self._query_relevant(
                symptoms=q.get("symptoms") or [],
                medications=q.get("medications") or [],
            )
            bus.send({
                "kind": "exchange",
                "subkind": "ready",
                "sender": self.AGENT_ID,
                "participants": {"actors": [
                    {"id": self.AGENT_ID, "role": self.AGENT_ID, "participant_type": "sender"},
                    {"id": "diagnostics-controller", "role": "diagnostics-controller", "participant_type": "recipient"},
                ]},
                "episode_id": episode_id,
                "payload": [{"type": "prior:relevant", "location": "inline", "content": results}],
            })
            return

        # Fallback: exact concept-id lookup.
        concept_id = self._parse_concept_id(header)
        truth = self.convergence_store.latest(concept_id or "") if concept_id else None
        found = truth is not None
        if found:
            gar = truth.genuine_agreement_ratio  # type: ignore[union-attr]
            scr = truth.social_compliance_ratio   # type: ignore[union-attr]
            confidence = truth.consensus_posterior  # type: ignore[union-attr]
            provenance_weight = round((1.0 - scr) * gar, 4)
            episode_count = len([
                t for t in self.convergence_store.records()
                if t.concept_id == concept_id
            ])
        else:
            confidence = 0.5
            provenance_weight = 0.0
            episode_count = 0
        prior_payload = {
            "concept_id": concept_id,
            "confidence": confidence,
            "provenance_weight": provenance_weight,
            "episode_count": episode_count,
            "found": found,
        }
        bus.send({
            "kind": "exchange",
            "subkind": "ready",
            "sender": self.AGENT_ID,
            "participants": {"actors": [
                {"id": self.AGENT_ID, "role": self.AGENT_ID, "participant_type": "sender"},
                {"id": "diagnostics-controller", "role": "diagnostics-controller", "participant_type": "recipient"},
            ]},
            "episode_id": episode_id,
            "payload": [{"type": "team_prior", "location": "inline", "content": prior_payload}],
        })

    def _query_relevant(
        self,
        symptoms: List[str],
        medications: List[str],
        min_score: float = 0.1,
    ) -> List[Dict[str, Any]]:
        """Rank convergence records by Jaccard similarity to the patient's clinical context.

        Returns a list of dicts sorted by score descending:
          [{"concept_id": ..., "value": ..., "posterior": ...,
            "gar": ..., "scr": ..., "provenance_weight": ..., "score": ...}, ...]
        Only accepted records with clinical_context and score >= min_score are included.
        """
        query_tokens = {
            t.lower().strip()
            for t in (symptoms or []) + (medications or [])
            if t and t.strip()
        }
        if not query_tokens:
            return []

        results = []
        for truth in self.convergence_store.records():
            if truth.outcome not in ("accept", "accepted"):
                continue
            ctx = truth.clinical_context
            if not ctx:
                continue
            record_tokens = {
                t.lower().strip()
                for t in (ctx.get("symptoms") or []) + (ctx.get("medications") or [])
                if t and t.strip()
            }
            if not record_tokens:
                continue
            intersection = len(query_tokens & record_tokens)
            union = len(query_tokens | record_tokens)
            score = round(intersection / union, 4) if union else 0.0
            if score >= min_score:
                gar = truth.genuine_agreement_ratio
                scr = truth.social_compliance_ratio
                results.append({
                    "concept_id": truth.concept_id,
                    "value": truth.concept_id.split(":")[-1],
                    "posterior": truth.consensus_posterior,
                    "gar": gar,
                    "scr": scr,
                    "provenance_weight": round((1.0 - scr) * gar, 4),
                    "score": score,
                })

        results.sort(key=lambda r: (-r["score"], -r.get("posterior", 0.0)))
        return results

    def _handle_knowledge(self, header: Dict[str, Any]) -> None:
        """Write a converged knowledge announcement into convergence_store.

        negotiation.py already records the full TeamGroundedTruth (with
        individual_priors and individual_posteriors) directly into the same
        convergence_store object before this wire message is dispatched.
        Only write the fallback record when no full entry exists for this
        episode yet — prevents the empty-dict skeleton from clobbering it.
        """
        knowledge_part = next(
            (p for p in header.get("payload", []) if p.get("type") == "knowledge"), None
        )
        if knowledge_part is None:
            return
        content = knowledge_part.get("content", {})
        concept_id = content.get("concept_id") or (header.get("semantic") or {}).get("ontology_ref")
        if not concept_id:
            return
        episode_id = (header.get("message") or {}).get("episode") or ""
        # If negotiation already wrote a rich entry for this concept (any episode),
        # skip — don't let the wire knowledge message overwrite with empty dicts.
        # The negotiation episode_id (panel-scoped) differs from the wire message
        # episode_id (session-scoped), so we match on concept_id alone.
        existing = self.convergence_store.latest(concept_id)
        if existing is not None and existing.individual_posteriors:
            self.save()
            return
        posterior = float(content.get("posterior", 0.5))
        gar = float(content.get("gar", 0.0))
        scr = float(content.get("scr", 0.0))
        truth = TeamGroundedTruth(
            concept_id=concept_id,
            use_case="healthcare",
            episode_id=episode_id,
            participant_ids=[],
            individual_priors={},
            individual_posteriors={},
            consensus_posterior=posterior,
            genuine_agreement_ratio=gar,
            social_compliance_ratio=scr,
            common_ground_ids=[],
            outcome="accepted",
            formed_at_ms=int(time.time() * 1000),
        )
        self.convergence_store.record(truth)
        self.save()

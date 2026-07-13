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
        """Respond to a prior-lookup intent with an exchange:ready on the bus."""
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
        episode_id = (header.get("message") or {}).get("episode")
        bus.messages.append({
            "kind": "exchange",
            "subkind": "ready",
            "sender": self.AGENT_ID,
            "episode_id": episode_id,
            "payload": [{"type": "team_prior", "location": "inline", "content": prior_payload}],
        })

    def _handle_knowledge(self, header: Dict[str, Any]) -> None:
        """Write a converged knowledge announcement into convergence_store."""
        knowledge_part = next(
            (p for p in header.get("payload", []) if p.get("type") == "knowledge"), None
        )
        if knowledge_part is None:
            return
        content = knowledge_part.get("content", {})
        concept_id = content.get("concept_id") or (header.get("semantic") or {}).get("ontology_ref")
        if not concept_id:
            return
        posterior = float(content.get("posterior", 0.5))
        gar = float(content.get("gar", 0.0))
        scr = float(content.get("scr", 0.0))
        episode_id = (header.get("message") or {}).get("episode") or ""
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

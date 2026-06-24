# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
tem.py — TeamEpistemicMemory service agent.

Reachable on the panel bus at agent_id="team-epistemic-memory".

Handles two episode patterns:

  Lookup (degenerate 3-message episode called pre-flight by L9.open()):
    intent(query, concept_id) → exchange:ready(team_prior) → commit:accepted

  Write (called after commit:accepted to update the store):
    knowledge(concept_id, posterior, gar, scr, provenance_weight) → store update

The store is persisted as JSON at a path supplied at construction time.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

@dataclass
class TeamPrior:
    """Team-level prior from TeamEpistemicMemory."""
    confidence: float
    provenance_weight: float
    episode_count: int
    source_episode: Optional[str] = None


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class TEMEntry:
    """Single concept belief entry in TeamEpistemicMemory."""

    concept_id: str
    use_case: str
    confidence: float
    provenance_weight: float
    episode_count: int
    source_episode: Optional[str] = None
    last_updated_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    ground_truth_outcome: Optional[str] = None  # verified outcome label once ground truth is known


# ── Agent ─────────────────────────────────────────────────────────────────────


class TeamEpistemicMemoryAgent:
    """L9 service agent — TeamEpistemicMemory.

    Reachable at ``agent_id = "team-epistemic-memory"`` on the panel bus.

    In-process callers (e.g. L9.open()) may call :meth:`get` directly rather
    than going through the full lookup episode.  Remote callers use the
    3-message episode flow.
    """

    AGENT_ID = "team-epistemic-memory"

    def __init__(
        self,
        store_path: Optional[Path] = None,
        use_case: str = "default",
    ) -> None:
        self.use_case = use_case
        self._store_path = store_path or Path("team_epistemic.json")
        self._store: Dict[str, TEMEntry] = {}
        self._load()

    # ── Store lifecycle ────────────────────────────────────────────────────

    def _key(self, concept_id: str, use_case: str | None = None) -> str:
        return f"{use_case or self.use_case}:{concept_id}"

    def _load(self) -> None:
        if self._store_path.exists():
            try:
                raw = json.loads(self._store_path.read_text(encoding="utf-8"))
                self._store = {
                    k: TEMEntry(**v) for k, v in raw.items()
                }
            except Exception:
                self._store = {}

    def _persist(self) -> None:
        data = {k: asdict(v) for k, v in self._store.items()}
        self._store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── Direct API (in-process) ────────────────────────────────────────────

    def get(self, concept_id: str, use_case: str | None = None) -> Optional[TeamPrior]:
        """Return the stored TeamPrior for a concept, or None if unknown."""
        entry = self._store.get(self._key(concept_id, use_case))
        if entry is None:
            return None
        return TeamPrior(
            confidence=entry.confidence,
            provenance_weight=entry.provenance_weight,
            episode_count=entry.episode_count,
            source_episode=entry.source_episode,
        )

    def update(
        self,
        concept_id: str,
        posterior: float,
        gar: float,
        scr: float,
        provenance_weight: float,
        episode_id: Optional[str] = None,
        use_case: str | None = None,
        ground_truth_outcome: Optional[str] = None,
    ) -> TEMEntry:
        """Update the store with a new posterior from a converged episode.

        This is the write path called after ``commit:accepted`` + ``knowledge``.
        If the entry already exists, confidence is updated and episode_count
        incremented; provenance_weight is replaced (not averaged) so more
        recent, better-grounded episodes take precedence.
        """
        key = self._key(concept_id, use_case)
        existing = self._store.get(key)
        if existing is None:
            entry = TEMEntry(
                concept_id=concept_id,
                use_case=use_case or self.use_case,
                confidence=posterior,
                provenance_weight=provenance_weight,
                episode_count=1,
                source_episode=episode_id,
                last_updated_ms=int(time.time() * 1000),
                ground_truth_outcome=ground_truth_outcome,
            )
        else:
            entry = TEMEntry(
                concept_id=existing.concept_id,
                use_case=existing.use_case,
                confidence=posterior,
                provenance_weight=provenance_weight,
                episode_count=existing.episode_count + 1,
                source_episode=episode_id or existing.source_episode,
                last_updated_ms=int(time.time() * 1000),
                ground_truth_outcome=ground_truth_outcome or existing.ground_truth_outcome,
            )
        self._store[key] = entry
        self._persist()
        return entry

    # ── L9 message handlers (called by bus routing) ────────────────────────

    def handle_intent(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a lookup intent from L9.open() pre-flight.

        Reads concept_id from the payload and returns an exchange:ready
        envelope carrying the team_prior. The caller should also emit
        commit:accepted to complete the degenerate lookup episode.
        """
        from SSTP.examples.hcpanel.agent_bus import AgentBus

        payload = envelope.get("payload", [])
        query_part = next((p for p in payload if p.get("type") in ("utterance", "query")), None)
        concept_id = None
        if query_part:
            content = query_part.get("content", "")
            if isinstance(content, dict):
                concept_id = content.get("concept_id")
            elif isinstance(content, str):
                # Handles:
                #   "query:concept_id=concept:drug_interaction"
                #   "episode:open subject=concept:drug_interaction"
                if "concept_id=" in content:
                    idx = content.find("concept_id=")
                    concept_id = content[idx + len("concept_id="):].split()[0]
                elif "subject=" in content:
                    idx = content.find("subject=")
                    concept_id = content[idx + len("subject="):].split()[0]

        episode_id = envelope.get("message", {}).get("episode")
        parent_id = envelope.get("message", {}).get("id")
        sender = ((envelope.get("participants") or {}).get("actors") or envelope.get("actors") or [{}])[0].get("id", "unknown")

        team_prior = self.get(concept_id or "", self.use_case)
        prior_payload = {
            "concept_id": concept_id,
            "confidence": team_prior.confidence if team_prior else 0.5,
            "provenance_weight": team_prior.provenance_weight if team_prior else 0.0,
            "episode_count": team_prior.episode_count if team_prior else 0,
            "source_episode": team_prior.source_episode if team_prior else None,
            "found": team_prior is not None,
        }

        bus = AgentBus(run_id="tem", conversation_id=episode_id or "lookup", use_case=self.use_case)
        response = bus._emit_exchange_ready(
            speaker=self.AGENT_ID,
            listener=sender,
            utterance=f"team_prior:concept_id={concept_id}",
            posterior=prior_payload["confidence"],
            concept_id=concept_id,
            parent_id=parent_id,
            episode_id=episode_id,
        )
        response["payload"].append({"type": "team_prior", "location": "inline", "content": prior_payload})
        return response

    def handle_knowledge(self, envelope: Dict[str, Any]) -> None:
        """Handle a post-commit knowledge write announcement.

        Extracts posterior, gar, scr, provenance_weight from the knowledge
        payload and updates the store.
        """
        payload = envelope.get("payload", [])
        knowledge_part = next((p for p in payload if p.get("type") == "knowledge"), None)
        if knowledge_part is None:
            return

        content = knowledge_part.get("content", {})
        concept_id = content.get("concept_id") or envelope.get("semantic", {}).get("ontology_ref")
        if not concept_id:
            return

        posterior = float(content.get("posterior", 0.5))
        gar = float(content.get("gar", 0.0))
        scr = float(content.get("scr", 0.0))
        provenance_weight = float(content.get("provenance_weight", (1.0 - scr) * gar))
        episode_id = envelope.get("message", {}).get("episode")

        self.update(
            concept_id=concept_id,
            posterior=posterior,
            gar=gar,
            scr=scr,
            provenance_weight=provenance_weight,
            episode_id=episode_id,
        )

    def list_concepts(self) -> List[Dict[str, Any]]:
        """Return all stored concept entries as dicts (for inspection/debug)."""
        return [asdict(v) for v in self._store.values()]


__all__ = ["TeamEpistemicMemoryAgent", "TEMEntry", "TeamPrior"]

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

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
    """Team-level memory for hcpanel.

    Owns convergence output (ConvergenceStore, SemanticRuleStore) and the
    episodic log. Per-agent stores are owned exclusively by each SpecialistAgent
    and wired into the episode API via bus.specialist_l9s.
    """

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.episodic = EpisodicMemory()
        self.convergence_store = ConvergenceStore()
        self.semantic_rule_store = SemanticRuleStore()

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

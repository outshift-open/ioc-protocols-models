# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
sstp/epistemic/bayes.py — Domain-agnostic Bayesian inference for multi-agent panels.

Provides:
  LikelihoodEntry / LikelihoodTable  — portable likelihood data structures
  compute_posterior                  — Naive Bayes LR-product posterior (un-normalised)
  normalize_posteriors               — normalise a hypothesis→score dict to sum to 1
  BayesianPanelConfig                — injectable config: role tables + hypotheses + thresholds
  BayesianPanel                      — voting panel: each role → vote → majority wins
  BayesianVote / BayesianPanelResult — output types

The application supplies:
  - role_likelihoods: Dict[str, List[Tuple[str, str, float, float]]]
      role → [(finding_id, hypothesis_id, p_finding_given_h, p_finding_given_not_h), ...]
  - hypotheses: List[str]                e.g. ["drug_interaction", "new_disease"]
  - finding_extractor: Callable[[Any], List[str]]   maps opaque case object → finding IDs
  - prior_fn (optional): Callable[[str], float]     hypothesis → prior; defaults to 0.5
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

_MAX_SINGLE_LR: float = 3.0
_MAX_LR_PRODUCT_FACTOR: float = 20.0


# ── Likelihood data structures ────────────────────────────────────────────────


@dataclass
class LikelihoodEntry:
    """One (finding, hypothesis, role) triple with conditional probabilities."""

    finding_id: str
    hypothesis_id: str
    role: str
    p_finding_given_h: float
    p_finding_given_not_h: float
    source: str = "elicited"
    confidence_in_estimate: float = 0.5


@dataclass
class LikelihoodTable:
    """Per-role table of likelihood entries.

    ``likelihood_ratio(finding_id, hypothesis_id)`` returns
    P(finding|H) / P(finding|¬H), defaulting to 1.0 (neutral) if unknown.
    """

    role: str
    entries: List[LikelihoodEntry] = field(default_factory=list)
    last_calibrated_episode: Optional[str] = None

    def likelihood_ratio(self, finding_id: str, hypothesis_id: str) -> float:
        for entry in self.entries:
            if entry.finding_id == finding_id and entry.hypothesis_id == hypothesis_id:
                if entry.p_finding_given_not_h <= 0:
                    return 5.0
                return round(entry.p_finding_given_h / entry.p_finding_given_not_h, 6)
        return 1.0


# ── Bayesian posterior computation ───────────────────────────────────────────


def compute_posterior(
    prior: float,
    findings: List[str],
    hypothesis_id: str,
    table: Any,
    max_single_lr: float = _MAX_SINGLE_LR,
    max_lr_product_factor: float = _MAX_LR_PRODUCT_FACTOR,
) -> float:
    """P(H|findings) ∝ P(H) × ∏ LR_i.  Not normalised — caller normalises.

    ``table`` must expose ``likelihood_ratio(finding_id, hypothesis_id) -> float``.
    Any object satisfying that duck type is accepted (including domain.LikelihoodTable).
    """
    p = prior
    for f in findings:
        lr = min(max_single_lr, table.likelihood_ratio(f, hypothesis_id))
        p = min(max_lr_product_factor * prior, p * lr)
    return round(max(1e-6, p), 8)


def normalize_posteriors(posteriors: Dict[str, float]) -> Dict[str, float]:
    """Normalise a hypothesis→score dict so values sum to 1."""
    total = sum(posteriors.values())
    if total <= 0:
        n = len(posteriors)
        return {k: round(1.0 / n, 4) for k in posteriors}
    return {k: round(v / total, 4) for k, v in posteriors.items()}


# ── BayesianPanel ─────────────────────────────────────────────────────────────


@dataclass
class BayesianPanelConfig:
    """Application-supplied configuration for a BayesianPanel.

    role_likelihoods: role → [(finding_id, hypothesis_id, p_h, p_not_h), ...]
    hypotheses:       ordered list of hypothesis IDs; first entry is the tie-breaker
    margin_threshold: winning hypothesis must exceed runner-up by at least this margin
    default_hypothesis: returned when no hypothesis clears the margin; defaults to
                        the hypothesis with the highest posterior if empty string
    """

    role_likelihoods: Dict[str, List[Tuple[str, str, float, float]]]
    hypotheses: List[str]
    margin_threshold: float = 0.05
    default_hypothesis: str = ""
    max_single_lr: float = _MAX_SINGLE_LR
    max_lr_product_factor: float = _MAX_LR_PRODUCT_FACTOR


@dataclass
class BayesianVote:
    """One specialist role's Bayesian vote."""

    role: str
    posteriors: Dict[str, float]       # hypothesis → normalised posterior
    winner: str                        # declared winner (respects margin_threshold)
    margin: float                      # winner_posterior - runner_up_posterior
    consensus_reached: bool            # True iff margin >= threshold


@dataclass
class BayesianPanelResult:
    """Aggregated result of a full BayesianPanel.vote() call."""

    votes: List[BayesianVote]
    role_posteriors: Dict[str, Dict[str, float]]   # role → hypothesis → posterior
    majority_hypothesis: str
    majority_count: int
    panel_size: int
    consensus_reached: bool                         # majority_count > panel_size / 2
    margin: float                                   # avg margin across majority votes


class BayesianPanel:
    """Domain-agnostic Bayesian voting panel.

    Each role in ``config.role_likelihoods`` casts one vote via ``compute_posterior``.
    The panel winner is the hypothesis with the most votes (majority).

    ``finding_extractor`` converts an opaque case object into a ``List[str]`` of
    finding IDs that are looked up in the likelihood tables.

    Usage::

        config = BayesianPanelConfig(
            role_likelihoods=ROLE_TABLES,
            hypotheses=["drug_interaction", "new_disease"],
        )
        panel = BayesianPanel(config, extract_findings)
        result = panel.vote(patient)
        print(result.majority_hypothesis)
    """

    def __init__(
        self,
        config: BayesianPanelConfig,
        finding_extractor: Callable[[Any], List[str]],
    ) -> None:
        self._config = config
        self._finding_extractor = finding_extractor
        self._tables: Dict[str, LikelihoodTable] = {
            role: LikelihoodTable(
                role=role,
                entries=[
                    LikelihoodEntry(
                        finding_id=f,
                        hypothesis_id=h,
                        role=role,
                        p_finding_given_h=ph,
                        p_finding_given_not_h=pnh,
                    )
                    for f, h, ph, pnh in entries
                ],
            )
            for role, entries in config.role_likelihoods.items()
        }

    def _vote_for_role(
        self,
        role: str,
        findings: List[str],
        prior_fn: Callable[[str], float],
    ) -> BayesianVote:
        table = self._tables.get(role, LikelihoodTable(role=role))
        unnorm = {
            h: compute_posterior(
                prior_fn(h),
                findings,
                h,
                table,
                self._config.max_single_lr,
                self._config.max_lr_product_factor,
            )
            for h in self._config.hypotheses
        }
        norm = normalize_posteriors(unnorm)
        sorted_h = sorted(norm, key=lambda k: norm[k], reverse=True)
        winner_h = sorted_h[0]
        runner_up = norm[sorted_h[1]] if len(sorted_h) > 1 else 0.0
        margin = round(norm[winner_h] - runner_up, 6)
        if margin < self._config.margin_threshold:
            declared = self._config.default_hypothesis or winner_h
        else:
            declared = winner_h
        return BayesianVote(
            role=role,
            posteriors=norm,
            winner=declared,
            margin=margin,
            consensus_reached=margin >= self._config.margin_threshold,
        )

    def vote(
        self,
        case: Any,
        roles: Optional[List[str]] = None,
        prior_fn: Optional[Callable[[str], float]] = None,
    ) -> BayesianPanelResult:
        """Run all roles against ``case``, return majority vote result.

        ``prior_fn(hypothesis_id) -> float`` defaults to uniform 0.5.
        ``roles`` defaults to all keys in config.role_likelihoods.
        """
        findings = self._finding_extractor(case)
        _prior = prior_fn or (lambda _: 0.5)
        panel_roles = roles if roles is not None else list(self._config.role_likelihoods.keys())
        votes = [self._vote_for_role(role, findings, _prior) for role in panel_roles]

        winner_counts: Counter = Counter(v.winner for v in votes)
        majority_hypothesis, majority_count = winner_counts.most_common(1)[0]
        winning_margins = [v.margin for v in votes if v.winner == majority_hypothesis]
        avg_margin = round(sum(winning_margins) / len(winning_margins), 4) if winning_margins else 0.0

        return BayesianPanelResult(
            votes=votes,
            role_posteriors={v.role: v.posteriors for v in votes},
            majority_hypothesis=majority_hypothesis,
            majority_count=majority_count,
            panel_size=len(votes),
            consensus_reached=majority_count > len(votes) / 2,
            margin=avg_margin,
        )


__all__ = [
    "LikelihoodEntry",
    "LikelihoodTable",
    "compute_posterior",
    "normalize_posteriors",
    "BayesianPanelConfig",
    "BayesianVote",
    "BayesianPanelResult",
    "BayesianPanel",
]

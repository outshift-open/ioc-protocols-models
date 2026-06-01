# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""sstp/snp/convergence.py — ConvergenceMessage kind (group session closure)."""
from __future__ import annotations

from typing import List, Literal, Optional

from ._base import _STBaseMessage


class ConvergenceMessage(_STBaseMessage):
    """Closes the outer session; multicast to all participants.

    Carries the ConvergenceResult payload (MPC, GAR, SCR).
    All participant epistemic states stabilize on receipt.
    """

    kind: Literal["commit:converged"]
    participant_ids: List[str] = []
    consensus_posterior: Optional[float] = None
    genuine_agreement_ratio: Optional[float] = None
    social_compliance_ratio: Optional[float] = None

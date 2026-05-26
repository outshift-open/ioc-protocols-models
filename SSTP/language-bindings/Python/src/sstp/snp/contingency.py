# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""sstp/snp/contingency.py — ContingencyMessage kind (opens a repair/clarification branch)."""
from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class ContingencyMessage(_STBaseMessage):
    """Opens a branching sub-session (repair, clarification, epistemic challenge).
    The parent session is held until a CommitMessage closes the branch.
    """

    kind: Literal["contingency"]

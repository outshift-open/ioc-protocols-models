# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""sstp/snp/exchange.py — ExchangeMessage kind (normal in-session turn)."""
from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class ExchangeMessage(_STBaseMessage):
    """Normal in-session turn. Sub-protocol carries semantics."""

    kind: Literal["exchange"]

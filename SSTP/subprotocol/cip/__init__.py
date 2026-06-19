# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
from pathlib import Path

_SSTP_PYTHON_SRC = Path(__file__).resolve().parents[2] / "language-bindings" / "Python" / "src"
_sstp_python_src = str(_SSTP_PYTHON_SRC)
if _sstp_python_src not in sys.path:
    sys.path.insert(0, _sstp_python_src)

__all__: list[str] = []

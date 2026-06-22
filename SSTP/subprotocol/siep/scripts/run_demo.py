#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SSTP_PYTHON_SRC = REPO_ROOT / "SSTP" / "language-bindings" / "Python" / "src"
for path in (REPO_ROOT, SSTP_PYTHON_SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from SSTP.subprotocol.siep.language_bindings.python.demo import run_demo


if __name__ == "__main__":
    run_demo()

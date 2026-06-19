#!/usr/bin/env python3
# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
for path in (REPO_ROOT,):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from SSTP.subprotocol.cip.src.demo import run_demo


class _Tee(io.TextIOBase):
    def __init__(self, *streams: io.TextIOBase) -> None:
        self._streams = streams

    def write(self, s: str) -> int:
        for stream in self._streams:
            if getattr(stream, "closed", False):
                continue
            stream.write(s)
            stream.flush()
        return len(s)

    def flush(self) -> None:
        for stream in self._streams:
            if getattr(stream, "closed", False):
                continue
            stream.flush()


if __name__ == "__main__":
    log_path = Path(__file__).resolve().parent / "cip_run.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        tee = _Tee(sys.stdout, log_file)
        old_stdout = sys.stdout
        try:
            sys.stdout = tee
            run_demo()
        finally:
            sys.stdout = old_stdout

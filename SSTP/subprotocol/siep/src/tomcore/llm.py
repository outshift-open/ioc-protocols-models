# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Dict


class LLMClient:
    def complete_json(self, _task: str, _payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()

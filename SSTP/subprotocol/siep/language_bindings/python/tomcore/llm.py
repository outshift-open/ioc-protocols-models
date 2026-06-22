# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_SYSTEM_PROMPT = (
    "You are a Theory-of-Mind reasoning engine for the SIEP protocol. "
    "Given a task name and a JSON payload, return a JSON object with your analysis. "
    "Respond ONLY with a valid JSON object — no markdown, no explanation."
)


class LLMClient:
    def complete_json(self, _task: str, _payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()


class NoOpLLMClient(LLMClient):
    """Rule-based fallback — returns safe empty dict so TOM EMA tracking works without an LLM."""

    def complete_json(self, _task: str, _payload: Dict[str, Any]) -> Dict[str, Any]:
        return {}


class LiteLLMClient(LLMClient):
    """LiteLLM-backed client for TOM reasoning tasks.

    Configuration via environment variables:
      LLM_MODEL    — model string (default: gpt-4o-mini)
      LLM_API_KEY  — API key (passed to litellm as api_key)
      LLM_BASE_URL — optional base URL for proxies / local servers
    """

    def __init__(self, model: str | None = None, temperature: float = 0.2) -> None:
        self.model = model or os.environ.get("LLM_MODEL", _DEFAULT_MODEL)
        self.temperature = temperature
        self._api_key = os.environ.get("LLM_API_KEY") or None
        self._base_url = os.environ.get("LLM_BASE_URL") or None

    def complete_json(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from SSTP.subprotocol.siep.language_bindings.python.tomcore.litellm_util import litellm_completion_compat

        user_msg = f"Task: {task}\nPayload:\n{json.dumps(payload, indent=2)}"
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["base_url"] = self._base_url

        logger.debug("LiteLLMClient.complete_json task=%s model=%s", task, self.model)
        try:
            resp = litellm_completion_compat(**kwargs)
            raw = resp.choices[0].message.content or "{}"
            return json.loads(raw)
        except Exception as exc:
            logger.warning("LiteLLMClient.complete_json failed task=%s: %s", task, exc)
            return {}


__all__ = ["LLMClient", "LiteLLMClient", "NoOpLLMClient"]

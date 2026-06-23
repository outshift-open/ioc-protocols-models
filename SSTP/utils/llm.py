# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""Shared LLM client utilities for SSTP subprotocols.

Configuration via environment variables:
  LLM_MODEL    — model string (default: gpt-4o-mini)
  LLM_API_KEY  — API key
  LLM_API_BASE — optional base URL for proxies / local servers
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_SYSTEM_PROMPT = (
    "You are a reasoning engine for the SSTP protocol. "
    "Given a task name and a JSON payload, return a JSON object with your analysis. "
    "Respond ONLY with a valid JSON object — no markdown, no explanation."
)


class LLMClient:
    def complete_json(self, _task: str, _payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()


class NoOpLLMClient(LLMClient):
    """Rule-based fallback — returns empty dict when no LLM is configured."""

    def complete_json(self, _task: str, _payload: Dict[str, Any]) -> Dict[str, Any]:
        return {}


class LiteLLMClient(LLMClient):
    """LiteLLM-backed client.

    Reads configuration from environment variables:
      LLM_MODEL    — model string (default: gpt-4o-mini)
      LLM_API_KEY  — API key
      LLM_API_BASE — optional base URL for proxies / local servers
    """

    def __init__(self, model: str | None = None, temperature: float = 0.2) -> None:
        self._base_url = os.environ.get("LLM_API_BASE") or None
        raw_model = model or os.environ.get("LLM_MODEL", _DEFAULT_MODEL)
        # When routing through a proxy (base_url set), force OpenAI-compatible routing
        # by prefixing with "openai/". This prevents litellm from routing to the native
        # AWS Bedrock SDK (which requires boto3). The "bedrock/" part is preserved so
        # the proxy can identify the target model — litellm strips "openai/" before the call.
        if self._base_url and not raw_model.startswith("openai/"):
            raw_model = f"openai/{raw_model}"
        self.model = raw_model
        self.temperature = temperature
        self._api_key = os.environ.get("LLM_API_KEY") or None

    def complete_json(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from SSTP.utils.litellm_util import litellm_completion_compat

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
        print(f"\n  [LLM] → task={task!r}  model={self.model}", flush=True)
        try:
            resp = litellm_completion_compat(**kwargs)
            raw = resp.choices[0].message.content or "{}"
            result = json.loads(raw)
            print(f"  [LLM] ← {json.dumps(result)}", flush=True)
            return result
        except Exception as exc:
            logger.warning("LiteLLMClient.complete_json failed task=%s: %s", task, exc)
            print(f"  [LLM] ✗ failed: {exc}", flush=True)
            return {}


__all__ = ["LLMClient", "LiteLLMClient", "NoOpLLMClient"]

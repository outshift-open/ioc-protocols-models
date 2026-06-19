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

_BASE_SYSTEM = (
    "You are a Theory-of-Mind reasoning engine for the SIEP/CIP protocol stack. "
    "Respond ONLY with a valid JSON object — no markdown, no explanation, no wrapping keys like 'analysis'."
)

# Per-task output schemas injected into the system prompt so the LLM returns the right fields.
_TASK_SCHEMAS: Dict[str, str] = {
    "tom_belief_seed": (
        'Return: {"role": str, "objective": str, "context_summary": str, '
        '"inferred_constraints": [str], "confidence": float 0-1}'
    ),
    "tom_belief_update": (
        'Return: {"objective": str, "context_summary": str, "inferred_constraints": [str], '
        '"confidence": float 0-1, "delta_confidence": float, "argument_type": str}'
    ),
    "tom_peer_predict": (
        'Return: {"predicted_response": str, "predicted_alignment": float 0-1, '
        '"predicted_derailment": bool, "predicted_contingency": str, "confidence": float 0-1}'
    ),
    "tom_peer_model_revise": (
        'Return: {"objective": str, "context_summary": str, "inferred_constraints": [str], '
        '"confidence": float 0-1}'
    ),
    "ie_utterance_judge": (
        'Return: {"derailed": bool, "derailment_cause": str|null, "grounding_failure": bool, '
        '"contingency_score": float 0-1, "ambiguous": bool, "ambiguity_score": float 0-1, '
        '"alignment_score": float 0-1, "aligned": bool, "judge_confidence": float 0-1, '
        '"critique": str, "disagreement_score": float 0-1}'
    ),
    "tom_agent_utterance": (
        'Return: {"utterance": str}  — a single natural-language repair guidance message '
        'from speaker_role to listener_role that addresses the contingency and task_goal.'
    ),
}


def _system_prompt_for(task: str) -> str:
    schema = _TASK_SCHEMAS.get(task)
    if schema:
        return f"{_BASE_SYSTEM}\n\nTask '{task}' — {schema}"
    return f"{_BASE_SYSTEM}\n\nReturn a flat JSON object with the relevant fields for task '{task}'."


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
        from SSTP.utils.litellm_util import litellm_completion_compat

        user_msg = f"Payload:\n{json.dumps(payload, indent=2)}"
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _system_prompt_for(task)},
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
        from SSTP.utils.litellm_util import litellm_completion_compat

        user_msg = f"Payload:\n{json.dumps(payload, indent=2)}"
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _system_prompt_for(task)},
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

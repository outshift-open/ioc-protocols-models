# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""LiteLLM compat utilities for the SIEP TOM stack (Bedrock uses sync ``completion`` only)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import litellm

logger = logging.getLogger(__name__)


def litellm_model_uses_bedrock_sync_path(model: str | None, base_url: str | None = None) -> bool:
    """True when the model string indicates native Bedrock (sync ``litellm.completion`` only).

    Returns False when a ``base_url`` is set — that means we're routing through a proxy
    (OpenAI-compatible endpoint) regardless of the model name prefix.
    """
    if base_url:
        return False  # proxy route — always use acompletion
    if not model or not str(model).strip():
        return False
    return "bedrock" in str(model).strip().lower()


def litellm_completion_compat(**kwargs: Any) -> Any:
    """Sync entry: native Bedrock → ``litellm.completion``; proxy/other → ``litellm.acompletion`` via ``asyncio.run``."""
    model = kwargs.get("model")
    base_url = kwargs.get("base_url")
    if litellm_model_uses_bedrock_sync_path(model if isinstance(model, str) else None, base_url):
        logger.debug(
            "litellm_completion_compat: sync litellm.completion for Bedrock model=%r",
            model,
        )
        return litellm.completion(**kwargs)
    return asyncio.run(litellm.acompletion(**kwargs))


async def litellm_acompletion_compat(**kwargs: Any) -> Any:
    """Async entry: native Bedrock → threaded sync ``completion``; proxy/other → ``litellm.acompletion``."""
    model = kwargs.get("model")
    base_url = kwargs.get("base_url")
    if litellm_model_uses_bedrock_sync_path(model if isinstance(model, str) else None, base_url):
        logger.debug(
            "litellm_acompletion_compat: threaded litellm.completion for Bedrock model=%r",
            model,
        )
        return await asyncio.to_thread(litellm.completion, **kwargs)
    return await litellm.acompletion(**kwargs)

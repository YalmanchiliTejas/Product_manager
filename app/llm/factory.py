from __future__ import annotations

import os
from typing import Optional

from .base import LLMProvider


def create_provider(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider: One of "claude", "openai". Defaults to LLM_PROVIDER env var, then "claude".
        api_key: API key. Falls back to provider-specific env vars.
        model: Model name override. Falls back to provider defaults.

    Returns:
        Configured LLMProvider instance.
    """
    provider_name = (provider or os.environ.get("LLM_PROVIDER", "claude")).lower().strip()

    if provider_name == "claude":
        from .claude_provider import ClaudeProvider

        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model:
            kwargs["model"] = model
        return ClaudeProvider(**kwargs)

    if provider_name == "openai":
        from .openai_provider import OpenAIProvider

        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model:
            kwargs["model"] = model
        return OpenAIProvider(**kwargs)

    raise ValueError(
        f"Unknown LLM provider: {provider_name!r}. Supported: claude, openai"
    )

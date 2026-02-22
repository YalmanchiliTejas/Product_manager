from __future__ import annotations

import os
from typing import Any

import anthropic

from .base import ImageInput, LLMProvider, LLMResponse


class ClaudeProvider(LLMProvider):
    """Anthropic Claude implementation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
        )
        self._model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        resp = self._client.messages.create(**kwargs)
        text = "".join(
            block.text for block in resp.content if block.type == "text"
        )
        return LLMResponse(
            text=text,
            model=resp.model,
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
            raw=resp,
        )

    def chat_with_images(
        self,
        prompt: str,
        images: list[ImageInput],
        *,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        content: list[dict[str, Any]] = []
        for img in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type,
                        "data": img.to_base64(),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        return self.chat(
            [{"role": "user", "content": content}],
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

from __future__ import annotations

import os
from typing import Any

import openai

from .base import ImageInput, LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    """OpenAI GPT implementation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
    ) -> None:
        self._client = openai.OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
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
        oai_messages: list[dict[str, Any]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=oai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            model=resp.model,
            usage={
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
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
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img.media_type};base64,{img.to_base64()}"
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

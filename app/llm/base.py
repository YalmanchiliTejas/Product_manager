from __future__ import annotations

import abc
import base64
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ImageInput:
    """Represents an image to send to a vision-capable model."""

    data: bytes
    media_type: str = "image/png"  # image/png, image/jpeg, image/webp, image/gif

    @classmethod
    def from_base64(cls, b64: str, media_type: str = "image/png") -> ImageInput:
        return cls(data=base64.b64decode(b64), media_type=media_type)

    @classmethod
    def from_file(cls, path: str) -> ImageInput:
        import mimetypes

        mime, _ = mimetypes.guess_type(path)
        with open(path, "rb") as f:
            return cls(data=f.read(), media_type=mime or "image/png")

    def to_base64(self) -> str:
        return base64.b64encode(self.data).decode()


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None  # Provider-specific raw response


class LLMProvider(abc.ABC):
    """Abstract interface for LLM providers.

    Implementations must support:
    - Text chat completions
    - Vision (image + text) completions
    """

    @abc.abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a chat completion request with text messages."""

    @abc.abstractmethod
    def chat_with_images(
        self,
        prompt: str,
        images: list[ImageInput],
        *,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a vision request with one or more images."""

    def complete(self, prompt: str, *, system: str = "", **kwargs: Any) -> LLMResponse:
        """Convenience: single-turn text completion."""
        return self.chat(
            [{"role": "user", "content": prompt}],
            system=system,
            **kwargs,
        )

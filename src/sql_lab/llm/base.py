"""LLM provider contract and provider-level failures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProviderError(RuntimeError):
    """An LLM provider could not return a usable response."""


class LLMExecutableNotFoundError(LLMProviderError):
    """The configured local CLI executable is unavailable."""


class LLMTimeoutError(LLMProviderError):
    """The local CLI did not finish within its configured timeout."""


class LLMProvider(ABC):
    @abstractmethod
    def generate(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> str:
        """Return the provider's final text response."""

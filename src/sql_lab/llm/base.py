"""LLM provider contract and provider-level failures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class LLMProviderError(RuntimeError):
    """An LLM provider could not return a usable response."""


class LLMExecutableNotFoundError(LLMProviderError):
    """The configured local CLI executable is unavailable."""


class LLMTimeoutError(LLMProviderError):
    """The local CLI did not finish within its configured timeout."""


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class LLMGeneration:
    """Provider output plus non-sensitive execution telemetry."""

    text: str
    provider: str
    cli: str | None = None
    cli_version: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    configuration_source: str | None = None
    usage: LLMUsage = LLMUsage()


class LLMProvider(ABC):
    @abstractmethod
    def generate(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> str:
        """Return the provider's final text response."""

    def generate_with_metadata(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> LLMGeneration:
        """Return output with telemetry when the provider exposes it."""

        return LLMGeneration(
            text=self.generate(prompt, output_schema=output_schema),
            provider=type(self).__name__,
        )

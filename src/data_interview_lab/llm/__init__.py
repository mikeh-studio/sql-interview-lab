"""Replaceable LLM content providers."""

from data_interview_lab.config import Settings
from data_interview_lab.llm.base import LLMProvider, LLMProviderError
from data_interview_lab.llm.claude_cli import ClaudeCLIProvider
from data_interview_lab.llm.codex_cli import (
    CodexCLIProvider,
    codex_command_with_overrides,
)


def create_provider(
    name: str,
    settings: Settings,
    *,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> LLMProvider:
    normalized = name.casefold()
    if normalized == "codex":
        return CodexCLIProvider(
            codex_command_with_overrides(
                settings.codex_command,
                model=model,
                reasoning_effort=reasoning_effort,
            ),
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if normalized == "claude":
        if model or reasoning_effort:
            raise LLMProviderError(
                "Interview model overrides are currently supported for Codex CLI only."
            )
        return ClaudeCLIProvider(
            settings.claude_command,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if normalized == "openai-api":
        raise LLMProviderError(
            "The API adapter is intentionally deferred to Phase 4; use codex or claude."
        )
    raise LLMProviderError(
        f"Unknown LLM provider '{name}'. Supported now: codex, claude."
    )


__all__ = [
    "ClaudeCLIProvider",
    "CodexCLIProvider",
    "LLMProvider",
    "LLMProviderError",
    "create_provider",
]

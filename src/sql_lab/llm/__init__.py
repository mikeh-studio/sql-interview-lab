"""Replaceable LLM content providers."""

from sql_lab.config import Settings
from sql_lab.llm.base import LLMProvider, LLMProviderError
from sql_lab.llm.claude_cli import ClaudeCLIProvider
from sql_lab.llm.codex_cli import CodexCLIProvider


def create_provider(name: str, settings: Settings) -> LLMProvider:
    normalized = name.casefold()
    if normalized == "codex":
        return CodexCLIProvider(
            settings.codex_command,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if normalized == "claude":
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

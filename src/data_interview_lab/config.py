"""Environment-backed configuration for replaceable external providers."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CODEX_COMMAND = (
    "codex",
    "exec",
    "--ephemeral",
    "--sandbox",
    "read-only",
    "--skip-git-repo-check",
    "--color",
    "never",
)

DEFAULT_CLAUDE_COMMAND = (
    "claude",
    "--print",
    "--no-session-persistence",
    "--permission-mode",
    "dontAsk",
    "--tools",
    "",
)

PRIMARY_ENV_PREFIX = "DATA_INTERVIEW_LAB_"
LEGACY_ENV_PREFIX = "SQL_LAB_"


def _environment_value(name: str, default: str | None = None) -> str | None:
    """Read a renamed setting while preserving the legacy SQL Lab variable."""
    configured = os.getenv(name)
    if configured is not None:
        return configured
    legacy_name = name.replace(PRIMARY_ENV_PREFIX, LEGACY_ENV_PREFIX, 1)
    return os.getenv(legacy_name, default)


def default_history_db_path() -> Path:
    configured = _environment_value("DATA_INTERVIEW_LAB_HISTORY_DB")
    if configured:
        return Path(configured).expanduser()
    current_path = Path.home() / ".data-interview-lab" / "history.db"
    legacy_path = Path.home() / ".sql-interview-lab" / "history.db"
    if not current_path.exists() and legacy_path.exists():
        return legacy_path
    return current_path


def history_limit_from_env() -> int:
    limit = int(_environment_value("DATA_INTERVIEW_LAB_HISTORY_LIMIT", "200"))
    if limit < 1:
        raise ValueError("DATA_INTERVIEW_LAB_HISTORY_LIMIT must be positive")
    return limit


def _command_from_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    configured = _environment_value(name)
    if configured is None:
        return default
    command = tuple(shlex.split(configured))
    if not command:
        raise ValueError(f"{name} cannot be empty")
    return command


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_timeout_seconds: float
    advanced_llm_timeout_seconds: float
    codex_command: tuple[str, ...]
    claude_command: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        timeout = float(_environment_value("DATA_INTERVIEW_LAB_LLM_TIMEOUT", "600"))
        if timeout <= 0:
            raise ValueError("DATA_INTERVIEW_LAB_LLM_TIMEOUT must be positive")
        advanced_timeout = float(
            _environment_value("DATA_INTERVIEW_LAB_ADVANCED_LLM_TIMEOUT", "1200")
        )
        if advanced_timeout <= 0:
            raise ValueError("DATA_INTERVIEW_LAB_ADVANCED_LLM_TIMEOUT must be positive")
        return cls(
            llm_provider=_environment_value("DATA_INTERVIEW_LAB_LLM_PROVIDER", "codex"),
            llm_timeout_seconds=timeout,
            advanced_llm_timeout_seconds=advanced_timeout,
            codex_command=_command_from_env(
                "DATA_INTERVIEW_LAB_CODEX_COMMAND", DEFAULT_CODEX_COMMAND
            ),
            claude_command=_command_from_env(
                "DATA_INTERVIEW_LAB_CLAUDE_COMMAND", DEFAULT_CLAUDE_COMMAND
            ),
        )

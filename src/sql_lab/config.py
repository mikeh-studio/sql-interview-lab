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


def default_history_db_path() -> Path:
    configured = os.getenv("SQL_LAB_HISTORY_DB")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sql-interview-lab" / "history.db"


def history_limit_from_env() -> int:
    limit = int(os.getenv("SQL_LAB_HISTORY_LIMIT", "200"))
    if limit < 1:
        raise ValueError("SQL_LAB_HISTORY_LIMIT must be positive")
    return limit


def _command_from_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    configured = os.getenv(name)
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
        timeout = float(os.getenv("SQL_LAB_LLM_TIMEOUT", "600"))
        if timeout <= 0:
            raise ValueError("SQL_LAB_LLM_TIMEOUT must be positive")
        advanced_timeout = float(os.getenv("SQL_LAB_ADVANCED_LLM_TIMEOUT", "1200"))
        if advanced_timeout <= 0:
            raise ValueError("SQL_LAB_ADVANCED_LLM_TIMEOUT must be positive")
        return cls(
            llm_provider=os.getenv("SQL_LAB_LLM_PROVIDER", "codex"),
            llm_timeout_seconds=timeout,
            advanced_llm_timeout_seconds=advanced_timeout,
            codex_command=_command_from_env(
                "SQL_LAB_CODEX_COMMAND", DEFAULT_CODEX_COMMAND
            ),
            claude_command=_command_from_env(
                "SQL_LAB_CLAUDE_COMMAND", DEFAULT_CLAUDE_COMMAND
            ),
        )

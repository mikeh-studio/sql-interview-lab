"""Safe subprocess transport shared by local CLI providers."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sql_lab.llm.base import (
    LLMExecutableNotFoundError,
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
)


@dataclass(frozen=True)
class CLICommandResult:
    stdout: str
    stderr: str


@lru_cache(maxsize=8)
def cli_version(executable: str) -> str | None:
    try:
        completed = subprocess.run(
            [executable, "--version"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = (completed.stdout or completed.stderr).strip()
    return version or None


def run_cli_process(
    command: Sequence[str], prompt: str, *, timeout_seconds: float
) -> CLICommandResult:
    """Run an argv vector with stdin input; never invoke a shell."""

    if not command:
        raise LLMProviderError("LLM CLI command cannot be empty")
    try:
        completed = subprocess.run(
            list(command),
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LLMExecutableNotFoundError(
            f"LLM CLI executable was not found: {command[0]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LLMTimeoutError(
            f"LLM CLI timed out after {timeout_seconds:g} seconds"
        ) from exc
    except OSError as exc:
        raise LLMProviderError(f"Could not start LLM CLI: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "no error output").strip()
        if len(detail) > 4000:
            detail = f"...{detail[-4000:]}"
        raise LLMProviderError(
            f"LLM CLI exited with status {completed.returncode}: {detail}"
        )

    response = completed.stdout.strip()
    if not response:
        raise LLMProviderError("LLM CLI returned an empty response")
    return CLICommandResult(stdout=response, stderr=completed.stderr.strip())


def run_cli_command(
    command: Sequence[str], prompt: str, *, timeout_seconds: float
) -> str:
    return run_cli_process(command, prompt, timeout_seconds=timeout_seconds).stdout


class CommandLLMProvider(LLMProvider):
    """Generic configurable CLI provider, useful for future local tools."""

    def __init__(self, command: Sequence[str], *, timeout_seconds: float = 600) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def generate(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> str:
        # Generic commands receive the schema in the prompt layer. Providers with
        # native schema flags override this method.
        return run_cli_command(
            self.command, prompt, timeout_seconds=self.timeout_seconds
        )

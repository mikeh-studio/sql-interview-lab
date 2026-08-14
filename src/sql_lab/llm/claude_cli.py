"""Structured generation through a locally installed Claude CLI."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sql_lab.config import DEFAULT_CLAUDE_COMMAND
from sql_lab.llm.base import LLMProvider
from sql_lab.llm.command import run_cli_command


class ClaudeCLIProvider(LLMProvider):
    def __init__(
        self,
        command: Sequence[str] = DEFAULT_CLAUDE_COMMAND,
        *,
        timeout_seconds: float = 600,
    ) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def generate(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> str:
        command = list(self.command)
        if output_schema is not None:
            compact_schema = json.dumps(output_schema, separators=(",", ":"))
            command.extend(("--json-schema", compact_schema))
        return run_cli_command(command, prompt, timeout_seconds=self.timeout_seconds)

"""Structured generation through the locally installed Codex CLI."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sql_lab.config import DEFAULT_CODEX_COMMAND
from sql_lab.llm.base import LLMProvider
from sql_lab.llm.command import run_cli_command


class CodexCLIProvider(LLMProvider):
    def __init__(
        self,
        command: Sequence[str] = DEFAULT_CODEX_COMMAND,
        *,
        timeout_seconds: float = 600,
    ) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def generate(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> str:
        command = list(self.command)
        if output_schema is None:
            command.append("-")
            return run_cli_command(
                command, prompt, timeout_seconds=self.timeout_seconds
            )

        with tempfile.TemporaryDirectory(prefix="sql-lab-codex-") as temp_dir:
            schema_path = Path(temp_dir) / "exercise.schema.json"
            schema_path.write_text(json.dumps(output_schema), encoding="utf-8")
            command.extend(("--output-schema", str(schema_path), "-"))
            return run_cli_command(
                command, prompt, timeout_seconds=self.timeout_seconds
            )

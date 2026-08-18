"""Structured generation through the locally installed Codex CLI."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_interview_lab.config import DEFAULT_CODEX_COMMAND
from data_interview_lab.llm.base import (
    LLMGeneration,
    LLMProvider,
    LLMProviderError,
    LLMUsage,
)
from data_interview_lab.llm.command import cli_version, run_cli_command, run_cli_process


@dataclass(frozen=True)
class CodexConfiguration:
    model: str | None
    reasoning_effort: str | None
    source: str


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _config_value(raw: str) -> object:
    try:
        return tomllib.loads(f"value = {raw}")["value"]
    except tomllib.TOMLDecodeError:
        return raw


def _read_config(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def resolve_codex_configuration(command: Sequence[str]) -> CodexConfiguration:
    """Resolve the non-sensitive model settings visible to a Codex CLI command."""

    profile: str | None = None
    command_model: str | None = None
    command_effort: str | None = None
    for index, value in enumerate(command):
        if value in {"-m", "--model"} and index + 1 < len(command):
            command_model = command[index + 1]
        elif value.startswith("--model="):
            command_model = value.partition("=")[2]
        if value in {"-p", "--profile"} and index + 1 < len(command):
            profile = command[index + 1]
        elif value.startswith("--profile="):
            profile = value.partition("=")[2]
        if value in {"-c", "--config"} and index + 1 < len(command):
            key, separator, raw = command[index + 1].partition("=")
        elif value.startswith("--config="):
            key, separator, raw = value.partition("=")[2].partition("=")
        else:
            continue
        if not separator:
            continue
        parsed = _string(_config_value(raw))
        if key == "model":
            command_model = parsed
        elif key == "model_reasoning_effort":
            command_effort = parsed

    config_root = Path(os.getenv("CODEX_HOME", Path.home() / ".codex"))
    config = _read_config(config_root / "config.toml")
    configured_model = _string(config.get("model"))
    configured_effort = _string(config.get("model_reasoning_effort"))
    source = "user_config" if configured_model or configured_effort else "cli_default"
    profiles = config.get("profiles")
    if profile and isinstance(profiles, dict):
        profile_config = profiles.get(profile)
        if isinstance(profile_config, dict):
            configured_model = _string(profile_config.get("model")) or configured_model
            configured_effort = (
                _string(profile_config.get("model_reasoning_effort"))
                or configured_effort
            )
            source = "profile"
    if profile:
        profile_config = _read_config(config_root / f"{profile}.config.toml")
        if profile_config:
            configured_model = _string(profile_config.get("model")) or configured_model
            configured_effort = (
                _string(profile_config.get("model_reasoning_effort"))
                or configured_effort
            )
            source = "profile"
    if command_model or command_effort:
        configured_model = command_model or configured_model
        configured_effort = command_effort or configured_effort
        source = "command_override"
    return CodexConfiguration(configured_model, configured_effort, source)


def _configured_model(command: Sequence[str]) -> str | None:
    return resolve_codex_configuration(command).model


def codex_command_with_overrides(
    command: Sequence[str],
    *,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> tuple[str, ...]:
    """Apply request-scoped overrides as distinct argv values, without a shell."""

    resolved = list(command)
    if model:
        resolved.extend(("--model", model))
    if reasoning_effort:
        resolved.extend(("-c", f"model_reasoning_effort={reasoning_effort}"))
    return tuple(resolved)


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _codex_metadata(jsonl: str, command: Sequence[str]) -> tuple[str | None, LLMUsage]:
    model = _configured_model(command)
    usage: dict[str, int | None] = {}
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_model = event.get("model") or event.get("model_name")
        if isinstance(event_model, str) and event_model:
            model = event_model
        event_usage = event.get("usage")
        if not isinstance(event_usage, dict):
            continue
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            parsed = _integer(event_usage.get(key))
            if parsed is not None:
                usage[key] = parsed
        if usage.get("reasoning_tokens") is None:
            parsed_reasoning = _integer(event_usage.get("reasoning_output_tokens"))
            if parsed_reasoning is not None:
                usage["reasoning_tokens"] = parsed_reasoning
    if usage.get("total_tokens") is None:
        counted = [
            usage.get("input_tokens"),
            usage.get("output_tokens"),
        ]
        if all(value is not None for value in counted):
            usage["total_tokens"] = sum(value for value in counted if value is not None)
    return model, LLMUsage(**usage)


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
        with tempfile.TemporaryDirectory(
            prefix="data-interview-lab-codex-"
        ) as temp_dir:
            schema_path = Path(temp_dir) / "exercise.schema.json"
            schema_path.write_text(json.dumps(output_schema), encoding="utf-8")
            command.extend(("--output-schema", str(schema_path), "-"))
            return run_cli_command(
                command, prompt, timeout_seconds=self.timeout_seconds
            )

    def generate_with_metadata(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> LLMGeneration:
        with tempfile.TemporaryDirectory(
            prefix="data-interview-lab-codex-"
        ) as temp_dir:
            temp_path = Path(temp_dir)
            output_path = temp_path / "last-message.json"
            command = list(self.command)
            if "--json" not in command:
                command.append("--json")
            command.extend(("--output-last-message", str(output_path)))
            if output_schema is not None:
                schema_path = temp_path / "exercise.schema.json"
                schema_path.write_text(json.dumps(output_schema), encoding="utf-8")
                command.extend(("--output-schema", str(schema_path)))
            command.append("-")
            result = run_cli_process(
                command, prompt, timeout_seconds=self.timeout_seconds
            )
            if not output_path.exists():
                raise LLMProviderError("Codex CLI did not write its final response")
            response = output_path.read_text(encoding="utf-8").strip()
            if not response:
                raise LLMProviderError("Codex CLI returned an empty final response")
            model, usage = _codex_metadata(result.stdout, command)
            configuration = resolve_codex_configuration(command)
            return LLMGeneration(
                text=response,
                provider="codex",
                cli=command[0],
                cli_version=cli_version(command[0]),
                model=model,
                reasoning_effort=configuration.reasoning_effort,
                configuration_source=configuration.source,
                usage=usage,
            )

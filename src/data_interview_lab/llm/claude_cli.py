"""Structured generation through a locally installed Claude CLI."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from data_interview_lab.config import DEFAULT_CLAUDE_COMMAND
from data_interview_lab.llm.base import (
    LLMGeneration,
    LLMProvider,
    LLMProviderError,
    LLMUsage,
)
from data_interview_lab.llm.command import cli_version, run_cli_command, run_cli_process


def _option_value(command: Sequence[str], name: str) -> str | None:
    for index, value in enumerate(command):
        if value == name and index + 1 < len(command):
            return command[index + 1]
        if value.startswith(f"{name}="):
            return value.partition("=")[2]
    return None


def _set_option(command: list[str], name: str, value: str) -> None:
    for index, current in enumerate(command):
        if current == name and index + 1 < len(command):
            command[index + 1] = value
            return
        if current.startswith(f"{name}="):
            command[index] = f"{name}={value}"
            return
    command.extend((name, value))


def _integer(*values: object) -> int | None:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _parse_claude_envelope(
    raw: str, command: Sequence[str]
) -> tuple[str, str | None, LLMUsage]:
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMProviderError("Claude CLI returned malformed JSON telemetry") from exc
    if not isinstance(envelope, dict):
        raise LLMProviderError("Claude CLI telemetry response must be one JSON object")
    if envelope.get("is_error") is True:
        detail = envelope.get("result")
        raise LLMProviderError(
            f"Claude CLI reported an error: {detail if isinstance(detail, str) else 'unknown error'}"
        )

    output = envelope.get("structured_output", envelope.get("result"))
    if isinstance(output, dict):
        text = json.dumps(output)
    elif isinstance(output, str):
        text = output
    else:
        raise LLMProviderError("Claude CLI JSON response did not contain a result")

    usage_data = envelope.get("usage")
    usage_data = usage_data if isinstance(usage_data, dict) else {}
    model_usage = envelope.get("modelUsage") or envelope.get("model_usage")
    model_usage = model_usage if isinstance(model_usage, dict) else {}
    models = [key for key in model_usage if isinstance(key, str)]
    model = ", ".join(models) or _option_value(command, "--model")
    input_tokens = _integer(
        usage_data.get("input_tokens"), usage_data.get("inputTokens")
    )
    cached_tokens = _integer(
        usage_data.get("cache_read_input_tokens"),
        usage_data.get("cacheReadInputTokens"),
    )
    output_tokens = _integer(
        usage_data.get("output_tokens"), usage_data.get("outputTokens")
    )
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    return (
        text,
        model,
        LLMUsage(
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        ),
    )


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

    def generate_with_metadata(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> LLMGeneration:
        command = list(self.command)
        if output_schema is not None:
            compact_schema = json.dumps(output_schema, separators=(",", ":"))
            command.extend(("--json-schema", compact_schema))
        _set_option(command, "--output-format", "json")
        result = run_cli_process(command, prompt, timeout_seconds=self.timeout_seconds)
        text, model, usage = _parse_claude_envelope(result.stdout, command)
        return LLMGeneration(
            text=text,
            provider="claude",
            cli=self.command[0] if self.command else None,
            cli_version=cli_version(self.command[0]) if self.command else None,
            model=model,
            usage=usage,
        )

from __future__ import annotations

import json
import sys
from copy import deepcopy
from typing import Any

import pytest

from sql_lab.exercises.static import STATIC_EXERCISE_SET
from sql_lab.generation.generator import ExerciseGenerationError, ExerciseGenerator
from sql_lab.generation.schema import make_strict_output_schema
from sql_lab.llm.base import LLMExecutableNotFoundError, LLMProvider, LLMProviderError
from sql_lab.llm.command import CommandLLMProvider
from sql_lab.models import Dialect, Difficulty, ExerciseRequest


class FakeProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.received_schema: dict[str, Any] | None = None

    def generate(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> str:
        self.received_schema = output_schema
        return self.response


def request() -> ExerciseRequest:
    return ExerciseRequest(
        company="Airbnb-style",
        difficulty=Difficulty.MEDIUM,
        additional_context="Focus on marketplace analytics.",
    )


def test_structured_generation_validates_json_and_request() -> None:
    provider = FakeProvider(json.dumps(STATIC_EXERCISE_SET))

    exercise = ExerciseGenerator(provider).generate(request())

    assert exercise.id == "airbnb_general_001"
    assert len(exercise.questions) == 3
    assert exercise.questions[0].task_summary
    assert exercise.questions[0].requirements
    assert provider.received_schema is not None
    assert provider.received_schema["type"] == "object"
    question_schema = provider.received_schema["$defs"]["ExerciseQuestion"]
    assert "task_summary" in question_schema["required"]
    assert "requirements" in question_schema["required"]


def test_provider_schema_requires_every_object_property() -> None:
    schema = make_strict_output_schema(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "nested": {
                    "type": "object",
                    "properties": {"enabled": {"type": "boolean", "default": True}},
                },
            },
        }
    )

    assert schema["required"] == ["name", "nested"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["nested"]["required"] == ["enabled"]
    assert "default" not in schema["properties"]["nested"]["properties"]["enabled"]


def test_malformed_llm_json_fails_clearly() -> None:
    provider = FakeProvider("```json\n{not valid}\n```")

    with pytest.raises(ExerciseGenerationError, match="malformed JSON"):
        ExerciseGenerator(provider).generate(request())


def test_invalid_generated_exercise_schema_fails_clearly() -> None:
    invalid = deepcopy(STATIC_EXERCISE_SET)
    invalid["tables"] = []
    invalid["unexpected"] = "not allowed"
    provider = FakeProvider(json.dumps(invalid))

    with pytest.raises(ExerciseGenerationError, match="schema validation"):
        ExerciseGenerator(provider).generate(request())


def test_generated_set_must_have_exactly_three_questions() -> None:
    invalid = deepcopy(STATIC_EXERCISE_SET)
    invalid["questions"] = invalid["questions"][:2]
    provider = FakeProvider(json.dumps(invalid))

    with pytest.raises(ExerciseGenerationError, match="schema validation"):
        ExerciseGenerator(provider).generate(request())


def test_generated_set_requires_progressive_disclosure_fields() -> None:
    invalid = deepcopy(STATIC_EXERCISE_SET)
    invalid["business_context"] = "x" * 241
    invalid["questions"][0]["task_summary"] = None
    invalid["questions"][1]["requirements"] = []
    provider = FakeProvider(json.dumps(invalid))

    with pytest.raises(ExerciseGenerationError, match="presentation fields") as error:
        ExerciseGenerator(provider).generate(request())

    message = str(error.value)
    assert "business_context" in message
    assert "missing task_summary" in message
    assert "3 to 6 requirements" in message


def test_generated_dialect_must_match_request() -> None:
    generated = deepcopy(STATIC_EXERCISE_SET)
    generated["dialect"] = "bigquery"
    provider = FakeProvider(json.dumps(generated))

    with pytest.raises(ExerciseGenerationError, match="dialect"):
        ExerciseGenerator(provider).generate(
            request().model_copy(update={"dialect": Dialect.SNOWFLAKE})
        )


def test_cli_subprocess_failure_includes_exit_status() -> None:
    provider = CommandLLMProvider(
        (
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('provider boom'); sys.exit(7)",
        )
    )

    with pytest.raises(LLMProviderError, match="status 7.*provider boom"):
        provider.generate("prompt")


def test_missing_cli_executable_fails_clearly() -> None:
    provider = CommandLLMProvider(("sql-lab-command-that-does-not-exist",))

    with pytest.raises(LLMExecutableNotFoundError, match="not found"):
        provider.generate("prompt")

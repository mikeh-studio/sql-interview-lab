from __future__ import annotations

import json
import sys
from copy import deepcopy
from typing import Any

import pytest

from sql_lab.config import Settings
from sql_lab.exercises import get_static_exercise
from sql_lab.exercises.static import STATIC_EXERCISE_SET
from sql_lab.generation.generator import ExerciseGenerationError, ExerciseGenerator
from sql_lab.generation.schema import make_strict_output_schema
from sql_lab.llm.base import LLMExecutableNotFoundError, LLMProvider, LLMProviderError
from sql_lab.llm.codex_cli import _codex_metadata
from sql_lab.llm.claude_cli import _parse_claude_envelope
from sql_lab.llm.command import CommandLLMProvider
from sql_lab.models import Dialect, Difficulty, ExerciseRequest
from sql_lab.models import ExerciseSet, QuestionType, RoleTrack, SessionMode
from sql_lab.services import generate_exercise_set, validate_exercise_runtime


class FakeProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.received_schema: dict[str, Any] | None = None
        self.last_prompt = ""

    def generate(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> str:
        self.last_prompt = prompt
        self.received_schema = output_schema
        return self.response


def request() -> ExerciseRequest:
    return ExerciseRequest(
        company="Airbnb-style",
        difficulty=Difficulty.MEDIUM,
        additional_context="Focus on marketplace analytics.",
    )


def advanced_payload() -> dict[str, Any]:
    payload = deepcopy(STATIC_EXERCISE_SET)
    payload["mode"] = "advanced"
    payload["role_track"] = "product_analytics"
    types = ("sql_build", "sql_debug", "analytical_case")
    topics = (
        ["cohort_retention", "window_functions"],
        ["sql_debugging", "data_quality", "ai_generated_code_review"],
        ["experimentation", "causal_inference", "metric_design"],
    )
    for index, question in enumerate(payload["questions"]):
        question.update(
            {
                "question_type": types[index],
                "starter_sql": "SELECT * FROM orders" if index == 1 else None,
                "clarifications": [
                    {
                        "candidate_question": "Which population is eligible?",
                        "interviewer_answer": "Use the complete base population.",
                    },
                    {
                        "candidate_question": "How should missing activity be handled?",
                        "interviewer_answer": "Retain it according to the zero-value rule.",
                    },
                ],
                "case_rubric": [],
                "modern_topics": topics[index],
                "reference_discussion": [],
            }
        )
    payload["questions"][2]["case_rubric"] = [
        {
            "criterion": name,
            "strong_signal": "State a concrete, decision-relevant approach.",
            "common_miss": "Jump directly to the final metric.",
        }
        for name in ("Framing", "Metric design", "Data quality", "Recommendation")
    ]
    payload["questions"][2]["reference_discussion"] = [
        "Frame the decision and success criteria.",
        "Validate instrumentation and important segments.",
        "Recommend an action with uncertainty and tradeoffs.",
    ]
    return payload


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
    invalid["questions"][0]["task_summary"] = None
    invalid["questions"][1]["requirements"] = []
    provider = FakeProvider(json.dumps(invalid))

    with pytest.raises(ExerciseGenerationError, match="presentation fields") as error:
        ExerciseGenerator(provider).generate(request())

    message = str(error.value)
    assert "missing task_summary" in message
    assert "3 to 6 requirements" in message


def test_long_business_context_is_compacted_without_rejecting_set() -> None:
    generated = deepcopy(STATIC_EXERCISE_SET)
    generated["business_context"] = (
        "A marketplace analytics team is preparing a quarterly planning review. "
        "The shared dataset represents fictional customer and order activity for interview "
        "practice rather than any proprietary company schema. "
        "This extra sentence intentionally pushes the generated context beyond the display "
        "limit."
    )
    provider = FakeProvider(json.dumps(generated))

    exercise_set = ExerciseGenerator(provider).generate(request())

    assert len(exercise_set.business_context) <= 240
    assert exercise_set.business_context == (
        "A marketplace analytics team is preparing a quarterly planning review. "
        "The shared dataset represents fictional customer and order activity for interview "
        "practice rather than any proprietary company schema."
    )


def test_generated_dialect_must_match_request() -> None:
    generated = deepcopy(STATIC_EXERCISE_SET)
    generated["dialect"] = "bigquery"
    provider = FakeProvider(json.dumps(generated))

    with pytest.raises(ExerciseGenerationError, match="dialect"):
        ExerciseGenerator(provider).generate(
            request().model_copy(update={"dialect": Dialect.SNOWFLAKE})
        )


def test_user_company_label_is_canonical_when_llm_shortens_it() -> None:
    generated = deepcopy(STATIC_EXERCISE_SET)
    generated["company"] = "Anduril"
    provider = FakeProvider(json.dumps(generated))
    anduril_request = request().model_copy(update={"company": "anduril Industries"})

    exercise_set = ExerciseGenerator(provider).generate(anduril_request)

    assert exercise_set.company == "anduril Industries"
    assert all(
        exercise.company == "anduril Industries"
        for exercise in exercise_set.exercises()
    )


def test_advanced_generation_requires_role_track_and_typed_question_mix() -> None:
    payload = advanced_payload()
    provider = FakeProvider(json.dumps(payload))
    advanced_request = request().model_copy(
        update={
            "mode": SessionMode.ADVANCED,
            "role_track": RoleTrack.PRODUCT_ANALYTICS,
        }
    )

    exercise_set = ExerciseGenerator(provider).generate(advanced_request)

    assert exercise_set.mode.value == "advanced"
    assert exercise_set.role_track.value == "product_analytics"
    assert [question.question_type.value for question in exercise_set.questions] == [
        "sql_build",
        "sql_debug",
        "analytical_case",
    ]
    assert len(exercise_set.questions[2].case_rubric) == 4
    assert "separate,\nrole-calibrated mode" in provider.last_prompt
    assert "self-review and coaching only" in provider.last_prompt


def test_advanced_model_allows_review_material_to_be_deferred() -> None:
    payload = advanced_payload()
    payload["questions"][2]["case_rubric"] = []

    exercise_set = ExerciseSet.model_validate(payload)

    assert exercise_set.questions[2].case_rubric == []


def test_advanced_generation_uses_separate_timeout(monkeypatch) -> None:
    captured_timeout = None

    def fake_create_provider(name: str, settings: Settings) -> LLMProvider:
        nonlocal captured_timeout
        assert name == "codex"
        captured_timeout = settings.llm_timeout_seconds
        return FakeProvider(json.dumps(advanced_payload()))

    monkeypatch.setattr("sql_lab.services.create_provider", fake_create_provider)
    settings = Settings(
        llm_provider="codex",
        llm_timeout_seconds=600,
        advanced_llm_timeout_seconds=1200,
        codex_command=("codex",),
        claude_command=("claude",),
    )
    advanced_request = request().model_copy(
        update={
            "mode": SessionMode.ADVANCED,
            "role_track": RoleTrack.PRODUCT_ANALYTICS,
        }
    )

    generate_exercise_set(advanced_request, "codex", settings)

    assert captured_timeout == 1200


def test_sql_debug_starter_must_run_and_fail_at_least_one_dataset() -> None:
    exercise = get_static_exercise()
    flawed = exercise.model_copy(
        update={
            "question_type": QuestionType.SQL_DEBUG,
            "starter_sql": "SELECT segment, COUNT(*) AS total FROM customers GROUP BY segment",
        }
    )
    accidentally_correct = exercise.model_copy(
        update={
            "question_type": QuestionType.SQL_DEBUG,
            "starter_sql": exercise.reference_sql,
        }
    )

    validate_exercise_runtime(flawed)
    with pytest.raises(ExerciseGenerationError, match="unexpectedly passes"):
        validate_exercise_runtime(accidentally_correct)


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


def test_codex_json_events_capture_model_and_token_usage() -> None:
    model, usage = _codex_metadata(
        "\n".join(
            [
                json.dumps({"type": "thread.started", "model": "gpt-5.6-sol"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 120,
                            "cached_input_tokens": 40,
                            "output_tokens": 30,
                            "reasoning_output_tokens": 12,
                        },
                    }
                ),
            ]
        ),
        ("codex", "exec", "--json"),
    )

    assert model == "gpt-5.6-sol"
    assert usage.input_tokens == 120
    assert usage.cached_input_tokens == 40
    assert usage.output_tokens == 30
    assert usage.reasoning_tokens == 12
    assert usage.total_tokens == 150


def test_claude_json_result_captures_structured_output_model_and_usage() -> None:
    text, model, usage = _parse_claude_envelope(
        json.dumps(
            {
                "type": "result",
                "result": "fallback",
                "structured_output": {"question": "validated"},
                "usage": {
                    "input_tokens": 80,
                    "cache_read_input_tokens": 50,
                    "output_tokens": 20,
                },
                "modelUsage": {"claude-sonnet-test": {"costUSD": 0.01}},
            }
        ),
        ("claude", "--print", "--output-format", "json"),
    )

    assert json.loads(text) == {"question": "validated"}
    assert model == "claude-sonnet-test"
    assert usage.input_tokens == 80
    assert usage.cached_input_tokens == 50
    assert usage.output_tokens == 20
    assert usage.total_tokens == 100

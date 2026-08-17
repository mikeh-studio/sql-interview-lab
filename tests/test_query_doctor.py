from __future__ import annotations

import json
from typing import Any

import pytest

from data_interview_lab.exercises import get_static_exercise
from data_interview_lab.feedback import QueryDoctor, QueryDoctorError
from data_interview_lab.llm.base import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt = ""
        self.schema: dict[str, Any] | None = None

    def generate(
        self, prompt: str, *, output_schema: dict[str, Any] | None = None
    ) -> str:
        self.prompt = prompt
        self.schema = output_schema
        return self.response


def feedback_payload() -> dict[str, object]:
    return {
        "summary": "The query executes but filters completed orders too late.",
        "categories": ["filtering mistake"],
        "strengths": ["The output grain matches the requested segment grain."],
        "issues": ["Cancelled orders remain in the revenue calculation."],
        "next_steps": ["Apply the status condition before aggregating revenue."],
    }


def test_query_doctor_uses_structured_cli_feedback_after_database_facts() -> None:
    exercise = get_static_exercise()
    provider = FakeProvider(json.dumps(feedback_payload()))
    execution = {"ok": True, "columns": ["segment"], "row_count": 3}
    grade = {"passed": False, "datasets": [{"label": "Visible test"}]}

    feedback = QueryDoctor(provider).review(
        exercise,
        "SELECT segment FROM customers",
        execution,
        grade,
    )

    assert feedback.categories[0].value == "filtering mistake"
    assert provider.schema is not None
    assert provider.schema["additionalProperties"] is False
    assert "only source of truth" in provider.prompt
    assert exercise.question in provider.prompt
    assert exercise.task_summary in provider.prompt
    assert exercise.requirements[0] in provider.prompt
    assert exercise.reference_sql not in provider.prompt
    assert json.dumps(grade) in provider.prompt


def test_query_doctor_rejects_malformed_or_invalid_json() -> None:
    exercise = get_static_exercise()

    with pytest.raises(QueryDoctorError, match="malformed JSON"):
        QueryDoctor(FakeProvider("```json\n{not json}\n```")).review(
            exercise, "SELECT 1", {"ok": True}, {"passed": False}
        )

    invalid = feedback_payload()
    invalid["unexpected"] = True
    with pytest.raises(QueryDoctorError, match="schema validation"):
        QueryDoctor(FakeProvider(json.dumps(invalid))).review(
            exercise, "SELECT 1", {"ok": True}, {"passed": False}
        )

"""Parse and validate structured LLM output without heuristic extraction."""

from __future__ import annotations

import json

from pydantic import ValidationError

from sql_lab.generation.prompts import build_exercise_prompt
from sql_lab.generation.schema import make_strict_output_schema
from sql_lab.llm.base import LLMProvider
from sql_lab.models import ExerciseRequest, ExerciseSet


class ExerciseGenerationError(RuntimeError):
    """The provider response is not a valid exercise."""


class ExerciseGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def generate(self, request: ExerciseRequest) -> ExerciseSet:
        prompt = build_exercise_prompt(request)
        raw_response = self.provider.generate(
            prompt,
            output_schema=make_strict_output_schema(
                ExerciseSet.model_json_schema(mode="validation")
            ),
        )
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise ExerciseGenerationError(
                f"LLM returned malformed JSON at line {exc.lineno}, column {exc.colno}: "
                f"{exc.msg}"
            ) from exc

        if not isinstance(payload, dict):
            raise ExerciseGenerationError("LLM response must be one JSON object")

        try:
            exercise_set = ExerciseSet.model_validate(payload)
        except ValidationError as exc:
            raise ExerciseGenerationError(
                f"LLM response failed exercise schema validation: {exc}"
            ) from exc

        presentation_errors: list[str] = []
        if len(exercise_set.business_context) > 240:
            presentation_errors.append(
                "business_context must be 240 characters or fewer"
            )
        for index, question in enumerate(exercise_set.questions, start=1):
            if question.task_summary is None:
                presentation_errors.append(f"question {index} is missing task_summary")
            if not 3 <= len(question.requirements) <= 6:
                presentation_errors.append(
                    f"question {index} must have 3 to 6 requirements"
                )
        if presentation_errors:
            raise ExerciseGenerationError(
                "Generated exercise did not honor presentation fields: "
                + "; ".join(presentation_errors)
            )

        mismatches: list[str] = []
        if exercise_set.company.casefold() != request.company.casefold():
            mismatches.append("company")
        if exercise_set.dialect != request.dialect:
            mismatches.append("dialect")
        if any(
            question.difficulty != request.difficulty
            for question in exercise_set.questions
        ):
            mismatches.append("difficulty")
        if mismatches:
            raise ExerciseGenerationError(
                "Generated exercise did not honor request fields: "
                + ", ".join(mismatches)
            )
        return exercise_set

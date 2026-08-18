"""Parse and validate structured LLM output without heuristic extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TypeVar

from pydantic import ValidationError

from data_interview_lab.generation.prompts import (
    build_advanced_foundation_prompt,
    build_advanced_question_prompt,
    build_exercise_prompt,
)
from data_interview_lab.generation.schema import make_strict_output_schema
from data_interview_lab.llm.base import LLMGeneration, LLMProvider
from data_interview_lab.models import (
    AdvancedFoundation,
    AdvancedQuestionOutput,
    ExerciseQuestion,
    ExerciseRequest,
    ExerciseSet,
    QuestionType,
    SessionMode,
    SharedExerciseDataset,
    StrictModel,
)


class ExerciseGenerationError(RuntimeError):
    """The provider response is not a valid exercise."""


GeneratedModel = TypeVar("GeneratedModel", bound=StrictModel)


@dataclass(frozen=True)
class GeneratedPart:
    value: StrictModel
    telemetry: LLMGeneration


def _parse_model(raw_response: str, model: type[GeneratedModel]) -> GeneratedModel:
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
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ExerciseGenerationError(
            f"LLM response failed exercise schema validation: {exc}"
        ) from exc


def _compact_business_context(value: str, limit: int = 240) -> str:
    """Keep generated context concise without rejecting an otherwise valid set."""

    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized

    last_sentence_end = 0
    for match in re.finditer(r"[.!?](?:\s|$)", normalized):
        sentence_end = match.start() + 1
        if sentence_end > limit:
            break
        last_sentence_end = sentence_end
    if last_sentence_end:
        return normalized[:last_sentence_end]

    shortened = normalized[: limit - 1].rstrip()
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return f"{shortened}…"


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
        return self._validate_set_response(raw_response, request)

    def generate_with_telemetry(
        self, request: ExerciseRequest
    ) -> tuple[ExerciseSet, LLMGeneration]:
        prompt = build_exercise_prompt(request)
        telemetry = self.provider.generate_with_metadata(
            prompt,
            output_schema=make_strict_output_schema(
                ExerciseSet.model_json_schema(mode="validation")
            ),
        )
        return self._validate_set_response(telemetry.text, request), telemetry

    @staticmethod
    def _validate_set_response(
        raw_response: str, request: ExerciseRequest
    ) -> ExerciseSet:
        exercise_set = _parse_model(raw_response, ExerciseSet)

        exercise_set = exercise_set.model_copy(
            update={
                # The user's label is request-owned metadata. LLMs commonly shorten or
                # decorate company names even when prompted to copy them exactly.
                "company": request.company,
                "business_context": _compact_business_context(
                    exercise_set.business_context
                ),
            }
        )

        presentation_errors: list[str] = []
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
        if exercise_set.dialect != request.dialect:
            mismatches.append("dialect")
        if exercise_set.mode != request.mode:
            mismatches.append("mode")
        if exercise_set.role_track != request.role_track:
            mismatches.append("role_track")
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
        if request.mode is SessionMode.ADVANCED:
            for index, question in enumerate(exercise_set.questions, start=1):
                if len(question.clarifications) < 2:
                    raise ExerciseGenerationError(
                        f"advanced question {index} must include at least two clarifications"
                    )
        return exercise_set

    def generate_advanced_foundation(
        self, request: ExerciseRequest
    ) -> tuple[SharedExerciseDataset, ExerciseQuestion, LLMGeneration]:
        prompt = build_advanced_foundation_prompt(request)
        telemetry = self.provider.generate_with_metadata(
            prompt,
            output_schema=make_strict_output_schema(
                AdvancedFoundation.model_json_schema(mode="validation")
            ),
        )
        foundation = _parse_model(telemetry.text, AdvancedFoundation)
        dataset = foundation.dataset.model_copy(
            update={
                "company": request.company,
                "dialect": request.dialect,
                "mode": SessionMode.ADVANCED,
                "role_track": request.role_track,
                "business_context": _compact_business_context(
                    foundation.dataset.business_context
                ),
            }
        )
        self._validate_advanced_question(
            foundation.question, request, QuestionType.SQL_BUILD
        )
        return dataset, foundation.question, telemetry

    def generate_advanced_question(
        self,
        request: ExerciseRequest,
        dataset: SharedExerciseDataset,
        question_type: QuestionType,
    ) -> tuple[ExerciseQuestion, LLMGeneration]:
        prompt = build_advanced_question_prompt(request, dataset, question_type)
        telemetry = self.provider.generate_with_metadata(
            prompt,
            output_schema=make_strict_output_schema(
                AdvancedQuestionOutput.model_json_schema(mode="validation")
            ),
        )
        output = _parse_model(telemetry.text, AdvancedQuestionOutput)
        self._validate_advanced_question(output.question, request, question_type)
        return output.question, telemetry

    @staticmethod
    def _validate_advanced_question(
        question: ExerciseQuestion,
        request: ExerciseRequest,
        expected_type: QuestionType,
    ) -> None:
        errors: list[str] = []
        if question.question_type is not expected_type:
            errors.append(f"question_type must be {expected_type.value}")
        if question.difficulty is not request.difficulty:
            errors.append("difficulty")
        if question.task_summary is None:
            errors.append("task_summary")
        if not 3 <= len(question.requirements) <= 6:
            errors.append("3 to 6 requirements")
        if len(question.clarifications) < 2:
            errors.append("at least two clarifications")
        if not question.modern_topics:
            errors.append("modern_topics")
        if expected_type is QuestionType.SQL_DEBUG and not question.starter_sql:
            errors.append("starter_sql")
        if errors:
            raise ExerciseGenerationError(
                "Generated advanced question did not honor request fields: "
                + ", ".join(errors)
            )

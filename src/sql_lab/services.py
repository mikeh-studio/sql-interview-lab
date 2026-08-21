"""Application services shared by the terminal and browser interfaces."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace

from sql_lab.config import Settings
from sql_lab.engines.factory import create_engine
from sql_lab.generation import ExerciseGenerationError, ExerciseGenerator
from sql_lab.grading.compare import compare_results
from sql_lab.llm import create_provider
from sql_lab.llm.base import LLMGeneration
from sql_lab.models import (
    Exercise,
    ExerciseRequest,
    ExerciseSet,
    QuestionType,
    SessionMode,
    SharedExerciseDataset,
)


GenerationEventCallback = Callable[[str, str, dict[str, object]], None]
FirstQuestionCallback = Callable[[SharedExerciseDataset, object, LLMGeneration], None]


def _create_generation_provider(
    provider_name: str, settings: Settings, request: ExerciseRequest
):
    if request.model_override or request.reasoning_effort_override:
        return create_provider(
            provider_name,
            settings,
            model=request.model_override,
            reasoning_effort=request.reasoning_effort_override,
        )
    return create_provider(provider_name, settings)


def validate_exercise_runtime(exercise: Exercise) -> None:
    """Prove that every dataset and the reference query execute before practice."""

    starter_passed_every_dataset = True
    for dataset in exercise.datasets():
        engine = create_engine(exercise.dialect)
        try:
            engine.setup(exercise, dataset)
            result = engine.execute(exercise.reference_sql)
            if not result.rows:
                raise ExerciseGenerationError(
                    f"Reference SQL returned no rows on dataset '{dataset.name}'"
                )
            if (
                exercise.question_type is QuestionType.SQL_DEBUG
                and exercise.starter_sql
            ):
                starter_result = engine.execute(exercise.starter_sql)
                if not compare_results(result, starter_result, exercise.grading).passed:
                    starter_passed_every_dataset = False
        finally:
            engine.close()
    if (
        exercise.question_type is QuestionType.SQL_DEBUG
        and starter_passed_every_dataset
    ):
        raise ExerciseGenerationError(
            "Advanced sql_debug starter_sql unexpectedly passes every grading dataset"
        )


def generate_exercise_set(
    request: ExerciseRequest,
    provider_name: str,
    settings: Settings | None = None,
) -> ExerciseSet:
    """Generate and validate three exercises backed by shared data."""

    resolved_settings = settings or Settings.from_env()
    provider_settings = (
        replace(
            resolved_settings,
            llm_timeout_seconds=resolved_settings.advanced_llm_timeout_seconds,
        )
        if request.mode is SessionMode.ADVANCED
        else resolved_settings
    )
    provider = _create_generation_provider(provider_name, provider_settings, request)
    exercise_set = ExerciseGenerator(provider).generate(request)
    for exercise in exercise_set.exercises():
        validate_exercise_runtime(exercise)
    return exercise_set


def generate_exercise_set_with_telemetry(
    request: ExerciseRequest,
    provider_name: str,
    settings: Settings | None = None,
) -> tuple[ExerciseSet, LLMGeneration]:
    """Generate a full set while retaining provider-reported usage metadata."""

    resolved_settings = settings or Settings.from_env()
    provider_settings = (
        replace(
            resolved_settings,
            llm_timeout_seconds=resolved_settings.advanced_llm_timeout_seconds,
        )
        if request.mode is SessionMode.ADVANCED
        else resolved_settings
    )
    provider = _create_generation_provider(provider_name, provider_settings, request)
    exercise_set, telemetry = ExerciseGenerator(provider).generate_with_telemetry(
        request
    )
    for exercise in exercise_set.exercises():
        validate_exercise_runtime(exercise)
    return exercise_set, telemetry


def generate_exercise(
    request: ExerciseRequest,
    provider_name: str,
    settings: Settings | None = None,
) -> Exercise:
    """Backward-compatible single exercise entry point for the terminal UI."""

    return generate_exercise_set(request, provider_name, settings).exercises()[0]


def generate_advanced_progressively(
    request: ExerciseRequest,
    provider_name: str,
    *,
    cached_dataset: SharedExerciseDataset | None = None,
    on_event: GenerationEventCallback | None = None,
    on_first_question: FirstQuestionCallback | None = None,
    settings: Settings | None = None,
) -> tuple[ExerciseSet, list[LLMGeneration]]:
    """Make question one usable, then build questions two and three in parallel."""

    if request.mode is not SessionMode.ADVANCED:
        raise ValueError("progressive generation is only available in Advanced Mode")
    emit = on_event or (lambda _stage, _message, _metadata: None)
    resolved_settings = settings or Settings.from_env()
    provider_settings = replace(
        resolved_settings,
        llm_timeout_seconds=resolved_settings.advanced_llm_timeout_seconds,
    )
    provider = _create_generation_provider(provider_name, provider_settings, request)
    generator = ExerciseGenerator(provider)
    calls: list[LLMGeneration] = []

    if cached_dataset is None:
        emit("dataset", "Generating a compact shared dataset and Question 1.", {})
        dataset, first_question, telemetry = generator.generate_advanced_foundation(
            request
        )
    else:
        dataset = cached_dataset.model_copy(
            update={
                "company": request.company,
                "dialect": request.dialect,
                "role_track": request.role_track,
            }
        )
        emit("cache", "Reusing the matching local dataset.", {"cache_hit": True})
        emit("question_1", "Generating Question 1 against the cached data.", {})
        first_question, telemetry = generator.generate_advanced_question(
            request, dataset, QuestionType.SQL_BUILD
        )
    calls.append(telemetry)
    emit("validate_1", "Validating Question 1 in the SQL engine.", {})
    validate_exercise_runtime(dataset.exercise(first_question))
    if on_first_question:
        on_first_question(dataset, first_question, telemetry)
    emit("ready_1", "Question 1 is ready. Questions 2 and 3 are continuing.", {})

    question_types = (QuestionType.SQL_DEBUG, QuestionType.ANALYTICAL_CASE)
    generated: dict[QuestionType, object] = {}
    emit("questions_2_3", "Generating Questions 2 and 3 in parallel.", {})
    with ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="sql-interview-lab-question"
    ) as pool:
        futures = {
            pool.submit(
                generator.generate_advanced_question,
                request,
                dataset,
                question_type,
            ): question_type
            for question_type in question_types
        }
        for future in as_completed(futures):
            question_type = futures[future]
            question, call = future.result()
            calls.append(call)
            emit(
                f"validate_{2 if question_type is QuestionType.SQL_DEBUG else 3}",
                f"Validating {question_type.value.replace('_', ' ')} in the SQL engine.",
                {},
            )
            validate_exercise_runtime(dataset.exercise(question))
            generated[question_type] = question

    exercise_set = dataset.with_questions(
        [
            first_question,
            generated[QuestionType.SQL_DEBUG],
            generated[QuestionType.ANALYTICAL_CASE],
        ]
    )
    emit("complete", "All three questions passed deterministic validation.", {})
    return exercise_set, calls

"""Application services shared by the terminal and browser interfaces."""

from __future__ import annotations

from sql_lab.config import Settings
from sql_lab.engines.factory import create_engine
from sql_lab.generation import ExerciseGenerationError, ExerciseGenerator
from sql_lab.llm import create_provider
from sql_lab.models import Exercise, ExerciseRequest, ExerciseSet


def validate_exercise_runtime(exercise: Exercise) -> None:
    """Prove that every dataset and the reference query execute before practice."""

    for dataset in exercise.datasets():
        engine = create_engine(exercise.dialect)
        try:
            engine.setup(exercise, dataset)
            result = engine.execute(exercise.reference_sql)
            if not result.rows:
                raise ExerciseGenerationError(
                    f"Reference SQL returned no rows on dataset '{dataset.name}'"
                )
        finally:
            engine.close()


def generate_exercise_set(
    request: ExerciseRequest,
    provider_name: str,
    settings: Settings | None = None,
) -> ExerciseSet:
    """Generate and validate three exercises backed by shared data."""

    resolved_settings = settings or Settings.from_env()
    provider = create_provider(provider_name, resolved_settings)
    exercise_set = ExerciseGenerator(provider).generate(request)
    for exercise in exercise_set.exercises():
        validate_exercise_runtime(exercise)
    return exercise_set


def generate_exercise(
    request: ExerciseRequest,
    provider_name: str,
    settings: Settings | None = None,
) -> Exercise:
    """Backward-compatible single exercise entry point for the terminal UI."""

    return generate_exercise_set(request, provider_name, settings).exercises()[0]

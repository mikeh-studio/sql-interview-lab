"""Execute user and reference SQL independently on every grading dataset."""

from __future__ import annotations

from dataclasses import dataclass
from data_interview_lab.engines.base import SQLEngine, SQLExecutionError
from data_interview_lab.engines.factory import create_engine
from data_interview_lab.grading.compare import ComparisonResult, compare_results
from data_interview_lab.models import DatasetDefinition, Exercise


class ReferenceSolutionError(RuntimeError):
    """The exercise itself cannot produce a trusted expected result."""


@dataclass(frozen=True)
class DatasetGrade:
    dataset_name: str
    hidden: bool
    comparison: ComparisonResult | None = None
    execution_error: str | None = None

    @property
    def passed(self) -> bool:
        return self.execution_error is None and bool(
            self.comparison and self.comparison.passed
        )


@dataclass(frozen=True)
class GradeResult:
    datasets: tuple[DatasetGrade, ...]

    @property
    def passed(self) -> bool:
        return bool(self.datasets) and all(dataset.passed for dataset in self.datasets)


class Grader:
    def _execute(self, exercise: Exercise, dataset: DatasetDefinition, sql: str):
        engine: SQLEngine = create_engine(exercise.dialect)
        try:
            engine.setup(exercise, dataset)
            return engine.execute(sql)
        finally:
            engine.close()

    def grade(self, exercise: Exercise, user_sql: str) -> GradeResult:
        dataset_grades: list[DatasetGrade] = []
        for dataset in exercise.datasets():
            try:
                expected = self._execute(exercise, dataset, exercise.reference_sql)
            except SQLExecutionError as exc:
                raise ReferenceSolutionError(
                    f"Reference SQL failed on dataset '{dataset.name}': {exc}"
                ) from exc

            try:
                actual = self._execute(exercise, dataset, user_sql)
            except SQLExecutionError as exc:
                dataset_grades.append(
                    DatasetGrade(
                        dataset_name=dataset.name,
                        hidden=dataset.hidden,
                        execution_error=str(exc),
                    )
                )
                continue

            dataset_grades.append(
                DatasetGrade(
                    dataset_name=dataset.name,
                    hidden=dataset.hidden,
                    comparison=compare_results(expected, actual, exercise.grading),
                )
            )
        return GradeResult(datasets=tuple(dataset_grades))

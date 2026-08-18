"""Backend-neutral history records and repository contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from data_interview_lab.models import (
    ExerciseRequest,
    ExerciseSet,
    SharedExerciseDataset,
)


@dataclass(frozen=True)
class HistoryQuestionState:
    question_id: str
    question_index: int
    latest_sql: str = ""
    passed: bool | None = None
    hint_count: int = 0
    solution_revealed: bool = False
    submission_count: int = 0


@dataclass(frozen=True)
class HistorySessionSummary:
    id: str
    exercise_set_id: str
    company: str
    dialect: str
    difficulty: str
    provider: str
    started_at: datetime
    last_activity_at: datetime
    completed_at: datetime | None
    questions_passed: int
    question_count: int
    submission_count: int


@dataclass(frozen=True)
class HistorySession:
    summary: HistorySessionSummary
    request: ExerciseRequest
    exercise_set: ExerciseSet
    questions: tuple[HistoryQuestionState, ...]


class HistoryRepository(ABC):
    """Persistence interface intentionally portable to a future BigQuery adapter."""

    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def create_session(
        self,
        exercise_set: ExerciseSet,
        request: ExerciseRequest,
        provider: str,
    ) -> HistorySession: ...

    @abstractmethod
    def list_sessions(self, *, limit: int = 200) -> list[HistorySessionSummary]: ...

    @abstractmethod
    def get_session(self, session_id: str) -> HistorySession | None: ...

    @abstractmethod
    def record_submission(
        self,
        session_id: str,
        question_id: str,
        user_sql: str,
        passed: bool,
        grading_summary: dict[str, Any],
    ) -> str: ...

    @abstractmethod
    def record_hint(
        self, session_id: str, question_id: str, hint_count: int
    ) -> None: ...

    @abstractmethod
    def record_solution_reveal(self, session_id: str, question_id: str) -> None: ...

    @abstractmethod
    def delete_session(self, session_id: str) -> bool: ...

    @abstractmethod
    def clear(self) -> int: ...

    @abstractmethod
    def storage_bytes(self) -> int: ...

    def start_generation(self, generation_id: str, fields: dict[str, Any]) -> None:
        """Persist non-sensitive generation metadata when supported."""

    def record_generation_event(
        self, generation_id: str, sequence: int, fields: dict[str, Any]
    ) -> None:
        """Append one user-visible stage event when supported."""

    def finish_generation(self, generation_id: str, fields: dict[str, Any]) -> None:
        """Record status and aggregated usage when supported."""

    def get_cached_dataset(self, cache_key: str) -> SharedExerciseDataset | None:
        return None

    def put_cached_dataset(
        self, cache_key: str, dataset: SharedExerciseDataset
    ) -> None:
        """Store a local shared dataset when supported."""

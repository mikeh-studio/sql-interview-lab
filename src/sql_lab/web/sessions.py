"""In-memory single-user lab sessions backed by isolated DuckDB databases."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from uuid import uuid4

from sql_lab.engines.base import QueryResult
from sql_lab.engines.base import SQLEngine
from sql_lab.engines.factory import create_engine
from sql_lab.grading.grader import GradeResult, Grader
from sql_lab.models import Exercise


class SessionNotFoundError(KeyError):
    """A browser session ID is missing or expired."""


@dataclass
class LabSession:
    exercise: Exercise
    provider_name: str = "codex"
    practice_session_id: str | None = None
    history_question_id: str | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    hint_index: int = 0
    _engine: SQLEngine = field(init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def __post_init__(self) -> None:
        self._engine = create_engine(self.exercise.dialect)
        self._engine.setup(self.exercise)

    def table_previews(self, row_limit: int = 5) -> list[dict[str, object]]:
        previews: list[dict[str, object]] = []
        with self._lock:
            self._engine.setup(self.exercise)
            for table in self.exercise.tables:
                result = self._engine.execute(
                    f'SELECT * FROM "{table.name}" LIMIT {int(row_limit)}'
                )
                previews.append(
                    {
                        "name": table.name,
                        "description": table.description,
                        "ddl": table.ddl.strip(),
                        "preview": {
                            "columns": result.columns,
                            "rows": result.rows,
                            "row_limit": row_limit,
                        },
                    }
                )
        return previews

    def run(self, sql: str) -> QueryResult:
        """Execute against a freshly seeded visible database on every run."""

        with self._lock:
            self._engine.setup(self.exercise)
            return self._engine.execute(sql)

    def grade(self, sql: str) -> GradeResult:
        return Grader().grade(self.exercise, sql)

    def next_hint(self) -> tuple[str | None, int]:
        with self._lock:
            if self.hint_index >= len(self.exercise.hints):
                return None, 0
            hint = self.exercise.hints[self.hint_index]
            self.hint_index += 1
            return hint, len(self.exercise.hints) - self.hint_index

    def reset(self) -> None:
        with self._lock:
            self._engine.setup(self.exercise)

    def close(self) -> None:
        with self._lock:
            self._engine.close()


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, LabSession] = {}
        self._lock = RLock()

    def create(
        self,
        exercise: Exercise,
        *,
        provider_name: str = "codex",
        practice_session_id: str | None = None,
        history_question_id: str | None = None,
        hint_index: int = 0,
    ) -> LabSession:
        session = LabSession(
            exercise=exercise,
            provider_name=provider_name,
            practice_session_id=practice_session_id,
            history_question_id=history_question_id,
            hint_index=hint_index,
        )
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> LabSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    def close_all(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()

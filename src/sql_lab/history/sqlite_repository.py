"""SQLite implementation of the portable practice-history repository."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from sql_lab import __version__
from sql_lab.history.base import (
    HistoryQuestionState,
    HistoryRepository,
    HistorySession,
    HistorySessionSummary,
)
from sql_lab.models import ExerciseRequest, ExerciseSet


SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _required_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


class SQLiteHistoryRepository(HistoryRepository):
    def __init__(self, path: Path, *, max_sessions: int = 200) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self.path = path.expanduser().resolve()
        self.max_sessions = max_sessions

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS history_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS exercise_sets (
                    id TEXT PRIMARY KEY,
                    source_exercise_set_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    company TEXT NOT NULL,
                    dialect TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    app_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS practice_sessions (
                    id TEXT PRIMARY KEY,
                    exercise_set_id TEXT NOT NULL UNIQUE,
                    started_at TEXT NOT NULL,
                    last_activity_at TEXT NOT NULL,
                    completed_at TEXT,
                    provider TEXT NOT NULL,
                    additional_context TEXT NOT NULL,
                    FOREIGN KEY (exercise_set_id) REFERENCES exercise_sets(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS question_states (
                    practice_session_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    question_index INTEGER NOT NULL,
                    latest_sql TEXT NOT NULL DEFAULT '',
                    passed INTEGER,
                    hint_count INTEGER NOT NULL DEFAULT 0,
                    solution_revealed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (practice_session_id, question_id),
                    FOREIGN KEY (practice_session_id) REFERENCES practice_sessions(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY,
                    practice_session_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    user_sql TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    grading_summary_json TEXT NOT NULL,
                    FOREIGN KEY (practice_session_id) REFERENCES practice_sessions(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_activity
                    ON practice_sessions(last_activity_at DESC);
                CREATE INDEX IF NOT EXISTS idx_submissions_session_question
                    ON submissions(practice_session_id, question_id, submitted_at);
                """
            )
            schema_row = connection.execute(
                "SELECT value FROM history_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if schema_row is None:
                connection.execute(
                    "INSERT INTO history_metadata(key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
            elif int(schema_row["value"]) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported history schema version {schema_row['value']}"
                )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def close(self) -> None:
        return None

    def create_session(
        self,
        exercise_set: ExerciseSet,
        request: ExerciseRequest,
        provider: str,
    ) -> HistorySession:
        created_at = _now()
        stored_set_id = uuid4().hex
        session_id = uuid4().hex
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO exercise_sets(
                    id, source_exercise_set_id, created_at, company, dialect,
                    difficulty, schema_version, app_version, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored_set_id,
                    exercise_set.id,
                    _timestamp(created_at),
                    exercise_set.company,
                    exercise_set.dialect.value,
                    request.difficulty.value,
                    SCHEMA_VERSION,
                    __version__,
                    exercise_set.model_dump_json(),
                ),
            )
            connection.execute(
                """
                INSERT INTO practice_sessions(
                    id, exercise_set_id, started_at, last_activity_at,
                    provider, additional_context
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    stored_set_id,
                    _timestamp(created_at),
                    _timestamp(created_at),
                    provider,
                    request.additional_context,
                ),
            )
            connection.executemany(
                """
                INSERT INTO question_states(
                    practice_session_id, question_id, question_index, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (session_id, question.id, index, _timestamp(created_at))
                    for index, question in enumerate(exercise_set.questions)
                ],
            )
            self._prune(connection)
        stored = self.get_session(session_id)
        assert stored is not None
        return stored

    def _prune(self, connection: sqlite3.Connection) -> None:
        stale = connection.execute(
            """
            SELECT id, exercise_set_id
            FROM practice_sessions
            ORDER BY last_activity_at DESC
            LIMIT -1 OFFSET ?
            """,
            (self.max_sessions,),
        ).fetchall()
        for row in stale:
            connection.execute(
                "DELETE FROM practice_sessions WHERE id = ?", (row["id"],)
            )
            connection.execute(
                "DELETE FROM exercise_sets WHERE id = ?", (row["exercise_set_id"],)
            )

    def _summary_from_row(self, row: sqlite3.Row) -> HistorySessionSummary:
        return HistorySessionSummary(
            id=row["id"],
            exercise_set_id=row["source_exercise_set_id"],
            company=row["company"],
            dialect=row["dialect"],
            difficulty=row["difficulty"],
            provider=row["provider"],
            started_at=_required_datetime(row["started_at"]),
            last_activity_at=_required_datetime(row["last_activity_at"]),
            completed_at=_datetime(row["completed_at"]),
            questions_passed=int(row["questions_passed"] or 0),
            question_count=int(row["question_count"] or 0),
            submission_count=int(row["submission_count"] or 0),
        )

    @staticmethod
    def _summary_query() -> str:
        return """
            SELECT ps.id, es.source_exercise_set_id, es.company, es.dialect,
                   es.difficulty, ps.provider, ps.started_at, ps.last_activity_at,
                   ps.completed_at,
                   COUNT(DISTINCT qs.question_id) AS question_count,
                   COUNT(DISTINCT CASE WHEN qs.passed = 1 THEN qs.question_id END)
                       AS questions_passed,
                   COUNT(DISTINCT sub.id) AS submission_count
            FROM practice_sessions ps
            JOIN exercise_sets es ON es.id = ps.exercise_set_id
            JOIN question_states qs ON qs.practice_session_id = ps.id
            LEFT JOIN submissions sub ON sub.practice_session_id = ps.id
        """

    def list_sessions(self, *, limit: int = 200) -> list[HistorySessionSummary]:
        with self._connection() as connection:
            rows = connection.execute(
                self._summary_query()
                + " GROUP BY ps.id ORDER BY ps.last_activity_at DESC LIMIT ?",
                (max(1, min(limit, self.max_sessions)),),
            ).fetchall()
        return [self._summary_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> HistorySession | None:
        with self._connection() as connection:
            summary_row = connection.execute(
                self._summary_query() + " WHERE ps.id = ? GROUP BY ps.id",
                (session_id,),
            ).fetchone()
            if summary_row is None:
                return None
            stored_row = connection.execute(
                """
                SELECT es.payload_json, ps.additional_context
                FROM practice_sessions ps
                JOIN exercise_sets es ON es.id = ps.exercise_set_id
                WHERE ps.id = ?
                """,
                (session_id,),
            ).fetchone()
            question_rows = connection.execute(
                """
                SELECT qs.question_id, qs.question_index, qs.latest_sql, qs.passed,
                       qs.hint_count, qs.solution_revealed, COUNT(sub.id) submission_count
                FROM question_states qs
                LEFT JOIN submissions sub
                  ON sub.practice_session_id = qs.practice_session_id
                 AND sub.question_id = qs.question_id
                WHERE qs.practice_session_id = ?
                GROUP BY qs.practice_session_id, qs.question_id
                ORDER BY qs.question_index
                """,
                (session_id,),
            ).fetchall()
        exercise_set = ExerciseSet.model_validate_json(stored_row["payload_json"])
        summary = self._summary_from_row(summary_row)
        request = ExerciseRequest(
            company=summary.company,
            dialect=summary.dialect,
            difficulty=summary.difficulty,
            additional_context=stored_row["additional_context"],
        )
        questions = tuple(
            HistoryQuestionState(
                question_id=row["question_id"],
                question_index=row["question_index"],
                latest_sql=row["latest_sql"],
                passed=None if row["passed"] is None else bool(row["passed"]),
                hint_count=row["hint_count"],
                solution_revealed=bool(row["solution_revealed"]),
                submission_count=row["submission_count"],
            )
            for row in question_rows
        )
        return HistorySession(summary, request, exercise_set, questions)

    def record_submission(
        self,
        session_id: str,
        question_id: str,
        user_sql: str,
        passed: bool,
        grading_summary: dict[str, Any],
    ) -> str:
        submission_id = uuid4().hex
        submitted_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO submissions(
                    id, practice_session_id, question_id, submitted_at,
                    user_sql, passed, grading_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    session_id,
                    question_id,
                    _timestamp(submitted_at),
                    user_sql,
                    int(passed),
                    json.dumps(
                        grading_summary,
                        separators=(",", ":"),
                        default=_json_default,
                    ),
                ),
            )
            connection.execute(
                """
                UPDATE question_states
                SET latest_sql = ?, passed = ?, updated_at = ?
                WHERE practice_session_id = ? AND question_id = ?
                """,
                (
                    user_sql,
                    int(passed),
                    _timestamp(submitted_at),
                    session_id,
                    question_id,
                ),
            )
            connection.execute(
                "UPDATE practice_sessions SET last_activity_at = ? WHERE id = ?",
                (_timestamp(submitted_at), session_id),
            )
            counts = connection.execute(
                """
                SELECT COUNT(*) question_count,
                       SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) passed_count
                FROM question_states WHERE practice_session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if counts["question_count"] == counts["passed_count"]:
                connection.execute(
                    "UPDATE practice_sessions SET completed_at = COALESCE(completed_at, ?) WHERE id = ?",
                    (_timestamp(submitted_at), session_id),
                )
        return submission_id

    def record_hint(self, session_id: str, question_id: str, hint_count: int) -> None:
        now = _timestamp(_now())
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE question_states SET hint_count = ?, updated_at = ?
                WHERE practice_session_id = ? AND question_id = ?
                """,
                (hint_count, now, session_id, question_id),
            )
            connection.execute(
                "UPDATE practice_sessions SET last_activity_at = ? WHERE id = ?",
                (now, session_id),
            )

    def record_solution_reveal(self, session_id: str, question_id: str) -> None:
        now = _timestamp(_now())
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE question_states SET solution_revealed = 1, updated_at = ?
                WHERE practice_session_id = ? AND question_id = ?
                """,
                (now, session_id, question_id),
            )
            connection.execute(
                "UPDATE practice_sessions SET last_activity_at = ? WHERE id = ?",
                (now, session_id),
            )

    def delete_session(self, session_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT exercise_set_id FROM practice_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "DELETE FROM practice_sessions WHERE id = ?", (session_id,)
            )
            connection.execute(
                "DELETE FROM exercise_sets WHERE id = ?", (row["exercise_set_id"],)
            )
        return True

    def clear(self) -> int:
        with self._connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM practice_sessions"
            ).fetchone()[0]
            connection.execute("DELETE FROM practice_sessions")
            connection.execute("DELETE FROM exercise_sets")
        return int(count)

    def storage_bytes(self) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (
                self.path,
                Path(f"{self.path}-wal"),
                Path(f"{self.path}-shm"),
            )
            if candidate.exists()
        )

from __future__ import annotations

import sqlite3

from sql_lab.exercises import get_static_exercise_set
from sql_lab.history import SQLiteHistoryRepository
from sql_lab.models import Difficulty, ExerciseRequest


def request() -> ExerciseRequest:
    return ExerciseRequest(
        company="Airbnb-style",
        difficulty=Difficulty.MEDIUM,
        additional_context="Focus on marketplace health.",
    )


def test_sqlite_history_persists_and_restores_full_exercise(tmp_path) -> None:
    path = tmp_path / "history.db"
    exercise_set = get_static_exercise_set()
    repository = SQLiteHistoryRepository(path)
    repository.initialize()
    created = repository.create_session(exercise_set, request(), "codex")
    question = created.questions[0]

    repository.record_submission(
        created.summary.id,
        question.question_id,
        "SELECT 1",
        False,
        {"passed": False, "datasets": []},
    )
    repository.record_hint(created.summary.id, question.question_id, 1)
    repository.record_solution_reveal(created.summary.id, question.question_id)

    reopened = SQLiteHistoryRepository(path)
    reopened.initialize()
    restored = reopened.get_session(created.summary.id)

    assert restored is not None
    assert restored.exercise_set == exercise_set
    assert restored.request.additional_context == "Focus on marketplace health."
    assert restored.questions[0].latest_sql == "SELECT 1"
    assert restored.questions[0].passed is False
    assert restored.questions[0].hint_count == 1
    assert restored.questions[0].solution_revealed is True
    assert restored.questions[0].submission_count == 1
    assert path.stat().st_mode & 0o777 == 0o600


def test_history_is_append_only_and_marks_completion(tmp_path) -> None:
    repository = SQLiteHistoryRepository(tmp_path / "history.db")
    repository.initialize()
    created = repository.create_session(get_static_exercise_set(), request(), "codex")

    for question in created.questions:
        repository.record_submission(
            created.summary.id,
            question.question_id,
            f"SELECT '{question.question_id}'",
            True,
            {"passed": True, "datasets": []},
        )
    first_question = created.questions[0]
    repository.record_submission(
        created.summary.id,
        first_question.question_id,
        "SELECT 'alternative'",
        True,
        {"passed": True, "datasets": []},
    )

    restored = repository.get_session(created.summary.id)
    assert restored is not None
    assert restored.summary.questions_passed == 3
    assert restored.summary.submission_count == 4
    assert restored.summary.completed_at is not None
    assert restored.questions[0].submission_count == 2
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 4


def test_history_limit_prunes_oldest_session_and_delete_cascades(tmp_path) -> None:
    repository = SQLiteHistoryRepository(tmp_path / "history.db", max_sessions=2)
    repository.initialize()
    first = repository.create_session(get_static_exercise_set(), request(), "codex")
    repository.create_session(get_static_exercise_set(), request(), "codex")
    newest = repository.create_session(get_static_exercise_set(), request(), "codex")

    assert repository.get_session(first.summary.id) is None
    assert len(repository.list_sessions()) == 2
    assert repository.delete_session(newest.summary.id) is True
    assert repository.delete_session(newest.summary.id) is False

    with sqlite3.connect(repository.path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM exercise_sets").fetchone()[0] == 1
        )


def test_clear_history_returns_deleted_count(tmp_path) -> None:
    repository = SQLiteHistoryRepository(tmp_path / "history.db")
    repository.initialize()
    repository.create_session(get_static_exercise_set(), request(), "codex")
    repository.create_session(get_static_exercise_set(), request(), "codex")

    assert repository.clear() == 2
    assert repository.list_sessions() == []

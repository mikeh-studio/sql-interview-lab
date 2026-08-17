from __future__ import annotations

import json
import sqlite3
from datetime import date

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


def test_history_serializes_temporal_values_in_grading_diffs(tmp_path) -> None:
    repository = SQLiteHistoryRepository(tmp_path / "history.db")
    repository.initialize()
    created = repository.create_session(get_static_exercise_set(), request(), "codex")
    question = created.questions[0]

    repository.record_submission(
        created.summary.id,
        question.question_id,
        "SELECT DATE '2025-01-01'",
        False,
        {
            "passed": False,
            "datasets": [
                {
                    "comparison": {
                        "expected": [date(2025, 1, 1)],
                        "actual": [date(2025, 1, 2)],
                    }
                }
            ],
        },
    )

    with sqlite3.connect(repository.path) as connection:
        payload = json.loads(
            connection.execute(
                "SELECT grading_summary_json FROM submissions"
            ).fetchone()[0]
        )
    comparison = payload["datasets"][0]["comparison"]
    assert comparison["expected"] == ["2025-01-01"]
    assert comparison["actual"] == ["2025-01-02"]


def test_history_restores_legacy_questions_without_disclosure_fields(tmp_path) -> None:
    repository = SQLiteHistoryRepository(tmp_path / "history.db")
    repository.initialize()
    created = repository.create_session(get_static_exercise_set(), request(), "codex")

    with sqlite3.connect(repository.path) as connection:
        row = connection.execute("SELECT payload_json FROM exercise_sets").fetchone()
        payload = json.loads(row[0])
        for question in payload["questions"]:
            question.pop("task_summary")
            question.pop("requirements")
        connection.execute(
            "UPDATE exercise_sets SET payload_json = ?", (json.dumps(payload),)
        )

    restored = repository.get_session(created.summary.id)

    assert restored is not None
    assert restored.exercise_set.questions[0].task_summary is None
    assert restored.exercise_set.questions[0].requirements == []


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

    repository.start_generation(
        "generation-to-clear",
        {
            "company": "Airbnb-style",
            "dialect": "duckdb",
            "difficulty": "medium",
            "mode": "standard",
            "role_track": None,
            "provider": "codex",
            "cache_key": None,
        },
    )

    assert repository.clear() == 2
    assert repository.list_sessions() == []
    with sqlite3.connect(repository.path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM dataset_cache").fetchone()[0] == 0
        )


def test_generation_log_and_dataset_cache_are_persisted(tmp_path) -> None:
    repository = SQLiteHistoryRepository(tmp_path / "history.db")
    repository.initialize()
    dataset_payload = get_static_exercise_set().model_dump(mode="json")
    dataset_payload.update({"mode": "advanced", "role_track": "data_science"})
    dataset_payload.pop("questions")
    from sql_lab.models import SharedExerciseDataset

    dataset = SharedExerciseDataset.model_validate(dataset_payload)
    fields = {
        "company": "Airbnb-style",
        "dialect": "duckdb",
        "difficulty": "medium",
        "mode": "advanced",
        "role_track": "data_science",
        "provider": "codex",
        "cache_key": "cache-1",
    }

    repository.start_generation("generation-1", fields)
    repository.record_generation_event(
        "generation-1",
        1,
        {
            "stage": "dataset",
            "message": "Generating compact data.",
            "elapsed_seconds": 1.25,
            "metadata": {},
        },
    )
    repository.finish_generation(
        "generation-1",
        {
            "status": "complete",
            "cli": "codex",
            "model": "gpt-5.6-sol",
            "prompt_count": 3,
            "input_tokens": 300,
            "output_tokens": 90,
            "total_tokens": 390,
        },
    )
    repository.put_cached_dataset("cache-1", dataset)

    assert repository.get_cached_dataset("cache-1") == dataset
    with sqlite3.connect(repository.path) as connection:
        run = connection.execute(
            "SELECT model, prompt_count, total_tokens FROM generation_runs"
        ).fetchone()
        event = connection.execute(
            "SELECT stage, message FROM generation_events"
        ).fetchone()
    assert run == ("gpt-5.6-sol", 3, 390)
    assert event == ("dataset", "Generating compact data.")


def test_dataset_cache_retains_only_fifty_recent_entries(tmp_path) -> None:
    repository = SQLiteHistoryRepository(tmp_path / "history.db")
    repository.initialize()
    payload = get_static_exercise_set().model_dump(mode="json")
    payload.update({"mode": "advanced", "role_track": "data_science"})
    payload.pop("questions")
    from sql_lab.models import SharedExerciseDataset

    dataset = SharedExerciseDataset.model_validate(payload)
    for index in range(51):
        repository.put_cached_dataset(f"cache-{index:02d}", dataset)

    with sqlite3.connect(repository.path) as connection:
        keys = {
            row[0] for row in connection.execute("SELECT cache_key FROM dataset_cache")
        }
    assert len(keys) == 50
    assert "cache-00" not in keys
    assert "cache-50" in keys

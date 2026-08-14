from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sql_lab.exercises import get_static_exercise_set
from sql_lab.feedback import QueryDoctorError, QueryDoctorFeedback
from sql_lab.history import SQLiteHistoryRepository
from sql_lab.models import ExerciseRequest, ExerciseSet
from sql_lab.web.app import create_app


class RecordingExerciseFactory:
    def __init__(self) -> None:
        self.requests: list[tuple[ExerciseRequest, str, bool]] = []
        self.exercise_sets: list[ExerciseSet] = []

    def __call__(
        self, request: ExerciseRequest, provider: str, demo: bool
    ) -> ExerciseSet:
        self.requests.append((request, provider, demo))
        base_set = get_static_exercise_set()
        exercise_set = base_set.model_copy(
            update={
                "company": request.company,
                "dialect": request.dialect,
                "questions": [
                    question.model_copy(update={"difficulty": request.difficulty})
                    for question in base_set.questions
                ],
            }
        )
        self.exercise_sets.append(exercise_set)
        return exercise_set


class RecordingQueryReviewer:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, exercise, sql, provider, execution, grade):
        self.calls.append((exercise, sql, provider, execution, grade))
        return QueryDoctorFeedback(
            summary="The deterministic evidence and query structure have been reviewed.",
            categories=["filtering mistake"] if not grade["passed"] else [],
            strengths=["The selected columns follow the requested output grain."],
            issues=[] if grade["passed"] else ["The result differs on an edge case."],
            next_steps=[]
            if grade["passed"]
            else ["Inspect filters before aggregation."],
        )


@pytest.fixture
def web_client(tmp_path):
    factory = RecordingExerciseFactory()
    application = create_app(factory, SQLiteHistoryRepository(tmp_path / "history.db"))
    with TestClient(application) as client:
        yield client, factory


def exercise_payload(**overrides):
    payload = {
        "company": "Meta",
        "dialect": "duckdb",
        "difficulty": "medium",
        "additional_context": "Focus on creator retention.",
        "provider": "codex",
        "demo": False,
    }
    payload.update(overrides)
    return payload


def create_session(client: TestClient, **overrides):
    response = client.post("/api/exercises", json=exercise_payload(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


def test_browser_shell_and_company_options_are_served(web_client) -> None:
    client, _ = web_client

    page = client.get("/")
    options = client.get("/api/options")
    app_script = client.get("/assets/app.js")

    assert page.status_code == 200
    assert "Which company are you preparing for?" in page.text
    assert "Additional context" in page.text
    assert "Target role" not in page.text
    assert "SQL dialect" in page.text
    assert "Concepts to practice" not in page.text
    assert "Query Doctor" in page.text
    assert "See More" in page.text
    assert "/assets/app.js?v=0.8.0" in page.text
    assert client.get("/favicon.ico").status_code == 200
    assert options.status_code == 200
    assert [company["name"] for company in options.json()["companies"]] == [
        "Airbnb",
        "Meta",
        "Uber",
        "DoorDash",
        "Netflix",
        "Another company",
    ]
    assert "roles" not in options.json()
    assert "concepts" not in options.json()
    assert [dialect["id"] for dialect in options.json()["dialects"]] == [
        "duckdb",
        "redshift",
        "bigquery",
        "snowflake",
        "databricks",
        "presto",
    ]
    assert options.json()["dialects"][0]["execution_mode"] == "native"
    assert all(
        dialect["execution_mode"] == "emulated"
        for dialect in options.json()["dialects"][1:]
    )
    assert app_script.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert app_script.headers["cache-control"] == "no-store"


def test_custom_company_and_additional_context_are_forwarded(web_client) -> None:
    client, factory = web_client
    missing_company_payload = exercise_payload()
    missing_company_payload.pop("company")

    missing_company = client.post("/api/exercises", json=missing_company_payload)
    created = create_session(
        client,
        company="Acme Health",
        dialect="snowflake",
        additional_context="Use patient engagement scenarios.",
    )

    assert missing_company.status_code == 422
    request, provider, demo = factory.requests[-1]
    assert request.company == "Acme Health"
    assert request.dialect.value == "snowflake"
    assert request.additional_context == "Use patient engagement scenarios."
    assert provider == "codex"
    assert demo is False
    assert created["company"] == "Acme Health"
    assert created["dialect"] == "snowflake"
    assert created["execution_mode"] == "emulated"
    assert len(created["questions"]) == 3
    assert created["history_id"]


def test_public_exercise_has_real_table_samples_but_no_hidden_solution(
    web_client,
) -> None:
    client, _ = web_client

    created = create_session(client)
    serialized = json.dumps(created)

    assert "reference_sql" not in serialized
    assert "seed_sql" not in serialized
    assert "hidden_datasets" not in serialized
    assert len(created["questions"]) == 3
    assert created["questions"][0]["task_summary"] == (
        "Measure completed-order conversion and revenue by customer segment."
    )
    assert len(created["questions"][0]["requirements"]) == 5
    assert len({question["session_id"] for question in created["questions"]}) == 3
    assert len(created["tables"]) == 2
    customers = created["tables"][0]
    assert customers["name"] == "customers"
    assert customers["preview"]["columns"] == [
        "customer_id",
        "segment",
        "signup_date",
    ]
    assert len(customers["preview"]["rows"]) == 5
    assert customers["preview"]["rows"][0] == [
        1,
        "small_business",
        "2024-10-01",
    ]


def test_legacy_questions_receive_progressive_disclosure_fallbacks(tmp_path) -> None:
    payload = get_static_exercise_set().model_dump(mode="json")
    for question in payload["questions"]:
        question.pop("task_summary")
        question.pop("requirements")
    legacy_set = ExerciseSet.model_validate(payload)

    def legacy_factory(*_):
        return legacy_set

    application = create_app(
        legacy_factory, SQLiteHistoryRepository(tmp_path / "history.db")
    )
    with TestClient(application) as client:
        created = create_session(client)

    question = created["questions"][0]
    assert question["task_summary"] == (
        "For every customer segment, report January 2025 completed-order performance."
    )
    assert question["requirements"] == [question["question"]]


def test_run_executes_sql_and_reseeds_visible_data_each_time(web_client) -> None:
    client, _ = web_client
    session_id = create_session(client)["questions"][0]["session_id"]

    first = client.post(
        f"/api/sessions/{session_id}/run",
        json={"sql": "DELETE FROM customers; SELECT COUNT(*) AS total FROM customers;"},
    )
    second = client.post(
        f"/api/sessions/{session_id}/run",
        json={"sql": "SELECT COUNT(*) AS total FROM customers;"},
    )
    syntax_error = client.post(
        f"/api/sessions/{session_id}/run",
        json={"sql": "SELEC not_sql"},
    )

    assert first.json()["rows"] == [[0]]
    assert second.json()["rows"] == [[5]]
    assert syntax_error.status_code == 200
    assert syntax_error.json()["ok"] is False
    assert "syntax" in syntax_error.json()["error"].casefold()


def test_submit_grades_visible_and_hidden_datasets(web_client) -> None:
    client, factory = web_client
    session_id = create_session(client)["questions"][0]["session_id"]
    reference_sql = factory.exercise_sets[-1].exercises()[0].reference_sql

    correct = client.post(
        f"/api/sessions/{session_id}/submit", json={"sql": reference_sql}
    )
    incorrect = client.post(
        f"/api/sessions/{session_id}/submit",
        json={
            "sql": (
                "SELECT segment, COUNT(*) AS customer_count, "
                "0 AS converting_customers, 0.0 AS conversion_rate, "
                "0.0 AS completed_revenue FROM customers GROUP BY segment ORDER BY segment"
            )
        },
    )

    assert correct.status_code == 200
    assert correct.json()["passed"] is True
    assert [dataset["label"] for dataset in correct.json()["datasets"]] == [
        "Visible test",
        "Hidden test 1",
    ]
    assert incorrect.json()["passed"] is False
    assert any(not dataset["passed"] for dataset in incorrect.json()["datasets"])

    history = client.get("/api/history").json()["sessions"]
    assert history[0]["submission_count"] == 2
    assert history[0]["questions_passed"] == 0


def test_query_doctor_executes_and_grades_before_cli_review(tmp_path) -> None:
    factory = RecordingExerciseFactory()
    reviewer = RecordingQueryReviewer()
    application = create_app(
        factory,
        SQLiteHistoryRepository(tmp_path / "history.db"),
        reviewer,
    )
    with TestClient(application) as client:
        created = create_session(client, provider="claude")
        session_id = created["questions"][0]["session_id"]
        reference_sql = factory.exercise_sets[-1].exercises()[0].reference_sql

        response = client.post(
            f"/api/sessions/{session_id}/doctor", json={"sql": reference_sql}
        )
        syntax_error = client.post(
            f"/api/sessions/{session_id}/doctor", json={"sql": "SELEC nope"}
        )

    assert response.status_code == 200
    diagnosis = response.json()
    assert diagnosis["provider"] == "claude"
    assert diagnosis["execution"]["ok"] is True
    assert diagnosis["grade"]["passed"] is True
    assert diagnosis["feedback"]["summary"].startswith("The deterministic evidence")
    assert "reference_sql" not in json.dumps(diagnosis)
    assert reviewer.calls[0][2] == "claude"
    assert reviewer.calls[0][3]["ok"] is True
    assert reviewer.calls[0][4]["passed"] is True
    assert syntax_error.status_code == 200
    assert syntax_error.json()["execution"]["ok"] is False
    assert syntax_error.json()["grade"]["passed"] is False


def test_query_doctor_provider_failure_is_reported(tmp_path) -> None:
    def failing_reviewer(*_):
        raise QueryDoctorError("doctor provider failed")

    application = create_app(
        RecordingExerciseFactory(),
        SQLiteHistoryRepository(tmp_path / "history.db"),
        failing_reviewer,
    )
    with TestClient(application) as client:
        session_id = create_session(client)["questions"][0]["session_id"]
        response = client.post(
            f"/api/sessions/{session_id}/doctor", json={"sql": "SELECT 1"}
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "doctor provider failed"


def test_hints_and_solution_require_explicit_endpoints(web_client) -> None:
    client, factory = web_client
    created = create_session(client)
    session_id = created["questions"][0]["session_id"]
    first_exercise = factory.exercise_sets[-1].exercises()[0]

    hint = client.post(f"/api/sessions/{session_id}/hint")
    solution = client.post(f"/api/sessions/{session_id}/solution")

    assert hint.status_code == 200
    assert hint.json()["hint"] == first_exercise.hints[0]
    assert solution.status_code == 200
    assert solution.json()["reference_sql"] == first_exercise.reference_sql

    stored = client.post(f"/api/history/{created['history_id']}/resume").json()
    assert stored["questions"][0]["hints_revealed"] == 1
    assert stored["questions"][0]["solution_revealed"] is True


def test_bundled_demo_cannot_be_mislabeled_as_another_company(web_client) -> None:
    client, factory = web_client

    response = client.post(
        "/api/exercises", json=exercise_payload(company="Netflix", demo=True)
    )

    assert response.status_code == 400
    assert "Airbnb" in response.json()["detail"]
    assert factory.requests == []


def test_bundled_demo_returns_three_questions_at_selected_difficulty(tmp_path) -> None:
    application = create_app(
        history_repository=SQLiteHistoryRepository(tmp_path / "history.db")
    )
    with TestClient(application) as client:
        response = client.post(
            "/api/exercises",
            json=exercise_payload(
                company="Airbnb",
                difficulty="hard",
                demo=True,
            ),
        )

    assert response.status_code == 200
    assert len(response.json()["questions"]) == 3
    assert {question["difficulty"] for question in response.json()["questions"]} == {
        "hard"
    }


def test_bundled_demo_rejects_emulated_dialect(tmp_path) -> None:
    application = create_app(
        history_repository=SQLiteHistoryRepository(tmp_path / "history.db")
    )
    with TestClient(application) as client:
        response = client.post(
            "/api/exercises",
            json=exercise_payload(company="Airbnb", dialect="bigquery", demo=True),
        )

    assert response.status_code == 400
    assert "DuckDB-native" in response.json()["detail"]


def test_history_can_resume_after_application_restart(tmp_path) -> None:
    path = tmp_path / "history.db"
    factory = RecordingExerciseFactory()
    first_app = create_app(factory, SQLiteHistoryRepository(path))
    with TestClient(first_app) as first_client:
        created = create_session(first_client)
        question_id = created["questions"][0]["session_id"]
        reference = factory.exercise_sets[-1].exercises()[0].reference_sql
        assert (
            first_client.post(
                f"/api/sessions/{question_id}/submit", json={"sql": reference}
            ).json()["passed"]
            is True
        )

    second_app = create_app(factory, SQLiteHistoryRepository(path))
    with TestClient(second_app) as second_client:
        listing = second_client.get("/api/history").json()
        resumed = second_client.post(f"/api/history/{created['history_id']}/resume")

    assert listing["sessions"][0]["questions_passed"] == 1
    assert listing["storage_bytes"] > 0
    assert resumed.status_code == 200
    assert resumed.json()["questions"][0]["passed"] is True
    assert resumed.json()["questions"][0]["latest_sql"] == reference
    assert "reference_sql" not in json.dumps(resumed.json())


def test_history_session_can_be_deleted(web_client) -> None:
    client, _ = web_client
    created = create_session(client)

    deleted = client.delete(f"/api/history/{created['history_id']}")
    missing = client.post(f"/api/history/{created['history_id']}/resume")

    assert deleted.json() == {"deleted": True}
    assert missing.status_code == 404
    assert client.get("/api/history").json()["sessions"] == []


def test_history_can_be_disabled_for_a_question_set(web_client) -> None:
    client, _ = web_client

    created = create_session(client, save_history=False)

    assert created["history_id"] is None
    assert client.get("/api/history").json()["sessions"] == []

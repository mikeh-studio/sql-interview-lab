from __future__ import annotations

import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

from data_interview_lab.config import Settings
from data_interview_lab.exercises import get_static_exercise_set
from data_interview_lab.feedback import QueryDoctorError, QueryDoctorFeedback
from data_interview_lab.history import SQLiteHistoryRepository
from data_interview_lab.llm.base import (
    LLMGeneration,
    LLMProvider,
    LLMTimeoutError,
    LLMUsage,
)
from data_interview_lab.models import ExerciseRequest, ExerciseSet, SessionMode
from data_interview_lab.web.app import create_app


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
        if request.mode is SessionMode.ADVANCED:
            payload = exercise_set.model_dump(mode="json")
            payload["mode"] = "advanced"
            payload["role_track"] = request.role_track.value
            question_types = ("sql_build", "sql_debug", "analytical_case")
            topics = (
                ["cohort_retention", "window_functions"],
                ["sql_debugging", "data_quality", "ai_generated_code_review"],
                ["experimentation", "causal_inference", "metric_design"],
            )
            for index, question in enumerate(payload["questions"]):
                question["question_type"] = question_types[index]
                question["modern_topics"] = topics[index]
                question["clarifications"] = [
                    {
                        "candidate_question": "What population is eligible?",
                        "interviewer_answer": "Use every entity present in the base table.",
                    },
                    {
                        "candidate_question": "How should missing activity be treated?",
                        "interviewer_answer": "Retain it and apply the stated zero-value rule.",
                    },
                ]
                question["starter_sql"] = (
                    "SELECT segment, COUNT(*) FROM orders GROUP BY segment"
                    if index == 1
                    else None
                )
                question["case_rubric"] = []
                question["reference_discussion"] = []
            payload["questions"][2]["case_rubric"] = [
                {
                    "criterion": name,
                    "strong_signal": signal,
                    "common_miss": "Treating the SQL result as the complete decision.",
                }
                for name, signal in (
                    (
                        "Problem framing",
                        "Connect the analysis to the stakeholder decision.",
                    ),
                    ("Metric design", "Define the metric, population, and grain."),
                    ("Data quality", "Check instrumentation and missingness."),
                    (
                        "Recommendation",
                        "State a decision with uncertainty and tradeoffs.",
                    ),
                )
            ]
            payload["questions"][2]["reference_discussion"] = [
                "Define the decision and guardrail metrics before interpreting movement.",
                "Check instrumentation and segment effects before attributing causality.",
                "Recommend an action while naming uncertainty and follow-up evidence.",
            ]
            exercise_set = ExerciseSet.model_validate(payload)
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
    assert "Independent and unofficial." in page.text
    assert "not affiliated with or" in page.text
    assert "endorsed by any company shown" in page.text
    assert "not copied from or claimed to" in page.text
    assert "real company interview questions" in page.text
    assert "Additional context" in page.text
    assert "Focus Area" in page.text
    assert "Target role" not in page.text
    assert "Advanced" in page.text
    assert 'id="generationStatus"' in page.text
    assert 'id="reuseDatasetInput"' in page.text
    assert 'id="loadingEvents"' in page.text
    assert 'id="generationProgress"' in page.text
    assert "SQL dialect" in page.text
    assert "Concepts to practice" not in page.text
    assert "Query Doctor" in page.text
    assert "See More" in page.text
    assert "/assets/app.js?v=0.9.2" in page.text
    assert 'id="modelConfiguration"' in page.text
    assert 'id="modelOverrideInput"' in page.text
    assert 'id="reasoningEffortInput"' in page.text
    assert "Follow Codex CLI settings" in page.text
    assert "Override for this interview" in page.text
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
    assert [role["id"] for role in options.json()["roles"]] == [
        "ai_product_safety",
        "analytics_engineering",
        "data_engineering",
        "data_science",
        "product_analytics",
    ]
    assert [role["name"] for role in options.json()["roles"]] == sorted(
        role["name"] for role in options.json()["roles"]
    )
    assert all(
        company.get("logo_path", "").startswith("/assets/brands/")
        for company in options.json()["companies"]
        if company["id"] != "custom"
    )
    for company in options.json()["companies"]:
        if logo_path := company.get("logo_path"):
            assert client.get(logo_path).status_code == 200
    assert options.json()["modes"] == ["standard", "advanced"]
    assert set(options.json()["codex_configuration"]) == {
        "model",
        "model_is_authoritative",
        "reasoning_effort",
        "reasoning_effort_is_authoritative",
        "source",
    }
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
    assert "roleTrackChoices" in app_script.text
    assert "roleTrackSelect" not in app_script.text
    assert "showGenerationFailure(error.message)" in app_script.text
    assert 'fetchJson("/api/generations"' in app_script.text
    assert "pollGeneration(started.generation_id)" in app_script.text
    assert "updateGenerationControls()" in app_script.text
    assert "consecutivePollFailures >= 4" in app_script.text
    assert "showToast(error.message, true, 12000)" in app_script.text
    assert "model_override: modelOverride || null" in app_script.text
    assert (
        "reasoning_effort_override: reasoningEffortOverride || null" in app_script.text
    )
    assert "project or managed settings may override it" in app_script.text
    assert "ignores base user config" in app_script.text
    assert page.headers["cache-control"] == "no-store"
    assert app_script.headers["cache-control"] == "no-store"


def test_generation_result_is_logged(web_client, caplog) -> None:
    client, _ = web_client

    with caplog.at_level(
        logging.INFO, logger="uvicorn.error.data_interview_lab.generation"
    ):
        created = create_session(client, mode="standard")

    messages = [record.getMessage() for record in caplog.records]
    started = next(message for message in messages if "generation_started" in message)
    succeeded = next(
        message for message in messages if "generation_succeeded" in message
    )
    assert '"mode": "standard"' in started
    assert f'"exercise_set_id": "{created["set_id"]}"' in succeeded
    assert '"question_type": "sql_build"' in succeeded
    assert '"duration_seconds":' in succeeded


def test_model_overrides_are_forwarded_without_changing_cli_defaults(
    web_client,
) -> None:
    client, factory = web_client

    created = create_session(
        client,
        model_override="gpt-future-7",
        reasoning_effort_override="ultra_next",
    )

    request, provider, demo = factory.requests[-1]
    assert created["generation_telemetry"]["requested_model"] == "gpt-future-7"
    assert created["generation_telemetry"]["requested_reasoning_effort"] == "ultra_next"
    assert created["generation_telemetry"]["resolved_model"] == "gpt-future-7"
    assert created["generation_telemetry"]["resolved_reasoning_effort"] == "ultra_next"
    assert (
        created["generation_telemetry"]["configuration_source"] == "interview_override"
    )
    assert request.model_override == "gpt-future-7"
    assert request.reasoning_effort_override == "ultra_next"
    assert provider == "codex"
    assert demo is False


def test_detected_codex_defaults_are_not_reported_as_resolved(
    tmp_path, monkeypatch
) -> None:
    config_root = tmp_path / "codex-home"
    config_root.mkdir()
    (config_root / "config.toml").write_text(
        'model = "gpt-detected"\nmodel_reasoning_effort = "high"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(config_root))
    settings = Settings(
        llm_provider="codex",
        llm_timeout_seconds=600,
        advanced_llm_timeout_seconds=1200,
        codex_command=("codex", "exec"),
        claude_command=("claude",),
    )
    factory = RecordingExerciseFactory()
    application = create_app(
        factory,
        SQLiteHistoryRepository(tmp_path / "history.db"),
        settings=settings,
    )

    with TestClient(application) as client:
        configuration = client.get("/api/options").json()["codex_configuration"]
        created = create_session(client)

    assert configuration == {
        "model": "gpt-detected",
        "reasoning_effort": "high",
        "source": "user_config",
        "model_is_authoritative": False,
        "reasoning_effort_is_authoritative": False,
    }
    telemetry = created["generation_telemetry"]
    assert telemetry["model"] is None
    assert telemetry["resolved_model"] is None
    assert telemetry["reasoning_effort"] is None
    assert telemetry["resolved_reasoning_effort"] is None
    assert telemetry["configuration_source"] == "user_config"


def test_model_overrides_are_rejected_for_non_codex_provider(web_client) -> None:
    client, _ = web_client

    response = client.post(
        "/api/exercises",
        json=exercise_payload(provider="claude", model_override="claude-future"),
    )

    assert response.status_code == 422
    assert "supported for Codex CLI only" in response.json()["detail"]


def test_generation_failure_is_logged(tmp_path, caplog) -> None:
    def timed_out_factory(*_):
        raise LLMTimeoutError("LLM CLI timed out after 1200 seconds")

    application = create_app(
        timed_out_factory, SQLiteHistoryRepository(tmp_path / "history.db")
    )
    with TestClient(application) as client:
        with caplog.at_level(
            logging.WARNING, logger="uvicorn.error.data_interview_lab.generation"
        ):
            response = client.post(
                "/api/exercises",
                json=exercise_payload(mode="advanced", role_track="product_analytics"),
            )

    assert response.status_code == 502
    failed = next(
        record.getMessage()
        for record in caplog.records
        if "generation_failed" in record.getMessage()
    )
    assert '"mode": "advanced"' in failed
    assert '"error_type": "LLMTimeoutError"' in failed
    assert "timed out after 1200 seconds" in failed


def test_advanced_generation_streams_first_question_and_logs_usage(
    tmp_path, monkeypatch
) -> None:
    factory = RecordingExerciseFactory()
    advanced_request = ExerciseRequest(
        company="Meta",
        difficulty="medium",
        additional_context="Focus on creator retention.",
        mode="advanced",
        role_track="product_analytics",
    )
    generated_set = factory(advanced_request, "codex", False)
    shared = generated_set.model_dump(mode="json")
    questions = shared.pop("questions")
    questions[1]["starter_sql"] = (
        "SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY customer_id"
    )

    class StagedProvider(LLMProvider):
        prompts: list[str] = []

        def generate(self, prompt, *, output_schema=None):
            return self.generate_with_metadata(prompt, output_schema=output_schema).text

        def generate_with_metadata(self, prompt, *, output_schema=None):
            self.prompts.append(prompt)
            if "foundation for an advanced" in prompt:
                payload = {"dataset": shared, "question": questions[0]}
            elif "sql_debug question" in prompt:
                payload = {"question": questions[1]}
            elif "analytical_case question" in prompt:
                payload = {"question": questions[2]}
            else:
                payload = {"question": questions[0]}
            return LLMGeneration(
                text=json.dumps(payload),
                provider="codex",
                cli="codex",
                cli_version="codex-cli 0.test",
                model="gpt-test",
                usage=LLMUsage(input_tokens=100, output_tokens=20, total_tokens=120),
            )

    provider = StagedProvider()
    monkeypatch.setattr(
        "data_interview_lab.services.create_provider", lambda *_: provider
    )
    repository = SQLiteHistoryRepository(tmp_path / "history.db")
    application = create_app(history_repository=repository)

    with TestClient(application) as client:
        started = client.post(
            "/api/generations",
            json=exercise_payload(
                mode="advanced",
                role_track="product_analytics",
                reuse_cached_dataset=True,
            ),
        )
        assert started.status_code == 200
        generation_id = started.json()["generation_id"]
        deadline = time.monotonic() + 5
        saw_partial = False
        while time.monotonic() < deadline:
            progress = client.get(f"/api/generations/{generation_id}").json()
            saw_partial = saw_partial or progress["partial_result"] is not None
            if progress["status"] != "running":
                break
            time.sleep(0.01)

        assert progress["status"] == "complete", progress
        assert saw_partial
        assert len(progress["result"]["questions"]) == 3
        assert progress["telemetry"]["model"] == "gpt-test"
        assert progress["telemetry"]["prompt_count"] == 3
        assert progress["telemetry"]["total_tokens"] == 360
        assert any(event["stage"] == "ready_1" for event in progress["events"])

        second = client.post(
            "/api/generations",
            json=exercise_payload(
                mode="advanced",
                role_track="product_analytics",
                reuse_cached_dataset=True,
            ),
        ).json()
        while time.monotonic() < deadline + 5:
            second_progress = client.get(
                f"/api/generations/{second['generation_id']}"
            ).json()
            if second_progress["status"] != "running":
                break
            time.sleep(0.01)

    assert second_progress["status"] == "complete", second_progress
    assert second_progress["telemetry"]["cache_hit"] is True
    assert any(event["stage"] == "cache" for event in second_progress["events"])
    assert (
        sum("foundation for an advanced" in prompt for prompt in provider.prompts) == 1
    )


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


def test_advanced_mode_is_role_calibrated_and_stages_interviewer_details(
    web_client,
) -> None:
    client, factory = web_client

    created = create_session(
        client,
        mode="advanced",
        role_track="ai_product_safety",
    )

    request, _, _ = factory.requests[-1]
    assert request.mode.value == "advanced"
    assert request.role_track.value == "ai_product_safety"
    assert created["mode"] == "advanced"
    assert created["role_track"] == "ai_product_safety"
    assert [question["question_type"] for question in created["questions"]] == [
        "sql_build",
        "sql_debug",
        "analytical_case",
    ]
    assert all(question["requirements"] == [] for question in created["questions"])
    assert created["questions"][1]["starter_sql"]
    assert "case_rubric" not in json.dumps(created)
    assert "reference_discussion" not in json.dumps(created)

    case_question = created["questions"][2]
    guarded_doctor = client.post(
        f"/api/sessions/{case_question['session_id']}/doctor",
        json={"sql": "SELECT 1"},
    )
    details = client.post(
        f"/api/sessions/{case_question['session_id']}/interviewer-details"
    )
    solution = client.post(f"/api/sessions/{case_question['session_id']}/solution")

    assert guarded_doctor.status_code == 409
    assert details.status_code == 200
    assert len(details.json()["clarifications"]) == 2
    assert details.json()["requirements"]
    assert len(solution.json()["case_rubric"]) == 4
    assert len(solution.json()["reference_discussion"]) == 3


def test_advanced_mode_requires_role_and_demo_remains_standard_only(web_client) -> None:
    client, factory = web_client

    missing_role = client.post("/api/exercises", json=exercise_payload(mode="advanced"))
    advanced_demo = client.post(
        "/api/exercises",
        json=exercise_payload(
            company="Airbnb",
            mode="advanced",
            role_track="product_analytics",
            demo=True,
        ),
    )

    assert missing_role.status_code == 422
    assert "focus area" in missing_role.json()["detail"]
    assert advanced_demo.status_code == 400
    assert "Standard Mode only" in advanced_demo.json()["detail"]
    assert factory.requests == []


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
    assert created["questions"][0]["task_summary"].startswith(
        "A marketplace growth team wants to understand"
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


def test_each_question_exposes_its_own_solution_endpoint(web_client) -> None:
    client, factory = web_client
    created = create_session(client)
    exercises = factory.exercise_sets[-1].exercises()

    responses = [
        client.post(f"/api/sessions/{question['session_id']}/solution")
        for question in created["questions"]
    ]

    assert all(response.status_code == 200 for response in responses)
    assert [response.json()["reference_sql"] for response in responses] == [
        exercise.reference_sql for exercise in exercises
    ]
    assert len({response.json()["reference_sql"] for response in responses}) == 3


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


def test_advanced_history_preserves_mode_role_and_staged_details(tmp_path) -> None:
    path = tmp_path / "advanced-history.db"
    factory = RecordingExerciseFactory()
    first_app = create_app(factory, SQLiteHistoryRepository(path))
    with TestClient(first_app) as first_client:
        created = create_session(
            first_client,
            mode="advanced",
            role_track="data_engineering",
        )

    second_app = create_app(factory, SQLiteHistoryRepository(path))
    with TestClient(second_app) as second_client:
        resumed = second_client.post(f"/api/history/{created['history_id']}/resume")

    assert resumed.status_code == 200
    assert resumed.json()["mode"] == "advanced"
    assert resumed.json()["role_track"] == "data_engineering"
    assert all(
        question["requirements"] == [] for question in resumed.json()["questions"]
    )


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


def test_history_cannot_be_cleared_during_generation(tmp_path) -> None:
    application = create_app(
        RecordingExerciseFactory(),
        SQLiteHistoryRepository(tmp_path / "history.db"),
    )
    with TestClient(application) as client:
        application.state.generation_jobs.create({"company": "Meta"})
        response = client.delete("/api/history")

    assert response.status_code == 409
    assert "generation" in response.json()["detail"]

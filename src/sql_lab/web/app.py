"""FastAPI application for the HackerRank-style local browser experience."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from sql_lab import __version__
from sql_lab.config import default_history_db_path, history_limit_from_env
from sql_lab.engines.base import SQLExecutionError
from sql_lab.engines.factory import SUPPORTED_DIALECTS, execution_mode
from sql_lab.exercises import get_static_exercise_set
from sql_lab.feedback import QueryDoctorError, QueryDoctorFeedback, review_query
from sql_lab.generation import ExerciseGenerationError
from sql_lab.grading.grader import GradeResult, ReferenceSolutionError
from sql_lab.history import (
    HistoryQuestionState,
    HistoryRepository,
    HistorySessionSummary,
    SQLiteHistoryRepository,
)
from sql_lab.llm import LLMProviderError
from sql_lab.models import Dialect, Difficulty, Exercise, ExerciseRequest, ExerciseSet
from sql_lab.services import generate_exercise_set
from sql_lab.web.sessions import LabSession, SessionNotFoundError, SessionStore


STATIC_DIR = Path(__file__).parent / "static"

COMPANIES = (
    {
        "id": "airbnb",
        "name": "Airbnb",
        "monogram": "A",
        "description": "Marketplace, bookings, hosts, listings, and conversion funnels.",
        "accent": "coral",
        "demo_available": True,
    },
    {
        "id": "meta",
        "name": "Meta",
        "monogram": "M",
        "description": "Social graphs, sessions, engagement, messaging, and ads.",
        "accent": "blue",
        "demo_available": False,
    },
    {
        "id": "uber",
        "name": "Uber",
        "monogram": "U",
        "description": "Trips, riders, drivers, dispatch, supply, and marketplace health.",
        "accent": "slate",
        "demo_available": False,
    },
    {
        "id": "doordash",
        "name": "DoorDash",
        "monogram": "D",
        "description": "Orders, merchants, delivery timing, couriers, and retention.",
        "accent": "red",
        "demo_available": False,
    },
    {
        "id": "netflix",
        "name": "Netflix",
        "monogram": "N",
        "description": "Viewing behavior, titles, subscriptions, discovery, and churn.",
        "accent": "rose",
        "demo_available": False,
    },
    {
        "id": "custom",
        "name": "Another company",
        "monogram": "+",
        "description": "Enter any company or organization you want to practice for.",
        "accent": "green",
        "custom": True,
        "demo_available": False,
    },
)

DIALECT_NAMES = {
    Dialect.DUCKDB: "DuckDB",
    Dialect.REDSHIFT: "Amazon Redshift",
    Dialect.BIGQUERY: "BigQuery (GoogleSQL)",
    Dialect.SNOWFLAKE: "Snowflake",
    Dialect.DATABRICKS: "Databricks SQL",
    Dialect.PRESTO: "Presto",
}


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateExercisePayload(APIModel):
    company: str = Field(min_length=1)
    dialect: Dialect = Dialect.DUCKDB
    difficulty: Difficulty = Difficulty.MEDIUM
    additional_context: str = Field(default="", max_length=2000)
    provider: Literal["codex", "claude"] = "codex"
    demo: bool = False
    save_history: bool = True


class SQLPayload(APIModel):
    sql: str = Field(min_length=1)


ExerciseFactory = Callable[[ExerciseRequest, str, bool], ExerciseSet]
QueryReviewer = Callable[
    [Exercise, str, str, dict[str, object], dict[str, object]], QueryDoctorFeedback
]


def _default_exercise_factory(
    request: ExerciseRequest, provider_name: str, demo: bool
) -> ExerciseSet:
    if demo:
        exercise_set = get_static_exercise_set()
        return exercise_set.model_copy(
            update={
                "company": request.company,
                "dialect": request.dialect,
                "questions": [
                    question.model_copy(update={"difficulty": request.difficulty})
                    for question in exercise_set.questions
                ],
            }
        )
    return generate_exercise_set(request, provider_name)


def _default_query_reviewer(
    exercise: Exercise,
    sql: str,
    provider_name: str,
    execution: dict[str, object],
    grade: dict[str, object],
) -> QueryDoctorFeedback:
    return review_query(exercise, sql, provider_name, execution, grade)


def _task_summary(exercise: Exercise) -> str:
    if exercise.task_summary:
        return exercise.task_summary
    first_sentence, separator, _ = exercise.question.partition(".")
    return f"{first_sentence}." if separator else exercise.question


def _requirements(exercise: Exercise) -> list[str]:
    return exercise.requirements or [exercise.question]


def _public_question(
    session: LabSession, state: HistoryQuestionState
) -> dict[str, object]:
    exercise = session.exercise
    return {
        "session_id": session.id,
        "id": exercise.id,
        "difficulty": exercise.difficulty.value,
        "question": exercise.question,
        "task_summary": _task_summary(exercise),
        "requirements": _requirements(exercise),
        "hint_count": len(exercise.hints),
        "hints_revealed": state.hint_count,
        "solution_revealed": state.solution_revealed,
        "latest_sql": state.latest_sql,
        "passed": state.passed,
    }


def _serialize_grade(grade: GradeResult) -> dict[str, object]:
    datasets: list[dict[str, object]] = []
    hidden_index = 0
    for dataset in grade.datasets:
        if dataset.hidden:
            hidden_index += 1
            label = f"Hidden test {hidden_index}"
        else:
            label = "Visible test"
        serialized: dict[str, object] = {
            "label": label,
            "hidden": dataset.hidden,
            "passed": dataset.passed,
        }
        if dataset.execution_error is not None:
            serialized["error"] = dataset.execution_error
        elif dataset.comparison is not None:
            comparison = dataset.comparison
            serialized["comparison"] = {
                "columns_match": comparison.columns_match,
                "expected_columns": comparison.expected_columns,
                "actual_columns": comparison.actual_columns,
                "expected_row_count": comparison.expected_row_count,
                "actual_row_count": comparison.actual_row_count,
                "differing_rows": comparison.differing_rows,
                "examples": [
                    {"expected": example.expected, "actual": example.actual}
                    for example in comparison.examples
                ],
            }
        datasets.append(serialized)
    return {"passed": grade.passed, "datasets": datasets}


def _serialize_history_summary(summary: HistorySessionSummary) -> dict[str, object]:
    return {
        "id": summary.id,
        "exercise_set_id": summary.exercise_set_id,
        "company": summary.company,
        "dialect": summary.dialect,
        "dialect_name": DIALECT_NAMES[Dialect(summary.dialect)],
        "difficulty": summary.difficulty,
        "provider": summary.provider,
        "started_at": summary.started_at.isoformat(),
        "last_activity_at": summary.last_activity_at.isoformat(),
        "completed_at": (
            summary.completed_at.isoformat() if summary.completed_at else None
        ),
        "questions_passed": summary.questions_passed,
        "question_count": summary.question_count,
        "submission_count": summary.submission_count,
    }


def _exercise_response(
    exercise_set: ExerciseSet,
    question_sessions: list[LabSession],
    states: tuple[HistoryQuestionState, ...],
    history_id: str | None,
) -> dict[str, object]:
    return {
        "history_id": history_id,
        "provider": question_sessions[0].provider_name,
        "set_id": exercise_set.id,
        "company": exercise_set.company,
        "dialect": exercise_set.dialect.value,
        "dialect_name": DIALECT_NAMES[exercise_set.dialect],
        "execution_mode": execution_mode(exercise_set.dialect),
        "execution_label": (
            "Native DuckDB"
            if exercise_set.dialect is Dialect.DUCKDB
            else f"{DIALECT_NAMES[exercise_set.dialect]} emulated on DuckDB"
        ),
        "business_context": exercise_set.business_context,
        "tables": question_sessions[0].table_previews(),
        "questions": [
            _public_question(session, state)
            for session, state in zip(question_sessions, states)
        ],
    }


def create_app(
    exercise_factory: ExerciseFactory | None = None,
    history_repository: HistoryRepository | None = None,
    query_reviewer: QueryReviewer | None = None,
) -> FastAPI:
    factory = exercise_factory or _default_exercise_factory
    reviewer = query_reviewer or _default_query_reviewer
    sessions = SessionStore()
    history = history_repository or SQLiteHistoryRepository(
        default_history_db_path(), max_sessions=history_limit_from_env()
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        history.initialize()
        try:
            yield
        finally:
            sessions.close_all()
            history.close()

    application = FastAPI(
        title="SQL Interview Lab",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.sessions = sessions
    application.state.history = history

    @application.middleware("http")
    async def disable_local_asset_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def get_session(session_id: str) -> LabSession:
        try:
            return sessions.get(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Lab session not found"
            ) from exc

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "engine": "duckdb",
            "execution": "native",
            "history": "sqlite",
            "version": __version__,
        }

    @application.get("/api/options")
    def options() -> dict[str, object]:
        return {
            "companies": COMPANIES,
            "dialects": [
                {
                    "id": dialect.value,
                    "name": DIALECT_NAMES[dialect],
                    "execution_mode": execution_mode(dialect),
                    "execution_label": (
                        "Native local execution"
                        if dialect is Dialect.DUCKDB
                        else "Emulated on DuckDB"
                    ),
                }
                for dialect in SUPPORTED_DIALECTS
            ],
            "difficulties": [difficulty.value for difficulty in Difficulty],
            "providers": ("codex", "claude"),
        }

    @application.post("/api/exercises")
    def create_exercise(payload: CreateExercisePayload):
        if payload.dialect not in SUPPORTED_DIALECTS:
            raise HTTPException(
                status_code=400,
                detail=f"{payload.dialect.value} is not available in this lab.",
            )
        if payload.demo and payload.company.casefold() != "airbnb":
            raise HTTPException(
                status_code=400,
                detail="The bundled demo exercise is available for Airbnb only.",
            )
        if payload.demo and payload.dialect is not Dialect.DUCKDB:
            raise HTTPException(
                status_code=400,
                detail="The bundled demo is DuckDB-native. Generate a new set to practice "
                f"{DIALECT_NAMES[payload.dialect]} syntax.",
            )
        request = ExerciseRequest(
            company=payload.company,
            dialect=payload.dialect,
            difficulty=payload.difficulty,
            additional_context=payload.additional_context,
        )
        try:
            exercise_set = factory(request, payload.provider, payload.demo)
            stored = (
                history.create_session(exercise_set, request, payload.provider)
                if payload.save_history
                else None
            )
            states = (
                stored.questions
                if stored
                else tuple(
                    HistoryQuestionState(question.id, index)
                    for index, question in enumerate(exercise_set.questions)
                )
            )
            question_sessions = [
                sessions.create(
                    exercise,
                    provider_name=payload.provider,
                    practice_session_id=stored.summary.id if stored else None,
                    history_question_id=state.question_id,
                    hint_index=state.hint_count,
                )
                for exercise, state in zip(exercise_set.exercises(), states)
            ]
            response = _exercise_response(
                exercise_set,
                question_sessions,
                states,
                stored.summary.id if stored else None,
            )
        except (ExerciseGenerationError, LLMProviderError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except SQLExecutionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return jsonable_encoder(response)

    @application.post("/api/sessions/{session_id}/run")
    def run_sql(session_id: str, payload: SQLPayload):
        session = get_session(session_id)
        try:
            result = session.run(payload.sql)
        except SQLExecutionError as exc:
            return {"ok": False, "error": str(exc)}
        return jsonable_encoder(
            {
                "ok": True,
                "columns": result.columns,
                "rows": result.rows,
                "row_count": len(result.rows),
                "duration_ms": round(result.duration_ms, 2),
            }
        )

    @application.post("/api/sessions/{session_id}/submit")
    def submit_sql(session_id: str, payload: SQLPayload):
        session = get_session(session_id)
        try:
            grade = session.grade(payload.sql)
        except ReferenceSolutionError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        serialized = _serialize_grade(grade)
        if session.practice_session_id and session.history_question_id:
            history.record_submission(
                session.practice_session_id,
                session.history_question_id,
                payload.sql,
                grade.passed,
                serialized,
            )
        return jsonable_encoder(serialized)

    @application.post("/api/sessions/{session_id}/doctor")
    def query_doctor(session_id: str, payload: SQLPayload):
        session = get_session(session_id)
        try:
            result = session.run(payload.sql)
            execution: dict[str, object] = {
                "ok": True,
                "columns": result.columns,
                "row_count": len(result.rows),
                "rows_preview": result.rows[:10],
            }
        except SQLExecutionError as exc:
            execution = {"ok": False, "error": str(exc)}

        try:
            grade = _serialize_grade(session.grade(payload.sql))
            feedback = reviewer(
                session.exercise,
                payload.sql,
                session.provider_name,
                execution,
                grade,
            )
        except ReferenceSolutionError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except (QueryDoctorError, LLMProviderError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return jsonable_encoder(
            {
                "provider": session.provider_name,
                "execution": execution,
                "grade": grade,
                "feedback": feedback,
            }
        )

    @application.post("/api/sessions/{session_id}/hint")
    def reveal_hint(session_id: str):
        session = get_session(session_id)
        hint, remaining = session.next_hint()
        if hint is None:
            raise HTTPException(status_code=404, detail="No more hints are available")
        if session.practice_session_id and session.history_question_id:
            history.record_hint(
                session.practice_session_id,
                session.history_question_id,
                session.hint_index,
            )
        return {"hint": hint, "remaining": remaining}

    @application.post("/api/sessions/{session_id}/solution")
    def reveal_solution(session_id: str):
        session = get_session(session_id)
        if session.practice_session_id and session.history_question_id:
            history.record_solution_reveal(
                session.practice_session_id, session.history_question_id
            )
        return {
            "reference_sql": session.exercise.reference_sql,
            "explanation": session.exercise.explanation,
        }

    @application.post("/api/sessions/{session_id}/reset")
    def reset_session(session_id: str):
        get_session(session_id).reset()
        return {"status": "reset"}

    @application.get("/api/history")
    def list_history():
        return jsonable_encoder(
            {
                "sessions": [
                    _serialize_history_summary(summary)
                    for summary in history.list_sessions()
                ],
                "storage_bytes": history.storage_bytes(),
            }
        )

    @application.post("/api/history/{history_id}/resume")
    def resume_history(history_id: str):
        stored = history.get_session(history_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Saved session not found")
        question_sessions = [
            sessions.create(
                exercise,
                provider_name=stored.summary.provider,
                practice_session_id=stored.summary.id,
                history_question_id=state.question_id,
                hint_index=state.hint_count,
            )
            for exercise, state in zip(
                stored.exercise_set.exercises(), stored.questions
            )
        ]
        return jsonable_encoder(
            _exercise_response(
                stored.exercise_set,
                question_sessions,
                stored.questions,
                stored.summary.id,
            )
        )

    @application.delete("/api/history/{history_id}")
    def delete_history(history_id: str):
        if not history.delete_session(history_id):
            raise HTTPException(status_code=404, detail="Saved session not found")
        return {"deleted": True}

    @application.delete("/api/history")
    def clear_history():
        return {"deleted_count": history.clear()}

    @application.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    application.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
    return application


app = create_app()

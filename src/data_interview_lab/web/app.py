"""FastAPI application for the HackerRank-style local browser experience."""

from __future__ import annotations

import json
import hashlib
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from data_interview_lab import __version__
from data_interview_lab.config import (
    Settings,
    default_history_db_path,
    history_limit_from_env,
)
from data_interview_lab.engines.base import SQLExecutionError
from data_interview_lab.engines.factory import SUPPORTED_DIALECTS, execution_mode
from data_interview_lab.exercises import get_static_exercise_set
from data_interview_lab.feedback import (
    QueryDoctorError,
    QueryDoctorFeedback,
    review_query,
)
from data_interview_lab.generation import ExerciseGenerationError
from data_interview_lab.grading.grader import GradeResult, ReferenceSolutionError
from data_interview_lab.history import (
    HistoryQuestionState,
    HistoryRepository,
    HistorySessionSummary,
    SQLiteHistoryRepository,
)
from data_interview_lab.llm import LLMProviderError
from data_interview_lab.llm.codex_cli import resolve_codex_configuration
from data_interview_lab.models import (
    Dialect,
    Difficulty,
    Exercise,
    ExerciseQuestion,
    ExerciseRequest,
    ExerciseSet,
    RoleTrack,
    SessionMode,
    SharedExerciseDataset,
)
from data_interview_lab.services import (
    generate_advanced_progressively,
    generate_exercise_set,
    generate_exercise_set_with_telemetry,
)
from data_interview_lab.llm.base import LLMGeneration
from data_interview_lab.web.generation_jobs import GenerationJob, GenerationJobStore
from data_interview_lab.web.sessions import (
    LabSession,
    SessionNotFoundError,
    SessionStore,
)


STATIC_DIR = Path(__file__).parent / "static"
GENERATION_LOGGER = logging.getLogger("uvicorn.error.data_interview_lab.generation")

COMPANIES = (
    {
        "id": "airbnb",
        "name": "Airbnb",
        "monogram": "A",
        "logo_path": "/assets/brands/airbnb.svg",
        "description": "Marketplace, bookings, hosts, listings, and conversion funnels.",
        "accent": "coral",
        "demo_available": True,
    },
    {
        "id": "meta",
        "name": "Meta",
        "monogram": "M",
        "logo_path": "/assets/brands/meta.svg",
        "description": "Social graphs, sessions, engagement, messaging, and ads.",
        "accent": "blue",
        "demo_available": False,
    },
    {
        "id": "uber",
        "name": "Uber",
        "monogram": "U",
        "logo_path": "/assets/brands/uber.svg",
        "description": "Trips, riders, drivers, dispatch, supply, and marketplace health.",
        "accent": "slate",
        "demo_available": False,
    },
    {
        "id": "doordash",
        "name": "DoorDash",
        "monogram": "D",
        "logo_path": "/assets/brands/doordash.svg",
        "description": "Orders, merchants, delivery timing, couriers, and retention.",
        "accent": "red",
        "demo_available": False,
    },
    {
        "id": "netflix",
        "name": "Netflix",
        "monogram": "N",
        "logo_path": "/assets/brands/netflix.svg",
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

ROLE_TRACKS = (
    {
        "id": RoleTrack.AI_PRODUCT_SAFETY.value,
        "name": "AI Product & Safety",
        "description": "AI adoption or safety metrics, eval tradeoffs, and instrumentation.",
    },
    {
        "id": RoleTrack.ANALYTICS_ENGINEERING.value,
        "name": "Analytics Engineering",
        "description": "Canonical models, data quality, reusable metrics, and trustworthy outputs.",
    },
    {
        "id": RoleTrack.DATA_ENGINEERING.value,
        "name": "Data Engineering",
        "description": "Data modeling, pipelines, reliability, and query performance.",
    },
    {
        "id": RoleTrack.DATA_SCIENCE.value,
        "name": "Data Science",
        "description": "Metric design, causal reasoning, diagnosis, and recommendations.",
    },
    {
        "id": RoleTrack.PRODUCT_ANALYTICS.value,
        "name": "Product Analytics",
        "description": "Funnels, retention, experiments, metrics, and launch decisions.",
    },
)


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
    mode: SessionMode = SessionMode.STANDARD
    role_track: RoleTrack | None = None
    reuse_cached_dataset: bool = True
    model_override: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    reasoning_effort_override: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
    )


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
    advanced = exercise.mode is SessionMode.ADVANCED
    details_revealed = not advanced or session.details_revealed
    return {
        "session_id": session.id,
        "id": exercise.id,
        "difficulty": exercise.difficulty.value,
        "question": exercise.question,
        "task_summary": _task_summary(exercise),
        "requirements": _requirements(exercise) if details_revealed else [],
        "details_revealed": details_revealed,
        "clarification_count": len(exercise.clarifications),
        "question_type": exercise.question_type.value,
        "starter_sql": exercise.starter_sql,
        "modern_topics": [topic.value for topic in exercise.modern_topics],
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
    exercise_set: ExerciseSet | SharedExerciseDataset,
    question_sessions: list[LabSession],
    states: tuple[HistoryQuestionState, ...],
    history_id: str | None,
) -> dict[str, object]:
    return {
        "history_id": history_id,
        "provider": question_sessions[0].provider_name,
        "set_id": exercise_set.id,
        "mode": exercise_set.mode.value,
        "role_track": (
            exercise_set.role_track.value if exercise_set.role_track else None
        ),
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


def _cache_key(request: ExerciseRequest) -> str:
    identity = {
        "company": request.company.casefold(),
        "dialect": request.dialect.value,
        "difficulty": request.difficulty.value,
        "mode": request.mode.value,
        "role_track": request.role_track.value if request.role_track else None,
        "additional_context": request.additional_context.strip().casefold(),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _telemetry_summary(calls: list[LLMGeneration]) -> dict[str, object]:
    def total(field: str) -> int | None:
        values = [getattr(call.usage, field) for call in calls]
        present = [value for value in values if value is not None]
        return sum(present) if present else None

    models = list(dict.fromkeys(call.model for call in calls if call.model))
    versions = list(
        dict.fromkeys(call.cli_version for call in calls if call.cli_version)
    )
    clis = list(dict.fromkeys(call.cli for call in calls if call.cli))
    reasoning_efforts = list(
        dict.fromkeys(call.reasoning_effort for call in calls if call.reasoning_effort)
    )
    configuration_sources = list(
        dict.fromkeys(
            call.configuration_source for call in calls if call.configuration_source
        )
    )
    resolved_model = ", ".join(models) or (
        "CLI default (not reported)" if calls else None
    )
    resolved_reasoning_effort = ", ".join(reasoning_efforts) or None
    return {
        "provider": calls[0].provider if calls else None,
        "cli": ", ".join(clis) or None,
        "cli_version": ", ".join(versions) or None,
        "model": resolved_model,
        "resolved_model": resolved_model,
        "reasoning_effort": resolved_reasoning_effort,
        "resolved_reasoning_effort": resolved_reasoning_effort,
        "configuration_source": ", ".join(configuration_sources) or None,
        "prompt_count": len(calls),
        "input_tokens": total("input_tokens"),
        "cached_input_tokens": total("cached_input_tokens"),
        "output_tokens": total("output_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "total_tokens": total("total_tokens"),
    }


def _configuration_telemetry(
    payload: CreateExercisePayload, settings: Settings
) -> dict[str, object]:
    requested_model = payload.model_override
    requested_effort = payload.reasoning_effort_override
    if payload.provider != "codex":
        return {
            "provider": payload.provider,
            "requested_model": None,
            "requested_reasoning_effort": None,
            "configuration_source": "cli_settings",
        }
    configured = resolve_codex_configuration(settings.codex_command)
    overridden = bool(requested_model or requested_effort)
    model = requested_model or configured.model
    reasoning_effort = requested_effort or configured.reasoning_effort
    return {
        "provider": "codex",
        "requested_model": requested_model,
        "requested_reasoning_effort": requested_effort,
        "model": model,
        "resolved_model": model,
        "reasoning_effort": reasoning_effort,
        "resolved_reasoning_effort": reasoning_effort,
        "configuration_source": (
            "interview_override" if overridden else configured.source
        ),
    }


def _combined_telemetry(
    payload: CreateExercisePayload,
    settings: Settings,
    calls: list[LLMGeneration],
) -> dict[str, object]:
    summary = _configuration_telemetry(payload, settings)
    observed = _telemetry_summary(calls)
    summary.update({key: value for key, value in observed.items() if value is not None})
    if payload.model_override or payload.reasoning_effort_override:
        summary["configuration_source"] = "interview_override"
    return summary


def _logged_error(exc: Exception) -> str:
    """Keep persisted logs diagnostic without copying provider payload fragments."""

    return str(exc).splitlines()[0][:500]


def _default_case_review(exercise: Exercise) -> tuple[list[dict[str, str]], list[str]]:
    rubric = [
        {
            "criterion": "Problem framing",
            "strong_signal": "Connect the SQL output to the stakeholder decision and define the analysis population.",
            "common_miss": "Jump directly into query mechanics without stating the decision or population.",
        },
        {
            "criterion": "Metric and grain",
            "strong_signal": "State the metric definition, denominator, time grain, and grouping dimensions explicitly.",
            "common_miss": "Mix grains or leave the denominator ambiguous.",
        },
        {
            "criterion": "Data quality and uncertainty",
            "strong_signal": "Call out instrumentation gaps, duplicates, missing values, and limits on causal interpretation.",
            "common_miss": "Treat observed data as complete and automatically causal.",
        },
        {
            "criterion": "Recommendation",
            "strong_signal": "Recommend an action with guardrails, tradeoffs, and a concrete follow-up measurement plan.",
            "common_miss": "Report a metric without explaining what the team should do next.",
        },
    ]
    discussion = [
        f"Frame how the result supports the {exercise.role_track.value.replace('_', ' ') if exercise.role_track else 'analytics'} decision.",
        "Validate the output grain and important imperfect-data cases before interpreting the metric.",
        "Close with a recommendation, uncertainty, guardrails, and the next measurement step.",
    ]
    return rubric, discussion


def create_app(
    exercise_factory: ExerciseFactory | None = None,
    history_repository: HistoryRepository | None = None,
    query_reviewer: QueryReviewer | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    factory = exercise_factory or _default_exercise_factory
    reviewer = query_reviewer or _default_query_reviewer
    resolved_settings = settings or Settings.from_env()
    sessions = SessionStore()
    generation_jobs = GenerationJobStore()
    generation_executor = ThreadPoolExecutor(
        max_workers=3, thread_name_prefix="data-interview-lab-generation"
    )
    history = history_repository or SQLiteHistoryRepository(
        default_history_db_path(), max_sessions=history_limit_from_env()
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        history.initialize()
        try:
            yield
        finally:
            generation_executor.shutdown(wait=False, cancel_futures=True)
            sessions.close_all()
            history.close()

    application = FastAPI(
        title="Data Interview Lab",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.sessions = sessions
    application.state.history = history
    application.state.generation_jobs = generation_jobs

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

    def append_generation_event(
        job: GenerationJob,
        stage: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        event = job.add_event(stage, message, metadata)
        try:
            history.record_generation_event(job.id, int(event["sequence"]), event)
        except Exception:
            GENERATION_LOGGER.exception(
                "generation_event_persistence_failed generation_id=%s", job.id
            )

    def finish_generation_log(generation_id: str, fields: dict[str, object]) -> None:
        try:
            history.finish_generation(generation_id, fields)
        except Exception:
            GENERATION_LOGGER.exception(
                "generation_log_persistence_failed generation_id=%s", generation_id
            )

    def run_progressive_generation(
        job: GenerationJob,
        request: ExerciseRequest,
        payload: CreateExercisePayload,
        cache_key: str,
    ) -> None:
        first_session: LabSession | None = None
        cache_hit = False
        try:
            cached_dataset = (
                history.get_cached_dataset(cache_key)
                if payload.reuse_cached_dataset
                else None
            )
            cache_hit = cached_dataset is not None

            def on_event(stage: str, message: str, metadata: dict[str, object]) -> None:
                append_generation_event(job, stage, message, metadata)

            def on_first_question(
                dataset: SharedExerciseDataset,
                question: ExerciseQuestion,
                call: LLMGeneration,
            ) -> None:
                nonlocal first_session
                if payload.reuse_cached_dataset and not cache_hit:
                    history.put_cached_dataset(cache_key, dataset)
                exercise = dataset.exercise(question)
                first_session = sessions.create(
                    exercise, provider_name=payload.provider
                )
                state = HistoryQuestionState(question.id, 0)
                partial = _exercise_response(dataset, [first_session], (state,), None)
                partial.update(
                    {
                        "generation_id": job.id,
                        "generation_status": "running",
                        "question_count_target": 3,
                    }
                )
                call_telemetry = _combined_telemetry(payload, resolved_settings, [call])
                partial["generation_telemetry"] = call_telemetry
                with job._lock:
                    job.partial_result = partial
                    job.telemetry = call_telemetry

            exercise_set, calls = generate_advanced_progressively(
                request,
                payload.provider,
                cached_dataset=cached_dataset,
                on_event=on_event,
                on_first_question=on_first_question,
                settings=resolved_settings,
            )
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
            assert first_session is not None
            if stored:
                sessions.attach_history(
                    first_session.id, stored.summary.id, states[0].question_id
                )
            remaining_sessions = [
                sessions.create(
                    exercise,
                    provider_name=payload.provider,
                    practice_session_id=stored.summary.id if stored else None,
                    history_question_id=state.question_id,
                    hint_index=state.hint_count,
                )
                for exercise, state in zip(exercise_set.exercises()[1:], states[1:])
            ]
            response = _exercise_response(
                exercise_set,
                [first_session, *remaining_sessions],
                states,
                stored.summary.id if stored else None,
            )
            response.update(
                {
                    "generation_id": job.id,
                    "generation_status": "complete",
                    "question_count_target": 3,
                }
            )
            telemetry = _combined_telemetry(payload, resolved_settings, calls)
            telemetry["cache_hit"] = cache_hit
            response["generation_telemetry"] = telemetry
            with job._lock:
                job.telemetry = telemetry
                job.result = response
                job.status = "complete"
            finish_generation_log(job.id, {"status": "complete", **telemetry})
        except Exception as exc:
            GENERATION_LOGGER.exception(
                "progressive_generation_failed generation_id=%s", job.id
            )
            append_generation_event(job, "failed", f"Generation failed: {exc}", {})
            with job._lock:
                job.status = "failed"
                job.error = str(exc)
            finish_generation_log(
                job.id,
                {
                    "status": "failed",
                    "cache_hit": cache_hit,
                    "error_type": type(exc).__name__,
                    "error": _logged_error(exc),
                    **job.telemetry,
                },
            )

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
        codex_configuration = resolve_codex_configuration(
            resolved_settings.codex_command
        )
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
            "modes": [mode.value for mode in SessionMode],
            "roles": ROLE_TRACKS,
            "codex_configuration": {
                "model": codex_configuration.model,
                "reasoning_effort": codex_configuration.reasoning_effort,
                "source": codex_configuration.source,
            },
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
        if payload.demo and payload.mode is SessionMode.ADVANCED:
            raise HTTPException(
                status_code=400,
                detail="The bundled demo is Standard Mode only. Generate an Advanced set instead.",
            )
        if payload.mode is SessionMode.ADVANCED and payload.role_track is None:
            raise HTTPException(
                status_code=422, detail="Advanced Mode requires a focus area."
            )
        if payload.mode is SessionMode.STANDARD and payload.role_track is not None:
            raise HTTPException(
                status_code=422, detail="Standard Mode does not accept a focus area."
            )
        if payload.provider != "codex" and (
            payload.model_override or payload.reasoning_effort_override
        ):
            raise HTTPException(
                status_code=422,
                detail="Interview model overrides are currently supported for Codex CLI only.",
            )
        request = ExerciseRequest(
            company=payload.company,
            dialect=payload.dialect,
            difficulty=payload.difficulty,
            additional_context=payload.additional_context,
            mode=payload.mode,
            role_track=payload.role_track,
            model_override=payload.model_override,
            reasoning_effort_override=payload.reasoning_effort_override,
        )
        generation_id = uuid4().hex[:12]
        started_at = time.perf_counter()
        log_context = {
            "generation_id": generation_id,
            "company": payload.company,
            "dialect": payload.dialect.value,
            "difficulty": payload.difficulty.value,
            "provider": payload.provider,
            "mode": payload.mode.value,
            "role_track": payload.role_track.value if payload.role_track else None,
            "demo": payload.demo,
            "save_history": payload.save_history,
            "additional_context_length": len(payload.additional_context),
            "requested_model": payload.model_override,
            "requested_reasoning_effort": payload.reasoning_effort_override,
            "configuration_source": _configuration_telemetry(
                payload, resolved_settings
            )["configuration_source"],
        }
        GENERATION_LOGGER.info(
            "generation_started %s", json.dumps(log_context, sort_keys=True)
        )
        history.start_generation(generation_id, {**log_context, "cache_key": None})
        history.record_generation_event(
            generation_id,
            1,
            {
                "stage": "generation",
                "message": "Generating the shared dataset and three questions.",
                "elapsed_seconds": 0.0,
                "metadata": {"demo": payload.demo},
            },
        )
        telemetry_calls: list[LLMGeneration] = []
        try:
            if exercise_factory is None and not payload.demo:
                exercise_set, telemetry = generate_exercise_set_with_telemetry(
                    request, payload.provider, resolved_settings
                )
                telemetry_calls.append(telemetry)
            else:
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
            finish_generation_log(
                generation_id,
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": _logged_error(exc),
                    **_combined_telemetry(payload, resolved_settings, telemetry_calls),
                },
            )
            GENERATION_LOGGER.warning(
                "generation_failed %s",
                json.dumps(
                    {
                        **log_context,
                        "duration_seconds": round(time.perf_counter() - started_at, 3),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except SQLExecutionError as exc:
            finish_generation_log(
                generation_id,
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": _logged_error(exc),
                    **_combined_telemetry(payload, resolved_settings, telemetry_calls),
                },
            )
            GENERATION_LOGGER.warning(
                "generation_failed %s",
                json.dumps(
                    {
                        **log_context,
                        "duration_seconds": round(time.perf_counter() - started_at, 3),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
            )
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            finish_generation_log(
                generation_id,
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": _logged_error(exc),
                    **_combined_telemetry(payload, resolved_settings, telemetry_calls),
                },
            )
            GENERATION_LOGGER.exception(
                "generation_failed %s",
                json.dumps(
                    {
                        **log_context,
                        "duration_seconds": round(time.perf_counter() - started_at, 3),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
            )
            raise
        telemetry_summary = (
            {}
            if payload.demo
            else _combined_telemetry(payload, resolved_settings, telemetry_calls)
        )
        if telemetry_summary:
            response["generation_telemetry"] = telemetry_summary
        GENERATION_LOGGER.info(
            "generation_succeeded %s",
            json.dumps(
                {
                    **log_context,
                    **telemetry_summary,
                    "duration_seconds": round(time.perf_counter() - started_at, 3),
                    "exercise_set_id": exercise_set.id,
                    "history_id": stored.summary.id if stored else None,
                    "questions": [
                        {
                            "id": question.id,
                            "question_type": question.question_type.value,
                            "task_summary": question.task_summary,
                        }
                        for question in exercise_set.questions
                    ],
                },
                sort_keys=True,
            ),
        )
        finish_generation_log(
            generation_id,
            {
                "status": "complete",
                **telemetry_summary,
            },
        )
        return jsonable_encoder(response)

    @application.post("/api/generations")
    def start_progressive_generation(payload: CreateExercisePayload):
        if payload.demo:
            raise HTTPException(
                status_code=400,
                detail="Progressive generation does not apply to the instant demo.",
            )
        if payload.mode is not SessionMode.ADVANCED or payload.role_track is None:
            raise HTTPException(
                status_code=422,
                detail="Progressive generation requires Advanced Mode and a focus area.",
            )
        if payload.dialect not in SUPPORTED_DIALECTS:
            raise HTTPException(status_code=400, detail="Unsupported SQL dialect.")
        if payload.provider != "codex" and (
            payload.model_override or payload.reasoning_effort_override
        ):
            raise HTTPException(
                status_code=422,
                detail="Interview model overrides are currently supported for Codex CLI only.",
            )
        request = ExerciseRequest(
            company=payload.company,
            dialect=payload.dialect,
            difficulty=payload.difficulty,
            additional_context=payload.additional_context,
            mode=payload.mode,
            role_track=payload.role_track,
            reuse_cached_dataset=payload.reuse_cached_dataset,
            model_override=payload.model_override,
            reasoning_effort_override=payload.reasoning_effort_override,
        )
        cache_key = _cache_key(request)
        metadata = {
            "company": request.company,
            "dialect": request.dialect.value,
            "difficulty": request.difficulty.value,
            "mode": request.mode.value,
            "role_track": request.role_track.value,
            "provider": payload.provider,
            "cache_key": cache_key,
            "requested_model": payload.model_override,
            "requested_reasoning_effort": payload.reasoning_effort_override,
            "configuration_source": _configuration_telemetry(
                payload, resolved_settings
            )["configuration_source"],
        }
        job = generation_jobs.create(metadata)
        job.telemetry = _configuration_telemetry(payload, resolved_settings)
        history.start_generation(job.id, metadata)
        append_generation_event(
            job,
            "queued",
            "Generation queued. Checking for a reusable local dataset.",
            {"reuse_cached_dataset": payload.reuse_cached_dataset},
        )
        generation_executor.submit(
            run_progressive_generation, job, request, payload, cache_key
        )
        return {"generation_id": job.id, "status": job.status}

    @application.get("/api/generations/{generation_id}")
    def generation_status(generation_id: str):
        job = generation_jobs.get(generation_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Generation log not found")
        return jsonable_encoder(job.snapshot())

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
        if (
            session.exercise.mode is SessionMode.ADVANCED
            and not session.details_revealed
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Reveal the interviewer details before using Query Doctor so coaching "
                    "does not expose staged requirements early."
                ),
            )
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

    @application.post("/api/sessions/{session_id}/interviewer-details")
    def reveal_interviewer_details(session_id: str):
        session = get_session(session_id)
        session.reveal_interviewer_details()
        return jsonable_encoder(
            {
                "clarifications": session.exercise.clarifications,
                "requirements": _requirements(session.exercise),
            }
        )

    @application.post("/api/sessions/{session_id}/solution")
    def reveal_solution(session_id: str):
        session = get_session(session_id)
        if session.practice_session_id and session.history_question_id:
            history.record_solution_reveal(
                session.practice_session_id, session.history_question_id
            )
        case_rubric = [
            criterion.model_dump() for criterion in session.exercise.case_rubric
        ]
        reference_discussion = list(session.exercise.reference_discussion)
        if (
            session.exercise.question_type.value == "analytical_case"
            and not case_rubric
            and not reference_discussion
        ):
            case_rubric, reference_discussion = _default_case_review(session.exercise)
        return {
            "reference_sql": session.exercise.reference_sql,
            "explanation": session.exercise.explanation,
            "case_rubric": case_rubric,
            "reference_discussion": reference_discussion,
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
        if generation_jobs.has_running():
            raise HTTPException(
                status_code=409,
                detail="Wait for active question generation to finish before clearing history.",
            )
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

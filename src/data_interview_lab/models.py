"""Validated domain models shared by generation, execution, and grading."""

from __future__ import annotations

import re
from enum import Enum
from typing import Iterator

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Dialect(str, Enum):
    DUCKDB = "duckdb"
    POSTGRES = "postgres"
    BIGQUERY = "bigquery"
    SNOWFLAKE = "snowflake"
    SPARK = "spark"
    DATABRICKS = "databricks"
    PRESTO = "presto"
    TRINO = "trino"
    MYSQL = "mysql"
    REDSHIFT = "redshift"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class PracticeMode(str, Enum):
    PRACTICE = "practice"
    INTERVIEW = "interview"
    REVIEW = "review"


class SessionMode(str, Enum):
    STANDARD = "standard"
    ADVANCED = "advanced"


class RoleTrack(str, Enum):
    PRODUCT_ANALYTICS = "product_analytics"
    DATA_SCIENCE = "data_science"
    ANALYTICS_ENGINEERING = "analytics_engineering"
    DATA_ENGINEERING = "data_engineering"
    AI_PRODUCT_SAFETY = "ai_product_safety"


class QuestionType(str, Enum):
    SQL_BUILD = "sql_build"
    SQL_DEBUG = "sql_debug"
    ANALYTICAL_CASE = "analytical_case"


class AdvancedTopic(str, Enum):
    COHORT_RETENTION = "cohort_retention"
    FUNNEL_ANALYSIS = "funnel_analysis"
    WINDOW_FUNCTIONS = "window_functions"
    EXPERIMENTATION = "experimentation"
    CAUSAL_INFERENCE = "causal_inference"
    METRIC_DESIGN = "metric_design"
    DATA_QUALITY = "data_quality"
    INSTRUMENTATION = "instrumentation"
    SQL_DEBUGGING = "sql_debugging"
    AI_CODE_REVIEW = "ai_generated_code_review"
    DATA_MODELING = "data_modeling"
    PIPELINE_RELIABILITY = "pipeline_reliability"
    QUERY_PERFORMANCE = "query_performance"
    SAFETY_EVALUATION = "safety_evaluation"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TableDefinition(StrictModel):
    name: str = Field(min_length=1)
    ddl: str = Field(min_length=1)
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_name(self) -> "TableDefinition":
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.name):
            raise ValueError("table name must be an unquoted SQL identifier")
        return self


class DatasetDefinition(StrictModel):
    """Seed data for one isolated grading run."""

    name: str = Field(min_length=1)
    seed_sql: str = Field(min_length=1)
    hidden: bool = True


class GradingConfig(StrictModel):
    order_matters: bool = False
    numeric_tolerance: float = Field(default=0.000001, ge=0)


class InterviewerClarification(StrictModel):
    candidate_question: str = Field(min_length=1, max_length=240)
    interviewer_answer: str = Field(min_length=1, max_length=500)


class CaseRubricCriterion(StrictModel):
    criterion: str = Field(min_length=1, max_length=100)
    strong_signal: str = Field(min_length=1, max_length=500)
    common_miss: str = Field(min_length=1, max_length=500)


class Exercise(StrictModel):
    id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    dialect: Dialect
    difficulty: Difficulty
    concepts: list[str] = Field(min_length=1)
    business_context: str = Field(min_length=1)
    question: str = Field(min_length=1)
    task_summary: str | None = Field(default=None, min_length=1, max_length=320)
    requirements: list[str] = Field(default_factory=list, max_length=8)
    tables: list[TableDefinition] = Field(min_length=1, max_length=6)
    seed_sql: str = Field(min_length=1)
    hidden_datasets: list[DatasetDefinition] = Field(default_factory=list)
    reference_sql: str = Field(min_length=1)
    grading: GradingConfig = Field(default_factory=GradingConfig)
    explanation: str = Field(min_length=1)
    hints: list[str] = Field(default_factory=list)
    question_type: QuestionType = QuestionType.SQL_BUILD
    starter_sql: str | None = None
    clarifications: list[InterviewerClarification] = Field(
        default_factory=list, max_length=6
    )
    case_rubric: list[CaseRubricCriterion] = Field(default_factory=list, max_length=8)
    modern_topics: list[AdvancedTopic] = Field(default_factory=list, max_length=8)
    reference_discussion: list[str] = Field(default_factory=list, max_length=6)
    mode: SessionMode = SessionMode.STANDARD
    role_track: RoleTrack | None = None

    @model_validator(mode="after")
    def validate_exercise(self) -> "Exercise":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.id):
            raise ValueError("exercise id must be a lowercase slug")

        table_names = [table.name.casefold() for table in self.tables]
        if len(table_names) != len(set(table_names)):
            raise ValueError("table names must be unique")

        dataset_names = [dataset.name.casefold() for dataset in self.hidden_datasets]
        if "visible" in dataset_names:
            raise ValueError("hidden dataset name 'visible' is reserved")
        if len(dataset_names) != len(set(dataset_names)):
            raise ValueError("hidden dataset names must be unique")
        if any(not dataset.hidden for dataset in self.hidden_datasets):
            raise ValueError("every hidden_datasets entry must set hidden=true")

        if any(not concept for concept in self.concepts):
            raise ValueError("concepts cannot contain empty values")
        if any(not requirement for requirement in self.requirements):
            raise ValueError("requirements cannot contain empty values")
        return self

    def datasets(self) -> Iterator[DatasetDefinition]:
        yield DatasetDefinition(name="visible", seed_sql=self.seed_sql, hidden=False)
        yield from self.hidden_datasets


class ExerciseRequest(StrictModel):
    company: str = Field(min_length=1)
    dialect: Dialect = Dialect.DUCKDB
    difficulty: Difficulty = Difficulty.MEDIUM
    additional_context: str = Field(default="", max_length=2000)
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

    @model_validator(mode="after")
    def validate_mode(self) -> "ExerciseRequest":
        if self.mode is SessionMode.ADVANCED and self.role_track is None:
            raise ValueError("advanced mode requires a role_track")
        if self.mode is SessionMode.STANDARD and self.role_track is not None:
            raise ValueError("standard mode does not accept a role_track")
        return self


class ExerciseQuestion(StrictModel):
    id: str = Field(min_length=1)
    difficulty: Difficulty
    concepts: list[str] = Field(min_length=1)
    question: str = Field(min_length=1)
    task_summary: str | None = Field(default=None, min_length=1, max_length=320)
    requirements: list[str] = Field(default_factory=list, max_length=8)
    reference_sql: str = Field(min_length=1)
    grading: GradingConfig = Field(default_factory=GradingConfig)
    explanation: str = Field(min_length=1)
    hints: list[str] = Field(default_factory=list)
    question_type: QuestionType = QuestionType.SQL_BUILD
    starter_sql: str | None = None
    clarifications: list[InterviewerClarification] = Field(
        default_factory=list, max_length=6
    )
    case_rubric: list[CaseRubricCriterion] = Field(default_factory=list, max_length=8)
    modern_topics: list[AdvancedTopic] = Field(default_factory=list, max_length=8)
    reference_discussion: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_question(self) -> "ExerciseQuestion":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.id):
            raise ValueError("question id must be a lowercase slug")
        if any(not concept for concept in self.concepts):
            raise ValueError("concepts cannot contain empty values")
        if any(not requirement for requirement in self.requirements):
            raise ValueError("requirements cannot contain empty values")
        return self


class SharedExerciseDataset(StrictModel):
    """Question-independent schema and rows that can be reused locally."""

    id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    dialect: Dialect = Dialect.DUCKDB
    business_context: str = Field(min_length=1)
    tables: list[TableDefinition] = Field(min_length=1, max_length=4)
    seed_sql: str = Field(min_length=1)
    hidden_datasets: list[DatasetDefinition] = Field(min_length=1, max_length=3)
    mode: SessionMode = SessionMode.ADVANCED
    role_track: RoleTrack

    @model_validator(mode="after")
    def validate_dataset(self) -> "SharedExerciseDataset":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.id):
            raise ValueError("dataset id must be a lowercase slug")
        table_names = [table.name.casefold() for table in self.tables]
        if len(table_names) != len(set(table_names)):
            raise ValueError("table names must be unique")
        dataset_names = [dataset.name.casefold() for dataset in self.hidden_datasets]
        if "visible" in dataset_names or len(dataset_names) != len(set(dataset_names)):
            raise ValueError(
                "hidden dataset names must be unique and cannot be visible"
            )
        if any(not dataset.hidden for dataset in self.hidden_datasets):
            raise ValueError("every hidden dataset must set hidden=true")
        if self.mode is not SessionMode.ADVANCED:
            raise ValueError("shared progressive datasets are advanced mode only")
        return self

    def with_questions(self, questions: list[ExerciseQuestion]) -> "ExerciseSet":
        return ExerciseSet(
            id=self.id,
            company=self.company,
            dialect=self.dialect,
            business_context=self.business_context,
            tables=self.tables,
            seed_sql=self.seed_sql,
            hidden_datasets=self.hidden_datasets,
            questions=questions,
            mode=self.mode,
            role_track=self.role_track,
        )

    def exercise(self, question: ExerciseQuestion) -> Exercise:
        return Exercise(
            id=f"{self.id}_{question.id}",
            company=self.company,
            dialect=self.dialect,
            difficulty=question.difficulty,
            concepts=question.concepts,
            business_context=self.business_context,
            question=question.question,
            task_summary=question.task_summary,
            requirements=question.requirements,
            tables=self.tables,
            seed_sql=self.seed_sql,
            hidden_datasets=self.hidden_datasets,
            reference_sql=question.reference_sql,
            grading=question.grading,
            explanation=question.explanation,
            hints=question.hints,
            question_type=question.question_type,
            starter_sql=question.starter_sql,
            clarifications=question.clarifications,
            case_rubric=question.case_rubric,
            modern_topics=question.modern_topics,
            reference_discussion=question.reference_discussion,
            mode=self.mode,
            role_track=self.role_track,
        )


class AdvancedFoundation(StrictModel):
    dataset: SharedExerciseDataset
    question: ExerciseQuestion


class AdvancedQuestionOutput(StrictModel):
    question: ExerciseQuestion


class ExerciseSet(StrictModel):
    """Three questions that intentionally share one schema and grading data."""

    id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    dialect: Dialect = Dialect.DUCKDB
    business_context: str = Field(min_length=1)
    tables: list[TableDefinition] = Field(min_length=1, max_length=6)
    seed_sql: str = Field(min_length=1)
    hidden_datasets: list[DatasetDefinition] = Field(default_factory=list)
    questions: list[ExerciseQuestion] = Field(min_length=3, max_length=3)
    mode: SessionMode = SessionMode.STANDARD
    role_track: RoleTrack | None = None

    @model_validator(mode="after")
    def validate_set(self) -> "ExerciseSet":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.id):
            raise ValueError("exercise set id must be a lowercase slug")
        table_names = [table.name.casefold() for table in self.tables]
        if len(table_names) != len(set(table_names)):
            raise ValueError("table names must be unique")
        dataset_names = [dataset.name.casefold() for dataset in self.hidden_datasets]
        if "visible" in dataset_names:
            raise ValueError("hidden dataset name 'visible' is reserved")
        if len(dataset_names) != len(set(dataset_names)):
            raise ValueError("hidden dataset names must be unique")
        if any(not dataset.hidden for dataset in self.hidden_datasets):
            raise ValueError("every hidden_datasets entry must set hidden=true")
        question_ids = [question.id.casefold() for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question ids must be unique")

        if self.mode is SessionMode.STANDARD:
            if self.role_track is not None:
                raise ValueError("standard exercise sets cannot define a role_track")
            if any(
                question.question_type is not QuestionType.SQL_BUILD
                or question.starter_sql is not None
                or question.clarifications
                or question.case_rubric
                or question.modern_topics
                or question.reference_discussion
                for question in self.questions
            ):
                raise ValueError(
                    "standard exercise sets cannot define advanced question metadata"
                )
            return self

        if self.role_track is None:
            raise ValueError("advanced exercise sets require a role_track")
        expected_types = [
            QuestionType.SQL_BUILD,
            QuestionType.SQL_DEBUG,
            QuestionType.ANALYTICAL_CASE,
        ]
        if [question.question_type for question in self.questions] != expected_types:
            raise ValueError(
                "advanced questions must be ordered sql_build, sql_debug, analytical_case"
            )
        for question in self.questions:
            if len(question.clarifications) < 2:
                raise ValueError(
                    "every advanced question requires at least two clarifications"
                )
            if not question.modern_topics:
                raise ValueError("every advanced question requires modern_topics")
        if not self.questions[1].starter_sql:
            raise ValueError("the advanced sql_debug question requires starter_sql")
        return self

    def exercises(self) -> list[Exercise]:
        return [
            Exercise(
                id=f"{self.id}_{question.id}",
                company=self.company,
                dialect=self.dialect,
                difficulty=question.difficulty,
                concepts=question.concepts,
                business_context=self.business_context,
                question=question.question,
                task_summary=question.task_summary,
                requirements=question.requirements,
                tables=self.tables,
                seed_sql=self.seed_sql,
                hidden_datasets=self.hidden_datasets,
                reference_sql=question.reference_sql,
                grading=question.grading,
                explanation=question.explanation,
                hints=question.hints,
                question_type=question.question_type,
                starter_sql=question.starter_sql,
                clarifications=question.clarifications,
                case_rubric=question.case_rubric,
                modern_topics=question.modern_topics,
                reference_discussion=question.reference_discussion,
                mode=self.mode,
                role_track=self.role_track,
            )
            for question in self.questions
        ]

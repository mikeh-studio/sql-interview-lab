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


class Exercise(StrictModel):
    id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    dialect: Dialect
    difficulty: Difficulty
    concepts: list[str] = Field(min_length=1)
    business_context: str = Field(min_length=1)
    question: str = Field(min_length=1)
    tables: list[TableDefinition] = Field(min_length=1, max_length=6)
    seed_sql: str = Field(min_length=1)
    hidden_datasets: list[DatasetDefinition] = Field(default_factory=list)
    reference_sql: str = Field(min_length=1)
    grading: GradingConfig = Field(default_factory=GradingConfig)
    explanation: str = Field(min_length=1)
    hints: list[str] = Field(default_factory=list)

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
        return self

    def datasets(self) -> Iterator[DatasetDefinition]:
        yield DatasetDefinition(name="visible", seed_sql=self.seed_sql, hidden=False)
        yield from self.hidden_datasets


class ExerciseRequest(StrictModel):
    company: str = Field(min_length=1)
    dialect: Dialect = Dialect.DUCKDB
    difficulty: Difficulty = Difficulty.MEDIUM
    additional_context: str = Field(default="", max_length=2000)


class ExerciseQuestion(StrictModel):
    id: str = Field(min_length=1)
    difficulty: Difficulty
    concepts: list[str] = Field(min_length=1)
    question: str = Field(min_length=1)
    reference_sql: str = Field(min_length=1)
    grading: GradingConfig = Field(default_factory=GradingConfig)
    explanation: str = Field(min_length=1)
    hints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_question(self) -> "ExerciseQuestion":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.id):
            raise ValueError("question id must be a lowercase slug")
        if any(not concept for concept in self.concepts):
            raise ValueError("concepts cannot contain empty values")
        return self


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
                tables=self.tables,
                seed_sql=self.seed_sql,
                hidden_datasets=self.hidden_datasets,
                reference_sql=question.reference_sql,
                grading=question.grading,
                explanation=question.explanation,
                hints=question.hints,
            )
            for question in self.questions
        ]

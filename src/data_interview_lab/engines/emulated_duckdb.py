"""Strict target-dialect emulation backed by an isolated DuckDB database."""

from __future__ import annotations

import sqlglot
from sqlglot import ErrorLevel
from sqlglot.errors import ParseError, UnsupportedError

from data_interview_lab.engines.base import QueryResult, SQLEngine, SQLExecutionError
from data_interview_lab.engines.duckdb_engine import DuckDBEngine
from data_interview_lab.models import DatasetDefinition, Dialect, Exercise


class EmulatedDuckDBEngine(SQLEngine):
    """Parse one supported dialect, fail closed, and execute translated SQL in DuckDB."""

    def __init__(self, source_dialect: Dialect) -> None:
        if source_dialect is Dialect.DUCKDB:
            raise ValueError("Use DuckDBEngine for native DuckDB execution")
        self.source_dialect = source_dialect
        self._engine = DuckDBEngine()

    def _transpile(self, sql: str, *, label: str) -> str:
        try:
            statements = sqlglot.transpile(
                sql,
                read=self.source_dialect.value,
                write=Dialect.DUCKDB.value,
                unsupported_level=ErrorLevel.RAISE,
            )
        except (ParseError, UnsupportedError) as exc:
            raise SQLExecutionError(
                f"{self.source_dialect.value} {label} cannot be faithfully emulated "
                f"on DuckDB: {exc}"
            ) from exc
        if not statements:
            raise SQLExecutionError(f"{label} cannot be empty")
        return ";\n".join(statements)

    def setup(
        self, exercise: Exercise, dataset: DatasetDefinition | None = None
    ) -> None:
        if exercise.dialect is not self.source_dialect:
            raise SQLExecutionError(
                f"Engine expects {self.source_dialect.value}, received "
                f"{exercise.dialect.value}"
            )
        selected_dataset = dataset or next(exercise.datasets())
        translated_tables = [
            table.model_copy(
                update={
                    "ddl": self._transpile(table.ddl, label=f"DDL for {table.name}")
                }
            )
            for table in exercise.tables
        ]
        translated_dataset = selected_dataset.model_copy(
            update={
                "seed_sql": self._transpile(
                    selected_dataset.seed_sql,
                    label=f"seed SQL for {selected_dataset.name}",
                )
            }
        )
        duckdb_exercise = exercise.model_copy(
            update={"dialect": Dialect.DUCKDB, "tables": translated_tables}
        )
        self._engine.setup(duckdb_exercise, translated_dataset)

    def execute(self, sql: str) -> QueryResult:
        translated = self._transpile(sql, label="query")
        return self._engine.execute(translated)

    def reset(self) -> None:
        self._engine.reset()

    def close(self) -> None:
        self._engine.close()


def transpile_to_duckdb(sql: str, source_dialect: Dialect) -> str:
    """Expose strict translation for focused validation and diagnostics."""

    engine = EmulatedDuckDBEngine(source_dialect)
    try:
        return engine._transpile(sql, label="query")
    finally:
        engine.close()

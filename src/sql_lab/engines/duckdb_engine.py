"""Native DuckDB execution in a fresh in-memory database."""

from __future__ import annotations

from time import perf_counter

import duckdb

from sql_lab.engines.base import (
    QueryResult,
    SQLEngine,
    SQLExecutionError,
    UnsupportedDialectError,
)
from sql_lab.models import DatasetDefinition, Dialect, Exercise


class DuckDBEngine(SQLEngine):
    def __init__(self) -> None:
        self._connection: duckdb.DuckDBPyConnection | None = None
        self.reset()

    def setup(
        self, exercise: Exercise, dataset: DatasetDefinition | None = None
    ) -> None:
        if exercise.dialect is not Dialect.DUCKDB:
            raise UnsupportedDialectError(
                f"DuckDBEngine provides native DuckDB execution, not {exercise.dialect.value}. "
                "No transpilation or emulation was attempted."
            )

        selected_dataset = dataset or next(exercise.datasets())
        self.reset()
        assert self._connection is not None
        try:
            for table in exercise.tables:
                self._connection.execute(table.ddl)
            self._connection.execute(selected_dataset.seed_sql)
        except duckdb.Error as exc:
            self.reset()
            raise SQLExecutionError(
                f"Failed to initialize dataset '{selected_dataset.name}': {exc}"
            ) from exc

    def execute(self, sql: str) -> QueryResult:
        if not sql.strip():
            raise SQLExecutionError("SQL cannot be empty")
        assert self._connection is not None
        started = perf_counter()
        try:
            cursor = self._connection.execute(sql)
            columns = tuple(column[0] for column in (cursor.description or ()))
            rows = tuple(tuple(row) for row in cursor.fetchall()) if columns else ()
        except duckdb.Error as exc:
            raise SQLExecutionError(str(exc)) from exc
        duration_ms = (perf_counter() - started) * 1000
        return QueryResult(columns=columns, rows=rows, duration_ms=duration_ms)

    def reset(self) -> None:
        self.close()
        self._connection = duckdb.connect(
            ":memory:", config={"enable_external_access": "false"}
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "DuckDBEngine":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

from __future__ import annotations

import pytest

from sql_lab.engines.base import SQLExecutionError, UnsupportedDialectError
from sql_lab.engines.duckdb_engine import DuckDBEngine
from sql_lab.models import Exercise


def test_duckdb_reset_isolates_exercises(exercise: Exercise) -> None:
    second_payload = exercise.model_dump(mode="json")
    second_payload.update(
        {
            "id": "second_exercise",
            "tables": [
                {
                    "name": "second_table",
                    "ddl": "CREATE TABLE second_table (value INTEGER);",
                    "description": "Isolation sentinel.",
                }
            ],
            "seed_sql": "INSERT INTO second_table VALUES (42);",
            "hidden_datasets": [],
            "reference_sql": "SELECT value FROM second_table;",
        }
    )
    second = Exercise.model_validate(second_payload)

    with DuckDBEngine() as engine:
        engine.setup(exercise)
        assert engine.execute("SELECT COUNT(*) FROM customers").rows == ((5,),)

        engine.setup(second)
        assert engine.execute("SELECT * FROM second_table").rows == ((42,),)
        with pytest.raises(SQLExecutionError, match="customers"):
            engine.execute("SELECT * FROM customers")


def test_duckdb_backend_refuses_other_dialects(exercise: Exercise) -> None:
    payload = exercise.model_dump(mode="json")
    payload["dialect"] = "postgres"
    postgres_exercise = Exercise.model_validate(payload)

    with DuckDBEngine() as engine, pytest.raises(UnsupportedDialectError):
        engine.setup(postgres_exercise)


def test_duckdb_external_file_access_is_disabled(exercise: Exercise, tmp_path) -> None:
    output_path = tmp_path / "should-not-exist.csv"

    with DuckDBEngine() as engine:
        engine.setup(exercise)
        with pytest.raises(
            SQLExecutionError, match="file system operations are disabled"
        ):
            engine.execute(f"COPY (SELECT 1) TO '{output_path}'")

    assert not output_path.exists()

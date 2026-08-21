from __future__ import annotations

import pytest

from sql_lab.engines.base import SQLExecutionError
from sql_lab.engines.factory import create_engine, execution_mode
from sql_lab.exercises import get_static_exercise_set
from sql_lab.grading.grader import Grader
from sql_lab.models import Dialect


DIALECT_QUERIES = {
    Dialect.REDSHIFT: (
        "SELECT DATEDIFF(day, DATE '2025-01-01', DATE '2025-02-01') AS days "
        "FROM customers LIMIT 1"
    ),
    Dialect.BIGQUERY: ("SELECT COUNTIF(status = 'completed') AS completed FROM orders"),
    Dialect.SNOWFLAKE: (
        "SELECT IFF(COUNT_IF(status = 'completed') > 0, 'yes', 'no') "
        "AS has_completed FROM orders"
    ),
    Dialect.DATABRICKS: (
        "SELECT DATEDIFF(DATE '2025-02-01', DATE '2025-01-01') AS days "
        "FROM customers LIMIT 1"
    ),
    Dialect.PRESTO: (
        "SELECT DATE_DIFF('day', DATE '2025-01-01', DATE '2025-02-01') AS days "
        "FROM customers LIMIT 1"
    ),
}


@pytest.mark.parametrize(("dialect", "query"), DIALECT_QUERIES.items())
def test_emulated_dialect_query_is_deterministically_graded(
    dialect: Dialect, query: str
) -> None:
    exercise = (
        get_static_exercise_set()
        .exercises()[0]
        .model_copy(update={"dialect": dialect, "reference_sql": query})
    )

    result = Grader().grade(exercise, query)

    assert result.passed is True
    assert execution_mode(dialect) == "emulated"


def test_invalid_target_dialect_sql_fails_with_emulation_context() -> None:
    exercise = (
        get_static_exercise_set()
        .exercises()[0]
        .model_copy(update={"dialect": Dialect.BIGQUERY})
    )
    engine = create_engine(Dialect.BIGQUERY)
    try:
        engine.setup(exercise)
        with pytest.raises(SQLExecutionError, match="bigquery query.*emulated"):
            engine.execute("SELECT FROM")
    finally:
        engine.close()

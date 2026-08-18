"""Execution backend routing with explicit native versus emulated modes."""

from data_interview_lab.engines.base import SQLEngine
from data_interview_lab.engines.duckdb_engine import DuckDBEngine
from data_interview_lab.engines.emulated_duckdb import EmulatedDuckDBEngine
from data_interview_lab.models import Dialect


SUPPORTED_DIALECTS = (
    Dialect.DUCKDB,
    Dialect.REDSHIFT,
    Dialect.BIGQUERY,
    Dialect.SNOWFLAKE,
    Dialect.DATABRICKS,
    Dialect.PRESTO,
)


def create_engine(dialect: Dialect) -> SQLEngine:
    if dialect is Dialect.DUCKDB:
        return DuckDBEngine()
    if dialect in SUPPORTED_DIALECTS:
        return EmulatedDuckDBEngine(dialect)
    raise ValueError(f"No execution path is configured for {dialect.value}")


def execution_mode(dialect: Dialect) -> str:
    return "native" if dialect is Dialect.DUCKDB else "emulated"

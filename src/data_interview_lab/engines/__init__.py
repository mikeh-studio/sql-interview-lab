"""SQL execution backends."""

from data_interview_lab.engines.duckdb_engine import DuckDBEngine
from data_interview_lab.engines.emulated_duckdb import EmulatedDuckDBEngine
from data_interview_lab.engines.factory import (
    SUPPORTED_DIALECTS,
    create_engine,
    execution_mode,
)

__all__ = [
    "DuckDBEngine",
    "EmulatedDuckDBEngine",
    "SUPPORTED_DIALECTS",
    "create_engine",
    "execution_mode",
]

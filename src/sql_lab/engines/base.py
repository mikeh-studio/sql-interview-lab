"""Execution backend contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sql_lab.models import DatasetDefinition, Exercise


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    duration_ms: float


class SQLExecutionError(RuntimeError):
    """A submitted SQL statement could not be executed."""


class UnsupportedDialectError(RuntimeError):
    """The selected backend cannot faithfully execute the requested dialect."""


class SQLEngine(ABC):
    @abstractmethod
    def setup(
        self, exercise: Exercise, dataset: DatasetDefinition | None = None
    ) -> None:
        """Reset the backend and load one exercise dataset."""

    @abstractmethod
    def execute(self, sql: str) -> QueryResult:
        """Execute SQL and return the database's actual result."""

    @abstractmethod
    def reset(self) -> None:
        """Destroy all current exercise state and create an empty backend."""

    @abstractmethod
    def close(self) -> None:
        """Release backend resources."""

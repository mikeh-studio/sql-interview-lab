"""Database-result comparison independent of SQL text."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from numbers import Real
from typing import Any

from sql_lab.engines.base import QueryResult
from sql_lab.models import GradingConfig


@dataclass(frozen=True)
class RowMismatch:
    expected: tuple[Any, ...] | None
    actual: tuple[Any, ...] | None


@dataclass(frozen=True)
class ComparisonResult:
    passed: bool
    expected_columns: tuple[str, ...]
    actual_columns: tuple[str, ...]
    expected_row_count: int
    actual_row_count: int
    differing_rows: int
    examples: tuple[RowMismatch, ...]

    @property
    def columns_match(self) -> bool:
        return self.expected_columns == self.actual_columns


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (Real, Decimal)) and not isinstance(value, bool)


def _values_equal(expected: Any, actual: Any, tolerance: float) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if _is_numeric(expected) and _is_numeric(actual):
        expected_float = float(expected)
        actual_float = float(actual)
        if math.isnan(expected_float) or math.isnan(actual_float):
            return math.isnan(expected_float) and math.isnan(actual_float)
        return math.isclose(
            expected_float,
            actual_float,
            rel_tol=0.0,
            abs_tol=tolerance,
        )
    return bool(expected == actual)


def _rows_equal(
    expected: tuple[Any, ...], actual: tuple[Any, ...], tolerance: float
) -> bool:
    return len(expected) == len(actual) and all(
        _values_equal(expected_value, actual_value, tolerance)
        for expected_value, actual_value in zip(expected, actual, strict=True)
    )


def _ordered_mismatches(
    expected_rows: tuple[tuple[Any, ...], ...],
    actual_rows: tuple[tuple[Any, ...], ...],
    tolerance: float,
) -> list[RowMismatch]:
    mismatches: list[RowMismatch] = []
    for index in range(max(len(expected_rows), len(actual_rows))):
        expected = expected_rows[index] if index < len(expected_rows) else None
        actual = actual_rows[index] if index < len(actual_rows) else None
        if (
            expected is None
            or actual is None
            or not _rows_equal(expected, actual, tolerance)
        ):
            mismatches.append(RowMismatch(expected=expected, actual=actual))
    return mismatches


def _unordered_mismatches(
    expected_rows: tuple[tuple[Any, ...], ...],
    actual_rows: tuple[tuple[Any, ...], ...],
    tolerance: float,
) -> list[RowMismatch]:
    adjacency = [
        [
            actual_index
            for actual_index, actual in enumerate(actual_rows)
            if _rows_equal(expected, actual, tolerance)
        ]
        for expected in expected_rows
    ]
    actual_to_expected: dict[int, int] = {}

    def find_match(expected_index: int, seen_actual: set[int]) -> bool:
        for actual_index in adjacency[expected_index]:
            if actual_index in seen_actual:
                continue
            seen_actual.add(actual_index)
            previous_expected = actual_to_expected.get(actual_index)
            if previous_expected is None or find_match(previous_expected, seen_actual):
                actual_to_expected[actual_index] = expected_index
                return True
        return False

    matched_expected: set[int] = set()
    for expected_index in range(len(expected_rows)):
        if find_match(expected_index, set()):
            matched_expected.add(expected_index)

    matched_actual = set(actual_to_expected)
    unmatched_expected = [
        row for index, row in enumerate(expected_rows) if index not in matched_expected
    ]
    unmatched_actual = [
        row for index, row in enumerate(actual_rows) if index not in matched_actual
    ]
    return [
        RowMismatch(
            expected=(
                unmatched_expected[index] if index < len(unmatched_expected) else None
            ),
            actual=(unmatched_actual[index] if index < len(unmatched_actual) else None),
        )
        for index in range(max(len(unmatched_expected), len(unmatched_actual)))
    ]


def compare_results(
    expected: QueryResult,
    actual: QueryResult,
    config: GradingConfig,
    *,
    max_examples: int = 3,
) -> ComparisonResult:
    """Compare result shape and values without comparing SQL source text."""

    if config.order_matters:
        mismatches = _ordered_mismatches(
            expected.rows, actual.rows, config.numeric_tolerance
        )
    else:
        mismatches = _unordered_mismatches(
            expected.rows, actual.rows, config.numeric_tolerance
        )

    columns_match = expected.columns == actual.columns
    passed = columns_match and not mismatches
    return ComparisonResult(
        passed=passed,
        expected_columns=expected.columns,
        actual_columns=actual.columns,
        expected_row_count=len(expected.rows),
        actual_row_count=len(actual.rows),
        differing_rows=len(mismatches),
        examples=tuple(mismatches[:max_examples]),
    )

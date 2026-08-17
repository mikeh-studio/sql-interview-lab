from __future__ import annotations

from data_interview_lab.engines.base import QueryResult
from data_interview_lab.grading.compare import compare_results
from data_interview_lab.models import GradingConfig


def result(columns: tuple[str, ...], *rows: tuple[object, ...]) -> QueryResult:
    return QueryResult(columns=columns, rows=rows, duration_ms=0)


def test_row_order_is_ignored_when_not_required() -> None:
    expected = result(("id",), (1,), (2,), (2,))
    actual = result(("id",), (2,), (1,), (2,))

    comparison = compare_results(expected, actual, GradingConfig(order_matters=False))

    assert comparison.passed


def test_row_order_fails_when_required() -> None:
    expected = result(("id",), (1,), (2,))
    actual = result(("id",), (2,), (1,))

    comparison = compare_results(expected, actual, GradingConfig(order_matters=True))

    assert not comparison.passed
    assert comparison.differing_rows == 2


def test_nulls_compare_deterministically() -> None:
    expected = result(("value",), (None,), ("x",))

    assert compare_results(expected, expected, GradingConfig()).passed
    assert not compare_results(
        expected,
        result(("value",), (0,), ("x",)),
        GradingConfig(),
    ).passed


def test_numeric_tolerance_is_applied_to_values() -> None:
    expected = result(("rate",), (0.031,))
    close = result(("rate",), (0.0310004,))
    far = result(("rate",), (0.03101,))
    config = GradingConfig(numeric_tolerance=0.000001)

    assert compare_results(expected, close, config).passed
    assert not compare_results(expected, far, config).passed


def test_column_names_are_part_of_the_contract() -> None:
    expected = result(("conversion_rate",), (0.031,))
    actual = result(("rate",), (0.031,))

    comparison = compare_results(expected, actual, GradingConfig())

    assert not comparison.passed
    assert not comparison.columns_match

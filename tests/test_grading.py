from __future__ import annotations

from sql_lab.grading.grader import Grader
from sql_lab.models import Exercise


EQUIVALENT_SQL = """
    WITH per_customer AS (
        SELECT
            c.customer_id,
            c.segment,
            MAX(CASE
                WHEN o.status = 'completed'
                 AND o.order_date >= DATE '2025-01-01'
                 AND o.order_date < DATE '2025-02-01'
                THEN 1 ELSE 0
            END) AS converted,
            SUM(CASE
                WHEN o.status = 'completed'
                 AND o.order_date >= DATE '2025-01-01'
                 AND o.order_date < DATE '2025-02-01'
                THEN COALESCE(o.amount, 0) ELSE 0
            END) AS revenue
        FROM customers c
        LEFT JOIN orders o USING (customer_id)
        GROUP BY c.customer_id, c.segment
    )
    SELECT
        segment,
        COUNT(*) AS customer_count,
        SUM(converted) AS converting_customers,
        ROUND(SUM(converted)::DOUBLE / COUNT(*), 3) AS conversion_rate,
        SUM(revenue) AS completed_revenue
    FROM per_customer
    GROUP BY segment
    ORDER BY segment;
"""


def test_reference_query_passes(exercise: Exercise) -> None:
    result = Grader().grade(exercise, exercise.reference_sql)

    assert result.passed
    assert len(result.datasets) == 2


def test_different_but_equivalent_query_passes(exercise: Exercise) -> None:
    result = Grader().grade(exercise, EQUIVALENT_SQL)

    assert result.passed


def test_incorrect_result_fails_with_diff(exercise: Exercise) -> None:
    wrong_sql = """
        SELECT
            segment,
            COUNT(*) AS customer_count,
            0 AS converting_customers,
            0.0 AS conversion_rate,
            0.0 AS completed_revenue
        FROM customers
        GROUP BY segment
    """

    result = Grader().grade(exercise, wrong_sql)

    assert not result.passed
    visible = result.datasets[0]
    assert visible.comparison is not None
    assert visible.comparison.differing_rows > 0
    assert visible.comparison.examples


def test_query_can_pass_visible_data_but_fail_hidden_edge_case(
    exercise: Exercise,
) -> None:
    amount_as_conversion = """
        WITH per_customer AS (
            SELECT
                c.customer_id,
                c.segment,
                COALESCE(SUM(o.amount) FILTER (
                    WHERE o.status = 'completed'
                      AND o.order_date >= DATE '2025-01-01'
                      AND o.order_date < DATE '2025-02-01'
                ), 0) > 0 AS converted,
                COALESCE(SUM(o.amount) FILTER (
                    WHERE o.status = 'completed'
                      AND o.order_date >= DATE '2025-01-01'
                      AND o.order_date < DATE '2025-02-01'
                ), 0) AS revenue
            FROM customers c
            LEFT JOIN orders o USING (customer_id)
            GROUP BY c.customer_id, c.segment
        )
        SELECT
            segment,
            COUNT(*) AS customer_count,
            COUNT(*) FILTER (WHERE converted) AS converting_customers,
            ROUND(COUNT(*) FILTER (WHERE converted) * 1.0 / COUNT(*), 3)
                AS conversion_rate,
            SUM(revenue) AS completed_revenue
        FROM per_customer
        GROUP BY segment
        ORDER BY segment
    """

    result = Grader().grade(exercise, amount_as_conversion)

    assert result.datasets[0].passed
    assert not result.datasets[1].passed
    assert not result.passed


def test_syntax_error_is_reported_as_execution_error(exercise: Exercise) -> None:
    result = Grader().grade(exercise, "SELEC definitely_not_sql")

    assert not result.passed
    assert result.datasets[0].execution_error is not None
    assert "syntax" in result.datasets[0].execution_error.casefold()

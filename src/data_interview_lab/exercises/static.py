"""A deterministic Phase 1 exercise that needs no LLM."""

from data_interview_lab.models import Exercise, ExerciseSet


STATIC_EXERCISE = {
    "id": "airbnb_medium_001",
    "company": "Airbnb-style",
    "dialect": "duckdb",
    "difficulty": "medium",
    "concepts": ["joins", "aggregation", "grain", "date boundaries"],
    "business_context": (
        "A fictional marketplace team tracks customer accounts and their orders. "
        "This is interview-style practice data, not an actual Airbnb schema."
    ),
    "question": (
        "For every customer segment, report January 2025 completed-order performance. "
        "Return segment, customer_count, converting_customers, conversion_rate, and "
        "completed_revenue. A converting customer has at least one completed order with "
        "order_date >= 2025-01-01 and < 2025-02-01. Round conversion_rate to three decimal "
        "places, include customers and segments with no qualifying orders, and order the "
        "result by segment."
    ),
    "task_summary": (
        "A marketplace growth team wants to understand whether customer segments convert "
        "January demand differently. Compare completed-order conversion and revenue by segment "
        "to identify where performance diverges."
    ),
    "requirements": [
        "Return segment, customer_count, converting_customers, conversion_rate, and completed_revenue.",
        "Count a customer as converting when they have at least one completed January 2025 order.",
        "Use order_date >= 2025-01-01 and order_date < 2025-02-01.",
        "Include customers and segments with no qualifying orders and treat their revenue as zero.",
        "Round conversion_rate to three decimal places and order by segment.",
    ],
    "tables": [
        {
            "name": "customers",
            "ddl": """
                CREATE TABLE customers (
                    customer_id INTEGER PRIMARY KEY,
                    segment VARCHAR NOT NULL,
                    signup_date DATE NOT NULL
                );
            """,
            "description": "One row per marketplace customer account.",
        },
        {
            "name": "orders",
            "ddl": """
                CREATE TABLE orders (
                    order_id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    order_date DATE NOT NULL,
                    status VARCHAR,
                    amount DECIMAL(12, 2)
                );
            """,
            "description": "One row per order attempt, including cancelled orders.",
        },
    ],
    "seed_sql": """
        INSERT INTO customers VALUES
            (1, 'small_business', '2024-10-01'),
            (2, 'small_business', '2024-11-15'),
            (3, 'enterprise', '2024-06-20'),
            (4, 'enterprise', '2024-12-31'),
            (5, 'mid_market', '2025-01-10');

        INSERT INTO orders VALUES
            (101, 1, '2025-01-03', 'completed', 100.00),
            (102, 1, '2025-01-20', 'completed', 50.00),
            (103, 2, '2025-01-12', 'cancelled', 80.00),
            (104, 3, '2025-01-05', 'completed', 200.00),
            (105, 3, '2025-01-05', 'completed', 200.00),
            (106, 4, '2025-02-01', 'completed', 125.00),
            (107, 5, '2025-01-31', NULL, 75.00);
    """,
    "hidden_datasets": [
        {
            "name": "edge_cases_1",
            "hidden": True,
            "seed_sql": """
                INSERT INTO customers VALUES
                    (10, 'enterprise', '2024-01-01'),
                    (11, 'enterprise', '2024-01-02'),
                    (12, 'small_business', '2024-01-03'),
                    (13, 'small_business', '2024-01-04'),
                    (14, 'small_business', '2024-01-05');

                INSERT INTO orders VALUES
                    (201, 10, '2024-12-31', 'completed', 999.00),
                    (202, 10, '2025-01-01', 'completed', 0.00),
                    (203, 10, '2025-01-01', 'completed', 25.00),
                    (204, 11, '2025-01-15', 'cancelled', 500.00),
                    (205, 12, '2025-01-31', 'completed', NULL),
                    (206, 12, '2025-02-01', 'completed', 100.00),
                    (207, 13, '2025-01-10', NULL, 40.00);
            """,
        }
    ],
    "reference_sql": """
        WITH customer_january AS (
            SELECT
                c.customer_id,
                c.segment,
                COUNT(*) FILTER (
                    WHERE o.status = 'completed'
                      AND o.order_date >= DATE '2025-01-01'
                      AND o.order_date < DATE '2025-02-01'
                ) > 0 AS converted,
                COALESCE(SUM(o.amount) FILTER (
                    WHERE o.status = 'completed'
                      AND o.order_date >= DATE '2025-01-01'
                      AND o.order_date < DATE '2025-02-01'
                ), 0) AS completed_revenue
            FROM customers AS c
            LEFT JOIN orders AS o ON o.customer_id = c.customer_id
            GROUP BY c.customer_id, c.segment
        )
        SELECT
            segment,
            COUNT(*) AS customer_count,
            COUNT(*) FILTER (WHERE converted) AS converting_customers,
            ROUND(
                COUNT(*) FILTER (WHERE converted) * 1.0 / COUNT(*),
                3
            ) AS conversion_rate,
            SUM(completed_revenue) AS completed_revenue
        FROM customer_january
        GROUP BY segment
        ORDER BY segment;
    """,
    "grading": {"order_matters": True, "numeric_tolerance": 0.000001},
    "explanation": (
        "First reduce orders to one row per customer, then aggregate customers by segment. "
        "That prevents customers with multiple completed orders from inflating the denominator."
    ),
    "hints": [
        "Start by producing exactly one row per customer.",
        "Use a half-open date range: >= January 1 and < February 1.",
        "A LEFT JOIN is needed to retain customers with no matching orders.",
    ],
}


STATIC_EXERCISE_SET = {
    "id": "airbnb_general_001",
    "company": STATIC_EXERCISE["company"],
    "dialect": STATIC_EXERCISE["dialect"],
    "business_context": STATIC_EXERCISE["business_context"],
    "tables": STATIC_EXERCISE["tables"],
    "seed_sql": STATIC_EXERCISE["seed_sql"],
    "hidden_datasets": STATIC_EXERCISE["hidden_datasets"],
    "questions": [
        {
            "id": "conversion",
            "difficulty": STATIC_EXERCISE["difficulty"],
            "concepts": STATIC_EXERCISE["concepts"],
            "question": STATIC_EXERCISE["question"],
            "task_summary": STATIC_EXERCISE["task_summary"],
            "requirements": STATIC_EXERCISE["requirements"],
            "reference_sql": STATIC_EXERCISE["reference_sql"],
            "grading": STATIC_EXERCISE["grading"],
            "explanation": STATIC_EXERCISE["explanation"],
            "hints": STATIC_EXERCISE["hints"],
        },
        {
            "id": "customer_mix",
            "difficulty": "medium",
            "concepts": ["aggregation", "grouping"],
            "question": (
                "Report the customer mix by segment. Return segment and customer_count, "
                "with one row per segment, ordered by customer_count descending and then "
                "segment ascending. Include every customer regardless of order activity."
            ),
            "task_summary": (
                "The marketplace strategy team is planning segment-specific programs and needs "
                "a clearer view of who the customer base serves. Describe the current customer "
                "mix across segments."
            ),
            "requirements": [
                "Return segment and customer_count with one row per segment.",
                "Include every customer regardless of order activity.",
                "Order by customer_count descending and then segment ascending.",
            ],
            "reference_sql": """
                SELECT segment, COUNT(*) AS customer_count
                FROM customers
                GROUP BY segment
                ORDER BY customer_count DESC, segment ASC;
            """,
            "grading": {"order_matters": True, "numeric_tolerance": 0.000001},
            "explanation": (
                "Aggregate directly from the customer-grain table so order activity cannot "
                "duplicate customers or remove inactive segments."
            ),
            "hints": [
                "The result only needs one table.",
                "Group at the segment grain before applying the requested ordering.",
            ],
        },
        {
            "id": "completed_orders",
            "difficulty": "medium",
            "concepts": ["joins", "conditional aggregation", "NULL handling"],
            "question": (
                "For every customer segment, report January 2025 completed orders. Return "
                "segment, completed_order_count, and completed_revenue. Count orders whose "
                "status is 'completed' and order_date is >= 2025-01-01 and < 2025-02-01. "
                "Treat missing revenue as zero, retain segments with no completed orders, "
                "and order by segment ascending."
            ),
            "task_summary": (
                "The operations team suspects completed-order activity varied across customer "
                "segments in January. Compare order volume and revenue to identify where "
                "performance was concentrated."
            ),
            "requirements": [
                "Return segment, completed_order_count, and completed_revenue.",
                "Include orders with status = 'completed' from 2025-01-01 inclusive to 2025-02-01 exclusive.",
                "Retain segments with no completed orders and treat missing revenue as zero.",
                "Order by segment ascending.",
            ],
            "reference_sql": """
                SELECT
                    c.segment,
                    COUNT(o.order_id) AS completed_order_count,
                    COALESCE(SUM(o.amount), 0) AS completed_revenue
                FROM customers AS c
                LEFT JOIN orders AS o
                  ON o.customer_id = c.customer_id
                 AND o.status = 'completed'
                 AND o.order_date >= DATE '2025-01-01'
                 AND o.order_date < DATE '2025-02-01'
                GROUP BY c.segment
                ORDER BY c.segment;
            """,
            "grading": {"order_matters": True, "numeric_tolerance": 0.000001},
            "explanation": (
                "Put the qualifying-order filters in the LEFT JOIN condition to retain every "
                "segment, then aggregate only matched order IDs and coalesce missing revenue."
            ),
            "hints": [
                "Start from customers so segments with no matches remain visible.",
                "Filtering the right table in WHERE would turn a LEFT JOIN into an inner join.",
                "COUNT(order_id) counts matches while COUNT(*) would count placeholder rows.",
            ],
        },
    ],
}


def get_static_exercise() -> Exercise:
    """Return a newly validated copy so callers cannot share mutable state."""

    return Exercise.model_validate(STATIC_EXERCISE)


def get_static_exercise_set() -> ExerciseSet:
    """Return three questions that share the bundled schema and datasets."""

    return ExerciseSet.model_validate(STATIC_EXERCISE_SET)

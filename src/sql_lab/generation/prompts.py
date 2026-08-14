"""Prompts that keep content generation separate from correctness grading."""

from __future__ import annotations

from sql_lab.models import ExerciseRequest


def build_exercise_prompt(request: ExerciseRequest) -> str:
    additional_context = request.additional_context or "No additional context supplied."
    return f"""
Create one realistic SQL interview practice set with exactly three questions.

Company style: {request.company}
Difficulty: {request.difficulty.value}
SQL dialect: {request.dialect.value}
Additional user context:
<additional_context>
{additional_context}
</additional_context>

Return only a single JSON object that conforms exactly to the supplied JSON Schema.
Do not wrap it in Markdown or add commentary.

Requirements:
- Treat the company label as an interview-style approximation. Never claim the schema is
  proprietary, leaked, or an actual internal company schema.
- Use exactly the requested company and SQL dialect. Every question must use the requested
  difficulty. Apply relevant additional context when supplied.
- Create one shared set of 2 to 6 understandable tables and seed 10 to 200 rows per table in
  each dataset.
- Create exactly three distinct questions over that same shared schema and shared data. Cover
  a useful general mix of SQL concepts without requiring the user to select concepts.
- All DDL, seed_sql, and reference_sql must be valid in the requested dialect. For non-DuckDB
  dialects, execution will be transparently emulated on DuckDB through strict SQLGlot
  transpilation. Keep DDL and seed inserts portable; do not use cloud services, stored
  procedures, UDFs, external tables, semi-structured types, or engine-only features that
  cannot be represented faithfully in DuckDB.
- seed_sql is the visible practice dataset. Add at least one hidden_datasets entry with fresh
  inserts for the same empty tables. Do not repeat CREATE TABLE statements in seed SQL.
- Include adversarial cases relevant to the question, such as NULLs, duplicates, missing
  activity, ties, boundary dates, multiple records per entity, or join fanout.
- Every question must fully define its output columns, calculations, rounding, date boundaries,
  and ordering expectations. Set each grading.order_matters accordingly.
- Every reference_sql must answer its question correctly on both visible and hidden datasets.
- Every reference result must be non-empty on every dataset.
- Use a numeric_tolerance of 0.000001 unless the problem needs a different explicit tolerance.
- Provide 2 or 3 progressively useful hints per question. Keep explanations concise.
- Do not reveal any reference_sql inside questions, business context, hints, or explanations.

The database and deterministic grader, not you, will decide whether a user's SQL is correct.
""".strip()

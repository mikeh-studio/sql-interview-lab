"""Prompts that keep content generation separate from correctness grading."""

from __future__ import annotations

from data_interview_lab.models import (
    ExerciseRequest,
    QuestionType,
    RoleTrack,
    SessionMode,
    SharedExerciseDataset,
)


ROLE_FOCUS = {
    RoleTrack.PRODUCT_ANALYTICS: (
        "product metrics, funnels, cohort retention, experiments, segmentation, and "
        "launch recommendations"
    ),
    RoleTrack.DATA_SCIENCE: (
        "metric design, experimentation, causal reasoning, anomaly diagnosis, and "
        "decision-ready analysis"
    ),
    RoleTrack.ANALYTICS_ENGINEERING: (
        "canonical metrics, model grain, data quality, reusable transformations, and "
        "stakeholder-facing analytical outputs"
    ),
    RoleTrack.DATA_ENGINEERING: (
        "data modeling, pipeline reliability, late or duplicate records, incremental "
        "processing, and query performance"
    ),
    RoleTrack.AI_PRODUCT_SAFETY: (
        "AI-product adoption or safety metrics, instrumentation, evaluation tradeoffs, "
        "experiments, and false-positive versus false-negative costs"
    ),
}


def build_exercise_prompt(request: ExerciseRequest) -> str:
    additional_context = request.additional_context or "No additional context supplied."
    if request.mode is SessionMode.ADVANCED:
        assert request.role_track is not None
        return _build_advanced_prompt(request, additional_context)
    return _build_standard_prompt(request, additional_context)


def _build_standard_prompt(request: ExerciseRequest, additional_context: str) -> str:
    return f"""
Create one realistic SQL interview practice set with exactly three questions.

Company style (copy this exact label into the top-level company field): {request.company}
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
- Copy the requested company label exactly into the top-level company field and use the
  requested SQL dialect. Every question must use the requested difficulty. Apply relevant
  additional context when supplied.
- Create one shared set of 2 to 6 understandable tables and seed 10 to 200 rows per table in
  each dataset.
- Create exactly three distinct questions over that same shared schema and shared data. Cover
  a useful general mix of SQL concepts without requiring the user to select concepts.
- Keep business_context to one or two short sentences (240 characters maximum). It should
  orient the user without repeating the task or describing every table.
- For each question, set task_summary to a short, interview-style case prompt of 20 to 40
  words. Introduce a fictional stakeholder and the decision or concern motivating the analysis,
  then name the main metric, timeframe when relevant, and grouping dimension. Give enough
  direction to start reasoning, but omit exact output aliases, edge-case rules, rounding, NULL
  handling, and ordering. Example: "A marketplace growth team wants to understand whether
  customer segments convert January demand differently. Compare completed-order conversion and
  revenue by segment to identify where performance diverges."
- For each question, provide 3 to 6 requirements. These must state the exact output columns,
  metric definitions, filters, boundaries, NULL handling, rounding, and ordering needed for
  deterministic grading. Keep question as the complete canonical specification and ensure its
  meaning exactly matches task_summary plus requirements without contradictions.
- All DDL, seed_sql, and reference_sql must be valid in the requested dialect. For non-DuckDB
  dialects, execution will be transparently emulated on DuckDB through strict SQLGlot
  transpilation. Keep DDL and seed inserts portable; do not use cloud services, stored
  procedures, UDFs, external tables, semi-structured types, or engine-only features that
  cannot be represented faithfully in DuckDB.
- seed_sql is the visible practice dataset. Add at least one hidden_datasets entry with fresh
  inserts for the same empty tables. Do not repeat CREATE TABLE statements in seed SQL.
- Include adversarial cases relevant to the question, such as NULLs, duplicates, missing
  activity, ties, boundary dates, multiple records per entity, or join fanout.
- Every canonical question and its requirements must fully define output columns, calculations,
  rounding, date boundaries, and ordering expectations. Set each grading.order_matters accordingly.
- Every reference_sql must answer its question correctly on both visible and hidden datasets.
- Every reference result must be non-empty on every dataset.
- Use a numeric_tolerance of 0.000001 unless the problem needs a different explicit tolerance.
- Provide 2 or 3 progressively useful hints per question. Keep explanations concise.
- Do not reveal any reference_sql inside questions, business context, hints, or explanations.
- Set mode to "standard" and role_track to null.
- Set every question_type to "sql_build". Set starter_sql to null and set clarifications,
  case_rubric, modern_topics, and reference_discussion to empty lists.

The database and deterministic grader, not you, will decide whether a user's SQL is correct.
""".strip()


def _build_advanced_prompt(request: ExerciseRequest, additional_context: str) -> str:
    assert request.role_track is not None
    role_focus = ROLE_FOCUS[request.role_track]
    topics = ", ".join(
        (
            "cohort_retention",
            "funnel_analysis",
            "window_functions",
            "experimentation",
            "causal_inference",
            "metric_design",
            "data_quality",
            "instrumentation",
            "sql_debugging",
            "ai_generated_code_review",
            "data_modeling",
            "pipeline_reliability",
            "query_performance",
            "safety_evaluation",
        )
    )
    return f"""
Create one advanced SQL interview set with exactly three questions. This is a separate,
role-calibrated mode for candidates who already know SQL fundamentals.

Company style (copy this exact label into the top-level company field): {request.company}
Role track: {request.role_track.value}
Role focus: {role_focus}
Difficulty: {request.difficulty.value}
SQL dialect: {request.dialect.value}
Additional user context:
<additional_context>
{additional_context}
</additional_context>

Return only a single JSON object that conforms exactly to the supplied JSON Schema.
Do not wrap it in Markdown or add commentary.

Set-level requirements:
- Set mode to "advanced" and role_track to "{request.role_track.value}".
- Treat the company label as a fictional interview-style approximation. Never claim the schema
  or questions came from that company's private interview bank.
- Use one shared set of 2 to 6 understandable tables. Seed 10 to 200 rows per table in the
  visible dataset and in at least one fresh hidden dataset. Keep Advanced datasets compact:
  use 2 to 4 tables, 10 to 30 visible rows per table, and 5 to 15 hidden rows per table.
- Include realistic imperfect-data conditions across the datasets: NULLs, duplicates, missing
  activity, boundary timestamps, ties, multiple records per entity, logging changes, or fanout.
- Cover at least five distinct modern_topics across the set. Allowed values: {topics}.
- Calibrate content to the requested role focus instead of producing a generic SQL mix.

Question composition and order:
1. sql_build: translate an ambiguous business objective into a correct analytical query. Prefer
   a cohort, retention, funnel, window, or multi-step metric problem. Set starter_sql to null.
2. sql_debug: provide runnable but logically incorrect starter_sql that resembles code inherited
   from a teammate or generated by an AI assistant. The candidate must explain and repair grain,
   join, date, NULL, metric, data-quality, or performance mistakes. starter_sql must be one
   read-only SELECT statement; never include INSERT, UPDATE, DELETE, DDL, or administrative SQL.
3. analytical_case: ask for a decision-oriented analysis plus a concrete SQL output that supports
   the decision. Include experiment or observational reasoning, instrumentation or data-quality
   risks, guardrails, and tradeoffs. SQL correctness remains deterministic; the case rubric is
   for self-review and coaching only, not automated pass/fail.

Staged problem formulation:
- task_summary is the opening interview prompt. It must introduce the stakeholder and decision
  without exposing exact output aliases, formulas, boundaries, NULL rules, or ordering.
- Provide 2 to 6 clarifications for every question. Each item contains a strong
  candidate_question and the interviewer's concise answer. These are revealed only when the
  candidate explicitly asks for interviewer details.
- Provide 3 to 6 exact requirements for deterministic SQL grading. The canonical question must
  match the opening prompt, clarifications, and requirements without contradiction.

Deferred review material:
- Set case_rubric and reference_discussion to empty lists for all three questions. The app adds
  a local role-calibrated self-review framework only if the user asks to view the solution.

Execution and grading requirements:
- All DDL, seed_sql, starter_sql, and reference_sql must be valid in the requested dialect. For
  non-DuckDB dialects, keep them portable enough for strict SQLGlot-to-DuckDB transpilation.
- Every reference_sql must return a non-empty result on visible and hidden datasets.
- Every question must completely define the SQL deliverable after clarifications are revealed:
  columns, calculations, filters, boundaries, NULL handling, rounding, and ordering.
- Set grading.order_matters correctly and normally use numeric_tolerance 0.000001.
- Provide 2 or 3 progressive hints and a concise explanation per question.
- Do not reveal reference_sql in user-visible prompts, clarifications, rubrics, hints, or
  discussion points.

The database and deterministic grader remain the only authority for SQL correctness. The case
rubric supports self-review and optional coaching; it is not an LLM-evaluated hiring score.
""".strip()


def build_advanced_foundation_prompt(request: ExerciseRequest) -> str:
    """Generate the small shared dataset and the first usable question."""

    assert request.role_track is not None
    context = request.additional_context or "No additional context supplied."
    return f"""
Create the foundation for an advanced SQL interview practice set. Return only JSON matching
the supplied schema: one nested dataset object and one nested question object.

Company label (copy exactly): {request.company}
Role track: {request.role_track.value}
Role focus: {ROLE_FOCUS[request.role_track]}
Difficulty: {request.difficulty.value}
SQL dialect: {request.dialect.value}
Additional context: {context}

Dataset requirements:
- Use 2 to 4 portable tables with 10 to 30 visible INSERT rows per table.
- Include one hidden dataset with 5 to 15 fresh INSERT rows per table.
- Include NULLs, missing activity, boundary values, duplicates, ties, or join fanout where useful.
- Keep business_context to at most 240 characters and treat the company as a fictional style.
- Set mode="advanced" and role_track="{request.role_track.value}".
- DDL and inserts must execute through the requested dialect's configured local backend.

First-question requirements:
- Set question_type="sql_build", starter_sql=null, and difficulty="{request.difficulty.value}".
- Ask a realistic case-style SQL build question using the shared data.
- Provide a 20 to 40 word task_summary, 3 to 6 exact requirements, and 2 to 4 interviewer
  clarifications. Include a concise explanation and at most two hints.
- Use modern_topics chosen from cohort_retention, funnel_analysis, window_functions,
  metric_design, data_modeling, and instrumentation.
- reference_sql must return rows on both visible and hidden data.
- Set case_rubric and reference_discussion to empty lists.

The database, not the LLM, decides SQL correctness.
""".strip()


def build_advanced_question_prompt(
    request: ExerciseRequest,
    dataset: SharedExerciseDataset,
    question_type: QuestionType,
) -> str:
    """Generate one follow-up question against an already validated dataset."""

    assert request.role_track is not None
    if question_type is QuestionType.SQL_BUILD:
        composition = """
Set question_type="sql_build" and starter_sql=null. Ask a case-style build problem.
Use modern_topics from cohort_retention, funnel_analysis, window_functions, and metric_design.
"""
    elif question_type is QuestionType.SQL_DEBUG:
        composition = """
Set question_type="sql_debug". Provide one read-only starter_sql query that runs but is
logically wrong on at least one dataset. Focus on grain, fanout, NULLs, dates, or metric logic.
Use modern_topics including sql_debugging, data_quality, and ai_generated_code_review.
"""
    else:
        composition = """
Set question_type="analytical_case" and starter_sql=null. Ask for a decision-oriented SQL
output involving measurement, instrumentation, tradeoffs, or experiment/causal reasoning.
Use modern_topics including experimentation, causal_inference, metric_design, and
instrumentation. Set case_rubric and reference_discussion to empty lists; those review-only
extras are intentionally deferred until the solution is opened.
"""
    return f"""
Create exactly one {question_type.value} question for this advanced SQL interview dataset.
Return only JSON matching the supplied schema, with the question nested under "question".

Company: {request.company}
Role track: {request.role_track.value}
Role focus: {ROLE_FOCUS[request.role_track]}
Difficulty: {request.difficulty.value}
Additional context: {request.additional_context or "No additional context supplied."}

Shared dataset (use exactly; do not add tables or rows):
{dataset.model_dump_json()}

{composition.strip()}

Provide a 20 to 40 word task_summary, 3 to 6 exact requirements, 2 to 4 staged interviewer
clarifications, a concise explanation, and at most two hints. The canonical question,
requirements, and clarifications must agree. reference_sql must execute and return a non-empty
result on visible and hidden datasets. Do not reveal reference_sql in user-visible text.
Set grading accurately and normally use numeric_tolerance 0.000001. The database remains the
only correctness authority.
""".strip()

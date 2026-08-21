"""Interactive local SQL practice loop."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
import webbrowser
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table

from sql_lab import __version__
from sql_lab.config import Settings
from sql_lab.engines.base import QueryResult, SQLExecutionError
from sql_lab.engines.factory import (
    SUPPORTED_DIALECTS,
    create_engine,
    execution_mode,
)
from sql_lab.exercises import get_static_exercise
from sql_lab.generation import ExerciseGenerationError
from sql_lab.grading.grader import (
    GradeResult,
    Grader,
    ReferenceSolutionError,
)
from sql_lab.llm import LLMProviderError
from sql_lab.models import Dialect, Difficulty, Exercise, ExerciseRequest
from sql_lab.services import generate_exercise


app = typer.Typer(
    add_completion=False,
    help="Practice generated SQL interviews against a real local database.",
)
console = Console()


def _display_value(value: object) -> str:
    return "NULL" if value is None else str(value)


def render_result(result: QueryResult, *, max_rows: int = 25) -> None:
    if not result.columns:
        console.print(
            f"[green]Statement completed[/green] ({result.duration_ms:.1f} ms)"
        )
        return

    table = Table(show_header=True, header_style="bold cyan")
    for column in result.columns:
        table.add_column(column)
    for row in result.rows[:max_rows]:
        table.add_row(*(_display_value(value) for value in row))
    console.print(table)
    suffix = f", showing first {max_rows}" if len(result.rows) > max_rows else ""
    console.print(
        f"[dim]{len(result.rows)} row(s){suffix} in {result.duration_ms:.1f} ms[/dim]"
    )


def _row_as_text(columns: tuple[str, ...], row: tuple[object, ...] | None) -> str:
    if row is None:
        return "<missing row>"
    if len(columns) != len(row):
        return repr(row)
    return ", ".join(
        f"{column} = {_display_value(value)}" for column, value in zip(columns, row)
    )


def render_grade(grade: GradeResult) -> None:
    if grade.passed:
        console.print(
            f"\n[bold green]PASS[/bold green] — matched on all "
            f"{len(grade.datasets)} grading dataset(s)."
        )
        return

    console.print("\n[bold red]NOT YET[/bold red] — deterministic results differ.")
    hidden_index = 0
    for dataset in grade.datasets:
        if dataset.hidden:
            hidden_index += 1
        if dataset.passed:
            continue
        if dataset.hidden:
            label = f"Hidden dataset {hidden_index}"
        else:
            label = "Visible dataset"
        console.print(f"\n[bold]{label}[/bold]")
        if dataset.execution_error is not None:
            console.print(
                f"[red]Database error:[/red] {escape(dataset.execution_error)}"
            )
            continue

        comparison = dataset.comparison
        assert comparison is not None
        if not comparison.columns_match:
            console.print(
                f"Expected columns {comparison.expected_columns}, received "
                f"{comparison.actual_columns}."
            )
        if comparison.expected_row_count != comparison.actual_row_count:
            console.print(
                f"Expected {comparison.expected_row_count} rows, received "
                f"{comparison.actual_row_count}."
            )
        if comparison.differing_rows:
            console.print(f"{comparison.differing_rows} row(s) differ.")
            for index, mismatch in enumerate(comparison.examples, start=1):
                console.print(f"  [dim]Example {index}[/dim]")
                console.print(
                    "    expected: "
                    + _row_as_text(comparison.expected_columns, mismatch.expected)
                )
                console.print(
                    "    actual:   "
                    + _row_as_text(comparison.actual_columns, mismatch.actual)
                )


def _show_exercise(exercise: Exercise) -> None:
    console.rule(
        f"[bold]{escape(exercise.company.upper())} — "
        f"{exercise.difficulty.value.upper()}[/bold]"
    )
    console.print(f"[dim]{escape(exercise.business_context)}[/dim]\n")
    mode = execution_mode(exercise.dialect)
    console.print(
        f"[dim]SQL dialect: {exercise.dialect.value} · "
        f"{'native execution' if mode == 'native' else 'emulated on DuckDB'}[/dim]\n"
    )
    console.print("[bold]Tables[/bold]")
    for table in exercise.tables:
        console.print(f"  • [cyan]{table.name}[/cyan] — {escape(table.description)}")
    console.print("\n[bold]Question[/bold]")
    console.print(escape(exercise.question))
    console.print(
        "\n[dim]Enter SQL; end with ';' to run it. Commands: .run .submit .schema "
        ".tables .hint .solution .clear .reset .new .quit[/dim]"
    )


def _show_schema(exercise: Exercise) -> None:
    for table in exercise.tables:
        console.print(
            f"\n[bold cyan]{table.name}[/bold cyan] — {escape(table.description)}"
        )
        console.print(Syntax(table.ddl.strip(), "sql", theme="ansi_dark"))


def _request_from_options(
    company: str | None,
    dialect: str | None,
    difficulty: str | None,
    additional_context: str | None,
) -> ExerciseRequest:
    selected_company = company or Prompt.ask(
        "Company / company style", default="Airbnb"
    )
    selected_dialect = dialect or Prompt.ask(
        "SQL dialect",
        choices=[
            "duckdb",
            "redshift",
            "bigquery",
            "snowflake",
            "databricks",
            "presto",
        ],
        default="duckdb",
    )
    selected_difficulty = difficulty or Prompt.ask(
        "Difficulty", choices=[item.value for item in Difficulty], default="medium"
    )
    try:
        difficulty_value = Difficulty(selected_difficulty.casefold())
    except ValueError as exc:
        raise typer.BadParameter("Difficulty must be easy, medium, or hard") from exc

    selected_context = additional_context
    if selected_context is None:
        selected_context = Prompt.ask(
            "Additional context (optional)", default="", show_default=False
        )

    try:
        dialect_value = Dialect(selected_dialect.casefold())
    except ValueError as exc:
        raise typer.BadParameter(
            "Dialect must be duckdb, redshift, bigquery, snowflake, databricks, or presto"
        ) from exc
    if dialect_value not in SUPPORTED_DIALECTS:
        raise typer.BadParameter(
            "Dialect must be duckdb, redshift, bigquery, snowflake, databricks, or presto"
        )

    return ExerciseRequest(
        company=selected_company,
        dialect=dialect_value,
        difficulty=difficulty_value,
        additional_context=selected_context,
    )


def _generate_exercise(
    provider_name: str,
    request: ExerciseRequest,
    settings: Settings,
) -> Exercise:
    console.print(
        f"\n[cyan]Generating {request.dialect.value} questions with {provider_name}, "
        "then validating every reference query against the configured execution "
        "backend...[/cyan]"
    )
    return generate_exercise(request, provider_name, settings)


def _browser_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{browser_host}:{port}"


def _sql_lab_is_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=0.6) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return (
        response.status == 200
        and payload.get("status") == "ok"
        and payload.get("engine") == "duckdb"
        and payload.get("version") == __version__
    )


def _port_is_in_use(host: str, port: int) -> bool:
    connect_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((connect_host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _open_web_browser(url: str) -> None:
    try:
        opened = webbrowser.open(url)
    except webbrowser.Error:
        opened = False
    if not opened:
        console.print(f"[yellow]Open this address in your browser:[/yellow] {url}")


def _launch_web(host: str, port: int, *, open_browser: bool) -> None:
    import uvicorn

    url = _browser_url(host, port)
    if _sql_lab_is_running(url):
        console.print(
            f"[bold green]SQL Interview Lab[/bold green] is already running at {url}"
        )
        if open_browser:
            _open_web_browser(url)
        return
    if _port_is_in_use(host, port):
        raise ValueError(
            f"Port {port} is already used by another application. "
            f"Try `sql-lab --web --port {port + 1}`."
        )

    console.print(f"[bold green]SQL Interview Lab[/bold green] is running at {url}")
    console.print("[dim]Press Ctrl+C to stop the local server.[/dim]")
    if open_browser:
        timer = threading.Timer(0.8, _open_web_browser, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run("sql_lab.web.app:app", host=host, port=port, log_level="info")


def _current_sql(buffer: list[str]) -> str:
    return "\n".join(buffer).strip()


def _run_practice_session(exercise: Exercise) -> str:
    hint_index = 0
    buffer: list[str] = []
    engine = create_engine(exercise.dialect)
    engine.setup(exercise)
    _show_exercise(exercise)
    try:
        while True:
            try:
                line = Prompt.ask("[bold green]sql>[/bold green]", default="")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Leaving SQL Interview Lab.[/dim]")
                return "quit"

            stripped = line.strip()
            if stripped.startswith("."):
                command = stripped.casefold()
                if command == ".quit":
                    return "quit"
                if command == ".new":
                    return "new"
                if command == ".schema":
                    _show_schema(exercise)
                    continue
                if command == ".tables":
                    console.print(", ".join(table.name for table in exercise.tables))
                    continue
                if command == ".hint":
                    if hint_index >= len(exercise.hints):
                        console.print("[dim]No more hints.[/dim]")
                    else:
                        console.print(
                            f"[yellow]Hint:[/yellow] "
                            f"{escape(exercise.hints[hint_index])}"
                        )
                        hint_index += 1
                    continue
                if command == ".solution":
                    console.print(
                        "[yellow]Solution explicitly requested; revealing reference SQL.[/yellow]"
                    )
                    console.print(
                        Syntax(exercise.reference_sql.strip(), "sql", theme="ansi_dark")
                    )
                    continue
                if command == ".clear":
                    buffer.clear()
                    console.print("[dim]SQL buffer cleared.[/dim]")
                    continue
                if command == ".reset":
                    engine.setup(exercise)
                    console.print("[dim]Visible database reset from seed data.[/dim]")
                    continue
                if command in {".run", ".submit"}:
                    sql = _current_sql(buffer)
                    if not sql:
                        console.print("[yellow]SQL buffer is empty.[/yellow]")
                        continue
                    if command == ".run":
                        try:
                            render_result(engine.execute(sql))
                        except SQLExecutionError as exc:
                            console.print(
                                f"[red]Database error:[/red] {escape(str(exc))}"
                            )
                    else:
                        try:
                            render_grade(Grader().grade(exercise, sql))
                        except ReferenceSolutionError as exc:
                            console.print(
                                f"[red]Exercise error:[/red] {escape(str(exc))}"
                            )
                    continue
                if command == ".help":
                    console.print(
                        ".run .submit .schema .tables .hint .solution .clear "
                        ".reset .new .quit"
                    )
                    continue
                console.print(f"[yellow]Unknown command:[/yellow] {escape(stripped)}")
                continue

            if not stripped:
                continue
            buffer.append(line)
            if stripped.endswith(";"):
                try:
                    render_result(engine.execute(_current_sql(buffer)))
                except SQLExecutionError as exc:
                    console.print(f"[red]Database error:[/red] {escape(str(exc))}")
            else:
                console.print(
                    "[dim]... SQL added to buffer; end with ';' or use .run[/dim]"
                )
    finally:
        engine.close()


@app.command()
def main(
    web: Annotated[
        bool,
        typer.Option("--web", help="Launch the local HackerRank-style browser UI."),
    ] = False,
    host: Annotated[
        str,
        typer.Option("--host", help="Host used by --web."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", min=1, max=65535, help="Port used by --web."),
    ] = 8765,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="Do not open a browser automatically."),
    ] = False,
    llm: Annotated[
        str | None,
        typer.Option("--llm", help="LLM provider: codex (default) or claude."),
    ] = None,
    static: Annotated[
        bool,
        typer.Option("--static", help="Use the bundled offline SQL exercise."),
    ] = False,
    company: Annotated[str | None, typer.Option("--company")] = None,
    dialect: Annotated[
        str | None,
        typer.Option("--dialect", help="SQL dialect for all three questions."),
    ] = None,
    difficulty: Annotated[str | None, typer.Option("--difficulty")] = None,
    additional_context: Annotated[
        str | None,
        typer.Option(
            "--additional-context",
            help="Optional guidance for the generated question set.",
        ),
    ] = None,
) -> None:
    """Practice generated SQL interviews against a real local database."""

    try:
        if web:
            _launch_web(host, port, open_browser=not no_open)
            return
        settings = Settings.from_env()
        provider_name = llm or settings.llm_provider
        request = None
        if not static:
            request = _request_from_options(
                company, dialect, difficulty, additional_context
            )

        while True:
            if static:
                exercise = get_static_exercise()
            else:
                assert request is not None
                exercise = _generate_exercise(provider_name, request, settings)
            action = _run_practice_session(exercise)
            if action == "quit":
                break
    except (
        ExerciseGenerationError,
        LLMProviderError,
        SQLExecutionError,
        ValueError,
    ) as exc:
        console.print(
            f"[bold red]Could not start SQL Interview Lab:[/bold red] {escape(str(exc))}"
        )
        if not static:
            console.print("[dim]Try `sql-lab --static` for the offline exercise.[/dim]")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()

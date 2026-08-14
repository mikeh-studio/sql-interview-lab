# SQL Interview Lab

SQL Interview Lab is a local SQL interview practice environment with a browser workspace
and terminal interface. An LLM creates the exercise content; DuckDB executes both the
learner's query and a hidden reference query; a deterministic grader compares the actual
results.

The current MVP includes Phase 1 and Phase 2:

- an offline static exercise for a zero-LLM execution/grading loop
- structured three-question set generation through the Codex CLI by default
- an interchangeable local CLI provider for Claude
- Pydantic validation for every generated exercise
- native DuckDB execution plus explicitly labeled warehouse-dialect emulation
- fresh in-memory DuckDB databases for runs and submissions
- visible and hidden grading datasets
- result comparison for columns, rows, duplicates, NULLs, ordering, and numeric tolerance
- a company-first browser flow with preset or user-entered companies
- optional free-text context applied to the complete question set
- exactly three questions sharing one schema and the same visible/hidden datasets
- a split question/editor/results workspace with real example rows from DuckDB
- resumable local browser history with append-only submission records
- a Rich interactive practice shell

Company labels describe fictional interview-style approximations. The project does not
claim that generated schemas represent proprietary company systems.

## Why execution, not LLM grading

An LLM is useful for creating business context, schemas, sample data, questions, hints,
and explanations. It is not the source of truth for correctness.

```text
LLM provider
  -> validated exercise JSON
  -> shared DDL + visible/hidden seed data + 3 questions and reference queries

user SQL -----------------------> fresh DuckDB -> actual result
reference SQL -> separate fresh DuckDB --------> expected result
                                                   |
actual result + expected result -> deterministic comparator -> pass/fail + diff
```

The user's SQL never has to resemble the reference SQL. Different queries pass when they
produce the same columns and values under the exercise's ordering and tolerance rules.

## Architecture

```text
src/sql_lab/
├── cli.py                    # terminal UI and local web launcher
├── config.py                 # environment-backed provider configuration
├── models.py                 # strict exercise/request schemas
├── services.py               # shared generation + runtime validation
├── engines/
│   ├── base.py               # SQLEngine contract
│   ├── duckdb_engine.py      # native in-memory DuckDB backend
│   ├── emulated_duckdb.py    # strict SQLGlot-to-DuckDB translation
│   └── factory.py            # native/emulated backend selection
├── exercises/
│   └── static.py             # offline Phase 1 exercise
├── generation/
│   ├── prompts.py            # structured generation contract
│   └── generator.py          # strict JSON parsing + Pydantic validation
├── grading/
│   ├── compare.py            # deterministic result comparison
│   └── grader.py             # isolated execution across all datasets
├── history/
│   ├── base.py               # backend-neutral HistoryRepository contract
│   └── sqlite_repository.py  # local SQLite snapshots and submissions
├── llm/
    ├── base.py               # LLMProvider interface
    ├── command.py            # shell-free subprocess transport
    ├── codex_cli.py          # Codex structured-output adapter
    └── claude_cli.py         # Claude structured-output adapter
└── web/
    ├── app.py                # local FastAPI session/API boundary
    ├── sessions.py           # isolated in-memory practice sessions
    └── static/               # responsive HTML/CSS/JavaScript workspace
```

Generation, execution, grading, and presentation communicate through typed domain
objects. DuckDB is the native backend. Redshift, BigQuery, Snowflake, Databricks SQL,
and Presto use a separate, clearly labeled emulation backend that parses the selected
dialect with SQLGlot, translates supported SQL to DuckDB, and fails when SQLGlot reports
an unsupported translation. Emulation is useful for local practice, but it is not claimed
to reproduce every native warehouse semantic.

## Installation

Python 3.12 or newer is required.

```bash
cd /path/to/sql-interview-lab
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

On a machine where a newer Python has a different executable name, use that executable
instead (for example, `python3.13`).

## Launch the browser interface

```bash
sql-lab --web
```

This starts a local server at `http://127.0.0.1:8765` and opens the interface. Use a
different port or keep the browser closed when needed:

```bash
sql-lab --web --port 9000 --no-open
```

If the lab is already running, repeating `sql-lab --web` reopens that existing session
instead of failing on the occupied port. If your shell cannot find `sql-lab`, activate the
project environment first:

```bash
source .venv/bin/activate
sql-lab --web
```

The browser journey is deliberately staged:

1. Select a preset company style or enter any company or organization name. No question
   is generated before this selection.
2. Choose a SQL dialect, difficulty, and local CLI provider, and optionally describe
   extra context.
3. Generate three questions over one shared dataset, or use the instant Airbnb demo.
4. Move among the three questions while inspecting the same DDL and example rows.
5. Write and run SQL, then submit each answer against visible and hidden datasets.
6. Open **Previous sessions** to resume or delete locally saved work.

Run resets the visible database from seed data before every execution. The web response
does not include seed SQL, hidden datasets, or reference SQL. The reference solution is
returned only after the user explicitly chooses **View solution** and confirms.

## Local session history

Browser sessions are saved by default to:

```text
~/.sql-interview-lab/history.db
```

Each three-question set stores one validated exercise snapshot plus compact, append-only
submission records. History also remembers the latest submitted SQL, pass/fail state,
revealed-hint count, and whether the solution was revealed. It does **not** persist
in-memory DuckDB databases, routine `.run` output, expected result tables, credentials, or
provider environment variables.

Use the **Save this session locally** checkbox to opt out before generating a set. From
**Previous sessions**, a saved set can be resumed after a server restart, deleted
individually, or cleared in full. The active session is protected from deletion until you
leave it. By default, the oldest session is removed after 200 saved sessions.

The path and retention limit are configurable:

```bash
export SQL_LAB_HISTORY_DB='/path/to/sql-lab-history.db'
export SQL_LAB_HISTORY_LIMIT=200
sql-lab --web
```

The application writes through a `HistoryRepository` interface. SQLite remains the local
operational store; a future BigQuery exporter can map the same stable IDs, UTC timestamps,
typed metadata, schema version, exercise JSON, and append-only submissions without
changing the practice-session code. Cloud export is not enabled in this release.

## Security and privacy

Keep the web server on its default `127.0.0.1` address. The MVP has no authentication and
accepts SQL that executes through DuckDB, so it is not safe to expose on a public interface
or untrusted network. Generated exercises and personal attempt history remain local and
must not be added to source control. See [SECURITY.md](SECURITY.md) for the complete local
deployment and practice-data guidance.

## Run the offline exercise

No LLM tool, API key, or network access is needed:

```bash
sql-lab --static
```

Useful commands inside the shell:

| Command | Behavior |
| --- | --- |
| `.run` | Execute the current SQL buffer on the visible database |
| `.submit` | Grade the buffer on every fresh visible/hidden dataset |
| `.schema` | Show table descriptions and DDL |
| `.tables` | List tables |
| `.hint` | Reveal the next hint |
| `.solution` | Explicitly reveal the reference SQL |
| `.clear` | Clear the SQL buffer |
| `.reset` | Recreate the visible in-memory database |
| `.new` | Start another exercise |
| `.quit` | Exit |

Ending a SQL statement with `;` runs it immediately. `.submit` never compares SQL text
and does not reveal the reference SQL.

## Codex CLI setup and generated exercises

Codex is the default provider. Install and sign in using the
[official Codex CLI instructions](https://learn.chatgpt.com/docs/codex/cli). Verify that
this works before starting the lab:

```bash
codex --version
```

Then run:

```bash
sql-lab
```

or provide selections non-interactively before entering the SQL shell:

```bash
sql-lab \
  --llm codex \
  --company "Acme Health" \
  --dialect snowflake \
  --difficulty medium \
  --additional-context "Focus on subscription retention and patient engagement"
```

The adapter invokes `codex exec` without a shell, passes the prompt on stdin, uses a
read-only sandbox, requests a response matching the Exercise JSON Schema, and validates
the returned JSON again locally. Codex CLI authentication is reused; this application
does not require an API credential.

The command prefix and timeout are configurable without changing application code:

```bash
export SQL_LAB_CODEX_COMMAND='codex exec --ephemeral --sandbox read-only --skip-git-repo-check --color never'
export SQL_LAB_LLM_TIMEOUT=600
sql-lab --llm codex
```

The default generation timeout is 600 seconds because a request now builds and validates
three complete questions. Override it with `SQL_LAB_LLM_TIMEOUT` when needed.

`SQL_LAB_CODEX_COMMAND` is parsed as an argv vector and executed with `shell=False`.
Do not include the final prompt sentinel or `--output-schema`; the adapter supplies both.

## Example session

```text
$ sql-lab --static
────────────────────── AIRBNB-STYLE — MEDIUM ──────────────────────
Tables
  • customers — One row per marketplace customer account.
  • orders — One row per order attempt, including cancelled orders.

Question
For every customer segment, report January 2025 completed-order performance...

sql> SELECT segment, COUNT(*) AS customer_count ...;
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ segment    ┃ customer_count ┃ converting_customers ┃ conversion_rate ┃ completed_revenue ┃
┗━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━┛
sql> .submit

PASS — matched on all 2 grading dataset(s).
```

## Optional Claude CLI provider

If the `claude` CLI is installed and authenticated locally, select it with:

```bash
claude --version
sql-lab --llm claude
```

Override its command prefix if needed:

```bash
export SQL_LAB_CLAUDE_COMMAND='claude --print --no-session-persistence --permission-mode dontAsk --tools ""'
```

The Claude adapter also uses stdin, `shell=False`, and the CLI's native JSON Schema flag.

## Optional API providers

The `LLMProvider` boundary is ready for an API-backed adapter, but `openai-api` is
intentionally not implemented in this Phase 1/2 MVP. No API package or secret is needed.
Phase 4 will add an optional adapter that reads credentials from environment variables;
it will not replace Codex CLI as the default.

## Dialect support

| Dialect | Model value | Execution status |
| --- | --- | --- |
| DuckDB | `duckdb` | Fully supported, native in-memory execution |
| Amazon Redshift | `redshift` | Emulated locally through SQLGlot and DuckDB |
| BigQuery (GoogleSQL) | `bigquery` | Emulated locally through SQLGlot and DuckDB |
| Snowflake | `snowflake` | Emulated locally through SQLGlot and DuckDB |
| Databricks SQL | `databricks` | Emulated locally through SQLGlot and DuckDB |
| Presto | `presto` | Emulated locally through SQLGlot and DuckDB |

The selected dialect is used for generated DDL, seed SQL, reference SQL, user-query
parsing, and grading. The browser and CLI always label whether execution is native or
emulated. Emulation deliberately excludes cloud-only services, external objects, UDFs,
semi-structured features that cannot be represented faithfully, and engine-specific
behavior SQLGlot cannot translate. Native warehouse backends remain a later extension of
the `SQLEngine` interface.

## Tests

```bash
pytest
```

The suite covers correct and equivalent SQL, incorrect results and mismatch examples,
ordering, duplicate rows, NULLs, numeric tolerance, syntax errors, schema validation,
DuckDB reset/isolation, visible-versus-hidden grading, CLI subprocess failures, and
malformed LLM JSON, and all five emulated dialect paths. History tests cover SQLite
persistence across restarts, append-only submissions, retention pruning, opt-out, resume,
and deletion. Browser API tests also cover
company gating, dialect selection and execution labels, three-question sets,
shared table previews, custom company and optional-context forwarding, session reseeding,
query errors, hints, explicit solution access, and visible/hidden submission results.

## Roadmap

- Phase 3: persistent company packs, post-grade LLM feedback, and explicit
  Practice/Interview/Review policies
- Phase 4: optional OpenAI API provider and native engines for additional dialects
- Later: timers, optional BigQuery history export, more than one hidden dataset, editor
  autocomplete, and saved company-specific exercise analytics

# Data Interview Lab

Data Interview Lab is a local data-interview practice environment with a browser workspace
and terminal interface. The current release focuses on SQL; Python practice is planned for
a later iteration. An LLM creates exercise content, DuckDB executes both the learner's query
and a hidden reference query, and a deterministic grader compares the actual results.

The current SQL experience includes:

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
- task-first prompts with compact business context and expandable exact requirements
- an additive Advanced Mode with focus-area SQL build, debugging, and analytical-case tasks
- staged interviewer clarifications plus a non-scoring case self-review rubric
- a Query Doctor tab that executes and grades first, then requests structured CLI coaching
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
                                                   |
                                                   v
                                optional Query Doctor CLI explanation
```

The user's SQL never has to resemble the reference SQL. Different queries pass when they
produce the same columns and values under the exercise's ordering and tolerance rules.

## Architecture

```text
src/data_interview_lab/
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
│   └── static.py             # offline SQL exercise
├── generation/
│   ├── prompts.py            # structured generation contract
│   └── generator.py          # strict JSON parsing + Pydantic validation
├── grading/
│   ├── compare.py            # deterministic result comparison
│   └── grader.py             # isolated execution across all datasets
├── feedback/
│   └── query_doctor.py       # post-grade structured CLI coaching
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
cd /path/to/data-interview-lab
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

On a machine where a newer Python has a different executable name, use that executable
instead (for example, `python3.13`).

## Launch the browser interface

```bash
data-interview-lab --web
```

This starts a local server at `http://127.0.0.1:8765` and opens the interface. Use a
different port or keep the browser closed when needed:

```bash
data-interview-lab --web --port 9000 --no-open
```

If the lab is already running, repeating `data-interview-lab --web` reopens that existing session
instead of failing on the occupied port. If your shell cannot find `data-interview-lab`, activate the
project environment first:

```bash
source .venv/bin/activate
data-interview-lab --web
```

The former `sql-lab` command remains available as a compatibility alias during the rename.

The browser journey is deliberately staged:

1. Select a preset company style or enter any company or organization name. No question
   is generated before this selection.
2. Choose a SQL dialect, difficulty, and local CLI provider, and optionally describe
   extra context.
3. Generate three questions over one shared dataset, or use the instant Airbnb demo.
4. Move among the three questions while inspecting the same DDL and example rows.
5. Write and run SQL, then submit each answer against visible and hidden datasets.
6. Open **Query Doctor** to run the same deterministic checks and ask the selected CLI
   provider for focused coaching without revealing the reference SQL.
7. Open **Previous sessions** to resume or delete locally saved work.

Standard Mode preserves the original three-question SQL practice flow. Advanced Mode adds a
focus area and generates one SQL construction problem, one inherited or AI-generated SQL
debugging problem, and one decision-oriented analytical case with a deterministically graded SQL
deliverable. Advanced requirements and interviewer answers remain hidden until explicitly
requested. The analytical-case rubric is for self-review and optional coaching; it never overrides
the database grader or produces an automated hiring score.

Advanced generation is progressive: it creates a compact shared dataset and validates Question 1
first, then opens the lab while Questions 2 and 3 generate concurrently. A matching dataset can be
reused from the local cache when **Reuse a matching local dataset** is enabled. Review-only case
rubric content is assembled only when the solution is opened, keeping it out of the initial LLM
payload.

Run resets the visible database from seed data before every execution. The web response
does not include seed SQL, hidden datasets, or reference SQL. The reference solution is
returned only after the user explicitly chooses **View solution** and confirms.

## Local session history

Browser sessions are saved by default to:

```text
~/.data-interview-lab/history.db
```

If the new database does not exist but `~/.sql-interview-lab/history.db` does, the application
reuses that existing database in place. It does not copy, move, or delete practice history.

Each three-question set stores one validated exercise snapshot plus compact, append-only
submission records. History also remembers the latest submitted SQL, pass/fail state,
revealed-hint count, and whether the solution was revealed. It does **not** persist
in-memory DuckDB databases, routine `.run` output, expected result tables, credentials, or
provider environment variables.

The same private SQLite file also keeps a compact generation audit log: stages, elapsed time,
provider and CLI identity, resolved model when available, cache usage, prompt count, and token
usage reported by the CLI. Prompts, LLM responses, reference SQL, and generated rows are not copied
into that audit log. The separate dataset cache necessarily stores the generated shared DDL and
rows locally so they can be reused; it retains the 50 most recently used datasets. Disable the
reuse checkbox to bypass it for a new generation. **Clear all history** also removes generation
logs and cached datasets.

Use the **Save this session locally** checkbox to opt out before generating a set. From
**Previous sessions**, a saved set can be resumed after a server restart, deleted
individually, or cleared in full. The active session is protected from deletion until you
leave it. By default, the oldest session is removed after 200 saved sessions.

The path and retention limit are configurable:

```bash
export DATA_INTERVIEW_LAB_HISTORY_DB='/path/to/data-interview-lab-history.db'
export DATA_INTERVIEW_LAB_HISTORY_LIMIT=200
data-interview-lab --web
```

Renamed `DATA_INTERVIEW_LAB_*` variables take precedence. Existing `SQL_LAB_*` variables
remain supported during the compatibility period.

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
data-interview-lab --static
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
data-interview-lab
```

or provide selections non-interactively before entering the SQL shell:

```bash
data-interview-lab \
  --llm codex \
  --company "Acme Health" \
  --dialect snowflake \
  --difficulty medium \
  --additional-context "Focus on subscription retention and patient engagement"
```

The adapter invokes `codex exec` without a shell, passes the prompt on stdin, uses a
read-only sandbox, requests a response matching the Exercise JSON Schema, and validates
the returned JSON again locally. It uses the Codex JSONL event stream to capture reported
token usage and the final-message file to keep structured output separate from progress events.
Codex CLI authentication is reused; this application does not require an API credential.

The command prefix and timeout are configurable without changing application code:

```bash
export DATA_INTERVIEW_LAB_CODEX_COMMAND='codex exec --ephemeral --sandbox read-only --skip-git-repo-check --color never'
export DATA_INTERVIEW_LAB_LLM_TIMEOUT=600
export DATA_INTERVIEW_LAB_ADVANCED_LLM_TIMEOUT=1200
data-interview-lab --llm codex
```

Standard Mode has a 600-second generation timeout. Each Advanced Mode provider call has a
separate 1,200-second default; Question 1 and its compact dataset are generated first, while the
remaining two calls run concurrently after Question 1 passes SQL validation. Override the
deadlines independently with `DATA_INTERVIEW_LAB_LLM_TIMEOUT` and `DATA_INTERVIEW_LAB_ADVANCED_LLM_TIMEOUT`.

`DATA_INTERVIEW_LAB_CODEX_COMMAND` is parsed as an argv vector and executed with `shell=False`.
Do not include the final prompt sentinel or `--output-schema`; the adapter supplies both.

## Example session

```text
$ data-interview-lab --static
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
data-interview-lab --llm claude
```

Override its command prefix if needed:

```bash
export DATA_INTERVIEW_LAB_CLAUDE_COMMAND='claude --print --no-session-persistence --permission-mode dontAsk --tools ""'
```

The Claude adapter also uses stdin, `shell=False`, and the CLI's native JSON Schema flag.

## Optional API providers

The `LLMProvider` boundary is ready for an API-backed adapter, but `openai-api` is not
implemented in the current release. No API package or secret is needed. A future optional
adapter can read credentials from environment variables without replacing Codex CLI as the
default.

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
malformed LLM JSON, Codex token telemetry, and all five emulated dialect paths. History tests cover SQLite
persistence across restarts, append-only submissions, retention pruning, opt-out, resume,
deletion, generation-event persistence, and dataset caching. Browser API tests also cover
company gating, dialect selection and execution labels, three-question sets,
shared table previews, custom company and optional-context forwarding, session reseeding,
query errors, hints, explicit solution access, visible/hidden submission results, and the
deterministic-before-LLM Query Doctor contract. The progressive API test verifies Question 1-first
delivery, concurrent set completion, cache reuse, and aggregated model/token metadata.

## Roadmap

- a Python interview-practice track alongside the current SQL track
- persistent company packs and explicit Practice/Interview/Review policies
- an optional OpenAI API provider and native engines for additional SQL dialects
- timers, optional BigQuery history export, additional hidden datasets, editor
  autocomplete, and saved company-specific exercise analytics

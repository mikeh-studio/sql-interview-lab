# Security and privacy

SQL Interview Lab is a local development tool. It has no authentication layer and allows
the person using the interface to execute SQL through DuckDB.

## Keep the server local

Run the browser interface on its default loopback address:

```bash
sql-lab --web
```

Do not bind the application to `0.0.0.0`, a public interface, or an untrusted network.
DuckDB SQL can access local resources, and this MVP is not designed as a hosted or
multi-user service.

## Private practice data

Generated exercises, additional context, submitted SQL, grading summaries, hints, and
solution-reveal activity can be stored in the local history database. The default path is:

```text
~/.sql-interview-lab/history.db
```

History databases, environment files, virtual environments, caches, and common credential
file patterns must not be committed. Before sharing this repository, review both the Git
working tree and complete Git history for private exercise content and credentials.

The application invokes configured LLM command-line tools locally. Keep authentication in
those tools or environment variables; never place credentials in application configuration
or generated exercise files.

## Reporting an issue

While the repository is private, report security or privacy concerns directly to the
repository owner. Do not include credentials, personal practice data, or other sensitive
material in an issue.

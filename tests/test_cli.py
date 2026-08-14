from __future__ import annotations

import pytest
import typer

from sql_lab import cli
from sql_lab.models import Dialect


def test_relaunch_opens_existing_healthy_lab(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(cli, "_sql_lab_is_running", lambda _: True)
    monkeypatch.setattr(cli, "_open_web_browser", opened.append)

    cli._launch_web("127.0.0.1", 8765, open_browser=True)

    assert opened == ["http://127.0.0.1:8765"]


def test_occupied_port_from_another_app_fails_clearly(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_sql_lab_is_running", lambda _: False)
    monkeypatch.setattr(cli, "_port_is_in_use", lambda *_: True)

    with pytest.raises(ValueError, match="already used.*--port 8766"):
        cli._launch_web("127.0.0.1", 8765, open_browser=False)


def test_wildcard_host_uses_loopback_browser_url() -> None:
    assert cli._browser_url("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert cli._browser_url("::", 8765) == "http://127.0.0.1:8765"


def test_health_check_rejects_stale_server_version(monkeypatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b'{"status":"ok","engine":"duckdb","version":"0.3.0"}'

    monkeypatch.setattr(
        cli.urllib.request, "urlopen", lambda *_args, **_kwargs: Response()
    )

    assert cli._sql_lab_is_running("http://127.0.0.1:8765") is False


def test_cli_accepts_only_the_six_exposed_dialects() -> None:
    request = cli._request_from_options("Airbnb", "bigquery", "medium", "")

    assert request.dialect is Dialect.BIGQUERY
    with pytest.raises(typer.BadParameter, match="duckdb, redshift, bigquery"):
        cli._request_from_options("Airbnb", "postgres", "medium", "")

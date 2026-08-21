from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from sql_lab.exercises import get_static_exercise_set


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[str]:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update(
        {
            "SQL_LAB_HISTORY_DB": str(tmp_path / "history.db"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "sql_lab.web.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                pytest.fail(f"Local server exited during startup:\n{output}")
            try:
                with urllib.request.urlopen(
                    f"{base_url}/api/health", timeout=0.5
                ) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            pytest.fail("Local server did not become healthy within 10 seconds")

        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()


def test_instant_demo_executes_grades_and_saves_history(live_server: str) -> None:
    reference_sql = get_static_exercise_set().questions[0].reference_sql
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        page.goto(live_server)
        expect(page).to_have_title("SQL Interview Lab")
        expect(
            page.get_by_role("heading", name="Which company are you preparing for?")
        ).to_be_visible()

        page.locator('[data-company-id="airbnb"]').click()
        page.get_by_role(
            "button", name="Continue to interview setup", exact=False
        ).click()
        expect(
            page.get_by_role("heading", name="Shape your question set")
        ).to_be_visible()
        expect(page.get_by_role("button", name="Load instant demo")).to_be_visible()

        page.get_by_role("button", name="Load instant demo").click()
        expect(page.locator("#labView")).to_be_visible()
        expect(page.locator("#challengePosition")).to_have_text("QUESTION 1 OF 3")
        expect(page.locator("#engineStatusLabel")).to_have_text("Native DuckDB")

        page.get_by_role("textbox", name="SQL query editor").fill(reference_sql)
        page.get_by_role("button", name="Run query").click()
        expect(page.locator("#executionMeta")).to_contain_text("3 rows")

        page.get_by_role("button", name="Submit answer").click()
        expect(page.locator("#testResult .result-summary.pass")).to_contain_text(
            "All tests passed"
        )
        expect(page.locator("#testResult")).to_contain_text(
            "Matched 2 deterministic grading datasets."
        )

        page.locator("#labHistoryButton").click()
        expect(page.get_by_role("heading", name="Previous sessions")).to_be_visible()
        expect(page.locator("#historyStorage")).to_contain_text("1 saved session")

        browser.close()

    assert page_errors == []

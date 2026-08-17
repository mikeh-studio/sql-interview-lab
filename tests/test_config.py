from __future__ import annotations

from data_interview_lab.config import Settings, default_history_db_path


def test_new_environment_variables_take_precedence(monkeypatch) -> None:
    monkeypatch.setenv("SQL_LAB_LLM_PROVIDER", "claude")
    monkeypatch.setenv("DATA_INTERVIEW_LAB_LLM_PROVIDER", "codex")

    assert Settings.from_env().llm_provider == "codex"


def test_legacy_environment_variables_remain_supported(monkeypatch) -> None:
    monkeypatch.delenv("DATA_INTERVIEW_LAB_LLM_TIMEOUT", raising=False)
    monkeypatch.setenv("SQL_LAB_LLM_TIMEOUT", "45")

    assert Settings.from_env().llm_timeout_seconds == 45


def test_existing_legacy_history_is_reused_without_copying(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("DATA_INTERVIEW_LAB_HISTORY_DB", raising=False)
    monkeypatch.delenv("SQL_LAB_HISTORY_DB", raising=False)
    monkeypatch.setattr("data_interview_lab.config.Path.home", lambda: tmp_path)
    legacy_path = tmp_path / ".sql-interview-lab" / "history.db"
    legacy_path.parent.mkdir()
    legacy_path.touch()

    assert default_history_db_path() == legacy_path


def test_new_history_path_wins_when_both_paths_exist(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("DATA_INTERVIEW_LAB_HISTORY_DB", raising=False)
    monkeypatch.delenv("SQL_LAB_HISTORY_DB", raising=False)
    monkeypatch.setattr("data_interview_lab.config.Path.home", lambda: tmp_path)
    legacy_path = tmp_path / ".sql-interview-lab" / "history.db"
    current_path = tmp_path / ".data-interview-lab" / "history.db"
    legacy_path.parent.mkdir()
    current_path.parent.mkdir()
    legacy_path.touch()
    current_path.touch()

    assert default_history_db_path() == current_path

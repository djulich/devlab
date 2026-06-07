from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from devlab.cli import main


def _run_cli(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr("sys.argv", ["devlab", *args])
    main()


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", root.as_posix(), *args], check=True)


def _git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def test_cli_init_creates_devlab_tree_and_git_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))

    output = capsys.readouterr().out
    assert "created: .devlab/manifest.toml" in output
    assert "Next steps:" in output
    assert ".devlab/config/agents.toml" in output
    assert "DevLab plan/run require a clean Git working tree" in output
    assert (tmp_path / ".devlab/manifest.toml").exists()
    assert (tmp_path / ".devlab/config/profiles/default.toml").exists()
    assert (tmp_path / ".devlab/config/agents.toml").exists()
    assert (tmp_path / ".git").exists()
    assert _git_output(tmp_path, "status", "--porcelain") == ""


def test_cli_init_force_overwrites_starter_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()
    tooling = tmp_path / ".devlab/config/tooling.md"
    tooling.write_text("custom\n")
    _git(tmp_path, "add", ".devlab/config/tooling.md")
    _git(tmp_path, "commit", "-m", "Customize tooling")

    _run_cli(monkeypatch, "init", "--root", str(tmp_path), "--force")

    output = capsys.readouterr().out
    assert "overwritten: .devlab/config/tooling.md" in output
    assert tooling.read_text().startswith("# Tooling Policy")


def test_cli_status_reports_next_role_for_initialized_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "status", "--root", str(tmp_path))

    assert capsys.readouterr().out.strip() == "Next role: architect"


def test_cli_status_verbose_reports_agent_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "status", "--verbose", "--root", str(tmp_path))

    output = capsys.readouterr().out
    assert "Next role: architect" in output
    assert "Agent configuration:" in output
    assert "Source: .devlab/config/agents.toml" in output


def test_cli_diagnostics_reports_workflow_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "diagnostics", "--root", str(tmp_path))

    output = capsys.readouterr().out
    assert "Workflow diagnostics:" in output
    assert "Sessions: 0" in output
    assert "Role sequence: none" in output
    assert "Profiles: default" in output
    assert "Warnings: none" in output


def test_cli_diagnostics_json_reports_structured_workflow_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "diagnostics", "--json", "--root", str(tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert payload["roles"] == []
    assert payload["tasks"]["total"] == 0
    assert payload["profiles"]["ids"] == ["default"]
    assert payload["quality"]["correctness_checked"] is False
    assert payload["quality"]["correctness_passed"] is None
    assert payload["quality"]["warnings"] == []


def test_cli_history_shows_none_for_initialized_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "history", "--root", str(tmp_path))

    assert capsys.readouterr().out.strip() == "Session history: none"


def test_cli_doctor_reports_ok_for_initialized_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "doctor", "--root", str(tmp_path))

    assert capsys.readouterr().out.strip() == "DevLab doctor: OK"


def test_cli_run_emits_progress_logs_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "run", "--root", str(tmp_path), "--max-sessions", "0")

    captured = capsys.readouterr()
    assert "Orchestrator finished after 0 session(s)." in captured.err


def test_cli_plan_passes_planning_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_run_loop(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)

    _run_cli(
        monkeypatch,
        "plan",
        "--revise",
        "--retain-prompts",
        "--root",
        str(tmp_path),
    )

    assert "auto" not in seen
    assert seen["planning_only"] is True
    assert seen["revise_plan"] is True
    assert seen["retain_prompts"] is True
    assert seen["max_sessions"] == 2


def test_cli_run_passes_retain_prompts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_run_loop(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)

    _run_cli(
        monkeypatch,
        "run",
        "--retain-prompts",
        "--root",
        str(tmp_path),
        "--max-sessions",
        "1",
    )

    assert "auto" not in seen
    assert seen["retain_prompts"] is True


def test_cli_run_quiet_suppresses_progress_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "run", "--quiet", "--root", str(tmp_path), "--max-sessions", "0")

    captured = capsys.readouterr()
    assert "Orchestrator finished" not in captured.err


def test_cli_run_verbose_emits_debug_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run_loop(*_args: object, **_kwargs: object) -> object:
        logging.getLogger("devlab").debug("debug detail")

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)

    _run_cli(monkeypatch, "run", "--verbose", "--root", str(tmp_path), "--max-sessions", "1")

    captured = capsys.readouterr()
    assert "DEBUG: debug detail" in captured.err


def test_cli_run_log_file_captures_debug_logs_when_console_is_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run_loop(*_args: object, **_kwargs: object) -> object:
        logging.getLogger("devlab").debug("file debug detail")

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)
    log_file = tmp_path / "logs/devlab.log"

    _run_cli(
        monkeypatch,
        "run",
        "--quiet",
        "--log-file",
        str(log_file),
        "--root",
        str(tmp_path),
        "--max-sessions",
        "1",
    )

    assert "file debug detail" in log_file.read_text()


def test_cli_doctor_exits_nonzero_for_invalid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()
    (tmp_path / ".devlab/config/agents.toml").write_text("[defaults\n")

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "doctor", "--root", str(tmp_path))

    assert exc.value.code == 1
    assert "DevLab doctor: 1 problem(s)" in capsys.readouterr().out

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import cast

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

    assert capsys.readouterr().out.strip() == (
        "Next role: architect\n"
        "Active generation: 1\n"
        "Archived generations: none"
    )


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


def test_cli_help_includes_workflow_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["devlab", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert "workflow-state" in capsys.readouterr().out


def test_cli_workflow_state_json_reports_lifecycle_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "workflow-state", "--json", "--root", str(tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert payload["project_mode"] == "unknown"
    assert payload["lifecycle_phase"] == "awaiting design"
    assert payload["next_role"] == "architect"


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
    monkeypatch.setattr(
        "devlab.doctor_agent_config.shutil.which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )

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


def test_cli_clean_failed_session_removes_untracked_diagnostics_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()
    agent_log = tmp_path / ".devlab/logs/agents/failed.stdout.log"
    agent_log.write_text("failure\n")
    env_log = tmp_path / ".devlab/logs/environment/setup.log"
    env_log.parent.mkdir(parents=True, exist_ok=True)
    env_log.write_text("setup failed\n")
    artifact = tmp_path / ".devlab/session-artifacts/developer/handoff.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("bad handoff\n")
    source_change = tmp_path / "app.py"
    source_change.write_text("print('keep me')\n")

    _run_cli(monkeypatch, "clean-failed-session", "--root", str(tmp_path))

    output = capsys.readouterr().out
    assert "Removed 3 failed-session artifact" in output
    assert not agent_log.exists()
    assert not env_log.exists()
    assert not artifact.exists()
    assert (tmp_path / ".devlab/session-artifacts/.gitkeep").exists()
    assert source_change.exists()
    assert "?? app.py" in _git_output(tmp_path, "status", "--porcelain")


def test_cli_doctor_exits_nonzero_for_invalid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()
    (tmp_path / ".devlab/config/agents.toml").write_text("[defaults\n")

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "doctor", "--root", str(tmp_path))

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "DevLab doctor: 2 problem(s)" in output
    assert "working tree is dirty" in output
    assert "invalid TOML" in output


def test_cli_agent_smoke_test_prints_report_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    def fake_smoke(*args: object, **kwargs: object) -> object:
        seen["args"] = args
        seen["kwargs"] = kwargs

        class Result:
            passed = True

        return Result()

    monkeypatch.setattr("devlab.cli.run_agent_smoke_test", fake_smoke)
    monkeypatch.setattr("devlab.cli.format_agent_smoke_report", lambda _result: "smoke report")

    _run_cli(
        monkeypatch,
        "agent-smoke-test",
        "--root",
        str(tmp_path),
        "--config",
        str(tmp_path / ".local/live-eval/agents.toml"),
        "--provider",
        "codex",
        "--model",
        "gpt-5.5",
        "--effort",
        "medium",
    )

    assert capsys.readouterr().out.strip() == "smoke report"
    assert seen["args"] == (tmp_path.resolve(),)
    kwargs = cast("dict[str, object]", seen["kwargs"])
    assert kwargs["config_path"] == (tmp_path / ".local/live-eval/agents.toml").resolve()
    assert kwargs["role_names"] is None
    assert kwargs["provider"] == "codex"
    assert kwargs["model"] == "gpt-5.5"
    assert kwargs["effort"] == "medium"
    assert kwargs["all_providers"] is False
    assert kwargs["use_provider_defaults"] is False


def test_cli_agent_smoke_test_exits_nonzero_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_smoke(*_args: object, **_kwargs: object) -> object:
        class Result:
            passed = False

        return Result()

    monkeypatch.setattr("devlab.cli.run_agent_smoke_test", fake_smoke)
    monkeypatch.setattr("devlab.cli.format_agent_smoke_report", lambda _result: "smoke report")

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "agent-smoke-test", "--root", str(tmp_path))

    assert exc.value.code == 1


def test_cli_agent_smoke_test_reports_configuration_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_smoke(*_args: object, **_kwargs: object) -> object:
        raise ValueError("providers.test.args[1] has invalid placeholder syntax")

    monkeypatch.setattr("devlab.cli.run_agent_smoke_test", fake_smoke)

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "agent-smoke-test", "--root", str(tmp_path))

    assert exc.value.code == 2
    assert "providers.test.args[1] has invalid placeholder syntax" in capsys.readouterr().err


def test_cli_agent_smoke_test_supports_all_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_smoke(*_args: object, **kwargs: object) -> object:
        seen["kwargs"] = kwargs

        class Result:
            passed = True

        return Result()

    monkeypatch.setattr("devlab.cli.run_agent_smoke_test", fake_smoke)
    monkeypatch.setattr("devlab.cli.format_agent_smoke_report", lambda _result: "smoke report")

    _run_cli(monkeypatch, "agent-smoke-test", "--root", str(tmp_path), "--all-providers")

    kwargs = cast("dict[str, object]", seen["kwargs"])
    assert kwargs["all_providers"] is True


def test_cli_agent_smoke_test_supports_provider_defaults_modifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_smoke(*_args: object, **kwargs: object) -> object:
        seen["kwargs"] = kwargs

        class Result:
            passed = True

        return Result()

    monkeypatch.setattr("devlab.cli.run_agent_smoke_test", fake_smoke)
    monkeypatch.setattr("devlab.cli.format_agent_smoke_report", lambda _result: "smoke report")

    _run_cli(
        monkeypatch,
        "agent-smoke-test",
        "--root",
        str(tmp_path),
        "--provider",
        "codex",
        "--use-provider-defaults",
    )

    kwargs = cast("dict[str, object]", seen["kwargs"])
    assert kwargs["provider"] == "codex"
    assert kwargs["use_provider_defaults"] is True


def test_cli_agent_smoke_test_requires_selector_for_provider_defaults_modifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit) as exc:
        _run_cli(
            monkeypatch,
            "agent-smoke-test",
            "--root",
            str(tmp_path),
            "--use-provider-defaults",
        )

    assert exc.value.code == 2

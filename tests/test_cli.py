from __future__ import annotations

import json
import logging
import subprocess
from importlib.metadata import version
from pathlib import Path
from typing import cast

import pytest

from devlab.clarifications import FileClarificationTracker
from devlab.cli import main
from devlab.executable_config import (
    ExecutableConfigSnapshot,
    build_executable_config_snapshot,
)
from devlab.handoffs import SessionEnvelope, write_session_envelope
from devlab.workflow_state import ResumeState, set_resume_state


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


def _create_clarification(root: Path) -> str:
    clarification = FileClarificationTracker(root).create(
        title="Auth session timeout",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="choice",
        recommended_option="A",
        body=(
            "# Auth session timeout\n\n"
            "## Context\nC\n\n"
            "## Question\nQ\n\n"
            "## Options\n"
            "- A: 24-hour idle timeout.\n"
            "- B: No expiry for MVP.\n"
        ),
    )
    return clarification.id


def test_cli_reports_installed_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["devlab", "--version"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"devlab {version('devlab')}"


def test_cli_session_handoff_rejects_then_accepts_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    envelope_path = tmp_path / ".devlab/session-artifacts/architect/session.toml"
    write_session_envelope(
        envelope_path,
        SessionEnvelope(1, "s1", "architect"),
    )
    monkeypatch.setenv("DEVLAB_SESSION_ENVELOPE", envelope_path.as_posix())

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "session", "--root", str(tmp_path), "handoff", "submit")

    assert exc.value.code == 1
    rejected = capsys.readouterr().out
    assert "Handoff rejected" in rejected
    assert "done must contain at least one entry" in rejected
    assert "next_session_hint must be non-empty" in rejected

    envelope_path.with_name("handoff-candidate.toml").write_text(
        'schema_version = 1\noutcome = "completed"\ncommit_message = "Design system"\n'
        'done = ["Designed the system"]\nchanged_artifacts = ["docs/design.md"]\n'
        'open_issues = []\naddressed_findings = []\n'
        'next_session_hint = "Create the implementation plan."\n'
    )

    _run_cli(monkeypatch, "session", "--root", str(tmp_path), "handoff", "submit")

    assert "Accepted handoff for architect session s1" in capsys.readouterr().out
    assert envelope_path.with_name("result.toml").exists()
    assert envelope_path.with_name("handoff.md").exists()


def test_cli_init_creates_devlab_tree_and_git_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))

    output = capsys.readouterr().out
    assert "created: .devlab/manifest.toml" in output
    assert "Next steps:" in output
    assert ".devlab/config/agents.toml" in output
    assert "DevLab plan/implement require a clean Git working tree" in output
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


def test_cli_init_selects_rust_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path), "--template", "rust")
    capsys.readouterr()

    manifest = (tmp_path / ".devlab/manifest.toml").read_text()
    profile = (tmp_path / ".devlab/config/profiles/default.toml").read_text()
    assert 'init_template = "rust"' in manifest
    assert "cargo clippy --workspace" in profile


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


def test_cli_clarify_list_shows_pending_clarifications(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _create_clarification(tmp_path)

    _run_cli(monkeypatch, "clarify", "--root", str(tmp_path), "list")

    output = capsys.readouterr().out
    assert "CL0001" in output
    assert "pending" in output
    assert "Auth session timeout" in output


def test_cli_clarify_show_prints_clarification_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clarification_id = _create_clarification(tmp_path)

    _run_cli(monkeypatch, "clarify", "--root", str(tmp_path), "show", clarification_id)

    output = capsys.readouterr().out
    assert 'id = "CL0001"' in output
    assert "## Question" in output


def test_cli_clarify_answer_choice_updates_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clarification_id = _create_clarification(tmp_path)

    _run_cli(
        monkeypatch,
        "clarify",
        "--root",
        str(tmp_path),
        "answer",
        clarification_id,
        "--choice",
        "A",
    )

    output = capsys.readouterr().out
    assert "Answered CL0001" in output
    clarification = FileClarificationTracker(tmp_path).get(clarification_id)
    assert clarification.status.value == "answered"
    assert "A: 24-hour idle timeout." in clarification.answer_text


def test_cli_clarify_supersede_updates_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clarification_id = _create_clarification(tmp_path)

    _run_cli(
        monkeypatch,
        "clarify",
        "--root",
        str(tmp_path),
        "supersede",
        clarification_id,
        "--reason",
        "Spec changed.",
    )

    output = capsys.readouterr().out
    assert "Superseded CL0001" in output
    clarification = FileClarificationTracker(tmp_path).get(clarification_id)
    assert clarification.status.value == "superseded"


def test_cli_resume_without_pointer_prints_next_inspection_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "resume", "--root", str(tmp_path))

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "No active clarification resume pointer" in output
    assert "devlab workflow-state" in output


def test_cli_resume_pending_clarification_prints_answer_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clarification_id = _create_clarification(tmp_path)
    set_resume_state(
        tmp_path,
        ResumeState(blocked_by=clarification_id, command="plan", role="planner"),
    )

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "resume", "--root", str(tmp_path))

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert f"Workflow is waiting to resume after {clarification_id}" in output
    assert "command=devlab plan" in output
    assert "role=planner" in output
    assert f"devlab clarify answer {clarification_id} ..." in output
    assert "devlab resume" in output


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


def test_cli_workflow_state_digest_reports_markdown_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "workflow-state", "--digest", "--root", str(tmp_path))

    output = capsys.readouterr().out
    assert output.startswith("# Workflow State")
    assert "## Next Action" in output
    assert "Run `devlab plan` to continue design or planning." in output


def test_cli_workflow_state_digest_json_reports_structured_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "workflow-state", "--digest", "--json", "--root", str(tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["lifecycle_phase"] == "awaiting design"
    assert payload["next_action"] == "Run `devlab plan` to continue design or planning."
    assert payload["validation"]["state"] == "not_reported"


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
    assert payload["clarifications"]["stops_total"] == 0
    assert payload["clarifications"]["stops_by_role"] == {}
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

    output = capsys.readouterr().out
    assert "DevLab doctor: OK" in output
    assert "Executable configuration: not trusted (exec-v1:" in output


def test_cli_implement_emits_progress_logs_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(
        monkeypatch,
        "implement",
        "--root",
        str(tmp_path),
        "--max-sessions",
        "0",
        "--accept-current-exec-config",
    )

    captured = capsys.readouterr()
    assert "Orchestrator finished after 0 session(s)." in captured.err


def test_cli_trust_executable_config_approves_shows_and_revokes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "operator-state"))
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(
        monkeypatch,
        "trust",
        "--root",
        str(tmp_path),
        "executable-config",
        "--show",
    )
    shown = capsys.readouterr().out
    assert "Fingerprint: exec-v1:" in shown
    assert "Trust status: not trusted" in shown

    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    _run_cli(
        monkeypatch,
        "trust",
        "--root",
        str(tmp_path),
        "executable-config",
    )
    assert "Trusted executable configuration exec-v1:" in capsys.readouterr().out

    _run_cli(
        monkeypatch,
        "trust",
        "--root",
        str(tmp_path),
        "executable-config",
        "--show",
    )
    assert "Trust status: trusted" in capsys.readouterr().out

    _run_cli(
        monkeypatch,
        "trust",
        "--root",
        str(tmp_path),
        "executable-config",
        "--revoke",
    )
    assert "Revoked executable-configuration trust" in capsys.readouterr().out


def test_cli_unattended_requires_trust_or_explicit_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    def fake_run_loop(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "implement", "--unattended", "--root", str(tmp_path))

    assert exc.value.code == 1
    assert "executable configuration is not trusted" in capsys.readouterr().err

    _run_cli(
        monkeypatch,
        "implement",
        "--unattended",
        "--root",
        str(tmp_path),
        "--accept-current-exec-config",
    )

    snapshot = cast("ExecutableConfigSnapshot", seen["executable_config"])
    assert snapshot.authorization is not None
    assert snapshot.authorization.source.value == "accepted_current"


def test_cli_accepts_independently_expected_executable_config_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_run_loop(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)
    digest = build_executable_config_snapshot(tmp_path).digest

    _run_cli(
        monkeypatch,
        "implement",
        "--unattended",
        "--root",
        str(tmp_path),
        "--require-exec-config-digest",
        digest,
    )

    snapshot = cast("ExecutableConfigSnapshot", seen["executable_config"])
    assert snapshot.authorization is not None
    assert snapshot.authorization.source.value == "expected_digest"


def test_cli_run_is_not_registered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["devlab", "run", "--max-sessions", "0"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert "invalid choice: 'run'" in capsys.readouterr().err


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
        "--mark-specs-planned",
        "--retain-prompts",
        "--root",
        str(tmp_path),
    )

    assert "auto" not in seen
    assert seen["planning_only"] is True
    assert seen["revise_plan"] is True
    assert seen["mark_specs_planned"] is True
    assert seen["retain_prompts"] is True
    assert seen["clarification_mode"] == "operator"
    assert seen["max_sessions"] == 2


def test_cli_implement_passes_retain_prompts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake_run_loop(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)

    _run_cli(
        monkeypatch,
        "implement",
        "--retain-prompts",
        "--root",
        str(tmp_path),
        "--max-sessions",
        "1",
        "--accept-current-exec-config",
    )

    assert "auto" not in seen
    assert seen["retain_prompts"] is True
    assert seen["clarification_mode"] == "operator"


def test_cli_unattended_sets_agent_clarification_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake_run_loop(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)

    _run_cli(
        monkeypatch,
        "implement",
        "--unattended",
        "--root",
        str(tmp_path),
        "--accept-current-exec-config",
    )

    assert seen["clarification_mode"] == "agent"


def test_cli_plan_passes_agent_clarification_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
        "--clarification-mode",
        "agent",
        "--root",
        str(tmp_path),
        "--accept-current-exec-config",
    )

    assert seen["clarification_mode"] == "agent"


def test_cli_plan_unattended_sets_agent_clarification_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
        "--unattended",
        "--root",
        str(tmp_path),
        "--accept-current-exec-config",
    )

    assert seen["clarification_mode"] == "agent"


def test_cli_implement_quiet_suppresses_progress_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(
        monkeypatch,
        "implement",
        "--quiet",
        "--root",
        str(tmp_path),
        "--max-sessions",
        "0",
        "--accept-current-exec-config",
    )

    captured = capsys.readouterr()
    assert "Orchestrator finished" not in captured.err


def test_cli_implement_verbose_emits_debug_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run_loop(*_args: object, **_kwargs: object) -> object:
        logging.getLogger("devlab").debug("debug detail")

        class Result:
            exit_code = 0

        return Result()

    monkeypatch.setattr("devlab.cli.run_loop", fake_run_loop)

    _run_cli(
        monkeypatch,
        "implement",
        "--verbose",
        "--root",
        str(tmp_path),
        "--max-sessions",
        "1",
        "--accept-current-exec-config",
    )

    captured = capsys.readouterr()
    assert "DEBUG: debug detail" in captured.err


def test_cli_implement_log_file_captures_debug_logs_when_console_is_quiet(
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
        "implement",
        "--quiet",
        "--log-file",
        str(log_file),
        "--root",
        str(tmp_path),
        "--max-sessions",
        "1",
        "--accept-current-exec-config",
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
    config_path = tmp_path / ".local/live-eval/agents.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        '[defaults]\nprovider = "codex"\n'
        '[providers.codex]\ncommand = "codex"\n'
        'args = ["{system_prompt}", "{session_prompt}"]\n'
    )

    _run_cli(
        monkeypatch,
        "agent-smoke-test",
        "--root",
        str(tmp_path),
        "--config",
        str(config_path),
        "--provider",
        "codex",
        "--model",
        "gpt-5.5",
        "--effort",
        "medium",
        "--accept-current-exec-config",
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
        _run_cli(
            monkeypatch,
            "agent-smoke-test",
            "--root",
            str(tmp_path),
            "--accept-current-exec-config",
        )

    assert exc.value.code == 1


def test_cli_agent_smoke_test_reports_configuration_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_smoke(*_args: object, **_kwargs: object) -> object:
        raise ValueError("providers.test.args[1] has invalid placeholder syntax")

    monkeypatch.setattr("devlab.cli.run_agent_smoke_test", fake_smoke)

    with pytest.raises(SystemExit) as exc:
        _run_cli(
            monkeypatch,
            "agent-smoke-test",
            "--root",
            str(tmp_path),
            "--accept-current-exec-config",
        )

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

    _run_cli(
        monkeypatch,
        "agent-smoke-test",
        "--root",
        str(tmp_path),
        "--all-providers",
        "--accept-current-exec-config",
    )

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
        "--accept-current-exec-config",
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

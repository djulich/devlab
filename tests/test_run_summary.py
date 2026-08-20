from __future__ import annotations

import json
from pathlib import Path

import pytest

from devlab.clarifications import FileClarificationTracker
from devlab.executable_config import (
    DEVLAB_STATE_HOME_ENV,
    build_executable_config_snapshot,
    trust_executable_config,
)
from devlab.init import init_workspace
from devlab.orchestrator import RunResult, RunStopReason
from devlab.run_summary import build_run_summary, format_run_summary
from devlab.workflow_state import ResumeState, set_resume_state
from devlab.workspace import Workspace


def _write_task(root: Path, *, status: str = "changes_requested") -> None:
    (root / ".devlab/tasks/T0001_profile.md").write_text(
        "+++\n"
        'id = "T0001"\n'
        'title = "Add reusable Python task profile"\n'
        f'status = "{status}"\n'
        'milestone = "M1"\n'
        'profile = "default"\n'
        'domain = "general"\n'
        "depends_on = []\n"
        "addresses_findings = []\n"
        "validation = []\n"
        "+++\n\n"
        "# T0001\n\n## Acceptance Criteria\n- [ ] Record validation.\n"
    )


def _result(reason: RunStopReason, *, sessions: int = 2) -> RunResult:
    return RunResult(sessions, False, 0, (), reason)


def test_summary_reports_requested_changes_and_new_untrusted_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    (tmp_path / ".devlab/plans/design-plan.md").write_text("# Design\n")
    _write_task(tmp_path)
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)
    profile = tmp_path / ".devlab/config/profiles/default.toml"
    profile.write_text(profile.read_text().replace("setup = []", 'setup = ["uv sync"]'))

    summary = build_run_summary(
        tmp_path,
        command="implement",
        result=_result(RunStopReason.SESSION_LIMIT),
        initial_executable_config=initial,
    )
    text = format_run_summary(summary)

    assert "DevLab stopped: session limit reached; work remains" in text
    assert "Task: T0001 — Add reusable Python task profile" in text
    assert "Task status: changes requested" in text
    assert "Operator clarification: none" in text
    assert "Executable configuration changed during this run and is not trusted" in text
    assert "devlab trust executable-config --show" in text
    assert text.rstrip().endswith("devlab implement")


def test_summary_calls_out_dependency_introduced_in_latest_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)
    log_dir = tmp_path / ".devlab/logs/agents"
    log_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "session_number": 1,
        "role_name": "developer",
        "provider": "codex",
        "model": "test",
        "return_code": 0,
        "failure_kind": "none",
        "duration_seconds": 1.0,
        "task_id": "T0001",
    }
    for invocation_id, package in (
        ("20260820T110000_001_developer", "old-package"),
        ("20260820T120000_001_developer", "new-package"),
    ):
        data = {
            **base,
            "invocation_id": invocation_id,
            "dependency_introductions": [
                {
                    "ecosystem": "node",
                    "manifest": "package.json",
                    "scope": "dependencies",
                    "name": package,
                    "constraint": "^1",
                }
            ],
        }
        (log_dir / f"{invocation_id}.metadata.json").write_text(json.dumps(data))

    summary = build_run_summary(
        tmp_path,
        command="implement",
        result=_result(RunStopReason.SESSION_LIMIT, sessions=1),
        initial_executable_config=initial,
    )
    text = format_run_summary(summary)

    assert "Review unverified direct dependency: new-package" in text
    assert "old-package" not in text


def test_summary_reports_executable_configuration_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    (tmp_path / ".devlab/plans/design-plan.md").write_text("# Design\n")
    _write_task(tmp_path)
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)
    profile = tmp_path / ".devlab/config/profiles/default.toml"
    profile.write_text(profile.read_text().replace("setup = []", 'setup = ["uv sync"]'))

    summary = build_run_summary(
        tmp_path,
        command="implement",
        result=_result(RunStopReason.EXECUTABLE_CONFIG_CHANGED, sessions=1),
        initial_executable_config=initial,
    )
    text = format_run_summary(summary)

    assert "fresh authorized run is required" in text
    assert "changed during this run and is not trusted" in text
    assert "devlab trust executable-config --show" in text
    assert text.rstrip().endswith("devlab implement")


def test_summary_prioritizes_durable_clarification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    (tmp_path / ".devlab/plans/design-plan.md").write_text("# Design\n")
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)
    clarification = FileClarificationTracker(tmp_path).create(
        title="Choose base currency",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="text",
        body="# Choose base currency\n\n## Expected Answer\nA currency.\n",
    )

    summary = build_run_summary(
        tmp_path,
        command="plan",
        result=_result(RunStopReason.CLARIFICATION_BLOCKED, sessions=1),
        initial_executable_config=initial,
    )
    text = format_run_summary(summary)

    assert f"Operator clarification: {clarification.id}" in text
    assert "Asked by: planner" in text
    assert f"devlab clarify show {clarification.id}" in text
    assert text.rstrip().endswith("devlab resume")


def test_summary_reports_complete_workflow_without_next_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    (tmp_path / ".devlab/plans/design-plan.md").write_text("# Design\n")
    (tmp_path / ".devlab/workflow.toml").write_text("version = 1\n\n[planning]\ncomplete = true\n")
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)

    summary = build_run_summary(
        tmp_path,
        command="implement",
        result=RunResult(0, True, 0, (), RunStopReason.WORKFLOW_COMPLETE),
        initial_executable_config=initial,
    )

    assert summary.next_role is None
    assert summary.next_commands == ()
    assert "No workflow action is currently required" in format_run_summary(summary)


def test_plan_summary_routes_actionable_work_to_implement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    (tmp_path / ".devlab/plans/design-plan.md").write_text("# Design\n")
    _write_task(tmp_path, status="open")
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)

    summary = build_run_summary(
        tmp_path,
        command="plan",
        result=RunResult(2, True, 0, (), RunStopReason.COMMAND_COMPLETE),
        initial_executable_config=initial,
    )

    assert summary.next_role == "developer"
    assert summary.next_commands == ("devlab implement",)


def test_implement_summary_continues_incremental_planning_with_implement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    (tmp_path / ".devlab/plans/design-plan.md").write_text("# Design\n")
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)

    summary = build_run_summary(
        tmp_path,
        command="implement",
        result=_result(RunStopReason.SESSION_LIMIT),
        initial_executable_config=initial,
    )

    assert summary.next_role == "planner"
    assert summary.next_commands == ("devlab implement",)


@pytest.mark.parametrize(
    "reason",
    [
        RunStopReason.DEVELOPER_NON_ADVANCING,
        RunStopReason.TASK_CONTRACT_INVALID,
        RunStopReason.VALIDATION_FAILED,
    ],
)
def test_guard_stop_reasons_request_operator_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: RunStopReason,
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)

    summary = build_run_summary(
        tmp_path,
        command="implement",
        result=_result(reason),
        initial_executable_config=initial,
    )

    text = format_run_summary(summary)
    assert "run devlab doctor before retrying" in text


def test_summary_explains_pending_research_and_uses_stored_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVLAB_STATE_HOME_ENV, str(tmp_path / "operator-state"))
    init_workspace(tmp_path)
    research = (
        Workspace(tmp_path)
        .research()
        .create(
            title="Dependency behavior",
            asking_role="planner",
            asking_session_id="p1",
            command="plan",
            scope="planning",
            question="What is documented?",
            context="Planning needs evidence.",
            desired_outcome="Choose an approach.",
            acceptance_criteria=("Use primary docs.",),
        )
    )
    set_resume_state(
        tmp_path,
        ResumeState(research.id, "plan", "planner", blocked_kind="research"),
    )
    initial = build_executable_config_snapshot(tmp_path)
    trust_executable_config(initial)

    summary = build_run_summary(
        tmp_path,
        command="implement",
        result=_result(RunStopReason.RESEARCH_PENDING, sessions=1),
        initial_executable_config=initial,
    )
    text = format_run_summary(summary)

    assert summary.next_commands == ("devlab plan",)
    assert f"Research: {research.id} — Dependency behavior" in text
    assert "Research state: requested" in text
    assert "Next step: researcher invocation" in text

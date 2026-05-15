from __future__ import annotations

from pathlib import Path

from devlab.doctor import check_workspace, format_doctor_report
from devlab.init import init_workspace


def test_doctor_accepts_missing_agents_config(tmp_path: Path) -> None:
    assert check_workspace(tmp_path) == []


def test_doctor_reports_multiple_agents_config_problems(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[defaults]\n"
        'provider = "missing"\n'
        "\n[roles.unknown]\n"
        'provider = "default"\n'
        "\n[providers.default]\n"
        "command = 123\n"
        'args = ["--bad", "{unknown_placeholder}"]\n'
    )

    problems = check_workspace(tmp_path)
    messages = [problem.message for problem in problems]

    assert "roles.unknown is not a known role" in messages
    assert "providers.default.command must be a string" in messages
    assert any("unsupported placeholder {unknown_placeholder}" in message for message in messages)
    assert any("references missing provider 'missing'" in message for message in messages)


def test_doctor_reports_prompt_context_configuration_problems(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[prompt_context]\n"
        "warning_tokens = 100\n"
        "critical_tokens = 50\n"
        "\n[prompt_context.roles.unknown]\n"
        "warning_tokens = 10\n"
        "critical_tokens = 20\n"
        "\n[prompt_context.roles.planner]\n"
        'warning_tokens = "many"\n'
    )

    messages = _messages(tmp_path)

    assert (
        "prompt_context.critical_tokens must be greater than or equal to warning_tokens"
        in messages
    )
    assert "prompt_context.roles.unknown is not a known role" in messages
    assert "prompt_context.roles.planner.warning_tokens must be an integer" in messages


def test_doctor_report_formats_success_and_failure(tmp_path: Path) -> None:
    assert format_doctor_report([]) == "DevLab doctor: OK"

    path = tmp_path / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[defaults\n")

    report = format_doctor_report(check_workspace(tmp_path))

    assert report.startswith("DevLab doctor: 1 problem(s)")
    assert ".devlab/config/agents.toml" in report
    assert "invalid TOML" in report


def test_doctor_reports_oversized_prompt_context(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    path = tmp_path / ".devlab/config/agents.toml"
    path.write_text(
        path.read_text()
        + "\n[prompt_context]\n"
        + "warning_tokens = 1\n"
        + "critical_tokens = 1_000_000\n"
        + "\n[prompt_context.roles.planner]\n"
        + "warning_tokens = 1\n"
        + "critical_tokens = 2\n"
    )

    messages = _messages(tmp_path)

    assert any(message.startswith("architect prompt context warning") for message in messages)
    assert any(message.startswith("planner prompt context is critical") for message in messages)


def test_doctor_prompt_context_check_does_not_sync_milestone_files(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _write_task(tmp_path, "T0001", milestone="M1")

    check_workspace(tmp_path)

    assert not (tmp_path / ".devlab/milestones/M1.toml").exists()


def test_doctor_reports_task_referencing_missing_milestone(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M1")

    messages = _messages(tmp_path)

    assert any("references missing milestone 'M1'" in message for message in messages)


def test_doctor_reports_stale_milestone_task_ids(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M1")
    _write_milestone(tmp_path, "M1", task_ids=[])

    messages = _messages(tmp_path)

    assert any("does not list task 'T0001'" in message for message in messages)


def test_doctor_reports_unknown_task_referenced_by_milestone(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1", task_ids=["T9999"])

    messages = _messages(tmp_path)

    assert "task_ids references unknown task 'T9999'" in messages


def test_doctor_reports_task_referenced_by_wrong_milestone(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M2")
    _write_milestone(tmp_path, "M1", task_ids=["T0001"])
    _write_milestone(tmp_path, "M2", task_ids=["T0001"])

    messages = _messages(tmp_path)

    assert any("task_ids references 'T0001' but task milestone is 'M2'" in m for m in messages)


def test_doctor_reports_integrated_milestone_missing_handoff(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1", status="integrated", integrated=True)

    messages = _messages(tmp_path)

    assert "integrated milestone is missing integration_handoff" in messages


def test_doctor_reports_architecture_approved_milestone_problems(tmp_path: Path) -> None:
    _write_milestone(
        tmp_path,
        "M1",
        status="architecture_approved",
        integrated=False,
        architecture_approved=True,
    )

    messages = _messages(tmp_path)

    assert "architecture-approved milestone is not integrated" in messages
    assert "architecture-approved milestone is missing architecture_review_handoff" in messages


def test_doctor_reports_missing_milestone_finding(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1", findings=["F0001"])

    messages = _messages(tmp_path)

    assert "findings references unknown finding 'F0001'" in messages


def test_doctor_accepts_consistent_milestone_state(tmp_path: Path) -> None:
    _write_default_profile(tmp_path)
    _write_task(tmp_path, "T0001", milestone="M1")
    _write_milestone(
        tmp_path,
        "M1",
        status="architecture_approved",
        integrated=True,
        architecture_approved=True,
        task_ids=["T0001"],
        integration_handoff="20260101T000000_integrator_handoff.md",
        architecture_review_handoff="20260101T000100_architect_handoff.md",
    )

    assert check_workspace(tmp_path) == []


def _messages(root: Path) -> list[str]:
    return [problem.message for problem in check_workspace(root)]


def _write_default_profile(root: Path) -> None:
    path = root / ".devlab/config/profiles/default.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('version = 1\nid = "default"\ntitle = "Default"\n')


def _write_task(root: Path, task_id: str, *, milestone: str) -> None:
    path = root / ".devlab/tasks" / f"{task_id}_task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{task_id}"\n'
        'status = "open"\n'
        f'milestone = "{milestone}"\n'
        "depends_on = []\n"
        "+++\n\n"
        f"# {task_id}\n"
    )


def _write_milestone(
    root: Path,
    milestone_id: str,
    *,
    status: str = "planned",
    integrated: bool = False,
    architecture_approved: bool = False,
    task_ids: list[str] | None = None,
    integration_handoff: str = "",
    architecture_review_handoff: str = "",
    findings: list[str] | None = None,
) -> None:
    task_ids = task_ids or []
    findings = findings or []
    task_ids_text = ", ".join(f'"{task_id}"' for task_id in task_ids)
    findings_text = ", ".join(f'"{finding_id}"' for finding_id in findings)
    path = root / ".devlab/milestones" / f"{milestone_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version = 1\n"
        f'id = "{milestone_id}"\n'
        f'title = "{milestone_id}"\n'
        f'status = "{status}"\n'
        "integration_required = true\n"
        f"integrated = {str(integrated).lower()}\n"
        f"architecture_approved = {str(architecture_approved).lower()}\n"
        f"task_ids = [{task_ids_text}]\n"
        f'integration_handoff = "{integration_handoff}"\n'
        f'architecture_review_handoff = "{architecture_review_handoff}"\n'
        f"findings = [{findings_text}]\n"
    )

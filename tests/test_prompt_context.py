from __future__ import annotations

from pathlib import Path

from devlab.init import init_workspace
from devlab.prompt_context import (
    PromptContextThresholds,
    build_prompt_context_report,
    estimate_tokens,
    load_prompt_context_thresholds,
    measure_prompt,
)
from devlab.workspace import Workspace


def test_estimate_tokens_uses_stable_character_estimate() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_measure_prompt_reports_characters_lines_and_tokens() -> None:
    size = measure_prompt("abcd\nefgh")

    assert size.characters == 9
    assert size.lines == 2
    assert size.estimated_tokens == 3


def test_prompt_context_report_includes_all_roles(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    report = build_prompt_context_report(Workspace(tmp_path).snapshot)

    assert {role.role_name for role in report.roles} == {
        "architect",
        "planner",
        "developer",
        "reviewer",
        "integrator",
    }
    assert all(role.base.estimated_tokens > 0 for role in report.roles)
    assert all(role.session.estimated_tokens > 0 for role in report.roles)


def test_prompt_context_report_accounts_for_project_knowledge(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    baseline = build_prompt_context_report(Workspace(tmp_path).snapshot)
    (tmp_path / "CONTEXT.md").write_text("# Context\n\nImportant domain language.\n")
    adr_dir = tmp_path / "docs/adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-important-decision.md").write_text(
        "# Important Decision\n\nUse this shape.\n"
    )

    report = build_prompt_context_report(Workspace(tmp_path).snapshot)

    by_role = {role.role_name: role for role in report.roles}
    baseline_by_role = {role.role_name: role for role in baseline.roles}
    assert (
        by_role["architect"].session.characters
        > baseline_by_role["architect"].session.characters
    )
    assert (
        by_role["developer"].session.characters
        > baseline_by_role["developer"].session.characters
    )


def test_prompt_context_report_does_not_sync_missing_milestone_files(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _write_task(tmp_path, "T0001", milestone="M1", status="closed")

    build_prompt_context_report(Workspace(tmp_path).snapshot)

    assert not (tmp_path / ".devlab/milestones/M1.toml").exists()


def test_thresholds_can_be_configured_globally_and_per_role(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _append_prompt_context_config(
        tmp_path,
        "[prompt_context]\n"
        "warning_tokens = 10\n"
        "critical_tokens = 20\n"
        "\n[prompt_context.roles.planner]\n"
        "warning_tokens = 30\n"
        "critical_tokens = 40\n",
    )

    thresholds = load_prompt_context_thresholds(tmp_path)

    assert thresholds["default"] == PromptContextThresholds(10, 20)
    assert thresholds["planner"] == PromptContextThresholds(30, 40)


def test_role_prompt_context_reports_warning_and_critical_status(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _append_prompt_context_config(
        tmp_path,
        "[prompt_context]\n"
        "warning_tokens = 1\n"
        "critical_tokens = 1_000_000\n"
        "\n[prompt_context.roles.planner]\n"
        "warning_tokens = 1\n"
        "critical_tokens = 2\n",
    )

    report = build_prompt_context_report(Workspace(tmp_path).snapshot)
    by_role = {role.role_name: role for role in report.roles}

    assert by_role["architect"].status == "warning"
    assert by_role["planner"].status == "critical"


def _write_task(root: Path, task_id: str, *, milestone: str, status: str) -> None:
    path = root / ".devlab/tasks" / f"{task_id}_task.md"
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{task_id}"\n'
        f'status = "{status}"\n'
        f'milestone = "{milestone}"\n'
        "depends_on = []\n"
        "+++\n\n"
        f"# {task_id}\n"
    )


def _append_prompt_context_config(root: Path, text: str) -> None:
    path = root / ".devlab/config/agents.toml"
    path.write_text(path.read_text() + "\n" + text)

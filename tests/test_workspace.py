from __future__ import annotations

from pathlib import Path

import pytest

from devlab.task_tracker import FileTaskTracker
from devlab.workspace import Workspace


def test_workspace_snapshot_caches_task_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_task(tmp_path, "T0001")
    calls = 0
    original = FileTaskTracker.list_tasks

    def counting_list_tasks(self: FileTaskTracker):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(FileTaskTracker, "list_tasks", counting_list_tasks)
    snapshot = Workspace(tmp_path).snapshot()

    assert [task.id for task in snapshot.list_tasks()] == ["T0001"]
    assert [task.id for task in snapshot.list_tasks()] == ["T0001"]
    assert calls == 1


def test_workspace_snapshot_is_disposable_after_file_changes(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001")
    workspace = Workspace(tmp_path)
    snapshot = workspace.snapshot()

    assert [task.id for task in snapshot.list_tasks()] == ["T0001"]

    _write_task(tmp_path, "T0002")

    assert [task.id for task in snapshot.list_tasks()] == ["T0001"]
    assert [task.id for task in workspace.snapshot().list_tasks()] == ["T0001", "T0002"]


def test_workspace_task_handle_changes_task_status(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001")
    workspace = Workspace(tmp_path)

    workspace.task("T0001").mark_in_review()
    assert workspace.snapshot().list_tasks()[0].status == "in_review"

    workspace.task_from_path(tmp_path / ".devlab/tasks/T0001_task.md").close()
    assert workspace.snapshot().list_tasks()[0].status == "closed"


def test_workspace_milestone_handle_exposes_tasks_and_transitions(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M1")
    _write_milestone(tmp_path, "M1")
    handoff = tmp_path / ".devlab/history/handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("handoff")
    milestone = Workspace(tmp_path).milestone("M1")

    assert [task.id for task in milestone.tasks()] == ["T0001"]

    milestone.mark_ready_for_integration()
    assert milestone.read().status == "tasks_complete"

    milestone.mark_integrated(handoff)
    assert milestone.read().integrated
    assert milestone.read().integration_handoff == "handoff.md"


def test_workspace_finding_handles_create_and_transition_findings(tmp_path: Path) -> None:
    handoff = tmp_path / ".devlab/history/handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("## Open Issues\nNeeds correction.\n")
    workspace = Workspace(tmp_path)

    finding = workspace.findings().create_from_handoff(
        source="integrator",
        milestone="M1",
        handoff_path=handoff,
    )
    workspace.finding(finding.id).mark_planned()

    planned = workspace.milestone("M1").planned_findings()
    assert [finding.id for finding in planned] == ["F0001"]

    planned[0].mark_resolved()
    assert workspace.finding("F0001").read().status == "resolved"


def _write_task(root: Path, task_id: str, milestone: str | None = None) -> None:
    path = root / ".devlab/tasks" / f"{task_id}_task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{task_id}"\n'
        'status = "open"\n'
        f'{f"milestone = {milestone!r}" if milestone is not None else ""}\n'
        "depends_on = []\n"
        "+++\n\n"
        f"# {task_id}\n"
    )


def _write_milestone(root: Path, milestone_id: str) -> None:
    path = root / ".devlab/milestones" / f"{milestone_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'version = 1\n'
        f'id = "{milestone_id}"\n'
        f'title = "{milestone_id}"\n'
        'status = "planned"\n'
        'integration_required = true\n'
        'integrated = false\n'
        'architecture_approved = false\n'
        'task_ids = ["T0001"]\n'
        'integration_handoff = ""\n'
        'architecture_review_handoff = ""\n'
        'findings = []\n'
    )

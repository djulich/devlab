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


def _write_task(root: Path, task_id: str) -> None:
    path = root / ".devlab/tasks" / f"{task_id}_task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{task_id}"\n'
        'status = "open"\n'
        "depends_on = []\n"
        "+++\n\n"
        f"# {task_id}\n"
    )

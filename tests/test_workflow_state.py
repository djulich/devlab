from __future__ import annotations

from pathlib import Path

from devlab.workflow_state import (
    PlanningState,
    WorkflowState,
    format_workflow_state,
    load_workflow_state,
    set_planning_complete,
)


def test_format_workflow_state_writes_minimal_toml() -> None:
    state = WorkflowState(version=1, planning=PlanningState(complete=True))

    assert format_workflow_state(state) == (
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n"
    )


def test_set_planning_complete_updates_workflow_toml(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True)
    path.write_text("version = 1\n\n[planning]\ncomplete = false\n")

    updated = set_planning_complete(tmp_path, True)

    assert updated.planning.complete is True
    assert load_workflow_state(tmp_path).planning.complete is True
    assert path.read_text() == "version = 1\n\n[planning]\ncomplete = true\n"


def test_set_planning_complete_preserves_unknown_future_state(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "version = 1\n\n"
        "[planning]\n"
        "complete = false\n"
        "generation = 3\n\n"
        "[specs]\n"
        'last_planned_tree = "abc123"\n'
    )

    set_planning_complete(tmp_path, True)

    assert path.read_text() == (
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n"
        "generation = 3\n\n"
        "[specs]\n"
        'last_planned_tree = "abc123"\n'
    )


def test_set_planning_complete_creates_missing_workflow_toml(tmp_path: Path) -> None:
    updated = set_planning_complete(tmp_path, False)

    assert updated.planning.complete is False
    assert (tmp_path / ".devlab/workflow.toml").read_text() == (
        "version = 1\n\n"
        "[planning]\n"
        "complete = false\n"
    )

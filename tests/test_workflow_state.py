from __future__ import annotations

from pathlib import Path

from devlab.workflow_state import (
    PlanningState,
    SpecsState,
    WorkflowState,
    format_workflow_state,
    load_workflow_state,
    set_planning_complete,
    update_workflow_state,
)


def test_format_workflow_state_writes_minimal_toml() -> None:
    state = WorkflowState(version=1, planning=PlanningState(complete=True))

    assert format_workflow_state(state) == (
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n"
        "generation = 1\n"
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
        "generation = 1\n"
    )


def test_parse_workflow_state_defaults_missing_generation_to_one(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True)
    path.write_text("version = 1\n\n[planning]\ncomplete = true\n")

    state = load_workflow_state(tmp_path)

    assert state.planning.generation == 1


def test_format_workflow_state_writes_spec_baseline() -> None:
    state = WorkflowState(
        version=1,
        planning=PlanningState(complete=True, generation=2),
        specs=SpecsState(last_planned_spec_commit="abc123"),
    )

    assert format_workflow_state(state) == (
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n"
        "generation = 2\n\n"
        "[specs]\n"
        'last_planned_spec_commit = "abc123"\n'
    )


def test_update_workflow_state_preserves_unknown_future_state(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "version = 1\n\n"
        "[planning]\n"
        "complete = false\n"
        "future = \"kept\"\n\n"
        "[custom]\n"
        "value = 1\n"
    )

    updated = update_workflow_state(
        tmp_path,
        planning_complete=True,
        planning_generation=3,
        last_planned_spec_commit="def456",
    )

    assert updated.planning.complete is True
    assert updated.planning.generation == 3
    assert updated.specs.last_planned_spec_commit == "def456"
    assert "future = \"kept\"" in path.read_text()
    assert "[custom]\nvalue = 1\n" in path.read_text()
    assert '[specs]\nlast_planned_spec_commit = "def456"\n' in path.read_text()

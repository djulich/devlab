from __future__ import annotations

from pathlib import Path

from devlab.workflow_state import (
    PlanningState,
    ResumeState,
    SpecsState,
    WorkflowState,
    clear_resume_state,
    format_workflow_state,
    load_workflow_state,
    set_planning_complete,
    set_resume_state,
    update_workflow_state,
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


def test_format_workflow_state_writes_spec_baseline() -> None:
    state = WorkflowState(
        version=1,
        planning=PlanningState(complete=True),
        specs=SpecsState(last_planned_spec_commit="abc123"),
    )

    assert format_workflow_state(state) == (
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n\n"
        "[specs]\n"
        'last_planned_spec_commit = "abc123"\n'
    )


def test_format_workflow_state_writes_resume_state() -> None:
    state = WorkflowState(
        version=1,
        planning=PlanningState(complete=True),
        resume=ResumeState(
            blocked_by="CL0001",
            command="implement",
            role="developer",
            task="T0003",
            milestone="",
        ),
    )

    assert format_workflow_state(state) == (
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n\n"
        "[resume]\n"
        'blocked_by = "CL0001"\n'
        'blocked_kind = "clarification"\n'
        'command = "implement"\n'
        'role = "developer"\n'
        'task = "T0003"\n'
        'milestone = ""\n'
    )


def test_load_workflow_state_reads_resume_state(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n\n"
        "[resume]\n"
        'blocked_by = "CL0001"\n'
        'command = "plan"\n'
        'role = "planner"\n'
        'task = ""\n'
        'milestone = ""\n'
    )

    resume = load_workflow_state(tmp_path).resume

    assert resume == ResumeState(
        blocked_by="CL0001",
        command="plan",
        role="planner",
        task="",
        milestone="",
    )


def test_load_workflow_state_reads_typed_research_resume_state(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "version = 1\n\n[planning]\ncomplete = true\n\n[resume]\n"
        'blocked_by = "RS0001"\nblocked_kind = "research"\n'
        'command = "plan"\nrole = "planner"\ntask = ""\nmilestone = "M2"\n'
    )

    assert load_workflow_state(tmp_path).resume == ResumeState(
        blocked_by="RS0001",
        blocked_kind="research",
        command="plan",
        role="planner",
        milestone="M2",
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
        last_planned_spec_commit="def456",
    )

    assert updated.planning.complete is True
    assert updated.specs.last_planned_spec_commit == "def456"
    assert "future = \"kept\"" in path.read_text()
    assert "[custom]\nvalue = 1\n" in path.read_text()
    assert '[specs]\nlast_planned_spec_commit = "def456"\n' in path.read_text()


def test_set_resume_state_preserves_unknown_future_state(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n"
        "future = \"kept\"\n\n"
        "[custom]\n"
        "value = 1\n"
    )

    updated = set_resume_state(
        tmp_path,
        ResumeState(
            blocked_by="CL0001",
            command="implement",
            role="developer",
            task="T0003",
            milestone="",
        ),
    )

    assert updated.resume is not None
    assert updated.resume.blocked_by == "CL0001"
    text = path.read_text()
    assert "future = \"kept\"" in text
    assert "[custom]\nvalue = 1\n" in text
    assert '[resume]\nblocked_by = "CL0001"\n' in text


def test_clear_resume_state_removes_resume_table(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n\n"
        "[resume]\n"
        'blocked_by = "CL0001"\n'
        'command = "implement"\n'
        'role = "developer"\n'
        'task = "T0003"\n'
        'milestone = ""\n\n'
        "[custom]\n"
        "value = 1\n"
    )

    updated = clear_resume_state(tmp_path)

    assert updated.resume is None
    text = path.read_text()
    assert "[resume]" not in text
    assert "[custom]\nvalue = 1\n" in text

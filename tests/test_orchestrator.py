from __future__ import annotations

from pathlib import Path

from harness.orchestrator import (
    DESIGN_PLAN,
    HISTORY_DIR,
    PROJECT_PLAN,
    ROLES,
    _all_milestones_complete,
    _task_is_complete,
    _timestamp,
    assess_state,
    build_system_prompt,
    close_task,
    select_task,
    validate_handoff,
)
from harness.task_tracker import TASKS_DIR


def _setup_tree(root: Path) -> None:
    (root / "work/plans").mkdir(parents=True)
    (root / TASKS_DIR).mkdir(parents=True)
    (root / "work/history").mkdir(parents=True)
    (root / "specs/development").mkdir(parents=True)
    (root / "specs/development/conventions.md").write_text("# Conventions\n")
    (root / "specs/development/tooling.md").write_text("# Tooling\n")
    for role in ROLES.values():
        (root / role.role_file).write_text(f"# Role: {role.name}\n")


def _write_task(
    root: Path,
    task_id: str,
    title: str = "Test task",
    status: str = "open",
    depends_on: list[str] | None = None,
    body: str | None = None,
) -> Path:
    depends_on = depends_on or []
    slug = title.lower().replace(" ", "-")
    path = root / TASKS_DIR / f"{task_id}_{slug}.md"
    depends = ", ".join(f'"{dependency}"' for dependency in depends_on)
    if body is None:
        body = f"# {task_id}: {title}\n\n## Acceptance Criteria\n- [ ] Done\n"
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{title}"\n'
        f'status = "{status}"\n'
        f"depends_on = [{depends}]\n"
        "+++\n\n"
        f"{body}"
    )
    return path


class TestAssessState:
    def test_no_design_plan_returns_architect(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("")
        assert assess_state(tmp_path) == "architect"

    def test_missing_design_plan_returns_architect(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        assert assess_state(tmp_path) == "architect"

    def test_design_plan_exists_no_tasks_returns_planner(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        assert assess_state(tmp_path) == "planner"

    def test_open_tasks_returns_developer(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Setup")
        assert assess_state(tmp_path) == "developer"

    def test_review_tasks_return_reviewer(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Setup", status="in_review")
        assert assess_state(tmp_path) == "reviewer"

    def test_all_tasks_closed_returns_none(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed")
        assert assess_state(tmp_path) is None


class TestAllMilestonesComplete:
    def test_empty_plan_is_not_complete(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("")
        assert _all_milestones_complete(tmp_path) is False

    def test_all_checked_is_complete_without_task_files(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("## M1: Init\n- [x] T0001: Done\n")
        assert _all_milestones_complete(tmp_path) is True

    def test_some_unchecked_is_not_complete_without_task_files(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("- [x] T0001\n- [ ] T0002\n")
        assert _all_milestones_complete(tmp_path) is False

    def test_task_files_override_project_plan_checkboxes(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "Done", status="closed")
        (tmp_path / PROJECT_PLAN).write_text("- [ ] T0001\n")
        assert _all_milestones_complete(tmp_path) is True


class TestSelectTaskCompatibility:
    def test_no_tasks_returns_none(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        assert select_task(tmp_path) is None

    def test_returns_task_path(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        path = _write_task(tmp_path, "T0001", "First")
        assert select_task(tmp_path) == path


class TestTaskIsComplete:
    def test_all_checked(self, tmp_path: Path) -> None:
        f = tmp_path / "task.md"
        f.write_text("- [x] criterion 1\n- [x] criterion 2\n")
        assert _task_is_complete(f) is True

    def test_some_unchecked(self, tmp_path: Path) -> None:
        f = tmp_path / "task.md"
        f.write_text("- [x] criterion 1\n- [ ] criterion 2\n")
        assert _task_is_complete(f) is False

    def test_no_criteria(self, tmp_path: Path) -> None:
        f = tmp_path / "task.md"
        f.write_text("# Task\nNo checklist\n")
        assert _task_is_complete(f) is False


class TestCloseTask:
    def test_marks_task_closed_in_place(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        task = _write_task(tmp_path, "T0001", "Test", status="in_review")
        close_task(tmp_path, task, "reviewer")
        assert task.exists()
        assert 'status = "closed"' in task.read_text()
        history = list((tmp_path / HISTORY_DIR).glob("*_reviewer_closed-task.md"))
        assert history == []


class TestBuildSystemPrompt:
    def test_includes_conventions_and_role_file(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        role = ROLES["planner"]
        prompt = build_system_prompt(tmp_path, role)
        assert "Conventions" in prompt
        assert "Role: planner" in prompt
        assert "Tooling" not in prompt

    def test_includes_tooling_for_developer(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        role = ROLES["developer"]
        prompt = build_system_prompt(tmp_path, role)
        assert "Tooling" in prompt


class TestValidateHandoff:
    def test_valid_handoff(self, tmp_path: Path) -> None:
        handoff = tmp_path / "handoff.md"
        handoff.write_text(
            "# Handoff\n"
            "## Done\n- Work\n"
            "## Changed Artifacts\n- None\n"
            "## Open Issues\n- None\n"
            "## Next Session Hint\nContinue\n"
        )
        valid, error = validate_handoff(handoff)
        assert valid is True
        assert error == ""

    def test_rejects_empty_handoff(self, tmp_path: Path) -> None:
        handoff = tmp_path / "handoff.md"
        handoff.write_text("")
        valid, error = validate_handoff(handoff)
        assert valid is False
        assert "empty" in error


class TestTimestamp:
    def test_format(self) -> None:
        ts = _timestamp()
        assert len(ts) == 15
        assert ts[8] == "T"

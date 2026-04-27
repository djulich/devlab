from __future__ import annotations

from pathlib import Path

from harness.orchestrator import (
    BACKLOG_DIR,
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
)


def _setup_tree(root: Path) -> None:
    (root / "work/plans").mkdir(parents=True)
    (root / "work/backlog").mkdir(parents=True)
    (root / "work/history").mkdir(parents=True)
    (root / "specs/development").mkdir(parents=True)
    (root / "specs/development/conventions.md").write_text("# Conventions\n")
    (root / "specs/development/tooling.md").write_text("# Tooling\n")
    for role in ROLES.values():
        (root / role.role_file).write_text(f"# Role: {role.name}\n")


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
        (tmp_path / BACKLOG_DIR / "T0001_setup.md").write_text("# T0001\n")
        assert assess_state(tmp_path) == "developer"

    def test_all_milestones_complete_returns_none(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        (tmp_path / PROJECT_PLAN).write_text("## M1: Init\n- [x] T0001: Done\n")
        assert assess_state(tmp_path) is None


class TestAllMilestonesComplete:
    def test_empty_plan_is_not_complete(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("")
        assert _all_milestones_complete(tmp_path) is False

    def test_all_checked_is_complete(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("- [x] T0001\n- [x] T0002\n")
        assert _all_milestones_complete(tmp_path) is True

    def test_some_unchecked_is_not_complete(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("- [x] T0001\n- [ ] T0002\n")
        assert _all_milestones_complete(tmp_path) is False

    def test_no_checklist_items_is_not_complete(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("# Project Plan\nJust text\n")
        assert _all_milestones_complete(tmp_path) is False


class TestSelectTask:
    def test_no_tasks_returns_none(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        assert select_task(tmp_path) is None

    def test_returns_lowest_numbered(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / BACKLOG_DIR / "T0003_third.md").write_text("")
        (tmp_path / BACKLOG_DIR / "T0001_first.md").write_text("")
        (tmp_path / BACKLOG_DIR / "T0002_second.md").write_text("")
        result = select_task(tmp_path)
        assert result is not None
        assert result.name == "T0001_first.md"


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
    def test_archives_and_removes(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        task = tmp_path / BACKLOG_DIR / "T0001_test.md"
        task.write_text("# T0001\n- [x] done\n")
        close_task(tmp_path, task, "developer")
        assert not task.exists()
        history = list((tmp_path / HISTORY_DIR).glob("*_developer_closed-task.md"))
        assert len(history) == 1


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


class TestTimestamp:
    def test_format(self) -> None:
        ts = _timestamp()
        assert len(ts) == 15
        assert ts[8] == "T"

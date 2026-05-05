from __future__ import annotations

from pathlib import Path

import pytest

from harness.task_tracker import TASKS_DIR, FileTaskTracker, TaskStatus


def _setup_tasks_dir(root: Path) -> None:
    (root / TASKS_DIR).mkdir(parents=True)


def _write_task(
    root: Path,
    task_id: str,
    title: str = "Test task",
    status: str = "open",
    depends_on: list[str] | None = None,
    extra_metadata: str = "",
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
        f"{extra_metadata}"
        "+++\n\n"
        f"{body}"
    )
    return path


class TestFileTaskTrackerParsing:
    def test_lists_tasks_sorted_by_task_id(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0003", "Third")
        _write_task(tmp_path, "T0001", "First")
        _write_task(tmp_path, "T0002", "Second")

        tasks = FileTaskTracker(tmp_path).list_tasks()

        assert [task.id for task in tasks] == ["T0001", "T0002", "T0003"]

    def test_reads_front_matter_fields(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(
            tmp_path,
            "T0001",
            "First",
            status="changes_requested",
            depends_on=["T0000"],
            extra_metadata='milestone = "M1"\npriority = "high"\n',
        )

        task = FileTaskTracker(tmp_path).get("T0001")

        assert task.id == "T0001"
        assert task.title == "First"
        assert task.status == TaskStatus.CHANGES_REQUESTED
        assert task.milestone == "M1"
        assert task.depends_on == ("T0000",)
        assert task.metadata["priority"] == "high"

    def test_missing_front_matter_defaults_to_open_task(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = tmp_path / TASKS_DIR / "T0001_first.md"
        path.write_text("# T0001: First\n\n## Acceptance Criteria\n- [ ] Done\n")

        task = FileTaskTracker(tmp_path).get("T0001")

        assert task.title == "First"
        assert task.status == TaskStatus.OPEN

    def test_reads_legacy_depends_on_section(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = tmp_path / TASKS_DIR / "T0001_first.md"
        path.write_text(
            "# T0001: First\n\n"
            "## Depends On\n"
            "- T0002\n"
            "- T0003\n\n"
            "## Acceptance Criteria\n"
            "- [ ] Done\n"
        )

        task = FileTaskTracker(tmp_path).get("T0001")

        assert task.depends_on == ("T0002", "T0003")

    def test_rejects_invalid_status(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", status="invalid")

        with pytest.raises(ValueError, match="invalid task status"):
            FileTaskTracker(tmp_path).list_tasks()

    def test_rejects_non_list_depends_on(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = tmp_path / TASKS_DIR / "T0001_first.md"
        path.write_text(
            "+++\n"
            'id = "T0001"\n'
            'title = "First"\n'
            'status = "open"\n'
            'depends_on = "T0002"\n'
            "+++\n\n"
            "# T0001: First\n"
        )

        with pytest.raises(ValueError, match="depends_on"):
            FileTaskTracker(tmp_path).list_tasks()


class TestFileTaskTrackerSelection:
    def test_selects_lowest_eligible_development_task(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0003", "Third")
        _write_task(tmp_path, "T0001", "First")
        _write_task(tmp_path, "T0002", "Second")

        result = FileTaskTracker(tmp_path).select_next_development_task()

        assert result is not None
        assert result.id == "T0001"

    def test_changes_requested_tasks_are_eligible_for_development(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", status="changes_requested")

        result = FileTaskTracker(tmp_path).select_next_development_task()

        assert result is not None
        assert result.id == "T0001"

    def test_in_review_and_closed_tasks_are_not_development_eligible(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", status="in_review")
        _write_task(tmp_path, "T0002", status="closed")

        assert FileTaskTracker(tmp_path).select_next_development_task() is None

    def test_skips_tasks_with_non_closed_dependencies(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", "First", depends_on=["T0002"])
        _write_task(tmp_path, "T0002", "Second")

        result = FileTaskTracker(tmp_path).select_next_development_task()

        assert result is not None
        assert result.id == "T0002"

    def test_allows_tasks_with_closed_dependencies(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", "First", depends_on=["T0002"])
        _write_task(tmp_path, "T0002", "Second", status="closed")

        result = FileTaskTracker(tmp_path).select_next_development_task()

        assert result is not None
        assert result.id == "T0001"

    def test_select_next_review_task_returns_lowest_in_review_task(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0002", "Second", status="in_review")
        _write_task(tmp_path, "T0001", "First", status="in_review")

        result = FileTaskTracker(tmp_path).select_next_review_task()

        assert result is not None
        assert result.id == "T0001"

    def test_blocked_tasks_reports_only_developable_tasks_with_open_dependencies(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", "Blocked", depends_on=["T0002"])
        _write_task(tmp_path, "T0002", "Dependency", status="in_review")
        _write_task(tmp_path, "T0003", "Closed blocked", status="closed", depends_on=["T0002"])

        blocked = FileTaskTracker(tmp_path).blocked_tasks()

        assert [task.id for task in blocked] == ["T0001"]


class TestFileTaskTrackerStatusTransitions:
    def test_mark_in_review_writes_status_to_task_file(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = _write_task(tmp_path, "T0001", "First")

        FileTaskTracker(tmp_path).mark_in_review("T0001")

        assert 'status = "in_review"' in path.read_text()

    def test_mark_changes_requested_writes_status_to_task_file(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = _write_task(tmp_path, "T0001", "First", status="in_review")

        FileTaskTracker(tmp_path).mark_changes_requested("T0001")

        assert 'status = "changes_requested"' in path.read_text()

    def test_close_writes_status_to_task_file(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = _write_task(tmp_path, "T0001", "First", status="in_review")

        FileTaskTracker(tmp_path).close("T0001")

        assert 'status = "closed"' in path.read_text()

    def test_status_update_preserves_body_and_extra_metadata(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = _write_task(
            tmp_path,
            "T0001",
            "First",
            extra_metadata='owner = "agent"\n',
            body="# T0001: First\n\n## Goal\nKeep this body.\n",
        )

        FileTaskTracker(tmp_path).mark_in_review("T0001")

        text = path.read_text()
        assert 'owner = "agent"' in text
        assert "## Goal\nKeep this body." in text

    def test_get_unknown_task_raises_key_error(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)

        with pytest.raises(KeyError, match="unknown task id"):
            FileTaskTracker(tmp_path).get("T9999")


class TestFileTaskTrackerStateSummary:
    def test_has_active_tasks_excludes_closed_tasks(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", status="closed")

        assert FileTaskTracker(tmp_path).has_active_tasks() is False

    def test_all_tasks_closed_requires_at_least_one_task(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)

        assert FileTaskTracker(tmp_path).all_tasks_closed() is False

    def test_all_tasks_closed_returns_true_when_every_task_is_closed(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", status="closed")
        _write_task(tmp_path, "T0002", status="closed")

        assert FileTaskTracker(tmp_path).all_tasks_closed() is True

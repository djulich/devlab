from __future__ import annotations

from pathlib import Path

import pytest

from devlab.task_tracker import TASKS_DIR, FileTaskTracker, TaskStatus


def _setup_tasks_dir(root: Path) -> None:
    (root / TASKS_DIR).mkdir(parents=True)


def _write_task(
    root: Path,
    task_id: str,
    title: str = "Test task",
    status: str = "open",
    milestone: str | None = None,
    depends_on: list[str] | None = None,
    validation: list[str] | None = None,
    domain: str | None = None,
    extra_metadata: str = "",
    body: str | None = None,
) -> Path:
    depends_on = depends_on or []
    slug = title.lower().replace(" ", "-")
    path = root / TASKS_DIR / f"{task_id}_{slug}.md"
    depends = ", ".join(f'"{dependency}"' for dependency in depends_on)
    milestone_line = f'milestone = "{milestone}"\n' if milestone is not None else ""
    validation_line = ""
    domain_line = f'domain = "{domain}"\n' if domain is not None else ""
    if validation is not None:
        validation_commands = ", ".join(f'"{command}"' for command in validation)
        validation_line = f"validation = [{validation_commands}]\n"
    if body is None:
        body = f"# {task_id}: {title}\n\n## Acceptance Criteria\n- [ ] Done\n"
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{title}"\n'
        f'status = "{status}"\n'
        f"{milestone_line}"
        f"depends_on = [{depends}]\n"
        f"{domain_line}"
        f"{validation_line}"
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
            extra_metadata='milestone = "M1"\nprofile = "api"\npriority = "high"\n',
        )

        task = FileTaskTracker(tmp_path).get("T0001")

        assert task.id == "T0001"
        assert task.title == "First"
        assert task.status == TaskStatus.CHANGES_REQUESTED
        assert task.milestone == "M1"
        assert task.profile == "api"
        assert task.domain == "general"
        assert task.depends_on == ("T0000",)
        assert task.addresses_findings == ()
        assert task.validation is None
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

    def test_reads_addresses_findings(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(
            tmp_path,
            "T0001",
            extra_metadata='addresses_findings = ["F0001", "F0002"]\n',
        )

        task = FileTaskTracker(tmp_path).get("T0001")

        assert task.addresses_findings == ("F0001", "F0002")

    def test_rejects_non_list_addresses_findings(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", extra_metadata='addresses_findings = "F0001"\n')

        with pytest.raises(ValueError, match="addresses_findings"):
            FileTaskTracker(tmp_path).list_tasks()

    def test_reads_task_domain(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", domain="deployment")

        task = FileTaskTracker(tmp_path).get("T0001")

        assert task.domain == "deployment"
        assert task.metadata["domain"] == "deployment"

    def test_rejects_invalid_task_domain(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", domain="../deployment")

        with pytest.raises(ValueError, match="domain"):
            FileTaskTracker(tmp_path).get("T0001")

    def test_reads_validation_commands(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(
            tmp_path,
            "T0001",
            validation=["uv run pytest", "cd frontend && npm test"],
        )

        task = FileTaskTracker(tmp_path).get("T0001")

        assert task.validation == ("uv run pytest", "cd frontend && npm test")

    def test_distinguishes_omitted_validation_from_explicit_empty_validation(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", "Omitted")
        _write_task(tmp_path, "T0002", "Empty", validation=[])

        omitted = FileTaskTracker(tmp_path).get("T0001")
        explicit_empty = FileTaskTracker(tmp_path).get("T0002")

        assert omitted.validation is None
        assert explicit_empty.validation == ()

    def test_rejects_non_list_validation(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = tmp_path / TASKS_DIR / "T0001_first.md"
        path.write_text(
            "+++\n"
            'id = "T0001"\n'
            'title = "First"\n'
            'status = "open"\n'
            'validation = "uv run pytest"\n'
            "+++\n\n"
            "# T0001: First\n"
        )

        with pytest.raises(ValueError, match="validation"):
            FileTaskTracker(tmp_path).list_tasks()

    def test_acceptance_criteria_complete_when_all_criteria_checked(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(
            tmp_path,
            "T0001",
            body=(
                "# T0001: First\n\n"
                "## Acceptance Criteria\n"
                "- [x] First criterion\n"
                "- [X] Second criterion\n"
            ),
        )

        assert FileTaskTracker(tmp_path).get("T0001").acceptance_criteria_complete

    def test_acceptance_criteria_incomplete_when_any_criterion_unchecked(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(
            tmp_path,
            "T0001",
            body=(
                "# T0001: First\n\n"
                "## Acceptance Criteria\n"
                "- [x] First criterion\n"
                "- [ ] Second criterion\n"
            ),
        )

        assert not FileTaskTracker(tmp_path).get("T0001").acceptance_criteria_complete

    def test_acceptance_criteria_missing_or_without_checkboxes_is_incomplete(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", "Missing", body="# T0001: Missing\n")
        _write_task(
            tmp_path,
            "T0002",
            "No boxes",
            body="# T0002: No boxes\n\n## Acceptance Criteria\nShip it.\n",
        )

        assert not FileTaskTracker(tmp_path).get("T0001").acceptance_criteria_complete
        assert not FileTaskTracker(tmp_path).get("T0002").acceptance_criteria_complete

    def test_acceptance_criteria_ignores_checkboxes_outside_section(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(
            tmp_path,
            "T0001",
            body=(
                "# T0001: First\n\n"
                "## Acceptance Criteria\n"
                "- [x] Criterion\n\n"
                "## Notes\n"
                "- [ ] Unrelated note\n"
            ),
        )

        assert FileTaskTracker(tmp_path).get("T0001").acceptance_criteria_complete

    def test_review_approved_reads_review_section_only(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(
            tmp_path,
            "T0001",
            body=(
                "# T0001: First\n\n"
                "## Acceptance Criteria\n"
                "- [x] Criterion\n\n"
                "## Notes\n"
                "- [x] Approved\n"
            ),
        )
        _write_task(
            tmp_path,
            "T0002",
            body=(
                "# T0002: Second\n\n"
                "## Acceptance Criteria\n"
                "- [x] Criterion\n\n"
                "## Review\n"
                "- [x] Approved\n"
            ),
        )

        assert not FileTaskTracker(tmp_path).get("T0001").review_approved
        assert FileTaskTracker(tmp_path).get("T0002").review_approved


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

    def test_status_transition_preserves_addresses_findings(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = _write_task(
            tmp_path,
            "T0001",
            "First",
            extra_metadata='addresses_findings = ["F0001"]\n',
        )

        FileTaskTracker(tmp_path).mark_in_review("T0001")

        assert 'addresses_findings = ["F0001"]' in path.read_text()

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

    def test_status_update_preserves_body_validation_and_extra_metadata(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        path = _write_task(
            tmp_path,
            "T0001",
            "First",
            validation=["uv run pytest"],
            domain="deployment",
            extra_metadata='profile = "api"\nowner = "agent"\n',
            body="# T0001: First\n\n## Goal\nKeep this body.\n",
        )

        FileTaskTracker(tmp_path).mark_in_review("T0001")

        text = path.read_text()
        assert 'validation = ["uv run pytest"]' in text
        assert 'profile = "api"' in text
        assert 'domain = "deployment"' in text
        assert 'owner = "agent"' in text
        assert "## Goal\nKeep this body." in text

    def test_status_update_preserves_omitted_validation(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = _write_task(tmp_path, "T0001", "First")

        FileTaskTracker(tmp_path).mark_in_review("T0001")

        assert "validation =" not in path.read_text()

    def test_status_update_preserves_explicit_empty_validation(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        path = _write_task(tmp_path, "T0001", "First", validation=[])

        FileTaskTracker(tmp_path).mark_in_review("T0001")

        assert "validation = []" in path.read_text()

    def test_get_unknown_task_raises_key_error(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)

        with pytest.raises(KeyError, match="unknown task id"):
            FileTaskTracker(tmp_path).get("T9999")


class TestFileTaskTrackerMilestones:
    def test_lists_milestones_naturally_and_ignores_tasks_without_milestone(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", milestone="M10")
        _write_task(tmp_path, "T0002", milestone="M2")
        _write_task(tmp_path, "T0003")

        assert FileTaskTracker(tmp_path).milestones() == ["M2", "M10"]

    def test_milestone_complete_requires_all_milestone_tasks_closed(
        self, tmp_path: Path
    ) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", status="closed", milestone="M1")
        _write_task(tmp_path, "T0002", status="open", milestone="M1")

        assert FileTaskTracker(tmp_path).milestone_complete("M1") is False

    def test_milestone_complete_when_all_milestone_tasks_closed(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", status="closed", milestone="M1")
        _write_task(tmp_path, "T0002", status="closed", milestone="M1")
        _write_task(tmp_path, "T0003", status="open", milestone="M2")

        assert FileTaskTracker(tmp_path).milestone_complete("M1") is True

    def test_completed_milestones_returns_only_complete_milestones(self, tmp_path: Path) -> None:
        _setup_tasks_dir(tmp_path)
        _write_task(tmp_path, "T0001", status="closed", milestone="M1")
        _write_task(tmp_path, "T0002", status="closed", milestone="M2")
        _write_task(tmp_path, "T0003", status="open", milestone="M2")

        assert FileTaskTracker(tmp_path).completed_milestones() == ["M1"]


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

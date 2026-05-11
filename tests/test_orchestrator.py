from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devlab.agents import AgentCall, MockProvider
from devlab.findings import FINDINGS_DIR, FileFindingTracker, FindingStatus
from devlab.milestones import FileMilestoneTracker, MilestoneStatus
from devlab.orchestrator import (
    DESIGN_PLAN,
    HISTORY_DIR,
    PROJECT_PLAN,
    ROLES,
    _all_milestones_complete,
    _task_is_complete,
    _timestamp,
    assess_state,
    build_session_prompt,
    build_system_prompt,
    close_task,
    run_loop,
    select_architecture_review_milestone,
    select_task,
    validate_handoff,
)
from devlab.task_tracker import TASKS_DIR


def _setup_tree(root: Path) -> None:
    (root / ".devlab/plans").mkdir(parents=True)
    (root / ".devlab/config").mkdir(parents=True)
    (root / TASKS_DIR).mkdir(parents=True)
    (root / ".devlab/history").mkdir(parents=True)
    (root / FINDINGS_DIR).mkdir(parents=True)
    (root / ".devlab/config/tooling.md").write_text("# Tooling\n")
    (root / ".devlab/config/profiles").mkdir(parents=True)
    (root / ".devlab/config/profiles/default.toml").write_text(
        'version = 1\n'
        'id = "default"\n'
        'title = "Default"\n'
        '\n[environment]\n'
        'managed_roles = ["developer", "reviewer", "integrator"]\n'
    )


def _write_task(
    root: Path,
    task_id: str,
    title: str = "Test task",
    status: str = "open",
    milestone: str | None = None,
    profile: str | None = None,
    depends_on: list[str] | None = None,
    validation: list[str] | None = None,
    body: str | None = None,
) -> Path:
    depends_on = depends_on or []
    slug = title.lower().replace(" ", "-")
    path = root / TASKS_DIR / f"{task_id}_{slug}.md"
    depends = ", ".join(f'"{dependency}"' for dependency in depends_on)
    milestone_line = f'milestone = "{milestone}"\n' if milestone is not None else ""
    profile_line = f'profile = "{profile}"\n' if profile is not None else ""
    validation_line = ""
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
        f"{profile_line}"
        f"depends_on = [{depends}]\n"
        f"{validation_line}"
        "+++\n\n"
        f"{body}"
    )
    return path


def _write_milestone(
    root: Path,
    milestone_id: str,
    *,
    integrated: bool = False,
    architecture_approved: bool = False,
    task_ids: list[str] | None = None,
) -> Path:
    path = root / ".devlab/milestones" / f"{milestone_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if architecture_approved:
        status = "architecture_approved"
    elif integrated:
        status = "integrated"
    else:
        status = "planned"
    task_ids_text = ", ".join(f'"{task_id}"' for task_id in (task_ids or []))
    path.write_text(
        "version = 1\n"
        f'id = "{milestone_id}"\n'
        f'title = "{milestone_id}"\n'
        f'status = "{status}"\n'
        "integration_required = true\n"
        f"integrated = {str(integrated).lower()}\n"
        f"architecture_approved = {str(architecture_approved).lower()}\n"
        f"task_ids = [{task_ids_text}]\n"
        'integration_handoff = ""\n'
        'architecture_review_handoff = ""\n'
        "findings = []\n"
    )
    return path


def _write_profile(
    root: Path,
    profile_id: str,
    *,
    validation: list[str] | None = None,
    environment: str = "",
) -> Path:
    profiles = root / ".devlab/config/profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    validation = validation or []
    validation_text = ", ".join(f'"{command}"' for command in validation)
    path = profiles / f"{profile_id}.toml"
    path.write_text(
        "version = 1\n"
        f"id = \"{profile_id}\"\n"
        f"title = \"{profile_id}\"\n"
        "\n[tooling]\n"
        f"default_validation = [{validation_text}]\n"
        f"{environment}"
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


class TestBuildSessionPrompt:
    def test_planner_prompt_includes_existing_profiles(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_profile(tmp_path, "api", validation=["uv run pytest tests/api"])

        prompt = build_session_prompt(tmp_path, "planner")

        assert "## Existing Profiles" in prompt
        assert "api.toml" in prompt
        assert "uv run pytest tests/api" in prompt

    def test_developer_prompt_includes_task_validation_commands(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First", validation=["uv run pytest"])

        prompt = build_session_prompt(tmp_path, "developer")

        assert "## Task Validation Commands" in prompt
        assert "`uv run pytest`" in prompt

    def test_developer_prompt_omits_validation_section_when_validation_is_omitted(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First")

        prompt = build_session_prompt(tmp_path, "developer")

        assert "## Task Validation Commands" not in prompt

    def test_developer_prompt_uses_profile_default_validation_when_validation_is_omitted(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_profile(tmp_path, "api", validation=["uv run pytest tests/api"])
        _write_task(tmp_path, "T0001", "First", profile="api")

        prompt = build_session_prompt(tmp_path, "developer")

        assert "Profile: `api`" in prompt
        assert "default validation from profile `api`" in prompt
        assert "`uv run pytest tests/api`" in prompt

    def test_developer_prompt_explains_explicit_empty_validation(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First", validation=[])

        prompt = build_session_prompt(tmp_path, "developer")

        assert "## Task Validation Commands" in prompt
        assert "validation = []" in prompt
        assert "No validation commands are required" in prompt
        assert "whether any validation was run and why" in prompt


class TestBuildSystemPrompt:
    def test_planner_includes_tooling(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        role = ROLES["planner"]
        prompt = build_system_prompt(tmp_path, role)
        assert "Conventions" in prompt
        assert "Role: Planner" in prompt
        assert "Tooling" in prompt

    def test_developer_includes_tooling(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        role = ROLES["developer"]
        prompt = build_system_prompt(tmp_path, role)
        assert "Tooling" in prompt


def _checked_task_body(task_id: str, title: str) -> str:
    return f"# {task_id}: {title}\n\n## Acceptance Criteria\n- [x] Done\n"


def _approve_task(call: AgentCall, task_id: str | None = None) -> None:
    if task_id is None:
        task_path = next((call.root / TASKS_DIR).glob("T*.md"))
    else:
        task_path = next((call.root / TASKS_DIR).glob(f"{task_id}_*.md"))
    task_path.write_text(task_path.read_text() + "\n## Review\n- [x] Approved\n")


def _complete_developer_task(call: AgentCall) -> None:
    task_path = next((call.root / TASKS_DIR).glob("T*.md"))
    text = task_path.read_text().replace("- [ ] Done", "- [x] Done")
    task_path.write_text(text)


class TestRunLoop:
    def test_developer_completed_task_is_marked_in_review(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First", body=_checked_task_body("T0001", "First"))
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert len(provider.calls) == 1
        assert provider.calls[0].role_name == "developer"
        assert 'status = "in_review"' in task.read_text()

    def test_developer_incomplete_task_stays_open(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First")
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert provider.calls[0].role_name == "developer"
        assert 'status = "open"' in task.read_text()

    def test_managed_role_runs_environment_lifecycle_around_session(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        _write_profile(
            tmp_path,
            "default",
            environment=(
                '\n[environment]\n'
                'managed_roles = ["developer"]\n'
                'pre_session = ["echo pre >> env-order.log"]\n'
                'setup = ["echo setup >> env-order.log"]\n'
                'post_session = ["echo post >> env-order.log"]\n'
            ),
        )

        def on_invoke(call: AgentCall) -> None:
            with (call.root / "env-order.log").open("a") as file:
                file.write("agent\n")

        provider = MockProvider(on_invoke=on_invoke)

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert (tmp_path / "env-order.log").read_text().splitlines() == [
            "pre",
            "setup",
            "agent",
            "post",
        ]
        assert list((tmp_path / ".devlab/logs/environment").glob("*_developer_*.log"))

    def test_task_profile_environment_lifecycle_is_used(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First", profile="api")
        _write_profile(
            tmp_path,
            "api",
            environment=(
                '\n[environment]\n'
                'managed_roles = ["developer"]\n'
                'setup = ["echo profile >> env-order.log"]\n'
            ),
        )
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert (tmp_path / "env-order.log").read_text().splitlines() == ["profile"]

    def test_unmanaged_planner_does_not_run_environment_lifecycle(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_profile(
            tmp_path,
            "default",
            environment=(
                '\n[environment]\n'
                'managed_roles = ["planner"]\n'
                'pre_session = ["echo pre >> env-order.log"]\n'
                'setup = ["echo setup >> env-order.log"]\n'
                'post_session = ["echo post >> env-order.log"]\n'
            ),
        )
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert provider.calls[0].role_name == "planner"
        assert not (tmp_path / "env-order.log").exists()

    def test_environment_setup_failure_prevents_agent_invocation(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        _write_profile(
            tmp_path,
            "default",
            environment=(
                '\n[environment]\n'
                'managed_roles = ["developer"]\n'
                'setup = ["exit 7"]\n'
            ),
        )
        provider = MockProvider()

        with pytest.raises(SystemExit) as exc_info:
            run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert exc_info.value.code == 1
        assert provider.calls == []
        assert list((tmp_path / ".devlab/logs/environment").glob("*_developer_setup_*.log"))

    def test_environment_teardown_runs_after_agent_failure(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        _write_profile(
            tmp_path,
            "default",
            environment=(
                '\n[environment]\n'
                'managed_roles = ["developer"]\n'
                'post_session = ["echo post >> env-order.log"]\n'
            ),
        )
        provider = MockProvider(return_code=3)

        with pytest.raises(SystemExit) as exc_info:
            run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert exc_info.value.code == 3
        assert (tmp_path / "env-order.log").read_text().splitlines() == ["post"]

    def test_reviewer_approval_closes_task(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(
            tmp_path,
            "T0001",
            "Review",
            status="in_review",
            body=_checked_task_body("T0001", "Review") + "\n## Review\n- [x] Approved\n",
        )
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert provider.calls[0].role_name == "reviewer"
        assert 'status = "closed"' in task.read_text()

    def test_reviewer_rejection_sets_changes_requested(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(
            tmp_path,
            "T0001",
            "Review",
            status="in_review",
            body=_checked_task_body("T0001", "Review"),
        )
        provider = MockProvider(
            handoff_text=(
                "# Handoff: reviewer\n"
                "## Done\n- Reviewed task.\n"
                "## Changed Artifacts\n- .devlab/tasks/T0001_review.md (modified)\n"
                "## Open Issues\n- Fix the implementation.\n"
                "## Addressed Findings\n- None\n"
                "## Next Session Hint\nAddress requested changes.\n"
            )
        )

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert provider.calls[0].role_name == "reviewer"
        assert 'status = "changes_requested"' in task.read_text()

    def test_invalid_handoff_stops_loop_without_status_change(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First", body=_checked_task_body("T0001", "First"))
        provider = MockProvider(write_handoff=False)

        try:
            run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        assert provider.calls[0].role_name == "developer"
        assert 'status = "open"' in task.read_text()

    def test_two_session_developer_reviewer_happy_path(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First")

        def on_invoke(call: AgentCall) -> None:
            if call.role_name == "developer":
                _complete_developer_task(call)
            elif call.role_name == "reviewer":
                _approve_task(call)

        provider = MockProvider(on_invoke=on_invoke)

        run_loop(tmp_path, auto=True, max_sessions=2, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["developer", "reviewer"]
        assert 'status = "closed"' in task.read_text()

    def test_completed_milestone_selects_integrator(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["integrator"]

    def test_integrated_architecture_approved_milestone_stops(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        _write_milestone(
            tmp_path,
            "M1",
            integrated=True,
            architecture_approved=True,
            task_ids=["T0001"],
        )
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert provider.calls == []

    def test_architect_review_runs_before_developer_for_next_milestone(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "M1 Done", status="closed", milestone="M1")
        _write_task(tmp_path, "T0002", "M2 Open", status="open", milestone="M2")
        _write_milestone(tmp_path, "M1", integrated=True, task_ids=["T0001"])
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["architect"]

    def test_integrator_runs_before_developer_for_next_milestone_without_architecture_review(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "M1 Done", status="closed", milestone="M1")
        _write_task(tmp_path, "T0002", "M2 Open", status="open", milestone="M2")
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["integrator"]

    def test_successful_integrator_handoff_marks_milestone_integrated(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        milestone = FileMilestoneTracker(tmp_path).get("M1")
        assert milestone.status == MilestoneStatus.INTEGRATED
        assert milestone.integrated is True
        assert milestone.integration_handoff.endswith("_integrator_handoff.md")

    def test_integrator_open_issues_create_finding_and_mark_milestone_failed(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        provider = MockProvider(
            handoff_text=(
                "# Handoff: integrator\n"
                "## Done\n- Ran integration checks.\n"
                "## Changed Artifacts\n- None\n"
                "## Open Issues\n- Missing frontend/API E2E coverage.\n"
                "## Addressed Findings\n- None\n"
                "## Next Session Hint\nPlan follow-up coverage task.\n"
            )
        )

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        findings = FileFindingTracker(tmp_path).open_findings()
        assert len(findings) == 1
        assert findings[0].source == "integrator"
        assert findings[0].milestone == "M1"
        assert "Missing frontend/API E2E coverage" in findings[0].body
        milestone = FileMilestoneTracker(tmp_path).get("M1")
        assert milestone.status == MilestoneStatus.INTEGRATION_FAILED
        assert milestone.integrated is False
        assert milestone.findings == (findings[0].id,)

    def test_successful_integration_then_architecture_review_in_next_session(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=2, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["integrator", "architect"]
        milestone = FileMilestoneTracker(tmp_path).get("M1")
        assert milestone.integrated is True
        assert milestone.architecture_approved is True

    def test_integrated_milestone_selects_architect_review(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        _write_milestone(tmp_path, "M1", integrated=True, task_ids=["T0001"])

        assert assess_state(tmp_path) == "architect"
        assert select_architecture_review_milestone(tmp_path) == "M1"

    def test_architect_review_handoff_marks_milestone_reviewed(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        _write_milestone(tmp_path, "M1", integrated=True, task_ids=["T0001"])
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["architect"]
        milestone = FileMilestoneTracker(tmp_path).get("M1")
        assert milestone.status == MilestoneStatus.ARCHITECTURE_APPROVED
        assert milestone.architecture_approved is True
        assert milestone.architecture_review_handoff.endswith("_architect_handoff.md")

    def test_architect_review_open_issues_create_finding(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        _write_milestone(tmp_path, "M1", integrated=True, task_ids=["T0001"])
        provider = MockProvider(
            handoff_text=(
                "# Handoff: architect\n"
                "## Done\n- Reviewed architecture.\n"
                "## Changed Artifacts\n- None\n"
                "## Open Issues\n- Design plan misses implemented boundary.\n"
                "## Addressed Findings\n- None\n"
                "## Next Session Hint\nPlan design correction.\n"
            )
        )

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        findings = FileFindingTracker(tmp_path).open_findings()
        assert len(findings) == 1
        assert findings[0].source == "architect"
        assert findings[0].milestone == "M1"
        assert "Design plan misses implemented boundary" in findings[0].body
        assert FileMilestoneTracker(tmp_path).get("M1").architecture_approved is False

    def test_architecture_review_prompt_includes_milestone_context(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        (tmp_path / PROJECT_PLAN).write_text("## M1: Foundation\n- T0001\n")
        (tmp_path / ".devlab/specs/system/README.md").parent.mkdir(parents=True)
        (tmp_path / ".devlab/specs/system/README.md").write_text("# System Spec\n")
        _write_task(
            tmp_path,
            "T0001",
            "Done",
            status="closed",
            milestone="M1",
            body="# T0001: Done\n\n## Goal\nImportant architecture behavior.\n",
        )
        _write_milestone(tmp_path, "M1", integrated=True, task_ids=["T0001"])

        prompt = build_session_prompt(tmp_path, "architect")

        assert "## Assigned Integrated Milestone for Architecture Review" in prompt
        assert "M1" in prompt
        assert "Important architecture behavior" in prompt
        assert "# System Spec" in prompt

    def test_open_finding_selects_planner_before_integrator(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        FileFindingTracker(tmp_path).create(
            title="Missing E2E coverage",
            source="integrator",
            milestone="M1",
            body="# Finding\n",
        )
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["planner"]

    def test_planner_addressed_findings_are_marked_planned(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        finding = FileFindingTracker(tmp_path).create(
            title="Missing E2E coverage",
            source="integrator",
            milestone="M1",
            body="# Finding\n",
        )
        provider = MockProvider(
            handoff_text=(
                "# Handoff: planner\n"
                "## Done\n- Created follow-up task.\n"
                "## Changed Artifacts\n- .devlab/tasks/T0002_e2e.md (created)\n"
                "## Open Issues\n- None\n"
                "## Addressed Findings\n"
                f"- {finding.id}\n"
                "## Next Session Hint\nImplement follow-up task.\n"
            )
        )

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert FileFindingTracker(tmp_path).get(finding.id).status == FindingStatus.PLANNED

    def test_successful_integration_resolves_planned_milestone_findings(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        tracker = FileFindingTracker(tmp_path)
        finding = tracker.create(
            title="Missing E2E coverage",
            source="integrator",
            milestone="M1",
            body="# Finding\n",
        )
        tracker.mark_planned(finding.id)
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert FileFindingTracker(tmp_path).get(finding.id).status == FindingStatus.RESOLVED

    def test_integrator_prompt_includes_milestone_and_task_content(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(
            tmp_path,
            "T0001",
            "Done",
            status="closed",
            milestone="M1",
            body="# T0001: Done\n\n## Goal\nImportant integration behavior.\n",
        )

        prompt = build_session_prompt(tmp_path, "integrator")

        assert "## Assigned Completed Milestone" in prompt
        assert "M1" in prompt
        assert "previously implemented system" in prompt
        assert "Important integration behavior" in prompt

    def test_logs_resolved_agent_config_for_configured_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        (tmp_path / ".devlab/config/agents.toml").write_text(
            "[defaults]\n"
            'provider = "mock-cli"\n'
            'model = "test-model"\n'
            'effort = "medium"\n'
            "\n[providers.mock-cli]\n"
            'command = "mock-agent"\n'
            'args = ["--role", "{role_name}", "--model", "{model}"]\n'
        )

        def fake_run(*args: Any, **kwargs: Any) -> object:
            handoff = (
                Path(kwargs["cwd"])
                / ".devlab/session-artifacts/developer/handoff.md"
            )
            handoff.parent.mkdir(parents=True, exist_ok=True)
            handoff.write_text(
                "# Handoff: developer\n"
                "## Done\n- done\n"
                "## Changed Artifacts\n- None\n"
                "## Open Issues\n- None\n"
                "## Addressed Findings\n- None\n"
                "## Next Session Hint\nContinue.\n"
            )

            class Result:
                returncode = 0

            return Result()

        monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

        run_loop(tmp_path, auto=True, max_sessions=1)

        logs = list((tmp_path / ".devlab/logs/agents").glob("*_developer.toml"))
        assert len(logs) == 1
        text = logs[0].read_text()
        assert 'role = "developer"' in text
        assert 'provider = "mock-cli"' in text
        assert 'model = "test-model"' in text
        assert "system_prompt" not in text

    def test_uses_role_specific_agent_provider(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Review", status="in_review")
        default_provider = MockProvider()
        reviewer_provider = MockProvider()

        run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            agent_providers={"default": default_provider, "reviewer": reviewer_provider},
            role_agent_providers={"reviewer": "reviewer"},
        )

        assert default_provider.calls == []
        assert len(reviewer_provider.calls) == 1
        assert reviewer_provider.calls[0].role_name == "reviewer"

    def test_stops_when_agent_provider_returns_failure(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider(return_code=12)

        try:
            run_loop(
                tmp_path,
                auto=True,
                max_sessions=1,
                agent_providers={"default": provider},
            )
        except SystemExit as exc:
            assert exc.code == 12
        else:
            raise AssertionError("expected SystemExit")

    def test_unrecoverable_handoff_stops_loop_without_status_change(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First", body=_checked_task_body("T0001", "First"))
        provider = MockProvider(
            handoff_text=(
                "# Handoff: developer\n"
                "## Done\n- Tried work.\n"
                "## Changed Artifacts\n- None\n"
                "## Open Issues\n- Unrecoverable: environment broken.\n"
                "## Addressed Findings\n- None\n"
                "## Next Session Hint\nStop.\n"
            )
        )

        with pytest.raises(SystemExit) as exc_info:
            run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert exc_info.value.code == 1
        assert provider.calls[0].role_name == "developer"
        assert 'status = "open"' in task.read_text()

    def test_blocked_dependency_stops_without_invoking_agent(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Blocked", depends_on=["T9999"])
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert provider.calls == []

    def test_dependency_unlocks_after_reviewed_task_closes(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        dependency = _write_task(
            tmp_path,
            "T0002",
            "Dependency",
            status="in_review",
            body=_checked_task_body("T0002", "Dependency"),
        )
        dependent = _write_task(tmp_path, "T0001", "Dependent", depends_on=["T0002"])

        def on_invoke(call: AgentCall) -> None:
            if call.role_name == "reviewer":
                _approve_task(call, "T0002")

        provider = MockProvider(on_invoke=on_invoke)

        run_loop(tmp_path, auto=True, max_sessions=2, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["reviewer", "developer"]
        assert 'status = "closed"' in dependency.read_text()
        assert 'status = "open"' in dependent.read_text()

    def test_planner_invoked_when_design_exists_and_no_tasks(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["planner"]

    def test_architect_invoked_when_design_plan_missing(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["architect"]

    def test_successful_session_archives_handoff(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        archived = list((tmp_path / HISTORY_DIR).glob("*_developer_handoff.md"))
        assert len(archived) == 1
        assert "Mock session completed" in archived[0].read_text()

    def test_non_auto_mode_stops_when_user_declines(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First")
        provider = MockProvider(on_invoke=_complete_developer_task)
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")

        run_loop(tmp_path, auto=False, max_sessions=5, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["developer"]
        assert 'status = "in_review"' in task.read_text()


class TestValidateHandoff:
    def test_valid_handoff(self, tmp_path: Path) -> None:
        handoff = tmp_path / "handoff.md"
        handoff.write_text(
            "# Handoff\n"
            "## Done\n- Work\n"
            "## Changed Artifacts\n- None\n"
            "## Open Issues\n- None\n"
            "## Addressed Findings\n- None\n"
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

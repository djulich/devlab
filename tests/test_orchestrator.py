from __future__ import annotations

import dataclasses
import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from devlab._logging import logger
from devlab.agents import AgentCall, AgentInvocation, AgentResult, MockProvider, ProviderError
from devlab.findings import FINDINGS_DIR, FileFindingTracker, FindingStatus
from devlab.handoffs import Handoff, HandoffError, parse_handoff
from devlab.milestones import FileMilestoneTracker, MilestoneStatus
from devlab.orchestrator import _timestamp, close_task, process_handoff, run_loop, validate_handoff
from devlab.prompts import build_session_prompt, build_system_prompt
from devlab.task_tracker import TASKS_DIR, FileTaskTracker, TaskStatus
from devlab.workspace import (
    AGENT_LOG_DIR,
    ARTIFACTS_DIR,
    DESIGN_PLAN,
    HISTORY_DIR,
    PROJECT_PLAN,
    ROLES,
    Workspace,
)


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
    domain: str | None = None,
    addresses_findings: list[str] | None = None,
    body: str | None = None,
) -> Path:
    depends_on = depends_on or []
    slug = title.lower().replace(" ", "-")
    path = root / TASKS_DIR / f"{task_id}_{slug}.md"
    depends = ", ".join(f'"{dependency}"' for dependency in depends_on)
    milestone_line = f'milestone = "{milestone}"\n' if milestone is not None else ""
    profile_line = f'profile = "{profile}"\n' if profile is not None else ""
    domain_line = f'domain = "{domain}"\n' if domain is not None else ""
    validation_line = ""
    addresses_findings = addresses_findings or []
    addresses_findings_text = ", ".join(f'"{finding_id}"' for finding_id in addresses_findings)
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
        f"{domain_line}"
        f"depends_on = [{depends}]\n"
        f"addresses_findings = [{addresses_findings_text}]\n"
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
    architecture_reviewed: bool = False,
    task_ids: list[str] | None = None,
) -> Path:
    path = root / ".devlab/milestones" / f"{milestone_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if architecture_reviewed:
        status = "architecture_reviewed"
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
        f"architecture_reviewed = {str(architecture_reviewed).lower()}\n"
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
        assert Workspace(tmp_path).snapshot.assess_state() == "architect"

    def test_missing_design_plan_returns_architect(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        assert Workspace(tmp_path).snapshot.assess_state() == "architect"

    def test_design_plan_exists_no_tasks_returns_planner(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        assert Workspace(tmp_path).snapshot.assess_state() == "planner"

    def test_open_tasks_returns_developer(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Setup")
        assert Workspace(tmp_path).snapshot.assess_state() == "developer"

    def test_review_tasks_return_reviewer(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Setup", status="in_review")
        assert Workspace(tmp_path).snapshot.assess_state() == "reviewer"

    def test_all_tasks_closed_returns_none(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed")
        assert Workspace(tmp_path).snapshot.assess_state() is None


class TestAllMilestonesComplete:
    def test_empty_plan_is_not_complete(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("")
        assert Workspace(tmp_path).snapshot.all_milestones_complete() is False

    def test_all_checked_is_complete_without_task_files(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("## M1: Init\n- [x] T0001: Done\n")
        assert Workspace(tmp_path).snapshot.all_milestones_complete() is True

    def test_some_unchecked_is_not_complete_without_task_files(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / PROJECT_PLAN).write_text("- [x] T0001\n- [ ] T0002\n")
        assert Workspace(tmp_path).snapshot.all_milestones_complete() is False

    def test_task_files_override_project_plan_checkboxes(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "Done", status="closed")
        (tmp_path / PROJECT_PLAN).write_text("- [ ] T0001\n")
        assert Workspace(tmp_path).snapshot.all_milestones_complete() is True


class TestSelectTaskCompatibility:
    def test_no_tasks_returns_none(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        assert Workspace(tmp_path).snapshot.select_task() is None

    def test_returns_task_path(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        path = _write_task(tmp_path, "T0001", "First")
        assert Workspace(tmp_path).snapshot.select_task() == path


class TestCloseTask:
    def test_marks_task_closed_in_place(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        task = _write_task(tmp_path, "T0001", "Test", status="in_review")
        close_task(Workspace(tmp_path), task, "reviewer")
        assert task.exists()
        assert 'status = "closed"' in task.read_text()
        history = list((tmp_path / HISTORY_DIR).glob("*_reviewer_closed-task.md"))
        assert history == []


class TestBuildSessionPrompt:
    def test_planner_prompt_includes_existing_profiles(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_profile(tmp_path, "api", validation=["uv run pytest tests/api"])

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "planner")

        assert "## Existing Profiles" in prompt
        assert "api.toml" in prompt
        assert "uv run pytest tests/api" in prompt

    def test_developer_prompt_includes_task_validation_commands(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First", validation=["uv run pytest"])

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "developer")

        assert "## Task Validation Commands" in prompt
        assert "`uv run pytest`" in prompt

    def test_developer_prompt_omits_validation_section_when_validation_is_omitted(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First")

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "developer")

        assert "## Task Validation Commands" not in prompt

    def test_developer_prompt_uses_profile_default_validation_when_validation_is_omitted(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_profile(tmp_path, "api", validation=["uv run pytest tests/api"])
        _write_task(tmp_path, "T0001", "First", profile="api")

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "developer")

        assert "Profile: `api`" in prompt
        assert "default validation from profile `api`" in prompt
        assert "`uv run pytest tests/api`" in prompt

    def test_developer_prompt_explains_explicit_empty_validation(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First", validation=[])

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "developer")

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

    def test_developer_system_prompt_includes_task_domain_overlay(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "Deploy", domain="deployment")
        role = ROLES["developer"]

        prompt = build_system_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="developer",
        )

        assert "Domain: Deployment / Developer" in prompt
        assert "do not install it" in prompt
        assert "Domain: Deployment / Reviewer" not in prompt

    def test_reviewer_deployment_overlay_treats_missing_tools_as_unverified(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "Deploy", status="in_review", domain="deployment")
        role = ROLES["reviewer"]

        prompt = build_system_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="reviewer",
        )

        assert "Domain: Deployment / Reviewer" in prompt
        assert "do not install it" in prompt
        assert "unverified" in prompt

    def test_developer_system_prompt_omits_domain_overlay_for_general_task(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "General")
        role = ROLES["developer"]

        prompt = build_system_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="developer",
        )

        assert "Domain: Deployment" not in prompt

    def test_planner_system_prompt_includes_deployment_overlay_for_deployment_spec(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        deployment_spec = tmp_path / ".devlab/specs/deployment/README.md"
        deployment_spec.parent.mkdir(parents=True)
        deployment_spec.write_text(
            "# Deployment Specification\n\nSupport local Podman deployment.\n"
        )
        role = ROLES["planner"]

        prompt = build_system_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment / Planner" in prompt

    def test_planner_system_prompt_activates_from_additional_deployment_spec_file(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        deployment_dir = tmp_path / ".devlab/specs/deployment"
        deployment_dir.mkdir(parents=True)
        (deployment_dir / "README.md").write_text(
            "<!-- devlab:placeholder -->\n"
            "# Deployment Specification\n\n"
            "Describe how this project should become deployment-ready.\n"
        )
        (deployment_dir / "compose.md").write_text(
            "# Compose Deployment\n\nSupport local Compose verification.\n"
        )
        role = ROLES["planner"]

        prompt = build_system_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment / Planner" in prompt

    def test_planner_system_prompt_ignores_placeholder_deployment_spec(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        deployment_spec = tmp_path / ".devlab/specs/deployment/README.md"
        deployment_spec.parent.mkdir(parents=True)
        deployment_spec.write_text(
            "<!-- devlab:placeholder -->\n"
            "# Deployment Specification\n\n"
            "Describe how this project should become deployment-ready.\n"
        )
        role = ROLES["planner"]

        prompt = build_system_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment" not in prompt

    def test_planner_system_prompt_activates_deployment_without_sentinel(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        deployment_spec = tmp_path / ".devlab/specs/deployment/README.md"
        deployment_spec.parent.mkdir(parents=True)
        deployment_spec.write_text(
            "# Deployment Specification\n\nSupport Kubernetes manifests with kind.\n"
        )
        role = ROLES["planner"]

        prompt = build_system_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment / Planner" in prompt

    def test_deployment_spec_with_sentinel_removed_activates_deployment(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        deployment_spec = tmp_path / ".devlab/specs/deployment/README.md"
        deployment_spec.parent.mkdir(parents=True)
        from devlab.prompts import DEPLOYMENT_PLACEHOLDER_SENTINEL
        init_template = (
            Path(__file__).resolve().parent.parent
            / "src/devlab/resources/init/specs/deployment/README.md"
        ).read_text()
        assert DEPLOYMENT_PLACEHOLDER_SENTINEL in init_template
        without_sentinel = init_template.replace(
            DEPLOYMENT_PLACEHOLDER_SENTINEL + "\n", ""
        )
        deployment_spec.write_text(without_sentinel)
        role = ROLES["planner"]

        prompt = build_system_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment / Planner" in prompt


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


class FailingProvider:
    def __init__(self, result: AgentResult) -> None:
        self.result = result
        self.calls: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.calls.append(invocation)
        return dataclasses.replace(
            self.result,
            role_name=invocation.role_name,
            stdout_log=invocation.stdout_log,
            stderr_log=invocation.stderr_log,
        )


class RaisingProvider:
    def __init__(self, exception: Exception) -> None:
        self.exception = exception

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        raise self.exception


class TestRunLoop:
    def test_revise_plan_requires_planning_only(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="revise_plan requires planning_only"):
            run_loop(tmp_path, auto=True, max_sessions=1, revise_plan=True)

    def test_planning_only_runs_architect_and_planner_then_stops(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)

        def on_invoke(call: AgentCall) -> None:
            if call.role_name == "architect":
                (call.root / DESIGN_PLAN).write_text("# Design\n")
            elif call.role_name == "planner":
                (call.root / PROJECT_PLAN).write_text("## M1: Initial\n- T0001: First\n")
                _write_task(call.root, "T0001", "First", milestone="M1")

        provider = MockProvider(on_invoke=on_invoke)

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=5,
            planning_only=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 2
        assert [call.role_name for call in provider.calls] == ["architect", "planner"]
        assert Workspace(tmp_path).snapshot.assess_state() == "developer"

    def test_planning_only_with_version_control_commits_synced_milestones(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        subprocess.run(["git", "-C", tmp_path.as_posix(), "init"], check=True)
        subprocess.run(
            ["git", "-C", tmp_path.as_posix(), "config", "user.name", "DevLab Test"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                tmp_path.as_posix(),
                "config",
                "user.email",
                "devlab-test@example.invalid",
            ],
            check=True,
        )
        subprocess.run(["git", "-C", tmp_path.as_posix(), "add", "-A"], check=True)
        subprocess.run(["git", "-C", tmp_path.as_posix(), "commit", "-m", "init"], check=True)

        def on_invoke(call: AgentCall) -> None:
            if call.role_name == "architect":
                (call.root / DESIGN_PLAN).write_text("# Design\n")
            elif call.role_name == "planner":
                (call.root / PROJECT_PLAN).write_text("## M1: Initial\n- T0001: First\n")
                _write_task(call.root, "T0001", "First", milestone="M1")

        provider = MockProvider(on_invoke=on_invoke)

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=5,
            planning_only=True,
            automatic_version_control=True,
            agent_providers={"default": provider},
        )

        status = subprocess.run(
            ["git", "-C", tmp_path.as_posix(), "status", "--porcelain"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        tracked_milestone = subprocess.run(
            ["git", "-C", tmp_path.as_posix(), "ls-files", ".devlab/milestones/M1.toml"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

        assert result.sessions_run == 2
        assert status == ""
        assert tracked_milestone == ".devlab/milestones/M1.toml"

    def test_planning_only_noops_when_already_planned(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=5,
            planning_only=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 0
        assert provider.calls == []

    def test_revise_plan_runs_architect_and_planner_even_when_planned(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        (tmp_path / PROJECT_PLAN).write_text("## M1: Initial\n- T0001: First\n")
        _write_task(tmp_path, "T0001", "First", milestone="M1")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=5,
            planning_only=True,
            revise_plan=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 2
        assert [call.role_name for call in provider.calls] == ["architect", "planner"]
        assert all("## Planning Revision Mode" in call.session_prompt for call in provider.calls)

    def test_developer_completed_task_is_marked_in_review(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First", body=_checked_task_body("T0001", "First"))
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert len(provider.calls) == 1
        assert provider.calls[0].role_name == "developer"
        assert 'status = "in_review"' in task.read_text()

    def test_session_progress_callback_reports_start_and_finish(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider()
        events: list[tuple[str, int, str]] = []

        run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            agent_providers={"default": provider},
            session_progress=lambda event, number, role: events.append((event, number, role)),
        )

        assert events == [("start", 1, "developer"), ("finish", 1, "developer")]

    def test_run_logs_session_context(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(
            tmp_path,
            "T0001",
            "First",
            milestone="M1",
            profile="default",
            domain="deployment",
        )
        provider = MockProvider()
        monkeypatch.setattr(logger, "propagate", True)
        caplog.set_level(logging.INFO, logger="devlab")

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        messages = [record.getMessage() for record in caplog.records]
        assert any(
            message
            == "Starting session 1: developer task=T0001 status=open profile=default "
            "domain=deployment milestone=M1"
            for message in messages
        )
        assert any(
            message == "Finished session 1: developer task=T0001 status=open next=developer"
            for message in messages
        )

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

        result = run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.completed is False
        assert result.errors[0].phase == "environment_setup"
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

        result = run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 3
        assert result.completed is False
        assert result.errors[0].phase == "agent_invocation"
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

    def test_reviewer_rejection_with_stale_approval_defaults_to_changes_requested(
        self, tmp_path: Path,
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(
            tmp_path,
            "T0001",
            "Review",
            status="in_review",
            body=_checked_task_body("T0001", "Review") + "\n## Review\n- [x] Approved\n",
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

        result = run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 0
        assert result.errors == ()
        assert 'status = "changes_requested"' in task.read_text()

    def test_reviewer_approval_without_review_marker_defaults_to_changes_requested(
        self, tmp_path: Path,
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(
            tmp_path,
            "T0001",
            "Review",
            status="in_review",
            body=_checked_task_body("T0001", "Review"),
        )
        provider = MockProvider()

        result = run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 0
        assert result.errors == ()
        assert 'status = "changes_requested"' in task.read_text()

    def test_invalid_handoff_stops_loop_without_status_change(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First", body=_checked_task_body("T0001", "First"))
        provider = MockProvider(write_handoff=False)

        result = run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.completed is False
        assert result.errors[0].phase == "handoff_validation"
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

        result = run_loop(
            tmp_path, auto=True, max_sessions=2,
            agent_providers={"default": provider},
        )

        assert result.completed is True
        assert result.exit_code == 0
        assert result.errors == ()
        assert [call.role_name for call in provider.calls] == ["developer", "reviewer"]
        assert 'status = "closed"' in task.read_text()

    def test_completed_milestone_selects_integrator(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["integrator"]

    def test_integrated_architecture_reviewed_milestone_stops(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        _write_milestone(
            tmp_path,
            "M1",
            integrated=True,
            architecture_reviewed=True,
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

    def test_open_issue_containing_no_is_not_treated_as_none(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        provider = MockProvider(
            handoff_text=(
                "# Handoff: integrator\n"
                "## Done\n- Validated milestone.\n"
                "## Changed Artifacts\n- None\n"
                "## Open Issues\n- No smoke test exists for the CLI.\n"
                "## Addressed Findings\n- None\n"
                "## Next Session Hint\nPlan smoke test.\n"
            )
        )

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        findings = FileFindingTracker(tmp_path).open_findings()
        assert len(findings) == 1
        assert "No smoke test exists" in findings[0].body

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
        assert milestone.architecture_reviewed is True

    def test_integrated_milestone_selects_architect_review(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        _write_milestone(tmp_path, "M1", integrated=True, task_ids=["T0001"])

        assert Workspace(tmp_path).snapshot.assess_state() == "architect"
        assert Workspace(tmp_path).snapshot.select_architecture_review_milestone() == "M1"

    def test_architect_review_handoff_marks_milestone_reviewed(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        _write_milestone(tmp_path, "M1", integrated=True, task_ids=["T0001"])
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["architect"]
        milestone = FileMilestoneTracker(tmp_path).get("M1")
        assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED
        assert milestone.architecture_reviewed is True
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
        assert FileMilestoneTracker(tmp_path).get("M1").architecture_reviewed is True
        assert Workspace(tmp_path).snapshot.assess_state() == "planner"

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
        finding = FileFindingTracker(tmp_path).create(
            title="Known drift",
            source="architect",
            milestone="M1",
            body="# Known drift\n",
        )
        FileFindingTracker(tmp_path).mark_planned(finding.id)
        _write_task(
            tmp_path,
            "T0002",
            "Fix drift",
            milestone="M2",
            addresses_findings=[finding.id],
        )
        _write_milestone(tmp_path, "M1", integrated=True, task_ids=["T0001"])

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "architect")

        assert "## Assigned Integrated Milestone for Architecture Review" in prompt
        assert "M1" in prompt
        assert "Important architecture behavior" in prompt
        assert "# System Spec" in prompt
        assert "## Unresolved Findings for Reviewed Milestone" in prompt
        assert "Known drift" in prompt
        assert "Addressing tasks: T0002" in prompt

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

        def on_invoke(call: AgentCall) -> None:
            _write_task(
                call.root,
                "T0002",
                "E2E",
                milestone="M1",
                addresses_findings=[finding.id],
            )

        provider = MockProvider(
            handoff_text=(
                "# Handoff: planner\n"
                "## Done\n- Created follow-up task.\n"
                "## Changed Artifacts\n- .devlab/tasks/T0002_e2e.md (created)\n"
                "## Open Issues\n- None\n"
                "## Addressed Findings\n"
                f"- {finding.id}: T0002\n"
                "## Next Session Hint\nImplement follow-up task.\n"
            ),
            on_invoke=on_invoke,
        )

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert FileFindingTracker(tmp_path).get(finding.id).status == FindingStatus.PLANNED

    def test_planner_addressed_findings_requires_task_mapping(self, tmp_path: Path) -> None:
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
                "## Changed Artifacts\n- None\n"
                "## Open Issues\n- None\n"
                "## Addressed Findings\n"
                f"- {finding.id}\n"
                "## Next Session Hint\nImplement follow-up task.\n"
            )
        )

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.completed is False
        assert result.errors[0].phase == "handoff_validation"
        assert FileFindingTracker(tmp_path).get(finding.id).status == FindingStatus.OPEN

    def test_closed_follow_up_task_resolves_planned_finding(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        tracker = FileFindingTracker(tmp_path)
        finding = tracker.create(
            title="Missing E2E coverage",
            source="integrator",
            milestone="M1",
            body="# Finding\n",
        )
        tracker.mark_planned(finding.id)
        task = _write_task(
            tmp_path,
            "T0001",
            "Fix finding",
            status="in_review",
            milestone="M1",
            addresses_findings=[finding.id],
            body=_checked_task_body("T0001", "Fix finding") + "\n## Review\n- [x] Approved\n",
        )
        provider = MockProvider()

        run_loop(tmp_path, auto=True, max_sessions=1, agent_providers={"default": provider})

        assert 'status = "closed"' in task.read_text()
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
        _write_milestone(tmp_path, "M1", task_ids=["T0001"])

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "integrator")

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
            'version_command = "mock-agent version"\n'
        )

        def fake_run(*args: Any, **kwargs: Any) -> object:
            if args[0] == ["mock-agent", "version"]:
                class VersionResult:
                    returncode = 0
                    stdout = "mock-agent 9.8.7\n"
                    stderr = ""

                return VersionResult()
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

        run_loop(tmp_path, auto=True, max_sessions=1, retain_prompts=True)

        logs = list((tmp_path / ".devlab/logs/agents").glob("*_developer.config.toml"))
        assert len(logs) == 1
        text = logs[0].read_text()
        assert 'role = "developer"' in text
        assert 'provider = "mock-cli"' in text
        assert 'model = "test-model"' in text
        assert 'provider_version = "mock-agent 9.8.7"' in text
        meta = _find_metadata(tmp_path)
        assert meta["provider_version"] == "mock-agent 9.8.7"
        assert "system_prompt =" not in text
        assert "session_prompt =" not in text
        assert "stdout_log" in text
        assert "stderr_log" in text
        assert "system_prompt_log" in text
        assert "session_prompt_log" in text

    def test_retains_split_prompt_logs_when_enabled(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider()

        run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            retain_prompts=True,
            agent_providers={"default": provider},
        )

        agent_logs = tmp_path / ".devlab/logs/agents"
        system_logs = list(agent_logs.glob("*_developer.system-prompt.md"))
        session_logs = list(agent_logs.glob("*_developer.session-prompt.md"))
        assert len(system_logs) == 1
        assert len(session_logs) == 1
        assert "Role: Developer" in system_logs[0].read_text()
        assert "## Assigned Task" in session_logs[0].read_text()

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

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 12
        assert result.completed is False
        assert result.errors[0].phase == "agent_invocation"
        assert "stdout_log" in result.errors[0].message
        assert "stderr_log" in result.errors[0].message

    def test_agent_timeout_is_structured_failure(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = FailingProvider(
            AgentResult(
                return_code=124,
                failure_kind="timeout",
                message="agent command timed out after 1 second(s)",
                timeout_seconds=1,
            )
        )

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 124
        assert result.completed is False
        assert result.errors[0].phase == "agent_invocation"
        assert "timeout" in result.errors[0].message
        assert "timeout_seconds=1" in result.errors[0].message

    def test_agent_failure_still_reports_after_environment_teardown(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        (tmp_path / ".devlab/config/profiles/default.toml").write_text(
            'version = 1\n'
            'id = "default"\n'
            'title = "Default"\n'
            '\n[environment]\n'
            'managed_roles = ["developer"]\n'
            'post_session = ["touch teardown-ran"]\n'
        )
        provider = MockProvider(return_code=12)

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 12
        assert (tmp_path / "teardown-ran").exists()

    def test_provider_error_is_caught_and_structured(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = RaisingProvider(ProviderError("connection refused"))

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.completed is False
        assert result.errors[0].phase == "agent_invocation"
        assert "connection refused" in result.errors[0].message

    def test_non_provider_error_propagates(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = RaisingProvider(RuntimeError("bug in provider"))

        with pytest.raises(RuntimeError, match="bug in provider"):
            run_loop(
                tmp_path,
                auto=True,
                max_sessions=1,
                agent_providers={"default": provider},
            )

    def test_invalid_handoff_error_includes_agent_log_paths(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First", body=_checked_task_body("T0001", "First"))
        provider = MockProvider(write_handoff=False)

        result = run_loop(
            tmp_path,
            auto=True,
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.errors[0].phase == "handoff_validation"
        assert "stdout_log" in result.errors[0].message
        assert "stderr_log" in result.errors[0].message

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

        result = run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.completed is False
        assert result.errors[0].phase == "handoff_validation"
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
        _setup_tree(tmp_path)
        path = tmp_path / "handoff.md"
        path.write_text(
            "# Handoff\n"
            "## Done\n- Work\n"
            "## Changed Artifacts\n- None\n"
            "## Open Issues\n- None\n"
            "## Addressed Findings\n- None\n"
            "## Next Session Hint\nContinue\n"
        )
        handoff = parse_handoff(path, "developer")
        validate_handoff(handoff, Workspace(tmp_path).snapshot)


class TestValidateReviewerOutcome:
    def _handoff(self, tmp_path: Path, *, open_issues: str = "- None") -> Handoff:
        path = tmp_path / "handoff.md"
        path.write_text(
            "# Handoff\n"
            "## Done\n- Review work\n"
            "## Changed Artifacts\n- None\n"
            f"## Open Issues\n{open_issues}\n"
            "## Addressed Findings\n- None\n"
            "## Next Session Hint\nContinue\n"
        )
        return parse_handoff(path, "reviewer")

    def _approved_body(self, task_id: str, title: str) -> str:
        return (
            f"# {task_id}: {title}\n\n"
            "## Acceptance Criteria\n- [x] Done\n\n"
            "## Review\n- [x] Approved\n"
        )

    def test_rejects_when_no_task_awaiting_review(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First")
        handoff = self._handoff(tmp_path)

        with pytest.raises(HandoffError, match="no task awaiting review"):
            validate_handoff(handoff, Workspace(tmp_path).snapshot)

    def test_accepts_open_issues_with_approved_task(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(
            tmp_path, "T0001", "First", status="in_review",
            body=self._approved_body("T0001", "First"),
        )
        handoff = self._handoff(tmp_path, open_issues="- Code needs refactoring.")

        validate_handoff(handoff, Workspace(tmp_path).snapshot)

    def test_accepts_no_open_issues_without_approval(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First", status="in_review")
        handoff = self._handoff(tmp_path)

        validate_handoff(handoff, Workspace(tmp_path).snapshot)

    def test_accepts_rejection_with_open_issues(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First", status="in_review")
        handoff = self._handoff(tmp_path, open_issues="- Code needs refactoring.")

        validate_handoff(handoff, Workspace(tmp_path).snapshot)

    def test_accepts_approval_without_open_issues(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        _write_task(
            tmp_path, "T0001", "First", status="in_review",
            body=self._approved_body("T0001", "First"),
        )
        handoff = self._handoff(tmp_path)

        validate_handoff(handoff, Workspace(tmp_path).snapshot)


class TestProcessHandoffReviewerDefaults:
    def _write_handoff(self, root: Path, *, open_issues: str = "- None") -> Handoff:
        artifacts = root / ARTIFACTS_DIR / "reviewer"
        artifacts.mkdir(parents=True, exist_ok=True)
        path = artifacts / "handoff.md"
        path.write_text(
            "# Handoff\n"
            "## Done\n- Review work\n"
            "## Changed Artifacts\n- None\n"
            f"## Open Issues\n{open_issues}\n"
            "## Addressed Findings\n- None\n"
            "## Next Session Hint\nContinue\n"
        )
        return parse_handoff(path, "reviewer")

    def _approved_body(self, task_id: str, title: str) -> str:
        return (
            f"# {task_id}: {title}\n\n"
            "## Acceptance Criteria\n- [x] Done\n\n"
            "## Review\n- [x] Approved\n"
        )

    def test_no_open_issues_without_approval_defaults_to_changes_requested(
        self, tmp_path: Path,
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First", status="in_review")
        handoff = self._write_handoff(tmp_path)

        process_handoff(handoff, Workspace(tmp_path))

        task = FileTaskTracker(tmp_path).get("T0001")
        assert task.status == TaskStatus.CHANGES_REQUESTED

    def test_open_issues_with_approved_task_defaults_to_changes_requested(
        self, tmp_path: Path,
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(
            tmp_path, "T0001", "First", status="in_review",
            body=self._approved_body("T0001", "First"),
        )
        handoff = self._write_handoff(tmp_path, open_issues="- Code needs refactoring.")

        process_handoff(handoff, Workspace(tmp_path))

        task = FileTaskTracker(tmp_path).get("T0001")
        assert task.status == TaskStatus.CHANGES_REQUESTED


def _find_metadata(root: Path) -> dict[str, Any]:
    import json
    files = list((root / AGENT_LOG_DIR).glob("*.metadata.json"))
    assert len(files) == 1, f"expected 1 metadata file, found {len(files)}: {files}"
    return json.loads(files[0].read_text())


class TestSessionMetadata:
    def test_metadata_written_for_successful_session(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(
            tmp_path, "T0001", "First",
            body=_checked_task_body("T0001", "First"),
        )
        provider = MockProvider()

        run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        meta = _find_metadata(tmp_path)
        assert meta["role_name"] == "developer"
        assert meta["return_code"] == 0
        assert meta["failure_kind"] == "none"
        assert meta["task_id"] == "T0001"
        assert meta["session_number"] == 1

    def test_metadata_written_for_failed_session(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = FailingProvider(
            AgentResult(return_code=3, failure_kind="nonzero_exit"),
        )

        run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        meta = _find_metadata(tmp_path)
        assert meta["return_code"] == 3
        assert meta["failure_kind"] == "nonzero_exit"
        assert meta["task_id"] == "T0001"

    def test_metadata_written_for_provider_error(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = RaisingProvider(ProviderError("connection refused"))

        run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        meta = _find_metadata(tmp_path)
        assert meta["return_code"] == 1
        assert meta["failure_kind"] == "provider_error"

    def test_metadata_written_for_handoff_validation_failure(
        self, tmp_path: Path,
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(
            tmp_path, "T0001", "First",
            body=_checked_task_body("T0001", "First"),
        )
        provider = MockProvider(write_handoff=False)

        run_loop(
            tmp_path, auto=True, max_sessions=1,
            agent_providers={"default": provider},
        )

        meta = _find_metadata(tmp_path)
        assert meta["return_code"] == 0
        assert meta["failure_kind"] == "none"


class TestTimestamp:
    def test_format(self) -> None:
        ts = _timestamp()
        assert len(ts) == 15
        assert ts[8] == "T"

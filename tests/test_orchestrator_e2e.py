from __future__ import annotations

from pathlib import Path

from devlab.agents import AgentCall, MockProvider
from devlab.findings import FileFindingTracker, FindingStatus
from devlab.init import init_workspace
from devlab.milestones import FileMilestoneTracker, MilestoneStatus
from devlab.orchestrator import RunResult, run_loop
from devlab.task_tracker import FileTaskTracker, TaskStatus
from devlab.version_control import commit_all
from tests.helpers import (
    approve_review_task,
    complete_acceptance,
    handoff,
    write_task,
)


class HappyPathWorkflow:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.role_counts: dict[str, int] = {}

    def on_invoke(self, call: AgentCall) -> None:
        self.calls.append(call.role_name)
        self.role_counts[call.role_name] = self.role_counts.get(call.role_name, 0) + 1
        count = self.role_counts[call.role_name]
        if call.role_name == "architect":
            if count == 1:
                assert "No design plan exists yet" in call.session_prompt
                _design_plan(call.root).write_text("# Design Plan\n\nBuild a tiny CLI.\n")
            else:
                assert (
                    "Assigned Integrated Milestone for Architecture Review" in call.session_prompt
                )
                assert "## Integration Handoff" in call.session_prompt
                assert "## Milestone Task Files" in call.session_prompt
        elif call.role_name == "planner":
            assert "# Design Plan" in call.session_prompt
            _project_plan(call.root).write_text(
                "# Project Plan\n\n"
                "## M1: Foundation\n"
                "- T0001: Implement tiny CLI\n"
            )  # fmt: skip
            write_task(call.root, "T0001", "Implement tiny CLI", "M1")
        elif call.role_name == "developer":
            assert "## Assigned Task" in call.session_prompt
            assert "T0001" in call.session_prompt
            assert "## Task Profile" in call.session_prompt
            complete_acceptance(call.root, "T0001")
            (call.root / "tiny_cli.py").write_text("print('hello from tiny cli')\n")
        elif call.role_name == "reviewer":
            assert "## Task Awaiting Review" in call.session_prompt
            assert "## Latest Developer Handoff" in call.session_prompt
            approve_review_task(call.root)
        elif call.role_name == "integrator":
            assert "## Assigned Completed Milestone" in call.session_prompt
            assert "T0001_implement-tiny-cli.md" in call.session_prompt

    def handoff_for(self, call: AgentCall) -> str:
        return handoff(call.role_name, changed="- Repository workflow artifacts updated.")


class CorrectiveWorkflow:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.role_counts: dict[str, int] = {}

    def on_invoke(self, call: AgentCall) -> None:
        self.calls.append(call.role_name)
        self.role_counts[call.role_name] = self.role_counts.get(call.role_name, 0) + 1
        count = self.role_counts[call.role_name]
        if call.role_name == "architect":
            if count == 1:
                _design_plan(call.root).write_text("# Design Plan\n\nBuild a tiny CLI.\n")
            else:
                assert (
                    "Assigned Integrated Milestone for Architecture Review" in call.session_prompt
                )
        elif call.role_name == "planner":
            if count == 1:
                _project_plan(call.root).write_text(
                    "# Project Plan\n\n"
                    "## M1: Foundation\n"
                    "- T0001: Implement tiny CLI\n"
                )  # fmt: skip
                write_task(call.root, "T0001", "Implement tiny CLI", "M1")
            else:
                assert "## Open Findings" in call.session_prompt
                assert "F0001" in call.session_prompt
                _project_plan(call.root).write_text(
                    "# Project Plan\n\n"
                    "## M1: Foundation\n"
                    "- T0001: Implement tiny CLI\n"
                    "- T0002: Add CLI smoke test\n"
                )
                write_task(
                    call.root,
                    "T0002",
                    "Add CLI smoke test",
                    "M1",
                    depends_on=["T0001"],
                    addresses_findings=["F0001"],
                )
        elif call.role_name == "developer":
            task = FileTaskTracker(call.root).select_next_development_task()
            assert task is not None
            assert task.id in call.session_prompt
            complete_acceptance(call.root, task.id)
            if task.id == "T0001":
                (call.root / "tiny_cli.py").write_text("print('hello from tiny cli')\n")
            elif task.id == "T0002":
                (call.root / "test_tiny_cli.py").write_text("def test_smoke():\n    assert True\n")
        elif call.role_name == "reviewer":
            approve_review_task(call.root)
        elif call.role_name == "integrator":
            assert "## Assigned Completed Milestone" in call.session_prompt

    def handoff_for(self, call: AgentCall) -> str:
        if call.role_name == "integrator" and self.role_counts["integrator"] == 1:
            return handoff(
                call.role_name,
                open_issues="- The milestone lacks a smoke test for the CLI.",
            )
        if call.role_name == "planner" and self.role_counts["planner"] == 2:
            return handoff(call.role_name, addressed="- F0001: T0002")
        return handoff(call.role_name)


class ChangesRequestedWorkflow:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.role_counts: dict[str, int] = {}

    def on_invoke(self, call: AgentCall) -> None:
        self.calls.append(call.role_name)
        self.role_counts[call.role_name] = self.role_counts.get(call.role_name, 0) + 1
        count = self.role_counts[call.role_name]
        if call.role_name == "architect":
            if count == 1:
                _design_plan(call.root).write_text("# Design Plan\n\nBuild a tiny CLI.\n")
            else:
                assert (
                    "Assigned Integrated Milestone for Architecture Review" in call.session_prompt
                )
        elif call.role_name == "planner":
            _project_plan(call.root).write_text(
                "# Project Plan\n\n"
                "## M1: Foundation\n"
                "- T0001: Implement tiny CLI\n"
            )  # fmt: skip
            write_task(call.root, "T0001", "Implement tiny CLI", "M1")
        elif call.role_name == "developer":
            assert "T0001" in call.session_prompt
            complete_acceptance(call.root, "T0001")
            if count == 1:
                (call.root / "tiny_cli.py").write_text("print('hello')\n")
            else:
                (call.root / "tiny_cli.py").write_text("print('hello from tiny cli')\n")
        elif call.role_name == "reviewer":
            if count == 1:
                pass
            else:
                approve_review_task(call.root)
        elif call.role_name == "integrator":
            assert "## Assigned Completed Milestone" in call.session_prompt

    def handoff_for(self, call: AgentCall) -> str:
        if call.role_name == "reviewer" and self.role_counts["reviewer"] == 1:
            return handoff(
                call.role_name,
                open_issues="- CLI output is incomplete, needs full message.",
            )
        return handoff(call.role_name)


def test_run_loop_completes_full_happy_path_workflow(tmp_path: Path) -> None:
    _init_target_workspace(tmp_path)
    workflow = HappyPathWorkflow()
    provider = MockProvider(on_invoke=workflow.on_invoke, handoff_text=workflow.handoff_for)

    result = run_loop(
        tmp_path,
        max_sessions=10,
        agent_providers={"default": provider},
    )

    _assert_successful_result(result, sessions=6)
    assert workflow.calls == [
        "architect",
        "planner",
        "developer",
        "reviewer",
        "integrator",
        "architect",
    ]
    task = FileTaskTracker(tmp_path).get("T0001")
    assert task.status == TaskStatus.CLOSED
    milestone = FileMilestoneTracker(tmp_path).get("M1")
    assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED
    assert milestone.integrated is True
    assert milestone.architecture_reviewed is True
    assert milestone.task_ids == ("T0001",)
    assert milestone.integration_handoff.endswith("_integrator_handoff.md")
    assert milestone.architecture_review_handoff.endswith("_architect_handoff.md")
    assert FileFindingTracker(tmp_path).list_findings() == []
    assert len(list((tmp_path / ".devlab/history").glob("*_handoff.md"))) == 6


def test_run_loop_replans_after_integration_finding(tmp_path: Path) -> None:
    _init_target_workspace(tmp_path)
    workflow = CorrectiveWorkflow()
    provider = MockProvider(on_invoke=workflow.on_invoke, handoff_text=workflow.handoff_for)

    result = run_loop(
        tmp_path,
        max_sessions=12,
        agent_providers={"default": provider},
    )

    _assert_successful_result(result, sessions=10)
    assert workflow.calls == [
        "architect",
        "planner",
        "developer",
        "reviewer",
        "integrator",
        "planner",
        "developer",
        "reviewer",
        "integrator",
        "architect",
    ]
    tasks = FileTaskTracker(tmp_path)
    assert tasks.get("T0001").status == TaskStatus.CLOSED
    assert tasks.get("T0002").status == TaskStatus.CLOSED
    milestone = FileMilestoneTracker(tmp_path).get("M1")
    assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED
    assert milestone.integrated is True
    assert milestone.architecture_reviewed is True
    assert milestone.task_ids == ("T0001", "T0002")
    assert milestone.findings == ("F0001",)
    finding = FileFindingTracker(tmp_path).get("F0001")
    assert finding.status == FindingStatus.RESOLVED
    assert finding.milestone == "M1"
    assert len(list((tmp_path / ".devlab/history").glob("*_handoff.md"))) == 10


def test_run_loop_handles_reviewer_rejection_and_rework(tmp_path: Path) -> None:
    _init_target_workspace(tmp_path)
    workflow = ChangesRequestedWorkflow()
    provider = MockProvider(on_invoke=workflow.on_invoke, handoff_text=workflow.handoff_for)

    result = run_loop(
        tmp_path,
        max_sessions=10,
        agent_providers={"default": provider},
    )

    _assert_successful_result(result, sessions=8)
    assert workflow.calls == [
        "architect",
        "planner",
        "developer",
        "reviewer",
        "developer",
        "reviewer",
        "integrator",
        "architect",
    ]
    task = FileTaskTracker(tmp_path).get("T0001")
    assert task.status == TaskStatus.CLOSED
    milestone = FileMilestoneTracker(tmp_path).get("M1")
    assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED
    assert milestone.integrated is True
    assert milestone.architecture_reviewed is True


def _init_target_workspace(root: Path) -> None:
    init_workspace(root, automatic_git=True)
    (root / ".devlab/specs/system/README.md").write_text(
        "# System Specification\n\nBuild a tiny CLI.\n"
    )
    (root / ".devlab/config/profiles/default.toml").write_text(
        "version = 1\n"
        'id = "default"\n'
        'title = "Default test profile"\n'
        "\n[tooling]\n"
        'summary = "Test profile with no external commands."\n'
        "default_validation = []\n"
        "\n[environment]\n"
        "managed_roles = []\n"
    )
    commit_all(root, "Configure test workflow")


def _assert_successful_result(result: RunResult, *, sessions: int) -> None:
    assert result.sessions_run == sessions
    assert result.completed is True
    assert result.exit_code == 0
    assert result.errors == ()


def _design_plan(root: Path) -> Path:
    return root / ".devlab/plans/design-plan.md"


def _project_plan(root: Path) -> Path:
    return root / ".devlab/plans/project-plan.md"

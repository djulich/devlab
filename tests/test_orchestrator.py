from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from devlab._logging import logger
from devlab.agents import AgentCall, AgentInvocation, AgentResult, MockProvider, ProviderError
from devlab.clarifications import FileClarificationTracker
from devlab.findings import FINDINGS_DIR, FileFindingTracker, FindingStatus
from devlab.handoffs import (
    Handoff,
    HandoffError,
    HandoffSubmissionError,
    SessionEnvelope,
    parse_handoff,
    write_session_envelope,
)
from devlab.milestones import FileMilestoneTracker, MilestoneStatus
from devlab.orchestrator import (
    RunStopReason,
    _timestamp,
    close_task,
    process_handoff,
    run_loop,
    submit_session_handoff,
    validate_handoff,
)
from devlab.prompts import build_base_prompt, build_session_prompt
from devlab.roles import ROLES
from devlab.task_tracker import TASKS_DIR, FileTaskTracker, TaskStatus
from devlab.workflow_events import load_workflow_events
from devlab.workflow_state import ResumeState, load_workflow_state, set_resume_state
from devlab.workspace import (
    AGENT_LOG_DIR,
    ARTIFACTS_DIR,
    DESIGN_PLAN,
    HISTORY_DIR,
    PROJECT_PLAN,
    Workspace,
)
from tests.helpers import complete_acceptance


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
    generation: int | None = None,
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
    generation_line = (
        f"planning_generation = {generation}\n" if generation is not None else ""
    )
    validation_line = ""
    addresses_findings = addresses_findings or []
    addresses_findings_text = ", ".join(f'"{finding_id}"' for finding_id in addresses_findings)
    if validation is not None:
        validation_commands = ", ".join(f'"{command}"' for command in validation)
        validation_line = f"validation = [{validation_commands}]\n"
    if body is None:
        body = (
            f"# {task_id}: {title}\n\n"
            f"## Goal\nComplete {title}.\n\n"
            "## Acceptance Criteria\n- [ ] Done\n"
        )
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{title}"\n'
        f'status = "{status}"\n'
        f"{milestone_line}"
        f"{profile_line}"
        f"{domain_line}"
        f"{generation_line}"
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
    generation: int | None = None,
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
    generation_line = (
        f"planning_generation = {generation}\n" if generation is not None else ""
    )
    path.write_text(
        "version = 1\n"
        f'id = "{milestone_id}"\n'
        f'title = "{milestone_id}"\n'
        f'status = "{status}"\n'
        "integration_required = true\n"
        f"integrated = {str(integrated).lower()}\n"
        f"architecture_reviewed = {str(architecture_reviewed).lower()}\n"
        f"{generation_line}"
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


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "-C", root.as_posix(), "init"], check=True)
    subprocess.run(
        ["git", "-C", root.as_posix(), "config", "user.name", "DevLab Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            root.as_posix(),
            "config",
            "user.email",
            "devlab-test@example.invalid",
        ],
        check=True,
    )


def _commit_all(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", root.as_posix(), "add", "-A"], check=True)
    subprocess.run(["git", "-C", root.as_posix(), "commit", "-m", message], check=True)
    return subprocess.run(
        ["git", "-C", root.as_posix(), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _write_system_spec(root: Path, text: str) -> None:
    path = root / ".devlab/specs/system/spec.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_workflow_state(
    root: Path,
    *,
    generation: int = 1,
    baseline: str | None = None,
) -> None:
    text = (
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n"
        f"generation = {generation}\n"
    )
    if baseline is not None:
        text += "\n[specs]\n" f'last_planned_spec_commit = "{baseline}"\n'
    (root / ".devlab/workflow.toml").write_text(text)


def _write_session_handoff(root: Path, role_name: str, text: str) -> Path:
    path = root / ARTIFACTS_DIR / role_name / "handoff.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _clarification_handoff(
    role_name: str = "developer",
    *,
    answer_shape: str = "choice",
) -> str:
    shape_fields = (
        'answer_shape = "choice"\nrecommended_option = "A"\n'
        if answer_shape == "choice"
        else f'answer_shape = "{answer_shape}"\n'
    )
    answer_details = (
        "### Options\n"
        "- A: 24-hour idle timeout.\n"
        "- B: No expiry for MVP.\n"
        if answer_shape == "choice"
        else (
            "### Expected File Edits\n"
            "- `docs/session-policy.md`: record the selected timeout policy.\n"
            if answer_shape == "file-edit"
            else "### Expected Answer\nA concise timeout policy.\n"
        )
    )
    return (
        f"# Handoff: {role_name}\n"
        "## Done\n"
        "- Reached a blocking ambiguity.\n"
        "## Changed Artifacts\n"
        "- None\n"
        "## Open Issues\n"
        "- Blocked pending operator clarification.\n"
        "## Addressed Findings\n"
        "- None\n"
        "## Next Session Hint\n"
        "Resume after clarification.\n"
        "## Clarification Request\n"
        "clarification_required = true\n"
        'title = "Auth session timeout"\n'
        'scope = "task:T0001"\n'
        'blocks = "implementation"\n'
        f"{shape_fields}\n"
        "### Context\n"
        "The task requires sessions but the spec does not define expiry.\n\n"
        "### Question\n"
        "Should sessions expire?\n\n"
        f"{answer_details}"
    )


def test_process_handoff_creates_clarification_without_developer_transition(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    _write_workflow_state(tmp_path)
    _write_task(
        tmp_path,
        "T0001",
        body=(
            "# T0001: Auth\n\n"
            "## Acceptance Criteria\n"
            "- [x] Implement auth sessions\n"
        ),
    )
    path = _write_session_handoff(tmp_path, "developer", _clarification_handoff())
    handoff = parse_handoff(path, "developer")

    result = process_handoff(
        handoff,
        Workspace(tmp_path),
        command="implement",
        session_id="20260707T101500_001_developer",
        task_id="T0001",
    )

    assert result.clarification_id == "CL0001"
    task = FileTaskTracker(tmp_path).get("T0001")
    assert task.status == TaskStatus.OPEN
    clarification = Workspace(tmp_path).snapshot.list_clarifications()[0]
    assert clarification.id == "CL0001"
    assert clarification.asking_role == "developer"
    assert clarification.blocks == "implementation"
    resume = load_workflow_state(tmp_path).resume
    assert resume is not None
    assert resume.blocked_by == "CL0001"
    assert resume.command == "implement"
    assert resume.role == "developer"
    assert resume.task == "T0001"


def test_process_handoff_creates_clarification_without_planner_state_update(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / ".devlab/workflow.toml").write_text(
        "version = 1\n\n[planning]\ncomplete = false\n"
    )
    handoff_text = (
        _clarification_handoff("planner")
        + "\n## Planning State\n"
        "planning_complete = true\n"
    )
    path = _write_session_handoff(tmp_path, "planner", handoff_text)
    handoff = parse_handoff(path, "planner")

    result = process_handoff(
        handoff,
        Workspace(tmp_path),
        command="plan",
        session_id="20260707T101500_001_planner",
    )

    assert result.clarification_id == "CL0001"
    state = load_workflow_state(tmp_path)
    assert state.planning.complete is False
    assert state.resume is not None
    assert state.resume.command == "plan"


def test_run_loop_rejects_wrong_plain_command_for_active_resume_pointer(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / ".devlab/workflow.toml").write_text(
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n\n"
        "[resume]\n"
        'blocked_by = "CL0001"\n'
        'command = "implement"\n'
        'role = "developer"\n'
        'task = "T0001"\n'
        'milestone = ""\n'
    )

    result = run_loop(tmp_path, max_sessions=1, planning_only=True)

    assert result.exit_code == 1
    assert result.errors[0].phase == "clarification_resume"
    assert "Workflow is waiting to resume after CL0001" in result.errors[0].message
    assert "command=devlab implement" in result.errors[0].message
    assert "role=developer" in result.errors[0].message
    assert "task=T0001" in result.errors[0].message
    assert "Run `devlab resume`" in result.errors[0].message
    assert "explicitly run `devlab implement`" in result.errors[0].message
    assert "devlab plan --revise" in result.errors[0].message


def test_run_loop_clears_matching_resume_pointer_after_session(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(
        tmp_path,
        "T0001",
        body=(
            "# T0001: First\n\n"
            "## Goal\nComplete First.\n\n"
            "## Acceptance Criteria\n"
            "- [x] Done\n"
        ),
    )
    clarification = Workspace(tmp_path).clarifications().create(
        title="Auth session timeout",
        asking_role="developer",
        session_id="s1",
        scope="task:T0001",
        blocks="implementation",
        answer_shape="text",
        body=(
            "# Auth session timeout\n\n"
            "## Context\nC\n\n"
            "## Question\nQ\n\n"
            "## Expected Answer\nA\n"
        ),
    )
    Workspace(tmp_path).clarifications().get(clarification.id).answer("Use 24h.")
    (tmp_path / ".devlab/workflow.toml").write_text(
        "version = 1\n\n"
        "[planning]\n"
        "complete = true\n\n"
        "[resume]\n"
        f'blocked_by = "{clarification.id}"\n'
        'command = "implement"\n'
        'role = "developer"\n'
        'task = "T0001"\n'
        'milestone = ""\n'
    )
    provider = MockProvider(
        handoff_text=(
            "# Handoff: developer\n"
            "## Done\n- Completed task.\n"
            "## Changed Artifacts\n- None\n"
            "## Open Issues\n- None\n"
            "## Addressed Findings\n- None\n"
            "## Next Session Hint\nReview.\n"
        )
    )

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"mock": provider},
        role_agent_providers={"developer": "mock"},
    )

    assert result.exit_code == 0
    assert load_workflow_state(tmp_path).resume is None


def test_run_loop_agent_clarification_mode_invokes_resolver_and_resumes(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    _write_workflow_state(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    task = _write_task(tmp_path, "T0001", "Auth")
    developer_calls = 0

    def handoff_for(call: AgentCall) -> str:
        nonlocal developer_calls
        if call.role_name == "developer":
            developer_calls += 1
        if call.role_name == "developer" and developer_calls == 1:
            return _clarification_handoff("developer")
        return (
            "# Handoff: developer\n"
            "## Done\n- Completed task.\n"
            "## Changed Artifacts\n- None\n"
            "## Open Issues\n- None\n"
            "## Addressed Findings\n- None\n"
            "## Next Session Hint\nReview.\n"
        )

    def on_invoke(call: AgentCall) -> None:
        if call.role_name == "clarification-resolver":
            answer_path = (
                call.root
                / ARTIFACTS_DIR
                / "clarification-resolver"
                / "answer.json"
            )
            answer_path.parent.mkdir(parents=True, exist_ok=True)
            answer_path.write_text(
                '{"clarification_id":"CL0001","answer_shape":"choice",'
                '"choice":"A"}'
            )
            assert "## Clarification To Resolve" in call.session_prompt
            assert "<clarification-data>" in call.session_prompt
            assert '"choice": "<option ID>"' in call.session_prompt
        if call.role_name == "developer" and developer_calls == 1:
            complete_acceptance(call.root, "T0001")

    provider = MockProvider(handoff_text=handoff_for, on_invoke=on_invoke)

    result = run_loop(
        tmp_path,
        max_sessions=3,
        agent_providers={"default": provider},
        clarification_mode="agent",
    )

    assert result.exit_code == 0
    assert [call.role_name for call in provider.calls] == [
        "developer",
        "clarification-resolver",
        "developer",
    ]
    clarification = FileClarificationTracker(tmp_path).get("CL0001")
    assert clarification.status.value == "answered"
    assert clarification.metadata["answered_by"].startswith(
        "agent:clarification-resolver:"
    )
    assert load_workflow_state(tmp_path).resume is None
    assert 'status = "in_review"' in task.read_text()


def test_run_loop_agent_clarification_mode_stops_on_invalid_resolver_answer(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    _write_workflow_state(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(tmp_path, "T0001", "Auth")

    def on_invoke(call: AgentCall) -> None:
        if call.role_name == "clarification-resolver":
            answer_path = (
                call.root
                / ARTIFACTS_DIR
                / "clarification-resolver"
                / "answer.json"
            )
            answer_path.parent.mkdir(parents=True, exist_ok=True)
            answer_path.write_text(
                '{"clarification_id":"CL0001","answer_shape":"choice",'
                '"choice":"C"}'
            )

    provider = MockProvider(
        handoff_text=_clarification_handoff("developer"),
        on_invoke=on_invoke,
    )

    result = run_loop(
        tmp_path,
        max_sessions=2,
        agent_providers={"default": provider},
        clarification_mode="agent",
    )

    assert result.exit_code == 1
    assert result.errors[0].phase == "clarification_resolver"
    assert "must match one listed option ID" in result.errors[0].message
    assert FileClarificationTracker(tmp_path).get("CL0001").status.value == "pending"
    assert load_workflow_state(tmp_path).resume is not None


def test_run_loop_agent_mode_rejects_invalid_recommendation_before_resolver(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    _write_workflow_state(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(tmp_path, "T0001", "Auth")
    invalid_handoff = _clarification_handoff("developer").replace(
        'recommended_option = "A"', 'recommended_option = "C"'
    )
    provider = MockProvider(handoff_text=invalid_handoff)

    result = run_loop(
        tmp_path,
        max_sessions=2,
        agent_providers={"default": provider},
        clarification_mode="agent",
    )

    assert result.exit_code == 1
    assert "must match one listed option" in result.errors[0].message
    assert [call.role_name for call in provider.calls] == ["developer"]
    assert Workspace(tmp_path).snapshot.list_clarifications() == []
    assert load_workflow_state(tmp_path).resume is None


@pytest.mark.parametrize("answer_shape", ["text", "file-edit"])
def test_run_loop_agent_clarification_mode_resolves_non_choice_answers(
    tmp_path: Path, answer_shape: str
) -> None:
    _setup_tree(tmp_path)
    _write_workflow_state(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(tmp_path, "T0001", "Auth")
    developer_calls = 0

    def handoff_for(call: AgentCall) -> str:
        nonlocal developer_calls
        if call.role_name == "developer":
            developer_calls += 1
            if developer_calls == 1:
                return _clarification_handoff(
                    "developer", answer_shape=answer_shape
                )
        return (
            "# Handoff: developer\n"
            "## Done\n- Completed task.\n"
            "## Changed Artifacts\n- None\n"
            "## Open Issues\n- None\n"
            "## Addressed Findings\n- None\n"
            "## Next Session Hint\nReview.\n"
        )

    def on_invoke(call: AgentCall) -> None:
        if call.role_name == "developer" and developer_calls == 1:
            complete_acceptance(call.root, "T0001")
        if call.role_name != "clarification-resolver":
            return
        if answer_shape == "file-edit":
            policy_path = call.root / "docs/session-policy.md"
            policy_path.parent.mkdir(parents=True, exist_ok=True)
            policy_path.write_text("# Session Policy\n\nUse a 24-hour idle timeout.\n")
            answer = "Recorded a 24-hour idle timeout in docs/session-policy.md."
        else:
            answer = "Use a 24-hour idle timeout."
        answer_path = call.root / ARTIFACTS_DIR / call.role_name / "answer.json"
        answer_path.write_text(
            '{"clarification_id":"CL0001","answer_shape":"'
            + answer_shape
            + '","answer":'
            + json.dumps(answer)
            + "}"
        )

    provider = MockProvider(handoff_text=handoff_for, on_invoke=on_invoke)

    result = run_loop(
        tmp_path,
        max_sessions=3,
        agent_providers={"default": provider},
        clarification_mode="agent",
    )

    assert result.exit_code == 0
    clarification = FileClarificationTracker(tmp_path).get("CL0001")
    assert clarification.status.value == "answered"
    assert "24-hour idle timeout" in clarification.answer_text
    if answer_shape == "file-edit":
        assert (tmp_path / "docs/session-policy.md").read_text() == (
            "# Session Policy\n\nUse a 24-hour idle timeout.\n"
        )


@pytest.mark.parametrize(
    ("artifact", "expected_error"),
    [
        (None, "did not write"),
        ("not valid json", "invalid JSON"),
        (
            '{"clarification_id":"CL9999","answer_shape":"choice","choice":"A"}',
            "clarification_id must be 'CL0001'",
        ),
        (
            '{"clarification_id":"CL0001","answer_shape":"choice","choice":""}',
            "requires non-empty choice",
        ),
    ],
)
def test_run_loop_resolver_artifact_failure_preserves_pending_resume(
    tmp_path: Path, artifact: str | None, expected_error: str
) -> None:
    _setup_tree(tmp_path)
    _write_workflow_state(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(tmp_path, "T0001", "Auth")

    def on_invoke(call: AgentCall) -> None:
        if call.role_name == "clarification-resolver" and artifact is not None:
            answer_path = call.root / ARTIFACTS_DIR / call.role_name / "answer.json"
            answer_path.write_text(artifact)

    provider = MockProvider(
        handoff_text=_clarification_handoff("developer"),
        on_invoke=on_invoke,
    )

    result = run_loop(
        tmp_path,
        max_sessions=2,
        agent_providers={"default": provider},
        clarification_mode="agent",
    )

    assert result.exit_code == 1
    assert result.sessions_run == 2
    assert len(provider.calls) == 2
    assert expected_error in result.errors[0].message
    assert "remains pending with its resume pointer" in result.errors[0].message
    assert "devlab implement --unattended" in result.errors[0].message
    assert FileClarificationTracker(tmp_path).get("CL0001").status.value == "pending"
    resume = load_workflow_state(tmp_path).resume
    assert resume is not None
    assert resume.blocked_by == "CL0001"


def test_run_loop_resolver_rejects_and_restores_forbidden_workflow_edit(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    _write_workflow_state(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(tmp_path, "T0001", "Auth")

    def on_invoke(call: AgentCall) -> None:
        if call.role_name != "clarification-resolver":
            return
        (call.root / ".devlab/workflow.toml").write_text("corrupted = true\n")
        answer_path = call.root / ARTIFACTS_DIR / call.role_name / "answer.json"
        answer_path.write_text(
            '{"clarification_id":"CL0001","answer_shape":"choice",'
            '"choice":"A"}'
        )

    provider = MockProvider(
        handoff_text=_clarification_handoff("developer"), on_invoke=on_invoke
    )

    result = run_loop(
        tmp_path,
        max_sessions=2,
        agent_providers={"default": provider},
        clarification_mode="agent",
    )

    assert result.exit_code == 1
    assert ".devlab/workflow.toml" in result.errors[0].message
    assert FileClarificationTracker(tmp_path).get("CL0001").status.value == "pending"
    resume = load_workflow_state(tmp_path).resume
    assert resume is not None
    assert resume.blocked_by == "CL0001"


def test_run_loop_file_edit_resolver_requires_declared_edit(tmp_path: Path) -> None:
    _setup_tree(tmp_path)
    _write_workflow_state(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(tmp_path, "T0001", "Auth")

    def on_invoke(call: AgentCall) -> None:
        if call.role_name != "clarification-resolver":
            return
        answer_path = call.root / ARTIFACTS_DIR / call.role_name / "answer.json"
        answer_path.write_text(
            '{"clarification_id":"CL0001","answer_shape":"file-edit",'
            '"answer":"No edit was needed."}'
        )

    provider = MockProvider(
        handoff_text=_clarification_handoff("developer", answer_shape="file-edit"),
        on_invoke=on_invoke,
    )

    result = run_loop(
        tmp_path,
        max_sessions=2,
        agent_providers={"default": provider},
        clarification_mode="agent",
    )

    assert result.exit_code == 1
    assert "did not edit expected path(s): docs/session-policy.md" in (
        result.errors[0].message
    )
    assert FileClarificationTracker(tmp_path).get("CL0001").status.value == "pending"


def _create_answered_clarification(root: Path) -> str:
    clarification = Workspace(root).clarifications().create(
        title="Auth session timeout",
        asking_role="developer",
        session_id="s1",
        scope="task:T0001",
        blocks="implementation",
        answer_shape="text",
        body=(
            "# Auth session timeout\n\n"
            "## Context\nC\n\n"
            "## Question\nQ\n\n"
            "## Expected Answer\nA\n"
        ),
    )
    Workspace(root).clarifications().get(clarification.id).answer("Use 24h.")
    return clarification.id


def _set_resume(
    root: Path,
    clarification_id: str,
    *,
    role: str = "developer",
    task: str = "T0001",
    milestone: str = "",
) -> None:
    set_resume_state(
        root,
        ResumeState(
            blocked_by=clarification_id,
            command="implement",
            role=role,
            task=task,
            milestone=milestone,
        ),
    )


def test_run_loop_resume_refuses_to_switch_development_tasks(tmp_path: Path) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_workflow_state(tmp_path)
    clarification_id = _create_answered_clarification(tmp_path)
    _write_task(tmp_path, "T0001", status="open", depends_on=["T9999"])
    _write_task(tmp_path, "T0002", status="open")
    _set_resume(tmp_path, clarification_id)

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"mock": MockProvider()},
        role_agent_providers={"developer": "mock"},
    )

    assert result.exit_code == 1
    assert result.errors[0].phase == "clarification_resume"
    assert "unsatisfied dependencies: T9999" in result.errors[0].message
    assert load_workflow_state(tmp_path).resume is not None


def test_run_loop_resume_fails_when_interrupted_task_is_missing(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_workflow_state(tmp_path)
    clarification_id = _create_answered_clarification(tmp_path)
    _write_task(tmp_path, "T0002", status="open")
    _set_resume(tmp_path, clarification_id)

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"mock": MockProvider()},
        role_agent_providers={"developer": "mock"},
    )

    assert result.exit_code == 1
    assert "Interrupted task T0001 no longer exists" in result.errors[0].message
    assert "command=devlab implement" in result.errors[0].message
    assert "devlab clarify supersede CL0001 --reason ..." in result.errors[0].message
    assert load_workflow_state(tmp_path).resume is not None


def test_run_loop_resume_fails_when_interrupted_task_is_closed(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_workflow_state(tmp_path)
    clarification_id = _create_answered_clarification(tmp_path)
    _write_task(tmp_path, "T0001", status="closed")
    _write_task(tmp_path, "T0002", status="open")
    _set_resume(tmp_path, clarification_id)

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"mock": MockProvider()},
        role_agent_providers={"developer": "mock"},
    )

    assert result.exit_code == 1
    assert "Interrupted task T0001 is closed" in result.errors[0].message
    assert load_workflow_state(tmp_path).resume is not None


def test_run_loop_resume_fails_when_next_development_task_differs(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_workflow_state(tmp_path)
    clarification_id = _create_answered_clarification(tmp_path)
    _write_task(tmp_path, "T0000", status="open")
    _write_task(tmp_path, "T0001", status="open")
    _set_resume(tmp_path, clarification_id)

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"mock": MockProvider()},
        role_agent_providers={"developer": "mock"},
    )

    assert result.exit_code == 1
    assert "Next development task is T0000" in result.errors[0].message
    assert load_workflow_state(tmp_path).resume is not None


def test_run_loop_resume_fails_when_review_task_is_no_longer_in_review(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_workflow_state(tmp_path)
    clarification_id = _create_answered_clarification(tmp_path)
    _write_task(tmp_path, "T0001", status="changes_requested")
    _set_resume(tmp_path, clarification_id, role="reviewer")

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"mock": MockProvider()},
        role_agent_providers={"reviewer": "mock"},
    )

    assert result.exit_code == 1
    assert "Interrupted task T0001 is changes_requested" in result.errors[0].message
    assert load_workflow_state(tmp_path).resume is not None


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

    def test_empty_plan_stops_when_explicit_planning_complete(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n[planning]\ncomplete = true\n"
        )
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        (tmp_path / PROJECT_PLAN).write_text("")
        assert Workspace(tmp_path).snapshot.assess_state() is None

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

    def test_all_tasks_closed_routes_to_planner_when_planning_incomplete(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n[planning]\ncomplete = false\n"
        )
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed")
        assert Workspace(tmp_path).snapshot.assess_state() == "planner"

    def test_all_tasks_closed_stops_when_planning_complete(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n[planning]\ncomplete = true\n"
        )
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

    def test_developer_prompt_includes_answered_task_clarification(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First")
        clarification = Workspace(tmp_path).clarifications().create(
            title="Auth session timeout",
            asking_role="developer",
            session_id="s1",
            scope="task:T0001",
            blocks="implementation",
            answer_shape="text",
            body=(
                "# Auth session timeout\n\n"
                "## Context\nC\n\n"
                "## Question\nQ\n\n"
                "## Expected Answer\nA\n"
            ),
        )
        Workspace(tmp_path).clarifications().get(clarification.id).answer(
            "Use a 24-hour idle timeout."
        )

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "developer")

        assert "## Operator Clarifications" in prompt
        assert "CL0001 Auth session timeout: Use a 24-hour idle timeout." in prompt

    def test_developer_prompt_omits_unrelated_answered_task_clarification(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "First")
        clarification = Workspace(tmp_path).clarifications().create(
            title="Other task policy",
            asking_role="developer",
            session_id="s1",
            scope="task:T0002",
            blocks="implementation",
            answer_shape="text",
            body=(
                "# Other task policy\n\n"
                "## Context\nC\n\n"
                "## Question\nQ\n\n"
                "## Expected Answer\nA\n"
            ),
        )
        Workspace(tmp_path).clarifications().get(clarification.id).answer("Answer.")

        prompt = build_session_prompt(Workspace(tmp_path).snapshot, "developer")

        assert "## Operator Clarifications" not in prompt


class TestBuildSystemPrompt:
    def test_planner_includes_tooling(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        role = ROLES["planner"]
        prompt = build_base_prompt(tmp_path, role)
        assert "Conventions" in prompt
        assert "Role: Planner" in prompt
        assert "Tooling" in prompt

    def test_developer_includes_tooling(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        role = ROLES["developer"]
        prompt = build_base_prompt(tmp_path, role)
        assert "Tooling" in prompt

    def test_developer_base_prompt_includes_task_domain_overlay(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "Deploy", domain="deployment")
        role = ROLES["developer"]

        prompt = build_base_prompt(
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

        prompt = build_base_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="reviewer",
        )

        assert "Domain: Deployment / Reviewer" in prompt
        assert "do not install it" in prompt
        assert "unverified" in prompt

    def test_developer_base_prompt_omits_domain_overlay_for_general_task(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_task(tmp_path, "T0001", "General")
        role = ROLES["developer"]

        prompt = build_base_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="developer",
        )

        assert "Domain: Deployment" not in prompt

    def test_planner_base_prompt_includes_deployment_overlay_for_deployment_spec(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        deployment_spec = tmp_path / ".devlab/specs/deployment/README.md"
        deployment_spec.parent.mkdir(parents=True)
        deployment_spec.write_text(
            "# Deployment Specification\n\nSupport local Podman deployment.\n"
        )
        role = ROLES["planner"]

        prompt = build_base_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment / Planner" in prompt

    def test_planner_base_prompt_activates_from_additional_deployment_spec_file(
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

        prompt = build_base_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment / Planner" in prompt

    def test_planner_base_prompt_ignores_placeholder_deployment_spec(
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

        prompt = build_base_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment" not in prompt

    def test_planner_base_prompt_activates_deployment_without_sentinel(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        deployment_spec = tmp_path / ".devlab/specs/deployment/README.md"
        deployment_spec.parent.mkdir(parents=True)
        deployment_spec.write_text(
            "# Deployment Specification\n\nSupport Kubernetes manifests with kind.\n"
        )
        role = ROLES["planner"]

        prompt = build_base_prompt(
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

        prompt = build_base_prompt(
            tmp_path,
            role,
            snapshot=Workspace(tmp_path).snapshot,
            role_name="planner",
        )

        assert "Domain: Deployment / Planner" in prompt


def _checked_task_body(task_id: str, title: str) -> str:
    return (
        f"# {task_id}: {title}\n\n"
        f"## Goal\nComplete {title}.\n\n"
        "## Acceptance Criteria\n- [x] Done\n"
    )


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
            run_loop(tmp_path, max_sessions=1, revise_plan=True)

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
            max_sessions=5,
            planning_only=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 2
        assert result.stop_reason == RunStopReason.COMMAND_COMPLETE
        assert result.completed is True
        assert [call.role_name for call in provider.calls] == ["architect", "planner"]
        assert Workspace(tmp_path).snapshot.assess_state() == "developer"

    def test_planning_only_records_lifecycle_events(self, tmp_path: Path) -> None:
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
            max_sessions=5,
            planning_only=True,
            agent_providers={"default": provider},
        )

        events = load_workflow_events(tmp_path)
        assert result.sessions_run == 2
        planning_events = [event for event in events if event.type.startswith("plan_")]
        assert [(event.type, event.data["mode"]) for event in planning_events] == [
            ("plan_started", "greenfield"),
            ("plan_completed", "greenfield"),
        ]

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
            max_sessions=5,
            planning_only=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 0
        assert result.stop_reason == RunStopReason.COMMAND_COMPLETE
        assert result.completed is True
        assert provider.calls == []

    def test_planning_only_noop_records_missing_spec_baseline(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        _write_task(tmp_path, "T0001", "First")
        _write_system_spec(tmp_path, "# Spec\n")
        _init_git_repo(tmp_path)
        baseline = _commit_all(tmp_path, "init")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=5,
            planning_only=True,
            automatic_version_control=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 0
        assert provider.calls == []
        assert f'last_planned_spec_commit = "{baseline}"' in (
            tmp_path / ".devlab/workflow.toml"
        ).read_text()
        assert not subprocess.run(
            ["git", "-C", tmp_path.as_posix(), "status", "--porcelain"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def test_planning_only_changed_specs_force_architect_and_planner(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        (tmp_path / PROJECT_PLAN).write_text("# Project\n")
        _write_task(tmp_path, "T0001", "First")
        _write_system_spec(tmp_path, "# Spec\n")
        _init_git_repo(tmp_path)
        baseline = _commit_all(tmp_path, "init")
        _write_workflow_state(tmp_path, generation=1, baseline=baseline)
        _commit_all(tmp_path, "record baseline")
        _write_system_spec(tmp_path, "# Changed spec\n")
        latest = _commit_all(tmp_path, "change spec")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            automatic_version_control=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 2
        assert [call.role_name for call in provider.calls] == ["architect", "planner"]
        workflow_text = (tmp_path / ".devlab/workflow.toml").read_text()
        assert "generation =" not in workflow_text
        assert f'last_planned_spec_commit = "{latest}"' in workflow_text
        assert "This is spec reconciliation" in provider.calls[-1].session_prompt
        assert (tmp_path / ".devlab/generations/0001/tasks/T0001_first.md").exists()
        assert not (tmp_path / ".devlab/tasks/T0001_first.md").exists()

    def test_replace_plan_archives_active_plan(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            replace_plan=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 2
        assert (tmp_path / ".devlab/generations/0001/tasks/T0001_first.md").exists()
        assert not (tmp_path / ".devlab/tasks/T0001_first.md").exists()
        assert "replacement planning" in provider.calls[-1].session_prompt

    def test_adopt_existing_is_rejected_when_active_plan_exists(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            adopt_existing=True,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 2
        assert result.errors[0].phase == "planning_mode"
        assert provider.calls == []

    def test_replace_plan_is_rejected_without_active_plan(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            replace_plan=True,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 2
        assert result.errors[0].phase == "planning_mode"
        assert provider.calls == []

    def test_adopt_existing_and_replace_plan_are_mutually_exclusive(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            adopt_existing=True,
            replace_plan=True,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 2
        assert result.errors[0].phase == "planning_mode"
        assert provider.calls == []

    def test_mark_specs_planned_is_mutually_exclusive_with_planning_modes(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            revise_plan=True,
            mark_specs_planned=True,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 2
        assert result.errors[0].phase == "planning_mode"
        assert "--mark-specs-planned" in result.errors[0].message
        assert provider.calls == []

    def test_adopt_existing_runs_first_planning_with_adoption_prompt(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            adopt_existing=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 2
        assert [call.role_name for call in provider.calls] == ["architect", "planner"]
        assert "existing-project adoption" in provider.calls[0].session_prompt
        assert "current-state design baseline" in provider.calls[0].session_prompt
        assert "Preserve the existing project's development stack" in (
            provider.calls[0].session_prompt
        )
        assert "target-owned validation path" in provider.calls[0].session_prompt
        assert "existing-project adoption" in provider.calls[-1].session_prompt
        assert "target-owned validation path" in provider.calls[-1].session_prompt
        assert "Do not silently rely on host-global" in provider.calls[-1].session_prompt
        assert not (tmp_path / ".devlab/generations").exists()

    def test_mark_specs_planned_updates_baseline_without_agent_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        _write_task(tmp_path, "T0001", "First")
        _write_system_spec(tmp_path, "# Spec\n")
        _init_git_repo(tmp_path)
        baseline = _commit_all(tmp_path, "init")
        _write_workflow_state(tmp_path, baseline=baseline)
        _commit_all(tmp_path, "record baseline")
        _write_system_spec(tmp_path, "# Format-only spec change\n")
        latest = _commit_all(tmp_path, "format spec")
        provider = MockProvider()
        warnings: list[str] = []

        def record_warning(message: str, *args: object, **_kwargs: object) -> None:
            warnings.append(message % args if args else message)

        monkeypatch.setattr(logger, "warning", record_warning)

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            mark_specs_planned=True,
            automatic_version_control=True,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 0
        assert result.sessions_run == 0
        assert result.stop_reason == RunStopReason.COMMAND_COMPLETE
        assert provider.calls == []
        assert f'last_planned_spec_commit = "{latest}"' in (
            tmp_path / ".devlab/workflow.toml"
        ).read_text()
        assert any("bypasses the spec reconciliation guardrail" in item for item in warnings)
        events = load_workflow_events(tmp_path)
        assert events[-1].type == "specs_marked_planned"
        assert events[-1].data["spec_baseline"] == latest
        assert not subprocess.run(
            ["git", "-C", tmp_path.as_posix(), "status", "--porcelain"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def test_mark_specs_planned_refuses_dirty_spec_paths(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        _write_system_spec(tmp_path, "# Spec\n")
        _init_git_repo(tmp_path)
        baseline = _commit_all(tmp_path, "init")
        _write_workflow_state(tmp_path, baseline=baseline)
        _commit_all(tmp_path, "record baseline")
        _write_system_spec(tmp_path, "# Dirty spec\n")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            mark_specs_planned=True,
            automatic_version_control=True,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.errors[0].phase == "spec_reconciliation"
        assert "commit them before running devlab plan" in result.errors[0].message
        assert provider.calls == []

    def test_planning_only_dirty_spec_paths_fail_before_agent_session(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        _write_system_spec(tmp_path, "# Spec\n")
        _init_git_repo(tmp_path)
        baseline = _commit_all(tmp_path, "init")
        _write_workflow_state(tmp_path, baseline=baseline)
        _commit_all(tmp_path, "record baseline")
        _write_system_spec(tmp_path, "# Dirty spec\n")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=2,
            planning_only=True,
            automatic_version_control=True,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.errors[0].phase == "spec_reconciliation"
        assert "commit them before running devlab plan" in result.errors[0].message
        assert provider.calls == []

    def test_run_blocks_when_spec_baseline_is_stale(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        _write_task(tmp_path, "T0001", "First")
        _write_system_spec(tmp_path, "# Spec\n")
        _init_git_repo(tmp_path)
        baseline = _commit_all(tmp_path, "init")
        _write_workflow_state(tmp_path, baseline=baseline)
        _commit_all(tmp_path, "record baseline")
        _write_system_spec(tmp_path, "# Changed spec\n")
        _commit_all(tmp_path, "change spec")
        provider = MockProvider()

        result = run_loop(
            tmp_path,
            max_sessions=1,
            automatic_version_control=True,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.errors[0].phase == "spec_reconciliation"
        assert "Run devlab plan to reconcile" in result.errors[0].message
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
            max_sessions=5,
            planning_only=True,
            revise_plan=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 2
        assert [call.role_name for call in provider.calls] == ["architect", "planner"]
        assert all("## Planning Revision Mode" in call.session_prompt for call in provider.calls)

    def test_revise_plan_rejects_deleted_active_task(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        (tmp_path / PROJECT_PLAN).write_text("## M1: Initial\n- T0001: First\n")
        task_path = _write_task(tmp_path, "T0001", "First", milestone="M1")

        def on_invoke(call: AgentCall) -> None:
            if call.role_name == "planner":
                task_path.unlink()

        provider = MockProvider(on_invoke=on_invoke)

        result = run_loop(
            tmp_path,
            max_sessions=5,
            planning_only=True,
            revise_plan=True,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 1
        assert result.exit_code == 1
        assert result.errors[0].phase == "handoff_validation"
        assert "planner deleted active task file(s): T0001" in result.errors[0].message

    def test_planner_follow_up_rejects_deleted_active_task(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\n")
        (tmp_path / PROJECT_PLAN).write_text("## M1: Initial\n- T0001: First\n")
        task_path = _write_task(tmp_path, "T0001", "First", status="closed", milestone="M1")
        FileFindingTracker(tmp_path).create(
            title="Missing follow-up",
            source="integrator",
            milestone="M1",
            body="# Finding\n",
        )

        def on_invoke(call: AgentCall) -> None:
            assert call.role_name == "planner"
            task_path.unlink()

        provider = MockProvider(on_invoke=on_invoke)

        result = run_loop(
            tmp_path,
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.sessions_run == 0
        assert result.exit_code == 1
        assert result.errors[0].phase == "handoff_validation"
        assert "planner deleted active task file(s): T0001" in result.errors[0].message

    def test_developer_completed_task_is_marked_in_review(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        task = _write_task(tmp_path, "T0001", "First", body=_checked_task_body("T0001", "First"))
        provider = MockProvider()

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert len(provider.calls) == 1
        assert provider.calls[0].role_name == "developer"
        assert 'status = "in_review"' in task.read_text()
        assert _find_metadata(tmp_path)["progress"] == "workflow_advance"

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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
            tmp_path, max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 1
        assert result.completed is False
        assert result.stop_reason == RunStopReason.ERROR
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
            tmp_path, max_sessions=1,
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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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
            tmp_path, max_sessions=1,
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
            tmp_path, max_sessions=1,
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
            tmp_path, max_sessions=1,
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
            tmp_path, max_sessions=2,
            agent_providers={"default": provider},
        )

        assert result.completed is True
        assert result.stop_reason == RunStopReason.WORKFLOW_COMPLETE
        assert result.exit_code == 0
        assert result.errors == ()
        assert [call.role_name for call in provider.calls] == ["developer", "reviewer"]
        assert 'status = "closed"' in task.read_text()

    def test_session_limit_is_not_workflow_completion(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider(on_invoke=_complete_developer_task)

        result = run_loop(
            tmp_path, max_sessions=1, agent_providers={"default": provider}
        )

        assert result.stop_reason == RunStopReason.SESSION_LIMIT
        assert result.completed is False
        assert result.exit_code == 0

    def test_blocking_clarification_precedes_no_role_selection(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n[planning]\ncomplete = true\n"
        )
        Workspace(tmp_path).clarifications().create(
            title="Choose retention policy",
            asking_role="planner",
            session_id="session-1",
            scope="planning",
            blocks="planning",
            answer_shape="text",
            body="# Choose retention policy\n\n## Expected Answer\nA duration.\n",
        )
        provider = MockProvider()

        result = run_loop(
            tmp_path, max_sessions=1, agent_providers={"default": provider}
        )

        assert result.stop_reason == RunStopReason.CLARIFICATION_BLOCKED
        assert result.completed is False
        assert result.exit_code == 0
        assert result.errors[0].phase == "clarification_required"
        assert provider.calls == []

    def test_nonblocking_clarification_does_not_block_completion(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n[planning]\ncomplete = true\n"
        )
        Workspace(tmp_path).clarifications().create(
            title="Optional note",
            asking_role="planner",
            session_id="session-1",
            scope="planning",
            blocks="none",
            answer_shape="text",
            body="# Optional note\n\n## Expected Answer\nOptional.\n",
        )

        result = run_loop(
            tmp_path,
            max_sessions=1,
            agent_providers={"default": MockProvider()},
        )

        assert result.stop_reason == RunStopReason.WORKFLOW_COMPLETE
        assert result.completed is True

    def test_dependency_blocked_tasks_have_distinct_stop_reason(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0002", "Blocked", depends_on=["T0001"])

        result = run_loop(
            tmp_path,
            max_sessions=1,
            agent_providers={"default": MockProvider()},
        )

        assert result.stop_reason == RunStopReason.NO_ELIGIBLE_ROLE
        assert result.completed is False
        assert result.exit_code == 0

    def test_completed_milestone_selects_integrator(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        provider = MockProvider()

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["architect"]

    def test_integrator_runs_before_developer_for_next_milestone_without_architecture_review(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "M1 Done", status="closed", milestone="M1")
        _write_task(tmp_path, "T0002", "M2 Open", status="open", milestone="M2")
        provider = MockProvider()

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["integrator"]

    def test_successful_integrator_handoff_marks_milestone_integrated(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed", milestone="M1")
        provider = MockProvider()

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=2, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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
                "## Planning State\nplanning_complete = true\n"
            ),
            on_invoke=on_invoke,
        )

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert FileFindingTracker(tmp_path).get(finding.id).status == FindingStatus.PLANNED

    def test_planner_added_task_remains_active_without_generation_metadata(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n[planning]\ncomplete = false\n"
        )
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")

        def on_invoke(call: AgentCall) -> None:
            _write_task(call.root, "T0002", "Current work", milestone="M1")

        provider = MockProvider(
            handoff_text=(
                "# Handoff: planner\n"
                "## Done\n- Created task.\n"
                "## Changed Artifacts\n- .devlab/tasks/T0002_current-work.md (created)\n"
                "## Open Issues\n- None\n"
                "## Addressed Findings\n- None\n"
                "## Next Session Hint\nImplement task.\n"
                "## Planning State\nplanning_complete = true\n"
            ),
            on_invoke=on_invoke,
        )

        result = run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert result.exit_code == 0
        task_text = (tmp_path / TASKS_DIR / "T0002_current-work.md").read_text()
        assert "planning_generation" not in task_text
        selected_task = Workspace(tmp_path).snapshot.select_next_development_task()
        assert selected_task is not None
        assert selected_task.id == "T0002"

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
                "## Planning State\nplanning_complete = false\n"
            )
        )

        result = run_loop(
            tmp_path,
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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

    def test_missing_configured_agent_executable_fails_before_writing_logs(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        (tmp_path / ".devlab/config/agents.toml").write_text(
            "[defaults]\n"
            'provider = "missing"\n'
            "\n[providers.missing]\n"
            'command = "definitely-missing-devlab-agent"\n'
            'args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]\n'
        )
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
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n"
            "[planning]\n"
            "complete = true\n"
            "generation = 1\n\n"
            "[specs]\n"
            'last_planned_spec_commit = ""\n'
        )
        subprocess.run(["git", "-C", tmp_path.as_posix(), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", tmp_path.as_posix(), "commit", "-m", "record baseline"],
            check=True,
        )

        result = run_loop(tmp_path, max_sessions=1, automatic_version_control=True)

        status = subprocess.run(
            ["git", "-C", tmp_path.as_posix(), "status", "--porcelain"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        assert result.exit_code == 127
        assert result.errors[0].phase == "agent_configuration"
        assert "definitely-missing-devlab-agent" in result.errors[0].message
        assert status == ""
        assert not list((tmp_path / ".devlab/logs/agents").glob("*"))

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
            'args = ["--role", "{role_name}", "--model", "{model}", '
            '"--system-prompt", "{system_prompt}", "{session_prompt}"]\n'
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

        run_loop(tmp_path, max_sessions=1, retain_prompts=True)

        logs = list((tmp_path / ".devlab/logs/agents").glob("*_developer.config.toml"))
        assert len(logs) == 1
        text = logs[0].read_text()
        assert 'role = "developer"' in text
        assert 'provider = "mock-cli"' in text
        assert 'model = "test-model"' in text
        assert 'provider_version = "mock-agent 9.8.7"' in text
        meta = _find_metadata(tmp_path)
        assert meta["provider_version"] == "mock-agent 9.8.7"
        assert "base_prompt =" not in text
        assert "session_prompt =" not in text
        assert '"{system_prompt}"' in text
        assert '"{session_prompt}"' in text
        assert "stdout_log" in text
        assert "stderr_log" in text
        assert "base_prompt_log" in text
        assert "session_prompt_log" in text

    def test_retains_split_prompt_logs_when_enabled(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider()

        run_loop(
            tmp_path,
            max_sessions=1,
            retain_prompts=True,
            agent_providers={"default": provider},
        )

        agent_logs = tmp_path / ".devlab/logs/agents"
        base_logs = list(agent_logs.glob("*_developer.base-prompt.md"))
        session_logs = list(agent_logs.glob("*_developer.session-prompt.md"))
        assert len(base_logs) == 1
        assert len(session_logs) == 1
        assert "Role: Developer" in base_logs[0].read_text()
        assert "## Assigned Task" in session_logs[0].read_text()

    def test_uses_role_specific_agent_provider(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Review", status="in_review")
        default_provider = MockProvider()
        reviewer_provider = MockProvider()

        run_loop(
            tmp_path,
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
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.exit_code == 12
        assert result.completed is False
        assert result.errors[0].phase == "agent_invocation"
        assert "stdout_log" in result.errors[0].message
        assert "stderr_log" in result.errors[0].message

    def test_agent_failure_message_includes_full_log_commands(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider(return_code=1)

        result = run_loop(
            tmp_path,
            max_sessions=1,
            agent_providers={"default": provider},
        )

        assert result.completed is False
        assert result.errors[0].phase == "agent_invocation"
        assert "stdout_command=cat" in result.errors[0].message
        assert "stderr_command=cat" in result.errors[0].message

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
            tmp_path, max_sessions=1,
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

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

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

        run_loop(tmp_path, max_sessions=2, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["reviewer", "developer"]
        assert 'status = "closed"' in dependency.read_text()
        assert 'status = "open"' in dependent.read_text()

    def test_planner_invoked_when_design_exists_and_no_tasks(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        provider = MockProvider()

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["planner"]

    def test_incremental_planner_must_create_work_or_mark_planning_complete(
        self, tmp_path: Path
    ) -> None:
        _setup_tree(tmp_path)
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n[planning]\ncomplete = false\n"
        )
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed")
        provider = MockProvider()

        result = run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert result.exit_code == 1
        assert result.errors[0].phase == "handoff_validation"
        assert "neither created new durable work nor reported planning_complete = true" in (
            result.errors[0].message
        )

    def test_incremental_planner_can_mark_planning_complete(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / ".devlab/workflow.toml").write_text(
            "version = 1\n\n[planning]\ncomplete = false\n"
        )
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "Done", status="closed")

        provider = MockProvider(
            handoff_text=(
                "# Handoff: planner\n"
                "## Done\n- Planning completed.\n"
                "## Changed Artifacts\n- None\n"
                "## Open Issues\n- None\n"
                "## Addressed Findings\n- None\n"
                "## Next Session Hint\nNone.\n"
                "## Planning State\nplanning_complete = true\n"
            )
        )

        result = run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert result.exit_code == 0
        assert result.sessions_run == 1
        assert Workspace(tmp_path).snapshot.assess_state() is None

    def test_architect_invoked_when_design_plan_missing(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        provider = MockProvider()

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        assert [call.role_name for call in provider.calls] == ["architect"]

    def test_successful_session_archives_handoff(self, tmp_path: Path) -> None:
        _setup_tree(tmp_path)
        (tmp_path / DESIGN_PLAN).write_text("# Design\nSome content\n")
        _write_task(tmp_path, "T0001", "First")
        provider = MockProvider()

        run_loop(tmp_path, max_sessions=1, agent_providers={"default": provider})

        archived = list((tmp_path / HISTORY_DIR).glob("*_developer_handoff.md"))
        assert len(archived) == 1
        assert "Mock session completed" in archived[0].read_text()

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
            tmp_path, max_sessions=1,
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
            tmp_path, max_sessions=1,
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
            tmp_path, max_sessions=1,
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
            tmp_path, max_sessions=1,
            agent_providers={"default": provider},
        )

        meta = _find_metadata(tmp_path)
        assert meta["return_code"] == 0
        assert meta["failure_kind"] == "none"


def test_run_loop_can_use_one_opt_in_handoff_correction(tmp_path: Path) -> None:
    _setup_tree(tmp_path)
    invocations = 0

    def on_invoke(call: AgentCall) -> None:
        nonlocal invocations
        invocations += 1
        if invocations != 2:
            return
        envelope_path = Path(call.environment["DEVLAB_SESSION_ENVELOPE"])
        envelope_path.with_name("handoff-candidate.toml").write_text(
            'schema_version = 1\noutcome = "completed"\n'
            'commit_message = "Describe architecture"\n'
            'done = ["Described the architecture"]\nchanged_artifacts = []\n'
            'open_issues = []\naddressed_findings = []\n'
            'next_session_hint = "Create the project plan."\n'
        )
        submit_session_handoff(call.root, envelope_path=envelope_path)

    provider = MockProvider(write_handoff=False, on_invoke=on_invoke)

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"default": provider},
        handoff_correction=True,
    )

    assert result.exit_code == 0
    assert invocations == 2
    assert provider.calls[0].environment["DEVLAB_PYTHON"] == str(
        Path(sys.executable).absolute()
    )
    assert (
        '"$DEVLAB_PYTHON" -m devlab.cli session handoff submit'
        in provider.calls[0].session_prompt
    )
    assert list((tmp_path / HISTORY_DIR).glob("*_architect_result.toml"))


def test_completed_developer_submission_requires_complete_acceptance(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    _write_task(
        tmp_path,
        "T0001",
        "First",
        body=(
            "# T0001: First\n\n"
            "## Acceptance Criteria\n"
            "- [x] Implement behavior\n"
            "- [ ] Add regression coverage\n"
        ),
    )
    artifacts = tmp_path / ARTIFACTS_DIR / "developer"
    artifacts.mkdir(parents=True)
    envelope_path = artifacts / "session.toml"
    write_session_envelope(
        envelope_path,
        SessionEnvelope(
            schema_version=1,
            session_id="session-1",
            role="developer",
            task="T0001",
            protected_active_tasks=("T0001",),
        ),
    )
    (artifacts / "handoff-candidate.toml").write_text(
        'schema_version = 1\noutcome = "completed"\n'
        'commit_message = "Finish task"\n'
        'done = ["Implemented task"]\n'
        'changed_artifacts = ["src/example.py"]\n'
        "open_issues = []\naddressed_findings = []\n"
        'next_session_hint = "Review the task."\n'
    )

    with pytest.raises(
        HandoffSubmissionError, match="Add regression coverage"
    ):
        submit_session_handoff(tmp_path, envelope_path=envelope_path)

    complete_acceptance(tmp_path, "T0001")
    result = submit_session_handoff(tmp_path, envelope_path=envelope_path)

    assert result.role_name == "developer"
    assert result.result_path.exists()


def test_handoff_correction_rejects_product_file_changes(tmp_path: Path) -> None:
    _setup_tree(tmp_path)
    invocations = 0

    def on_invoke(call: AgentCall) -> None:
        nonlocal invocations
        invocations += 1
        if invocations == 2:
            (call.root / "unexpected.txt").write_text("not allowed\n")

    provider = MockProvider(write_handoff=False, on_invoke=on_invoke)

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"default": provider},
        handoff_correction=True,
    )

    assert result.exit_code == 1
    assert result.errors[0].phase == "handoff_correction"
    assert "unexpected.txt" in result.errors[0].message
    assert invocations == 2


def test_handoff_correction_can_check_assigned_acceptance_criterion(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    task = _write_task(tmp_path, "T0001", "First")
    invocations = 0

    def on_invoke(call: AgentCall) -> None:
        nonlocal invocations
        invocations += 1
        envelope_path = Path(call.environment["DEVLAB_SESSION_ENVELOPE"])
        candidate = envelope_path.with_name("handoff-candidate.toml")
        candidate.write_text(
            'schema_version = 1\noutcome = "completed"\n'
            'commit_message = "Finish task"\n'
            'done = ["Implemented task"]\nchanged_artifacts = []\n'
            "open_issues = []\naddressed_findings = []\n"
            'next_session_hint = "Review."\n'
        )
        if invocations == 2:
            complete_acceptance(call.root, "T0001")
            submit_session_handoff(call.root, envelope_path=envelope_path)

    provider = MockProvider(write_handoff=False, on_invoke=on_invoke)

    result = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"default": provider},
        handoff_correction=True,
    )

    assert result.exit_code == 0
    assert invocations == 2
    assert 'status = "in_review"' in task.read_text()


def test_repeated_non_advancing_developer_stops_after_one_recovery(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(tmp_path, "T0001", "First")

    def on_invoke(call: AgentCall) -> None:
        envelope_path = Path(call.environment["DEVLAB_SESSION_ENVELOPE"])
        envelope_path.with_name("handoff-candidate.toml").write_text(
            'schema_version = 1\noutcome = "failed"\n'
            'commit_message = "Unable to progress"\n'
            'done = ["Inspected task"]\nchanged_artifacts = []\n'
            'open_issues = ["No implementation progress"]\n'
            "addressed_findings = []\n"
            'next_session_hint = "Retry once."\n'
        )
        submit_session_handoff(call.root, envelope_path=envelope_path)

    provider = MockProvider(write_handoff=False, on_invoke=on_invoke)

    result = run_loop(
        tmp_path,
        max_sessions=3,
        agent_providers={"default": provider},
    )

    assert result.stop_reason == RunStopReason.DEVELOPER_NON_ADVANCING
    assert result.sessions_run == 2
    assert len(provider.calls) == 2
    assert "## Bounded Recovery" in provider.calls[1].session_prompt


def test_repeated_validation_failure_stops_after_one_developer_recovery(
    tmp_path: Path,
) -> None:
    _setup_tree(tmp_path)
    (tmp_path / DESIGN_PLAN).write_text("# Design\n")
    _write_task(tmp_path, "T0001", "First", validation=["false"])

    def on_invoke(call: AgentCall) -> None:
        complete_acceptance(call.root, "T0001")

    provider = MockProvider(on_invoke=on_invoke)

    result = run_loop(
        tmp_path,
        max_sessions=3,
        agent_providers={"default": provider},
    )

    assert result.stop_reason == RunStopReason.VALIDATION_FAILED
    assert result.sessions_run == 2
    assert len(provider.calls) == 2
    assert "## Validation Recovery" in provider.calls[1].session_prompt
    task = FileTaskTracker(tmp_path).get("T0001")
    assert task.status == TaskStatus.CHANGES_REQUESTED
    assert not task.acceptance_criteria_complete


class TestTimestamp:
    def test_format(self) -> None:
        ts = _timestamp()
        assert len(ts) == 15
        assert ts[8] == "T"

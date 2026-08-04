from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import sys
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from devlab._logging import logger
from devlab.agent_config import (
    ResolvedAgentConfig,
    find_agent_executable_problems,
    format_resolved_agent_config,
    load_agent_configuration,
)
from devlab.agents import (
    AgentInvocation,
    AgentProvider,
    AgentResult,
    ProviderError,
    provider_for_role,
)
from devlab.clarification_ops import (
    apply_validated_clarification_answer,
)
from devlab.clarifications import (
    Clarification,
    clarification_file_edit_path_forbidden,
    expected_file_edit_paths,
    option_text,
)
from devlab.environment import (
    EnvironmentCommandError,
    EnvironmentManager,
    ValidationRun,
    run_validation_commands,
)
from devlab.executable_config import ExecutableConfigSnapshot
from devlab.generations import active_generation, archive_active_generation, has_active_plan
from devlab.git import VersionControlError, run_git
from devlab.handoffs import (
    DEVLAB_PYTHON_ENV,
    HANDOFF_CANDIDATE_FILE,
    HANDOFF_FILE,
    MAX_SUBMISSION_ATTEMPTS,
    SESSION_ENVELOPE_ENV,
    SESSION_ENVELOPE_FILE,
    SESSION_RESULT_FILE,
    Handoff,
    HandoffCandidate,
    HandoffError,
    HandoffFailureReason,
    HandoffSubmissionError,
    SessionEnvelope,
    active_session_envelope,
    load_session_envelope,
    load_session_result,
    parse_handoff,
    parse_handoff_candidate,
    publish_session_result,
    record_submission_attempt,
    submission_attempt_count,
    write_session_envelope,
)
from devlab.profiles import (
    Profile,
    ProfileNotFoundError,
    effective_validation,
    load_profile,
    profile_from_snapshot,
)
from devlab.prompt_resources import read_prompt_resource
from devlab.prompts import (
    build_base_prompt,
    build_clarification_resolver_prompt,
    build_session_prompt,
)
from devlab.roles import ROLES, RoleConfig
from devlab.session_logging import session_finish_context, session_start_context
from devlab.spec_reconciliation import (
    SpecReconciliationStatus,
    inspect_spec_reconciliation,
)
from devlab.task_tracker import DEVELOPABLE_STATUSES, Task, TaskStatus
from devlab.version_control import (
    assert_clean_worktree,
    commit_all,
    ensure_git_repository,
)
from devlab.version_control import (
    tag as create_git_tag,
)
from devlab.workflow_events import append_workflow_event, load_workflow_events
from devlab.workflow_state import (
    ResumeState,
    WorkflowState,
    clear_resume_state,
    load_workflow_state,
    set_resume_state,
    update_workflow_state,
)
from devlab.workspace import (
    AGENT_LOG_DIR,
    ARTIFACTS_DIR,
    HISTORY_DIR,
    Workspace,
    WorkspaceSnapshot,
)

DEFAULT_PROJECT_ROOT = Path.cwd()
CLARIFICATION_RESOLVER_ROLE = "clarification-resolver"
CLARIFICATION_MODES = {"operator", "agent"}

SessionProgressCallback = Callable[[str, int, str], None]


@dataclasses.dataclass(frozen=True)
class SessionError:
    """Actionable diagnostic associated with an orchestrator stop."""

    phase: str
    message: str
    exit_code: int


class RunStopReason(StrEnum):
    """Stable reason why one bounded orchestrator invocation stopped."""

    WORKFLOW_COMPLETE = "workflow_complete"
    COMMAND_COMPLETE = "command_complete"
    SESSION_LIMIT = "session_limit"
    CLARIFICATION_BLOCKED = "clarification_blocked"
    NO_ELIGIBLE_ROLE = "no_eligible_role"
    DEVELOPER_NON_ADVANCING = "developer_non_advancing"
    TASK_CONTRACT_INVALID = "task_contract_invalid"
    VALIDATION_FAILED = "validation_failed"
    ERROR = "error"


@dataclasses.dataclass(frozen=True)
class RunResult:
    """Outcome of a run_loop execution.

    ``stop_reason`` is the authoritative outcome. ``completed`` remains for
    compatibility and is true only for a terminal workflow or command boundary.
    """

    sessions_run: int
    completed: bool
    exit_code: int
    errors: tuple[SessionError, ...]
    stop_reason: RunStopReason


def _error_result(
    sessions_run: int,
    error: SessionError,
    *additional: SessionError,
    reason: RunStopReason = RunStopReason.ERROR,
) -> RunResult:
    return RunResult(
        sessions_run,
        False,
        error.exit_code,
        (error, *additional),
        reason,
    )


def _stop_result(
    sessions_run: int,
    reason: RunStopReason,
    errors: tuple[SessionError, ...] = (),
) -> RunResult:
    completed = reason in {
        RunStopReason.WORKFLOW_COMPLETE,
        RunStopReason.COMMAND_COMPLETE,
    }
    return RunResult(sessions_run, completed, 0, errors, reason)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _agent_invocation_id(session_number: int, role_name: str) -> str:
    return f"{_timestamp()}_{session_number:03d}_{role_name}"


def _agent_log_path(root: Path, invocation_id: str, suffix: str) -> Path:
    return root / AGENT_LOG_DIR / f"{invocation_id}.{suffix}"


@dataclasses.dataclass(frozen=True)
class SessionContext:
    """Per-session log paths and identity, built once per loop iteration."""

    root: Path
    session_number: int
    role_name: str
    invocation_id: str
    stdout_log: Path
    stderr_log: Path
    base_prompt_log: Path | None
    session_prompt_log: Path | None

    def build_invocation(
        self, base_prompt: str, session_prompt: str
    ) -> AgentInvocation:
        envelope = self.root / ARTIFACTS_DIR / self.role_name / SESSION_ENVELOPE_FILE
        return AgentInvocation(
            root=self.root,
            role_name=self.role_name,
            system_prompt=base_prompt,
            session_prompt=session_prompt,
            invocation_id=self.invocation_id,
            stdout_log=self.stdout_log,
            stderr_log=self.stderr_log,
            environment={
                SESSION_ENVELOPE_ENV: envelope.as_posix(),
                # Preserve a virtual-environment symlink: resolving it can bypass
                # that environment's installed DevLab package.
                DEVLAB_PYTHON_ENV: str(Path(sys.executable).absolute()),
            },
        )

    def log_resolved_config(self, config: ResolvedAgentConfig) -> Path:
        path = _agent_log_path(self.root, self.invocation_id, "config.toml")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = format_resolved_agent_config(config)
        text += f'stdout_log = "{self.stdout_log.as_posix()}"\n'
        text += f'stderr_log = "{self.stderr_log.as_posix()}"\n'
        if self.base_prompt_log is not None:
            text += f'base_prompt_log = "{self.base_prompt_log.as_posix()}"\n'
        if self.session_prompt_log is not None:
            text += f'session_prompt_log = "{self.session_prompt_log.as_posix()}"\n'
        path.write_text(text)
        return path

    def write_prompt_logs(self, base_prompt: str, session_prompt: str) -> None:
        if self.base_prompt_log is None or self.session_prompt_log is None:
            return
        self.base_prompt_log.parent.mkdir(parents=True, exist_ok=True)
        self.base_prompt_log.write_text(base_prompt)
        self.session_prompt_log.parent.mkdir(parents=True, exist_ok=True)
        self.session_prompt_log.write_text(session_prompt)

    def write_session_metadata(self, metadata: SessionMetadata) -> Path:
        path = _agent_log_path(self.root, self.invocation_id, "metadata.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataclasses.asdict(metadata), indent=2) + "\n")
        return path


@dataclasses.dataclass(frozen=True)
class SessionMetadata:
    invocation_id: str
    session_number: int
    role_name: str
    provider: str
    model: str
    return_code: int
    failure_kind: str
    duration_seconds: float | None
    task_id: str
    provider_version: str = ""
    executable_config_digest: str = ""
    executable_config_authorization: str = ""
    progress: str = ""


class SessionProgress(StrEnum):
    """Observed repository/workflow effect of one accepted role session."""

    PRODUCT_CHANGE = "product_change"
    WORKFLOW_ADVANCE = "workflow_advance"
    LEGITIMATE_STOP = "legitimate_stop"
    NON_ADVANCING = "non_advancing"


@dataclasses.dataclass(frozen=True)
class SessionProgressBaseline:
    tasks: dict[str, tuple[TaskStatus, bool, bool, str]]
    milestones: dict[str, object]
    workflow_state: WorkflowState
    findings: tuple[object, ...]


@dataclasses.dataclass(frozen=True)
class SessionRoute:
    """Trusted workflow identity selected for one role session."""

    role_name: str
    task: Task | None = None
    milestone_id: str | None = None

    @property
    def task_id(self) -> str | None:
        return self.task.id if self.task is not None else None


def _build_session_context(
    root: Path,
    session_number: int,
    role_name: str,
    *,
    retain_prompts: bool,
) -> SessionContext:
    invocation_id = _agent_invocation_id(session_number, role_name)
    return SessionContext(
        root=root,
        session_number=session_number,
        role_name=role_name,
        invocation_id=invocation_id,
        stdout_log=_agent_log_path(root, invocation_id, "stdout.log"),
        stderr_log=_agent_log_path(root, invocation_id, "stderr.log"),
        base_prompt_log=(
            _agent_log_path(root, invocation_id, "base-prompt.md")
            if retain_prompts
            else None
        ),
        session_prompt_log=(
            _agent_log_path(root, invocation_id, "session-prompt.md") if retain_prompts else None
        ),
    )


def _select_session_route(
    snapshot: WorkspaceSnapshot, role_name: str
) -> SessionRoute:
    milestone_id = (
        snapshot.select_integration_milestone()
        if role_name == "integrator"
        else snapshot.select_architecture_review_milestone()
        if role_name == "architect"
        else None
    )
    return SessionRoute(
        role_name=role_name,
        task=_task_for_role(snapshot, role_name),
        milestone_id=milestone_id,
    )


# ---------------------------------------------------------------------------
# Session invocation
# ---------------------------------------------------------------------------


def invoke_session(
    invocation: AgentInvocation,
    *,
    agent_provider: AgentProvider,
) -> AgentResult:
    """Invoke an agent session through the configured provider."""
    logger.info("Invoking %s session", invocation.role_name)
    result = agent_provider.invoke(invocation)
    duration = result.duration_seconds
    duration_info = f" duration={duration:.1f}s" if duration is not None else ""
    logger.info(
        "%s session exited with code %s%s",
        invocation.role_name, result.return_code, duration_info,
    )
    return result


# ---------------------------------------------------------------------------
# Post-session processing
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class HandoffSubmissionResult:
    """Accepted result and paths published by an in-session submission."""

    session_id: str
    role_name: str
    result_path: Path
    handoff_path: Path


def submit_session_handoff(
    root: Path,
    *,
    envelope_path: Path | None = None,
) -> HandoffSubmissionResult:
    """Validate and publish the active session's candidate without workflow mutation."""
    root = root.resolve()
    resolved_envelope = active_session_envelope(root, envelope_path)
    try:
        resolved_envelope.relative_to(root)
    except ValueError as exc:
        raise HandoffError("session envelope must be inside the target workspace") from exc
    envelope = load_session_envelope(resolved_envelope)
    if envelope.role not in ROLES:
        raise HandoffError(f"session envelope has unknown role {envelope.role!r}")
    if resolved_envelope.parent.name != envelope.role:
        raise HandoffError("session envelope role does not match its artifact directory")
    result_path = resolved_envelope.with_name(SESSION_RESULT_FILE)
    if result_path.exists():
        raise HandoffError("this session already has an accepted result")
    if submission_attempt_count(resolved_envelope) >= MAX_SUBMISSION_ATTEMPTS:
        raise HandoffError(
            f"session reached the maximum of {MAX_SUBMISSION_ATTEMPTS} handoff submissions"
        )

    try:
        candidate = parse_handoff_candidate(
            resolved_envelope.with_name(HANDOFF_CANDIDATE_FILE), envelope.role
        )
        handoff_path = resolved_envelope.with_name(HANDOFF_FILE)
        handoff = candidate.as_handoff(handoff_path, envelope.role)
        snapshot = Workspace(root).snapshot
        validate_handoff(handoff, snapshot)
        if envelope.role == "developer" and candidate.outcome == "completed":
            _validate_completed_developer_candidate(snapshot, envelope, candidate)
        if envelope.role == "planner" and not envelope.allow_active_task_replacement:
            current_ids = {task.id for task in snapshot.list_tasks()}
            deleted = sorted(set(envelope.protected_active_tasks) - current_ids)
            if deleted:
                raise HandoffError(
                    "planner deleted active task file(s): " + ", ".join(deleted),
                    reason=HandoffFailureReason.SEMANTIC_CONFLICT,
                )
        if (
            envelope.role == "planner"
            and envelope.incremental_planning_required
            and not candidate.planning_complete
            and not _has_actionable_or_planned_work(snapshot)
        ):
            raise HandoffError(
                "planner was invoked because the backlog was exhausted while "
                ".devlab/workflow.toml has planning.complete = false, but it "
                "neither created new durable work nor reported planning_complete = true",
                reason=HandoffFailureReason.SEMANTIC_CONFLICT,
            )
    except HandoffSubmissionError as exc:
        record_submission_attempt(
            resolved_envelope, accepted=False, issues=exc.issues
        )
        raise
    except HandoffError as exc:
        record_submission_attempt(
            resolved_envelope, accepted=False, issues=(str(exc),)
        )
        raise HandoffSubmissionError((str(exc),), reason=exc.reason) from exc
    publish_session_result(resolved_envelope, envelope, candidate)
    record_submission_attempt(resolved_envelope, accepted=True)
    return HandoffSubmissionResult(
        session_id=envelope.session_id,
        role_name=envelope.role,
        result_path=result_path,
        handoff_path=handoff_path,
    )


def _validate_completed_developer_candidate(
    snapshot: WorkspaceSnapshot,
    envelope: SessionEnvelope,
    candidate: HandoffCandidate,
) -> None:
    """Require a completed developer result to satisfy its task postconditions."""
    if candidate.open_issues:
        raise HandoffError(
            "completed developer result must not report open issues; use outcome "
            "failed or needs_clarification",
            reason=HandoffFailureReason.SEMANTIC_CONFLICT,
        )
    if not envelope.task:
        raise HandoffError(
            "completed developer session has no assigned task",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    task = next((task for task in snapshot.list_tasks() if task.id == envelope.task), None)
    if task is None:
        raise HandoffError(
            f"completed developer session references unknown task {envelope.task}",
            reason=HandoffFailureReason.REFERENCE,
        )
    if task.status not in DEVELOPABLE_STATUSES:
        raise HandoffError(
            f"assigned task {task.id} is not developable (status={task.status.value})",
            reason=HandoffFailureReason.SEMANTIC_CONFLICT,
        )
    if task.acceptance_criteria_complete:
        return
    unchecked = task.unchecked_acceptance_criteria
    detail = "; ".join(criterion or "<empty criterion>" for criterion in unchecked)
    if not detail:
        detail = "task has no complete Acceptance Criteria checklist"
    raise HandoffError(
        f"completed developer result left acceptance criteria incomplete for "
        f"{task.id}: {detail}",
        reason=HandoffFailureReason.SEMANTIC_CONFLICT,
    )


def validate_handoff(
    handoff: Handoff,
    snapshot: WorkspaceSnapshot,
) -> None:
    if "unrecoverable" in handoff.open_issues.lower():
        raise HandoffError(
            "handoff reports an unrecoverable issue",
            reason=HandoffFailureReason.SEMANTIC_CONFLICT,
        )
    if handoff.role_name == "planner":
        planner_error = _validate_planner_addressed_findings(snapshot, handoff)
        if planner_error:
            raise HandoffError(
                planner_error, reason=HandoffFailureReason.REFERENCE
            )
    if handoff.role_name == "reviewer":
        reviewer_error = _validate_reviewer_outcome(snapshot, handoff)
        if reviewer_error:
            raise HandoffError(
                reviewer_error, reason=HandoffFailureReason.SEMANTIC_CONFLICT
            )


def archive_handoff(root: Path, role_name: str) -> Path:
    src = root / ARTIFACTS_DIR / role_name / "handoff.md"
    history = root / HISTORY_DIR
    history.mkdir(parents=True, exist_ok=True)
    timestamp = _timestamp()
    dest = history / f"{timestamp}_{role_name}_handoff.md"
    counter = 2
    while dest.exists():
        dest = history / f"{timestamp}_{counter}_{role_name}_handoff.md"
        counter += 1
    shutil.copy2(src, dest)
    result_src = src.with_name(SESSION_RESULT_FILE)
    if result_src.exists():
        result_dest = dest.with_name(dest.name.removesuffix("_handoff.md") + "_result.toml")
        shutil.copy2(result_src, result_dest)
    attempts_src = src.with_name("submission-attempts.jsonl")
    if attempts_src.exists():
        attempts_dest = dest.with_name(
            dest.name.removesuffix("_handoff.md") + "_submission-attempts.jsonl"
        )
        shutil.copy2(attempts_src, attempts_dest)
    return dest


def close_task(workspace: Workspace, task_path: Path, role_name: str = "reviewer") -> None:
    task = workspace.tasks().from_path(task_path)
    task.close()
    logger.info("Task %s closed by %s; status set to closed", task.path.name, role_name)
    task.resolve_addressed_findings()


def _validate_planner_addressed_findings(snapshot: WorkspaceSnapshot, handoff: Handoff) -> str:
    task_by_id = {task.id: task for task in snapshot.list_tasks()}
    finding_by_id = {finding.id: finding for finding in snapshot.list_findings()}
    for finding_id, task_ids in handoff.addressed_finding_tasks().items():
        if finding_id not in finding_by_id:
            return f"planner Addressed Findings references unknown finding {finding_id}"
        for task_id in task_ids:
            task = task_by_id.get(task_id)
            if task is None:
                return f"planner Addressed Findings references unknown task {task_id}"
            if finding_id not in task.addresses_findings:
                return (
                    f"planner Addressed Findings maps {finding_id} to {task_id}, "
                    f"but {task_id} does not list it in addresses_findings"
                )
    return ""


def _validate_reviewer_outcome(snapshot: WorkspaceSnapshot, handoff: Handoff) -> str:
    task = snapshot.select_next_review_task()
    if task is None:
        return "reviewer handoff has no task awaiting review"
    return ""


def _mark_addressed_findings_planned(workspace: Workspace, handoff: Handoff) -> None:
    findings = workspace.findings()
    for finding_id in handoff.addressed_finding_tasks():
        finding = findings.get(finding_id)
        finding.mark_planned()
        finding.resolve_if_complete()


@dataclasses.dataclass(frozen=True)
class PlanningStateUpdate:
    last_planned_spec_commit: str | None = None


def _apply_planner_workflow_state(
    workspace: Workspace,
    handoff: Handoff,
    *,
    planning_update: PlanningStateUpdate | None = None,
) -> None:
    if handoff.role_name != "planner":
        return
    planning_complete = handoff.planning_complete
    if planning_complete is None:
        raise HandoffError("planner handoff is missing planning completion state")
    update_workflow_state(
        workspace.root,
        planning_complete=planning_complete,
        last_planned_spec_commit=(
            planning_update.last_planned_spec_commit if planning_update else None
        ),
    )
    workspace.did_mutate()
    logger.info(
        "Planning completion set to %s by planner handoff",
        str(planning_complete).lower(),
    )

@dataclasses.dataclass(frozen=True)
class ProcessResult:
    integrated_milestone: str | None = None
    clarification_id: str | None = None


def process_handoff(
    handoff: Handoff,
    workspace: Workspace,
    *,
    command: str = "",
    session_id: str = "",
    task_id: str | None = None,
    milestone_id: str | None = None,
) -> ProcessResult:
    archived = archive_handoff(workspace.root, handoff.role_name)
    logger.info("Handoff archived to %s", archived.name)

    clarification_request = handoff.clarification_request
    if clarification_request is not None:
        clarification = workspace.clarifications().create(
            title=clarification_request.title,
            asking_role=handoff.role_name,
            session_id=session_id,
            scope=clarification_request.scope,
            blocks=clarification_request.blocks,
            answer_shape=clarification_request.answer_shape,
            recommended_option=clarification_request.recommended_option,
            body=_clarification_body(clarification_request.title, clarification_request.details),
        )
        set_resume_state(
            workspace.root,
            ResumeState(
                blocked_by=clarification.id,
                command=command,
                role=handoff.role_name,
                task=task_id or "",
                milestone=milestone_id or "",
            ),
        )
        workspace.did_mutate()
        append_workflow_event(
            workspace.root,
            "clarification_requested",
            clarification=clarification.id,
            role=handoff.role_name,
            command=command,
            task=task_id or "",
            milestone=milestone_id or "",
        )
        logger.info(
            "Workflow stopped: operator clarification required: %s %s",
            clarification.id,
            clarification.title,
        )
        return ProcessResult(clarification_id=clarification.id)

    if handoff.role_name == "architect":
        milestone = workspace.snapshot.select_architecture_review_milestone()
        if milestone is not None:
            if handoff.has_open_issues:
                workspace.findings().create_from_handoff(
                    source="architect",
                    milestone=milestone,
                    handoff_path=archived,
                )
                logger.info("Architecture review reported open issues; finding created")
            workspace.milestones().get(milestone).mark_architecture_reviewed(archived)
            logger.info("Milestone %s marked architecture-reviewed", milestone)
        return ProcessResult()
    elif handoff.role_name == "developer":
        task = workspace.snapshot.select_next_development_task()
        if task and task.acceptance_criteria_complete:
            task_handle = workspace.tasks().get(task.id)
            task_handle.mark_in_review()
            logger.info(
                "Task %s completed by developer; status set to in_review",
                task_handle.path.name,
            )
        return ProcessResult()
    elif handoff.role_name == "planner":
        _mark_addressed_findings_planned(workspace, handoff)
        return ProcessResult()
    elif handoff.role_name == "reviewer":
        task = workspace.snapshot.select_next_review_task()
        if task and task.review_approved and not handoff.has_open_issues:
            task_handle = workspace.tasks().get(task.id)
            task_handle.close()
            logger.info(
                "Task %s closed by %s; status set to closed",
                task_handle.path.name,
                handoff.role_name,
            )
            task_handle.resolve_addressed_findings()
        elif task:
            task_handle = workspace.tasks().get(task.id)
            task_handle.mark_changes_requested()
            if not handoff.has_open_issues and not task.review_approved:
                logger.warning(
                    "Task %s: reviewer reports no open issues but review approval "
                    "checkbox is missing; defaulting to changes_requested",
                    task_handle.path.name,
                )
            elif handoff.has_open_issues and task.review_approved:
                logger.warning(
                    "Task %s: reviewer approved task but handoff reports open issues; "
                    "defaulting to changes_requested",
                    task_handle.path.name,
                )
            else:
                logger.info(
                    "Task %s rejected by reviewer; status set to changes_requested",
                    task_handle.path.name,
                )
        return ProcessResult()
    elif handoff.role_name == "integrator":
        milestone = workspace.snapshot.select_integration_milestone()
        if handoff.has_open_issues:
            finding = workspace.findings().create_from_handoff(
                source="integrator",
                milestone=milestone,
                handoff_path=archived,
            )
            if milestone is not None:
                workspace.milestones().get(milestone).mark_integration_failed(finding.id)
            logger.info(
                "Integration reported open issues; finding created for planner follow-up"
            )
            return ProcessResult()
        if milestone is not None:
            workspace.milestones().get(milestone).mark_integrated(archived)
            logger.info("Milestone %s marked integrated", milestone)
            return ProcessResult(integrated_milestone=milestone)
    return ProcessResult()


def _clarification_body(title: str, details: str) -> str:
    normalized_lines: list[str] = []
    fence: str | None = None
    headings = {"Context", "Question", "Options", "Expected Answer", "Expected File Edits"}
    for line in details.strip().splitlines():
        stripped = line.lstrip()
        marker = stripped[:3] if stripped.startswith(("```", "~~~")) else None
        if marker is not None:
            fence = None if fence == marker else marker if fence is None else fence
        if fence is None and line.startswith("### ") and line[4:].strip() in headings:
            line = "## " + line[4:]
        normalized_lines.append(line)
    normalized = "\n".join(normalized_lines)
    return f"# {title}\n\n{normalized}\n"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _task_for_role(snapshot: WorkspaceSnapshot, role_name: str) -> Task | None:
    if role_name == "developer":
        return snapshot.select_next_development_task()
    if role_name == "reviewer":
        return snapshot.select_next_review_task()
    return None


def _commit_prefix(snapshot: WorkspaceSnapshot, role_name: str) -> str:
    task = _task_for_role(snapshot, role_name)
    if task is not None:
        return task.id
    return role_name


def _fallback_commit_description(snapshot: WorkspaceSnapshot, role_name: str) -> str:
    task = _task_for_role(snapshot, role_name)
    if task is not None:
        return task.title
    return f"Complete {role_name} session"


def _commit_message(snapshot: WorkspaceSnapshot, handoff: Handoff) -> str:
    description = " ".join(handoff.commit_message.split())
    if not description:
        description = _fallback_commit_description(snapshot, handoff.role_name)
    return f"[{_commit_prefix(snapshot, handoff.role_name)}] {description}"


def _milestone_tag_name(milestone: str) -> str:
    return f"devlab/milestone/{milestone}"


def _environment_for_session(
    root: Path,
    snapshot: WorkspaceSnapshot,
    role_name: str,
    profiles: dict[str, Profile] | None = None,
) -> EnvironmentManager:
    task = _task_for_role(snapshot, role_name)
    profile_id = task.profile if task is not None else None
    profile = (
        profile_from_snapshot(profiles, profile_id, root=root)
        if profiles is not None
        else load_profile(root, profile_id)
    )
    return EnvironmentManager(root, profile.environment)




def _validate_exhausted_backlog_planner_progress(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
    role_name: str,
    *,
    reported_planning_complete: bool | None = None,
) -> str | None:
    if role_name != "planner" or not _needs_incremental_planning(before):
        return None
    if reported_planning_complete or after.workflow_state().planning.complete:
        return None
    if _has_actionable_or_planned_work(after):
        return None
    return (
        "planner was invoked because the backlog was exhausted while "
        ".devlab/workflow.toml has planning.complete = false, but it neither created "
        "new durable work nor reported planning_complete = true"
    )


def _validate_planner_preserved_active_tasks(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
    role_name: str,
    *,
    fresh_generation_plan: bool,
) -> str | None:
    if role_name != "planner" or fresh_generation_plan:
        return None
    before_tasks = {task.id: task for task in before.current_generation_tasks()}
    if not before_tasks:
        return None
    after_task_ids = {task.id for task in after.current_generation_tasks()}
    deleted_ids = sorted(set(before_tasks) - after_task_ids)
    if not deleted_ids:
        return None
    deleted = ", ".join(
        f"{task_id} ({before_tasks[task_id].path.relative_to(before.root).as_posix()})"
        for task_id in deleted_ids
    )
    return f"planner deleted active task file(s): {deleted}"


def _needs_incremental_planning(snapshot: WorkspaceSnapshot) -> bool:
    return snapshot.all_milestones_complete() and not snapshot.workflow_state().planning.complete


def _has_actionable_or_planned_work(snapshot: WorkspaceSnapshot) -> bool:
    return any(
        task.status != TaskStatus.CLOSED for task in snapshot.current_generation_tasks()
    )



def _failed_session_cleanup_hint() -> str:
    return (
        "Inspect logs/artifacts, then run 'devlab clean-failed-session' to remove "
        "untracked failed-session diagnostics before retrying."
    )



def _preflight_agent_executable(
    role_name: str, config: ResolvedAgentConfig
) -> SessionError | None:
    problems = find_agent_executable_problems({role_name: config}, role_names=(role_name,))
    if not problems:
        return None
    problem = problems[0]
    exit_code = 1 if problem.empty_command else 127
    return SessionError(
        "agent_configuration",
        f"{role_name} {problem.format_message()}; edit .devlab/config/agents.toml "
        "or install the configured agent CLI",
        exit_code,
    )



def _agent_error_message(
    ctx: SessionContext, result: AgentResult, config_log: Path | None
) -> str:
    details = [
        f"{ctx.role_name} session failed ({result.failure_kind})",
        f"exit_code={result.return_code}",
    ]
    if result.message:
        details.append(result.message)
    if result.command:
        details.append("command=" + " ".join(result.command))
    if result.duration_seconds is not None:
        details.append(f"duration={result.duration_seconds:.1f}s")
    if result.timeout_seconds is not None:
        details.append(f"timeout_seconds={result.timeout_seconds}")
    details.extend(_log_path_details(ctx.stdout_log, ctx.stderr_log, config_log))
    details.extend(_log_command_details(ctx.stdout_log, ctx.stderr_log, config_log))
    return "; ".join(details)


def _handoff_error_message(
    ctx: SessionContext, error: str, config_log: Path | None
) -> str:
    details = [error]
    details.extend(_log_path_details(ctx.stdout_log, ctx.stderr_log, config_log))
    details.extend(_log_command_details(ctx.stdout_log, ctx.stderr_log, config_log))
    return "; ".join(details)


def _log_path_details(
    stdout_log: Path | None, stderr_log: Path | None, config_log: Path | None
) -> list[str]:
    details: list[str] = []
    if stdout_log is not None:
        details.append(f"stdout_log={stdout_log.as_posix()}")
    if stderr_log is not None:
        details.append(f"stderr_log={stderr_log.as_posix()}")
    if config_log is not None:
        details.append(f"config_log={config_log.as_posix()}")
    return details


def _log_command_details(
    stdout_log: Path | None, stderr_log: Path | None, config_log: Path | None
) -> list[str]:
    details: list[str] = []
    if stdout_log is not None:
        details.append(f"stdout_command=cat {stdout_log.as_posix()}")
    if stderr_log is not None:
        details.append(f"stderr_command=cat {stderr_log.as_posix()}")
    if config_log is not None:
        details.append(f"config_command=cat {config_log.as_posix()}")
    return details


def _handoff_correction_snapshot(root: Path, artifacts_dir: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    allowed_artifacts = {
        (artifacts_dir / HANDOFF_CANDIDATE_FILE).relative_to(root).as_posix(),
        (artifacts_dir / HANDOFF_FILE).relative_to(root).as_posix(),
        (artifacts_dir / SESSION_RESULT_FILE).relative_to(root).as_posix(),
        (artifacts_dir / "submission-attempts.jsonl").relative_to(root).as_posix(),
    }
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".git/") or relative.startswith(f"{AGENT_LOG_DIR}/"):
            continue
        if relative in allowed_artifacts:
            continue
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _changed_snapshot_paths(
    before: dict[str, str], after: dict[str, str]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            path
            for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        )
    )


def _attempt_handoff_correction(
    ctx: SessionContext,
    agent_provider: AgentProvider,
    issues: tuple[str, ...],
    *,
    semantic_task: Task | None = None,
) -> SessionError | None:
    """Run one correction-only invocation and enforce narrow edit isolation."""
    artifacts_dir = ctx.root / ARTIFACTS_DIR / ctx.role_name
    before = _handoff_correction_snapshot(ctx.root, artifacts_dir)
    task_before = semantic_task.path.read_text() if semantic_task is not None else None
    correction_id = ctx.invocation_id + "_handoff-correction"
    correction_ctx = dataclasses.replace(
        ctx,
        invocation_id=correction_id,
        stdout_log=_agent_log_path(ctx.root, correction_id, "stdout.log"),
        stderr_log=_agent_log_path(ctx.root, correction_id, "stderr.log"),
        base_prompt_log=None,
        session_prompt_log=None,
    )
    diagnostics = "\n".join(f"- {issue}" for issue in issues) or "- No candidate was submitted."
    if semantic_task is None:
        system_prompt = (
            "You are repairing only the result submission for a completed DevLab role "
            "session. Do not redo role work or edit product, task, milestone, finding, "
            "workflow, or configuration files."
        )
        edit_instruction = (
            f"Edit only {ARTIFACTS_DIR}/{ctx.role_name}/{HANDOFF_CANDIDATE_FILE}"
        )
    else:
        relative_task = semantic_task.path.relative_to(ctx.root).as_posix()
        system_prompt = (
            "You are repairing only the completion bookkeeping for a finished DevLab "
            "developer session. You may check acceptance-criteria boxes in the assigned "
            "task and repair the result candidate. Do not change criterion text, product "
            "code, task metadata/status, requested changes, plans, milestones, findings, "
            "workflow state, or configuration."
        )
        edit_instruction = (
            f"Edit only acceptance-criteria checkboxes in {relative_task} and "
            f"{ARTIFACTS_DIR}/{ctx.role_name}/{HANDOFF_CANDIDATE_FILE}"
        )
    session_prompt = (
        f"The completed {ctx.role_name} session did not publish an accepted result.\n\n"
        f"Validation diagnostics:\n{diagnostics}\n\n"
        f"{edit_instruction}, then "
        "run `\"$DEVLAB_PYTHON\" -m devlab.cli session handoff submit`. "
        "Finish only after DevLab reports "
        "Accepted. Existing workspace changes are evidence; do not modify them."
    )
    result = invoke_session(
        correction_ctx.build_invocation(system_prompt, session_prompt),
        agent_provider=agent_provider,
    )
    after = _handoff_correction_snapshot(ctx.root, artifacts_dir)
    changed = set(_changed_snapshot_paths(before, after))
    if semantic_task is not None:
        relative_task = semantic_task.path.relative_to(ctx.root).as_posix()
        if relative_task in changed:
            task_after = semantic_task.path.read_text()
            if task_before is not None and _only_acceptance_boxes_checked(
                task_before, task_after
            ):
                changed.remove(relative_task)
    unexpected = tuple(sorted(changed))
    if unexpected:
        return SessionError(
            "handoff_correction",
            "handoff correction changed forbidden path(s): " + ", ".join(unexpected),
            1,
        )
    if not result.succeeded:
        return SessionError(
            "handoff_correction",
            _agent_error_message(correction_ctx, result, None),
            result.return_code or 1,
        )
    if not (artifacts_dir / SESSION_RESULT_FILE).exists():
        return SessionError(
            "handoff_correction",
            "handoff correction exited without an accepted result",
            1,
        )
    return None


def _only_acceptance_boxes_checked(before: str, after: str) -> bool:
    """Return whether only unchecked Acceptance Criteria boxes became checked."""
    heading = re.compile(r"^## Acceptance Criteria\s*$", re.MULTILINE)
    before_match = heading.search(before)
    after_match = heading.search(after)
    if before_match is None or after_match is None:
        return False

    def split(text: str, match: re.Match[str]) -> tuple[str, str, str]:
        start = match.end()
        next_heading = re.search(r"^##\s+", text[start:], flags=re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(text)
        return text[:start], text[start:end], text[end:]

    before_prefix, before_section, before_suffix = split(before, before_match)
    after_prefix, after_section, after_suffix = split(after, after_match)
    if before_prefix != after_prefix or before_suffix != after_suffix:
        return False
    normalized_after = re.sub(r"^(\s*- )\[[xX]\]", r"\1[ ]", after_section, flags=re.MULTILINE)
    normalized_before = re.sub(r"^(\s*- )\[[xX]\]", r"\1[ ]", before_section, flags=re.MULTILINE)
    if normalized_before != normalized_after or before_section == after_section:
        return False
    before_checked = len(re.findall(r"^\s*- \[[xX]\]", before_section, flags=re.MULTILINE))
    after_checked = len(re.findall(r"^\s*- \[[xX]\]", after_section, flags=re.MULTILINE))
    return after_checked > before_checked


def _build_session_metadata(
    ctx: SessionContext,
    agent_result: AgentResult,
    resolved_agent_configs: dict[str, ResolvedAgentConfig] | None,
    task_id: str | None,
    executable_config: ExecutableConfigSnapshot | None = None,
    progress: SessionProgress | None = None,
) -> SessionMetadata:
    provider = ""
    model = ""
    provider_version = ""
    if resolved_agent_configs is not None and ctx.role_name in resolved_agent_configs:
        config = resolved_agent_configs[ctx.role_name]
        provider = config.provider
        model = config.model
        provider_version = config.provider_version
    return SessionMetadata(
        invocation_id=ctx.invocation_id,
        session_number=ctx.session_number,
        role_name=ctx.role_name,
        provider=provider,
        model=model,
        return_code=agent_result.return_code,
        failure_kind=agent_result.failure_kind,
        duration_seconds=agent_result.duration_seconds,
        task_id=task_id or "",
        provider_version=provider_version,
        executable_config_digest=(
            executable_config.digest if executable_config is not None else ""
        ),
        executable_config_authorization=(
            executable_config.authorization.source.value
            if executable_config is not None
            and executable_config.authorization is not None
            else ""
        ),
        progress=progress.value if progress is not None else "",
    )


def _classify_session_progress(
    root: Path,
    before: SessionProgressBaseline,
    after: WorkspaceSnapshot,
    process_result: ProcessResult,
) -> SessionProgress:
    """Classify progress from Git and durable workflow facts, not handoff claims."""
    if _git_has_product_changes(root):
        return SessionProgress.PRODUCT_CHANGE
    if process_result.clarification_id is not None:
        return SessionProgress.LEGITIMATE_STOP
    after_tasks = {
        task.id: (
            task.status,
            task.acceptance_criteria_complete,
            task.review_approved,
            task.body,
        )
        for task in after.list_tasks()
    }
    after_milestones = {
        milestone.id: milestone for milestone in after.list_milestones()
    }
    if (
        before.tasks != after_tasks
        or before.milestones != after_milestones
        or before.workflow_state != after.workflow_state()
        or before.findings != tuple(after.list_findings())
    ):
        return SessionProgress.WORKFLOW_ADVANCE
    return SessionProgress.NON_ADVANCING


def _session_progress_baseline(snapshot: WorkspaceSnapshot) -> SessionProgressBaseline:
    return SessionProgressBaseline(
        tasks={
            task.id: (
                task.status,
                task.acceptance_criteria_complete,
                task.review_approved,
                task.body,
            )
            for task in snapshot.list_tasks()
        },
        milestones={
            milestone.id: milestone for milestone in snapshot.list_milestones()
        },
        workflow_state=snapshot.workflow_state(),
        findings=tuple(snapshot.list_findings()),
    )


def _git_has_product_changes(root: Path) -> bool:
    try:
        lines = run_git(root, "status", "--porcelain").stdout.splitlines()
    except VersionControlError:
        return False
    for line in lines:
        path = line[3:].split(" -> ")[-1]
        if path and not path.startswith(".devlab/"):
            return True
    return False


def _is_non_advancing_recovery(root: Path, route: SessionRoute) -> bool:
    """Return whether the last accepted session stalled on this exact route."""
    events = load_workflow_events(root)
    for event in reversed(events):
        if event.type != "session_progress":
            continue
        return (
            event.data.get("role") == route.role_name
            and event.data.get("task") == (route.task_id or "")
            and event.data.get("progress") == SessionProgress.NON_ADVANCING.value
        )
    return False


def _recovery_prompt(route: SessionRoute) -> str:
    return (
        "## Bounded Recovery\n\n"
        f"The previous `{route.role_name}` session for task "
        f"`{route.task_id or 'none'}` claimed completion but produced no relevant "
        "product change, workflow transition, or legitimate bounded stop. This is "
        "the single recovery attempt. Inspect the remaining task state and make "
        "concrete progress; another non-advancing result will stop the workflow."
    )


def _latest_validation_failure(root: Path, task_id: str) -> dict[str, object] | None:
    records = sorted((root / ".devlab/verification/tasks" / task_id).glob("*.json"))
    for path in reversed(records):
        try:
            data = json.loads(path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if data.get("source") == "task" and data.get("outcome") in {
            "failed",
            "timeout",
            "infrastructure_error",
        }:
            return data
        return None
    return None


def _validation_recovery_prompt(record: dict[str, object]) -> str:
    commands = record.get("commands")
    detail = "the recorded validation command"
    if isinstance(commands, list) and commands and isinstance(commands[-1], dict):
        command_result = cast("dict[str, object]", commands[-1])
        command = command_result.get("command")
        outcome = command_result.get("outcome")
        if isinstance(command, str) and isinstance(outcome, str):
            detail = f"`{command}` ({outcome})"
    return (
        "## Validation Recovery\n\n"
        f"The previous developer submission failed {detail}. Inspect the durable "
        "validation record and correct the implementation. A repeated deterministic "
        "failure will stop the workflow."
    )


def _resolver_answer_path(root: Path) -> Path:
    return root / ARTIFACTS_DIR / CLARIFICATION_RESOLVER_ROLE / "answer.json"


_RESOLVER_SNAPSHOT_EXCLUSIONS = (
    ".git/",
    f"{AGENT_LOG_DIR}/",
    f"{ARTIFACTS_DIR}/{CLARIFICATION_RESOLVER_ROLE}/",
)


def _resolver_file_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if any(
            relative == prefix.rstrip("/") or relative.startswith(prefix)
            for prefix in _RESOLVER_SNAPSHOT_EXCLUSIONS
        ):
            continue
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _resolver_forbidden_contents(root: Path) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if _resolver_path_forbidden(relative):
            contents[relative] = path.read_bytes()
    return contents


def _resolver_path_forbidden(path: str) -> bool:
    return clarification_file_edit_path_forbidden(path)


def _restore_forbidden_resolver_edits(
    root: Path, changed_paths: set[str], before: dict[str, bytes]
) -> None:
    for relative in sorted(path for path in changed_paths if _resolver_path_forbidden(path)):
        path = root / relative
        original = before.get(relative)
        if original is None:
            if path.is_file() or path.is_symlink():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            path.unlink()
        path.write_bytes(original)


def _validate_resolver_file_edits(
    root: Path,
    clarification: Clarification,
    before: dict[str, str],
    forbidden_before: dict[str, bytes],
    *,
    require_expected: bool,
) -> str | None:
    after = _resolver_file_snapshot(root)
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    allowed = (
        set(expected_file_edit_paths(clarification.body))
        if clarification.answer_shape.value == "file-edit"
        else set()
    )
    missing = allowed - set(after)
    if require_expected and missing:
        joined = ", ".join(sorted(missing))
        return f"clarification resolver did not edit expected path(s): {joined}"
    unexpected = changed - allowed
    if not unexpected:
        return None
    _restore_forbidden_resolver_edits(root, unexpected, forbidden_before)
    joined = ", ".join(sorted(unexpected))
    return (
        "clarification resolver changed paths outside its allowed file-edit set: "
        f"{joined}"
    )


def _resolver_repair_guidance(clarification_id: str, command: str) -> str:
    return (
        f"Clarification {clarification_id} remains pending with its resume pointer. "
        f"Repair the resolver output and rerun `devlab {command} --unattended`, or "
        f"answer it with `devlab clarify answer {clarification_id} --resume`."
    )


def _parse_resolver_answer(root: Path, path: Path, clarification: Clarification) -> str:
    if not path.exists():
        raise HandoffError(
            "clarification resolver did not write "
            f"{path.relative_to(root).as_posix()}"
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise HandoffError("clarification resolver answer.json is invalid JSON") from exc
    if not isinstance(data, dict):
        raise HandoffError("clarification resolver answer.json must contain an object")
    found_id = data.get("clarification_id")
    if found_id != clarification.id:
        raise HandoffError(
            "clarification resolver answer.json clarification_id must be "
            f"{clarification.id!r}"
        )
    answer_shape = clarification.answer_shape.value
    if data.get("answer_shape") != answer_shape:
        raise HandoffError(
            "clarification resolver answer.json answer_shape must be "
            f"{answer_shape!r}"
        )
    if answer_shape == "choice":
        if set(data) != {"clarification_id", "answer_shape", "choice"}:
            raise HandoffError(
                "clarification resolver choice answer.json must contain exactly "
                "clarification_id, answer_shape, and choice"
            )
        choice = data.get("choice")
        if not isinstance(choice, str) or not choice.strip():
            raise HandoffError("clarification resolver answer.json requires non-empty choice")
        answer = option_text(clarification.body, choice)
        if answer is None:
            raise HandoffError(
                f"clarification resolver choice {choice!r} must match one listed option ID"
            )
        return answer
    if set(data) != {"clarification_id", "answer_shape", "answer"}:
        raise HandoffError(
            "clarification resolver answer.json must contain exactly clarification_id, "
            "answer_shape, and answer"
        )
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise HandoffError("clarification resolver answer.json requires non-empty answer")
    return answer.strip()


def _answer_clarification_from_resolver(
    root: Path,
    clarification_id: str,
    answer: str,
    *,
    resolver_session_id: str,
) -> None:
    try:
        apply_validated_clarification_answer(
            root,
            clarification_id,
            answer,
            operator=f"agent:{CLARIFICATION_RESOLVER_ROLE}:{resolver_session_id}",
        )
    except ValueError as exc:
        raise HandoffError(str(exc)) from exc


def _invoke_clarification_resolver(
    root: Path,
    *,
    clarification_id: str,
    session_number: int,
    agent_providers: dict[str, AgentProvider],
    role_agent_providers: dict[str, str] | None,
    blocked_role: str,
    retain_prompts: bool,
    session_progress: SessionProgressCallback | None,
) -> tuple[SessionError | None, bool]:
    workflow_state = load_workflow_state(root)
    if workflow_state.resume is None:
        return SessionError(
            "clarification_resolver",
            "Cannot resolve clarification without an active resume pointer.",
            1,
        ), False
    try:
        clarification = Workspace(root).clarifications().get(clarification_id).read()
    except KeyError:
        return SessionError(
            "clarification_resolver",
            f"Cannot resolve unknown clarification {clarification_id}.",
            1,
        ), False

    artifacts_dir = root / ARTIFACTS_DIR / CLARIFICATION_RESOLVER_ROLE
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    ctx = _build_session_context(
        root,
        session_number,
        CLARIFICATION_RESOLVER_ROLE,
        retain_prompts=retain_prompts,
    )
    base_prompt = read_prompt_resource("role-clarification-resolver.md")
    session_prompt = build_clarification_resolver_prompt(
        Workspace(root).snapshot,
        clarification,
        workflow_state.resume,
    )
    ctx.write_prompt_logs(base_prompt, session_prompt)
    invocation = ctx.build_invocation(base_prompt, session_prompt)
    agent_provider = provider_for_role(blocked_role, agent_providers, role_agent_providers)
    try:
        resolver_files_before = _resolver_file_snapshot(root)
        forbidden_contents_before = _resolver_forbidden_contents(root)
    except OSError as exc:
        return SessionError(
            "clarification_resolver",
            f"Cannot snapshot workspace before clarification resolver: {exc}",
            1,
        ), False

    logger.info("Starting session %s: %s", ctx.session_number, CLARIFICATION_RESOLVER_ROLE)
    _notify_session_progress(
        session_progress, "start", ctx.session_number, CLARIFICATION_RESOLVER_ROLE
    )
    try:
        agent_result = invoke_session(invocation, agent_provider=agent_provider)
    except ProviderError as exc:
        agent_result = AgentResult(
            return_code=1,
            failure_kind="provider_error",
            message=f"agent provider error: {exc}",
        )
    ctx.write_session_metadata(_build_session_metadata(ctx, agent_result, None, None))
    try:
        edit_error = _validate_resolver_file_edits(
            root,
            clarification,
            resolver_files_before,
            forbidden_contents_before,
            require_expected=agent_result.succeeded,
        )
    except OSError as exc:
        edit_error = f"Cannot validate clarification resolver file edits: {exc}"
    if edit_error is not None:
        guidance = _resolver_repair_guidance(
            clarification_id, workflow_state.resume.command
        )
        return SessionError(
            "clarification_resolver", f"{edit_error}. {guidance}", 1
        ), True
    if not agent_result.succeeded:
        message = _agent_error_message(ctx, agent_result, None)
        guidance = _resolver_repair_guidance(
            clarification_id, workflow_state.resume.command
        )
        return SessionError(
            "clarification_resolver",
            f"{message} {guidance}",
            agent_result.return_code or 1,
        ), True

    try:
        answer = _parse_resolver_answer(root, _resolver_answer_path(root), clarification)
        _answer_clarification_from_resolver(
            root,
            clarification_id,
            answer,
            resolver_session_id=ctx.invocation_id,
        )
    except HandoffError as exc:
        message = _resolver_repair_guidance(
            clarification_id, workflow_state.resume.command
        )
        return SessionError("clarification_resolver", f"{exc}. {message}", 1), True

    _notify_session_progress(
        session_progress, "finish", ctx.session_number, CLARIFICATION_RESOLVER_ROLE
    )
    logger.info("Finished session %s: %s", ctx.session_number, CLARIFICATION_RESOLVER_ROLE)
    return None, True


def _dirty_spec_error(paths: tuple[str, ...]) -> SessionError:
    joined = ", ".join(paths)
    return SessionError(
        "spec_reconciliation",
        "specification paths have staged or unstaged changes; commit them before "
        f"running devlab plan: {joined}",
        1,
    )


def _stale_specs_error(status: SpecReconciliationStatus) -> SessionError:
    if not status.baseline_exists:
        message = (
            "Specifications have no recorded devlab plan baseline. "
            "Run devlab plan to reconcile .devlab/specs with workflow state before "
            "continuing."
        )
    else:
        message = (
            "Specifications changed since the last devlab plan baseline. "
            "Run devlab plan to reconcile .devlab/specs with workflow state before "
            "continuing."
        )
    return SessionError("spec_reconciliation", message, 1)


def _command_family(*, planning_only: bool) -> str:
    return "plan" if planning_only else "implement"


def _blocking_clarification_error(snapshot: WorkspaceSnapshot) -> SessionError | None:
    blockers = snapshot.blocking_clarifications()
    if not blockers:
        return None
    first = blockers[0]
    message = (
        "Workflow is blocked by pending operator clarification "
        f"{first.id}: {first.title}. Answer it with "
        f"`devlab clarify answer {first.id} ...` and then run `devlab resume`."
    )
    return SessionError("clarification_required", message, 0)


def _wrong_resume_command_error(
    workflow_state: WorkflowState,
    *,
    requested_command: str,
    revise_plan: bool,
) -> SessionError | None:
    resume = workflow_state.resume
    if resume is None:
        return None
    if resume.command == requested_command:
        return None
    if requested_command == "plan" and revise_plan:
        return None
    message = _resume_guidance(
        resume,
        "The requested plain command is "
        f"`devlab {requested_command}`, but the stored resume route is "
        f"`devlab {resume.command}`.",
        include_wrong_command_repair=True,
    )
    return SessionError("clarification_resume", message, 1)


def _resume_context(resume: ResumeState) -> str:
    details = [f"command=devlab {resume.command}"]
    if resume.role:
        details.append(f"role={resume.role}")
    if resume.task:
        details.append(f"task={resume.task}")
    if resume.milestone:
        details.append(f"milestone={resume.milestone}")
    return ", ".join(details)


def _resume_guidance(
    resume: ResumeState,
    reason: str,
    *,
    include_wrong_command_repair: bool = False,
) -> str:
    message = (
        f"Workflow is waiting to resume after {resume.blocked_by} "
        f"({_resume_context(resume)}). {reason} "
        "Run `devlab resume` to continue the stored route."
    )
    if include_wrong_command_repair:
        message += (
            f" Or explicitly run `devlab {resume.command}`. "
            "If you intended to revise planning instead, run `devlab plan --revise`."
        )
    return message


def _task_by_id(snapshot: WorkspaceSnapshot, task_id: str) -> Task | None:
    for task in snapshot.list_tasks():
        if task.id == task_id:
            return task
    return None


def _resume_validation_error(
    snapshot: WorkspaceSnapshot,
    resume: ResumeState | None,
    *,
    requested_command: str,
    role_name: str | None,
    task_id: str | None,
    milestone_id: str | None,
) -> SessionError | None:
    if resume is None or resume.command != requested_command:
        return None

    def error(reason: str) -> SessionError:
        repair = (
            f"{reason} Run `devlab plan --revise` to reconcile workflow state, "
            f"or supersede the clarification with `devlab clarify supersede "
            f"{resume.blocked_by} --reason ...` if the interrupted work is obsolete."
        )
        return SessionError(
            "clarification_resume",
            _resume_guidance(resume, repair),
            1,
        )

    if resume.role == "developer":
        if not resume.task:
            return error("The resume pointer is missing the interrupted task.")
        task = _task_by_id(snapshot, resume.task)
        if task is None:
            return error(f"Interrupted task {resume.task} no longer exists.")
        if task.status not in {TaskStatus.OPEN, TaskStatus.CHANGES_REQUESTED}:
            return error(
                f"Interrupted task {resume.task} is {task.status.value}, not developable."
            )
        closed_ids = {
            candidate.id
            for candidate in snapshot.list_tasks()
            if candidate.status == TaskStatus.CLOSED
        }
        missing_dependencies = sorted(set(task.depends_on) - closed_ids)
        if missing_dependencies:
            return error(
                f"Interrupted task {resume.task} has unsatisfied dependencies: "
                f"{', '.join(missing_dependencies)}."
            )
        if role_name != resume.role:
            selected = role_name or "no role"
            return error(
                f"Current workflow selection is {selected}, so DevLab will not "
                "resume a different route."
            )
        if task_id != resume.task:
            selected = task_id or "none"
            return error(
                f"Next development task is {selected}, not interrupted task {resume.task}."
            )

    elif resume.role == "reviewer":
        if not resume.task:
            return error("The resume pointer is missing the interrupted task.")
        task = _task_by_id(snapshot, resume.task)
        if task is None:
            return error(f"Interrupted task {resume.task} no longer exists.")
        if task.status != TaskStatus.IN_REVIEW:
            return error(
                f"Interrupted task {resume.task} is {task.status.value}, not in_review."
            )
        if role_name != resume.role:
            selected = role_name or "no role"
            return error(
                f"Current workflow selection is {selected}, so DevLab will not "
                "resume a different route."
            )
        if task_id != resume.task:
            selected = task_id or "none"
            return error(
                f"Next review task is {selected}, not interrupted task {resume.task}."
            )

    elif resume.role in {"integrator", "architect"} and resume.milestone:
        if role_name != resume.role:
            selected = role_name or "no role"
            return error(
                f"Current workflow selection is {selected}, so DevLab will not "
                "resume a different route."
            )
        if milestone_id != resume.milestone:
            selected = milestone_id or "none"
            return error(
                f"Selected milestone is {selected}, not interrupted milestone "
                f"{resume.milestone}."
            )

    elif role_name != resume.role:
        selected = role_name or "no role"
        return error(
            f"Current workflow selection is {selected}, so DevLab will not resume "
            "a different route."
        )

    return None


def _load_workflow_and_spec_status(
    root: Path,
) -> tuple[WorkflowState, SpecReconciliationStatus]:
    workflow_state = load_workflow_state(root)
    return workflow_state, inspect_spec_reconciliation(root, workflow_state)


def _planning_event_mode(
    *,
    revise_plan: bool,
    replace_plan: bool,
    adopt_existing: bool,
    mark_specs_planned: bool,
    reconcile_plan: bool,
) -> str:
    if mark_specs_planned:
        return "mark_specs_planned"
    if reconcile_plan:
        return "spec_reconciliation"
    if replace_plan:
        return "replace_plan"
    if revise_plan:
        return "revise"
    if adopt_existing:
        return "adopt_existing"
    return "greenfield"


def _notify_session_progress(
    callback: SessionProgressCallback | None,
    event: str,
    session_number: int,
    role_name: str,
) -> None:
    if callback is None:
        return
    try:
        callback(event, session_number, role_name)
    except Exception as exc:  # pragma: no cover - defensive observability path
        logger.warning("Session progress callback failed: %s", exc)


@dataclasses.dataclass(frozen=True)
class AgentLifecycleResult:
    """Provider result plus lifecycle errors for one role session."""

    agent_result: AgentResult
    errors: tuple[SessionError, ...] = ()


def _invoke_role_agent(
    ctx: SessionContext,
    role: RoleConfig,
    environment: EnvironmentManager,
    agent_provider: AgentProvider,
    base_prompt: str,
    session_prompt: str,
    config_log: Path | None,
) -> AgentLifecycleResult:
    """Prepare, invoke, and tear down one role's managed environment."""
    manage_environment = role.needs_environment and environment.manages_role(ctx.role_name)
    if manage_environment:
        try:
            logger.info("Preparing environment for %s session", ctx.role_name)
            environment.pre_session(ctx.role_name)
            environment.setup(ctx.role_name)
        except EnvironmentCommandError as exc:
            return AgentLifecycleResult(
                AgentResult(return_code=1, failure_kind="provider_error"),
                (SessionError("environment_setup", str(exc), 1),),
            )

    agent_result = AgentResult(return_code=1, failure_kind="provider_error")
    agent_error: SessionError | None = None
    try:
        agent_result = invoke_session(
            ctx.build_invocation(base_prompt, session_prompt),
            agent_provider=agent_provider,
        )
    except ProviderError as exc:
        agent_error = SessionError(
            "agent_invocation",
            _agent_error_message(
                ctx,
                dataclasses.replace(
                    agent_result, message=f"agent provider error: {exc}"
                ),
                config_log,
            ),
            1,
        )
    else:
        if not agent_result.succeeded:
            agent_error = SessionError(
                "agent_invocation",
                _agent_error_message(ctx, agent_result, config_log),
                agent_result.return_code or 1,
            )

    teardown_error: SessionError | None = None
    if manage_environment:
        try:
            logger.info("Tearing down environment for %s session", ctx.role_name)
            environment.post_session(ctx.role_name)
        except EnvironmentCommandError as exc:
            teardown_error = SessionError("environment_teardown", str(exc), 1)
    errors = tuple(error for error in (agent_error, teardown_error) if error is not None)
    return AgentLifecycleResult(agent_result, errors)


def _load_accepted_handoff(
    ctx: SessionContext,
    artifacts_dir: Path,
    *,
    route: SessionRoute,
) -> Handoff:
    """Load an accepted result and verify it belongs to the selected route."""
    handoff_path = artifacts_dir / HANDOFF_FILE
    result_path = artifacts_dir / SESSION_RESULT_FILE
    if not result_path.exists():
        # Parse legacy output only to preserve its more precise format diagnostic.
        parse_handoff(handoff_path, ctx.role_name)
        raise HandoffError(
            "session exited without an accepted result; run "
            "'devlab session handoff submit' before exiting"
        )
    session_result = load_session_result(result_path)
    expected = {
        "session": (session_result.envelope.session_id, ctx.invocation_id),
        "role": (session_result.envelope.role, ctx.role_name),
        "task": (session_result.envelope.task, route.task_id or ""),
        "milestone": (session_result.envelope.milestone, route.milestone_id or ""),
    }
    for label, (actual, wanted) in expected.items():
        if actual != wanted:
            raise HandoffError(f"accepted result belongs to a different {label}")
    return session_result.as_handoff(handoff_path)


def run_loop(
    root: Path,
    *,
    max_sessions: int,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    retain_prompts: bool = False,
    agent_providers: dict[str, AgentProvider] | None = None,
    role_agent_providers: dict[str, str] | None = None,
    automatic_version_control: bool = False,
    planning_only: bool = False,
    revise_plan: bool = False,
    replace_plan: bool = False,
    adopt_existing: bool = False,
    mark_specs_planned: bool = False,
    clarification_mode: str = "operator",
    handoff_correction: bool = False,
    session_progress: SessionProgressCallback | None = None,
    executable_config: ExecutableConfigSnapshot | None = None,
) -> RunResult:
    """Run the orchestrator loop, returning a structured result."""
    if clarification_mode not in CLARIFICATION_MODES:
        raise ValueError(
            "clarification_mode must be one of: " + ", ".join(sorted(CLARIFICATION_MODES))
        )
    if revise_plan and not planning_only:
        raise ValueError("revise_plan requires planning_only")
    if replace_plan and not planning_only:
        raise ValueError("replace_plan requires planning_only")
    if adopt_existing and not planning_only:
        raise ValueError("adopt_existing requires planning_only")
    if mark_specs_planned and not planning_only:
        raise ValueError("mark_specs_planned requires planning_only")
    if replace_plan and adopt_existing:
        return _error_result(
            0,
            SessionError(
                "planning_mode",
                "devlab plan cannot combine --replace-plan and --adopt-existing",
                2,
            ),
        )
    if mark_specs_planned and (revise_plan or replace_plan or adopt_existing):
        return _error_result(
            0,
            SessionError(
                "planning_mode",
                "devlab plan cannot combine --mark-specs-planned with "
                "--revise, --replace-plan, or --adopt-existing",
                2,
            ),
        )
    sessions_run = 0
    spec_status: SpecReconciliationStatus | None = None
    workflow_state: WorkflowState | None = None
    active_plan_exists = has_active_plan(root)
    if planning_only and adopt_existing and active_plan_exists:
        return _error_result(
            0,
            SessionError(
                "planning_mode",
                "--adopt-existing is only allowed when no active DevLab plan exists",
                2,
            ),
        )
    if planning_only and replace_plan and not active_plan_exists:
        return _error_result(
            0,
            SessionError(
                "planning_mode",
                "--replace-plan requires an active DevLab plan to archive",
                2,
            ),
        )
    if automatic_version_control:
        try:
            ensure_git_repository(root)
            workflow_state, spec_status = _load_workflow_and_spec_status(root)
            if planning_only and spec_status.dirty_spec_paths:
                error = _dirty_spec_error(spec_status.dirty_spec_paths)
                logger.error("%s. Stopping.", error.message)
                return _error_result(0, error)
            assert_clean_worktree(root)
        except VersionControlError as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(0, SessionError("version_control", str(exc), 1))
        except (OSError, ValueError) as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(0, SessionError("workflow_state", str(exc), 1))
        if not planning_only and spec_status is not None and spec_status.changed:
            error = _stale_specs_error(spec_status)
            logger.error("%s. Stopping.", error.message)
            return _error_result(0, error)
    else:
        try:
            workflow_state = load_workflow_state(root)
        except (OSError, ValueError) as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(0, SessionError("workflow_state", str(exc), 1))

    if mark_specs_planned:
        if spec_status is None:
            return _error_result(
                0,
                SessionError(
                    "spec_reconciliation",
                    "--mark-specs-planned requires automatic version control",
                    1,
                ),
            )
        logger.warning(
            "Marking current committed specs as planned without architect/planner "
            "reconciliation. This bypasses the spec reconciliation guardrail."
        )
        try:
            update_workflow_state(
                root,
                last_planned_spec_commit=spec_status.latest_spec_commit,
            )
            append_workflow_event(
                root,
                "specs_marked_planned",
                generation=active_generation(root),
                spec_baseline=spec_status.latest_spec_commit,
                previous_spec_baseline=spec_status.baseline_spec_commit,
            )
            if automatic_version_control:
                committed = commit_all(root, "Mark DevLab specs planned")
                if committed:
                    logger.info("Committed DevLab spec planning baseline")
        except VersionControlError as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(0, SessionError("version_control", str(exc), 1))
        except OSError as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(0, SessionError("workflow_state", str(exc), 1))
        logger.info("Specs marked planned; no planning sessions were run.")
        return _stop_result(0, RunStopReason.COMMAND_COMPLETE)

    workspace = Workspace(root)
    if workflow_state is None:
        workflow_state = load_workflow_state(root)
    requested_command = _command_family(planning_only=planning_only)
    resume_command_error = _wrong_resume_command_error(
        workflow_state,
        requested_command=requested_command,
        revise_plan=revise_plan,
    )
    if resume_command_error is not None:
        logger.error("%s. Stopping.", resume_command_error.message)
        return _error_result(0, resume_command_error)
    active_resume = workflow_state.resume
    resolved_agent_configs = None
    frozen_profiles: dict[str, Profile] | None = None
    frozen_profile_texts: dict[str, str] | None = None
    if agent_providers is None:
        try:
            agent_configuration = (
                executable_config.resolve_agents(discover_provider_versions=True)
                if executable_config is not None
                else load_agent_configuration(
                    root,
                    provider=provider,
                    model=model,
                    effort=effort,
                    discover_provider_versions=True,
                )
            )
        except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(0, SessionError("agent_configuration", str(exc), 1))
        agent_providers = agent_configuration.providers
        role_agent_providers = agent_configuration.role_providers
        resolved_agent_configs = agent_configuration.resolved
    if executable_config is not None:
        frozen_profiles = executable_config.profiles
        frozen_profile_texts = executable_config.profile_texts

    reconcile_plan = bool(spec_status and spec_status.changed)
    planning_event_mode = _planning_event_mode(
        revise_plan=revise_plan,
        replace_plan=replace_plan,
        adopt_existing=adopt_existing,
        mark_specs_planned=mark_specs_planned,
        reconcile_plan=reconcile_plan,
    )
    fresh_generation_plan = planning_only and (replace_plan or reconcile_plan)
    if fresh_generation_plan:
        try:
            manifest = archive_active_generation(
                root,
                reason="spec_reconciliation" if reconcile_plan else "replace_plan",
                spec_baseline=(
                    spec_status.baseline_spec_commit if spec_status is not None else ""
                ),
            )
            append_workflow_event(
                root,
                "generation_archived",
                mode="spec_reconciliation" if reconcile_plan else "replace_plan",
                generation=manifest.generation,
                spec_baseline=manifest.spec_baseline,
            )
            workspace = Workspace(root)
            logger.info("Archived active DevLab generation %s", manifest.generation)
            if automatic_version_control:
                committed = commit_all(root, f"Archive DevLab generation {manifest.generation}")
                if committed:
                    logger.info("Committed DevLab generation archive")
        except OSError as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(0, SessionError("generation_archive", str(exc), 1))
    forced_planning_roles = (
        ("architect", "planner")
        if revise_plan or fresh_generation_plan or adopt_existing
        else ()
    )
    planning_update = PlanningStateUpdate(
        last_planned_spec_commit=(
            spec_status.latest_spec_commit
            if spec_status is not None
            and (planning_only or not spec_status.baseline_exists)
            else None
        ),
    )
    plan_started_recorded = False

    while sessions_run < max_sessions:
        if automatic_version_control:
            try:
                assert_clean_worktree(root)
            except VersionControlError as exc:
                logger.error("%s. Stopping.", exc)
                return _error_result(
                    sessions_run, SessionError("version_control", str(exc), 1)
                )
        clarification_error = _blocking_clarification_error(workspace.snapshot)
        if clarification_error is not None:
            logger.info("%s", clarification_error.message)
            logger.info("Stopping.")
            return _stop_result(
                sessions_run,
                RunStopReason.CLARIFICATION_BLOCKED,
                (clarification_error,),
            )
        if planning_only and not revise_plan and not fresh_generation_plan and not adopt_existing:
            role_name = workspace.snapshot.assess_state()
        else:
            workspace.sync()
            role_name = (
                forced_planning_roles[sessions_run]
                if sessions_run < len(forced_planning_roles)
                else workspace.snapshot.assess_state()
            )
        selected_task = _task_for_role(workspace.snapshot, role_name) if role_name else None
        selected_task_id = selected_task.id if selected_task is not None else None
        selected_milestone_id = (
            workspace.snapshot.select_integration_milestone()
            if role_name == "integrator"
            else workspace.snapshot.select_architecture_review_milestone()
            if role_name == "architect"
            else None
        )
        resume_validation_error = _resume_validation_error(
            workspace.snapshot,
            active_resume,
            requested_command=requested_command,
            role_name=role_name,
            task_id=selected_task_id,
            milestone_id=selected_milestone_id,
        )
        if resume_validation_error is not None:
            logger.error("%s. Stopping.", resume_validation_error.message)
            return _error_result(sessions_run, resume_validation_error)
        if role_name is None:
            if workspace.snapshot.blocked_tasks():
                logger.info(
                    "No task is eligible; remaining development tasks"
                    " are blocked by dependencies."
                )
                reason = RunStopReason.NO_ELIGIBLE_ROLE
            else:
                logger.info("All milestones complete or no task can proceed.")
                reason = RunStopReason.WORKFLOW_COMPLETE
            logger.info("Stopping.")
            return _stop_result(sessions_run, reason)

        if (
            not planning_only
            and spec_status is not None
            and (
                spec_status.dirty_spec_paths
                or not spec_status.baseline_exists
                or spec_status.changed
            )
            and role_name not in {"architect", "planner"}
        ):
            error = _stale_specs_error(spec_status)
            logger.error("%s. Stopping.", error.message)
            return _error_result(sessions_run, error)

        if (
            planning_only
            and not revise_plan
            and not fresh_generation_plan
            and not adopt_existing
            and role_name not in {"architect", "planner"}
        ):
            if sessions_run == 0:
                logger.info(
                    "Planning state already exists; no planning session needed. "
                    "Use devlab plan --revise to review and update plans."
                )
                if spec_status is not None and not spec_status.baseline_exists:
                    try:
                        update_workflow_state(
                            root,
                            last_planned_spec_commit=spec_status.latest_spec_commit,
                        )
                        workspace.did_mutate()
                        if automatic_version_control:
                            committed = commit_all(
                                root,
                                "Record DevLab spec planning baseline",
                            )
                            if committed:
                                logger.info("Committed DevLab spec planning baseline")
                    except VersionControlError as exc:
                        logger.error("%s. Stopping.", exc)
                        return _error_result(
                            sessions_run, SessionError("version_control", str(exc), 1)
                        )
            else:
                logger.info("Planning complete; stopping before implementation roles.")
            logger.info("Stopping before %s session.", role_name)
            return _stop_result(sessions_run, RunStopReason.COMMAND_COMPLETE)
        if (
            planning_only
            and (revise_plan or fresh_generation_plan or adopt_existing)
            and sessions_run >= len(forced_planning_roles)
        ):
            logger.info("Planning revision complete; stopping before implementation roles.")
            return _stop_result(sessions_run, RunStopReason.COMMAND_COMPLETE)

        if automatic_version_control and resolved_agent_configs is not None:
            agent_config_error = _preflight_agent_executable(
                role_name, resolved_agent_configs[role_name]
            )
            if agent_config_error is not None:
                logger.error("%s. Stopping.", agent_config_error.message)
                return _error_result(sessions_run, agent_config_error)

        if role_name == "integrator":
            milestone = workspace.snapshot.select_integration_milestone()
            if milestone is not None:
                workspace.milestones().get(milestone).mark_ready_for_integration()

        start_snapshot = workspace.snapshot
        planner_generation_update = (
            planning_update
            if role_name == "planner"
            and (
                planning_only
                or (spec_status is not None and not spec_status.baseline_exists)
            )
            else None
        )
        route = _select_session_route(start_snapshot, role_name)
        progress_baseline = _session_progress_baseline(start_snapshot)
        non_advancing_recovery = (
            role_name == "developer" and _is_non_advancing_recovery(root, route)
        )
        prior_validation_failure = (
            _latest_validation_failure(root, route.task_id)
            if role_name == "developer" and route.task_id is not None
            else None
        )
        if role_name == "developer" and route.task is not None:
            contract_errors = route.task.contract_errors
            if contract_errors:
                message = "; ".join(contract_errors)
                logger.error(
                    "Task %s has an invalid work packet: %s. Stopping.",
                    route.task.id,
                    message,
                )
                return _error_result(
                    sessions_run,
                    SessionError(
                        "task_contract",
                        f"task {route.task.id} is not executable: {message}",
                        1,
                    ),
                    reason=RunStopReason.TASK_CONTRACT_INVALID,
                )
        role = ROLES[role_name]
        ctx = _build_session_context(
            root, sessions_run + 1, role_name, retain_prompts=retain_prompts,
        )
        config_log: Path | None = None

        logger.info(
            "Starting session %s: %s %s",
            ctx.session_number,
            role_name,
            session_start_context(start_snapshot, role_name, route.task),
        )
        _notify_session_progress(session_progress, "start", ctx.session_number, role_name)
        if resolved_agent_configs is not None:
            config_log = ctx.log_resolved_config(resolved_agent_configs[role_name])
            logger.debug("Resolved agent config written to %s", config_log)
            logger.debug("Agent stdout log: %s", ctx.stdout_log)
            logger.debug("Agent stderr log: %s", ctx.stderr_log)

        artifacts_dir = root / ARTIFACTS_DIR / role_name
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        write_session_envelope(
            artifacts_dir / SESSION_ENVELOPE_FILE,
            SessionEnvelope(
                schema_version=1,
                session_id=ctx.invocation_id,
                role=role_name,
                task=route.task_id or "",
                milestone=route.milestone_id or "",
                protected_active_tasks=tuple(
                    task.id for task in start_snapshot.active_tasks()
                ),
                incremental_planning_required=(
                    role_name == "planner" and _needs_incremental_planning(start_snapshot)
                ),
                allow_active_task_replacement=fresh_generation_plan,
            ),
        )

        try:
            snapshot = workspace.snapshot
            base_prompt = build_base_prompt(
                root, role, snapshot=snapshot, role_name=role_name
            )
            session_prompt = build_session_prompt(
                snapshot,
                role_name,
                profiles=frozen_profiles,
                profile_texts=frozen_profile_texts,
                planning_revision=planning_only
                and (revise_plan or fresh_generation_plan or adopt_existing),
                adopt_existing=planning_only and adopt_existing,
                fresh_generation=planning_only and fresh_generation_plan,
                spec_reconciliation=reconcile_plan,
            )
            if non_advancing_recovery:
                session_prompt += "\n\n" + _recovery_prompt(route)
            if prior_validation_failure is not None:
                session_prompt += "\n\n" + _validation_recovery_prompt(
                    prior_validation_failure
                )
            ctx.write_prompt_logs(base_prompt, session_prompt)
            environment = _environment_for_session(
                root,
                workspace.snapshot,
                role_name,
                frozen_profiles,
            )
        except ProfileNotFoundError as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(
                sessions_run, SessionError("profile_resolution", str(exc), 1)
            )

        agent_provider = provider_for_role(role_name, agent_providers, role_agent_providers)
        lifecycle = _invoke_role_agent(
            ctx,
            role,
            environment,
            agent_provider,
            base_prompt,
            session_prompt,
            config_log,
        )
        agent_result = lifecycle.agent_result
        if lifecycle.errors:
            primary_error = lifecycle.errors[0]
            logger.error("%s. Stopping.", primary_error.message)
            logger.info(_failed_session_cleanup_hint())
            metadata = _build_session_metadata(
                ctx,
                agent_result,
                resolved_agent_configs,
                route.task_id,
                executable_config,
            )
            ctx.write_session_metadata(metadata)
            return _error_result(
                sessions_run, primary_error, *lifecycle.errors[1:]
            )

        workspace.did_mutate()

        result_path = artifacts_dir / SESSION_RESULT_FILE
        if not result_path.exists():
            submission_issues: tuple[str, ...]
            submission_reason = HandoffFailureReason.CONTRACT
            try:
                submit_session_handoff(
                    root, envelope_path=artifacts_dir / SESSION_ENVELOPE_FILE
                )
            except HandoffSubmissionError as exc:
                submission_issues = exc.issues
                submission_reason = exc.reason
            except HandoffError as exc:
                submission_issues = (str(exc),)
                submission_reason = exc.reason
            else:
                submission_issues = ()
            if not result_path.exists() and handoff_correction:
                semantic_task = (
                    route.task
                    if role_name == "developer"
                    and submission_reason == HandoffFailureReason.SEMANTIC_CONFLICT
                    else None
                )
                correction_error = _attempt_handoff_correction(
                    ctx,
                    agent_provider,
                    submission_issues,
                    semantic_task=semantic_task,
                )
                if correction_error is not None:
                    logger.error("%s. Stopping.", correction_error.message)
                    metadata = _build_session_metadata(
                        ctx,
                        agent_result,
                        resolved_agent_configs,
                        route.task_id,
                        executable_config,
                    )
                    ctx.write_session_metadata(metadata)
                    return _error_result(sessions_run, correction_error)
        try:
            handoff = _load_accepted_handoff(
                ctx,
                artifacts_dir,
                route=route,
            )
            validate_handoff(handoff, workspace.snapshot)
            if handoff.clarification_request is None:
                planner_task_error = _validate_planner_preserved_active_tasks(
                    start_snapshot,
                    workspace.snapshot,
                    role_name,
                    fresh_generation_plan=fresh_generation_plan,
                )
                if planner_task_error is not None:
                    raise HandoffError(planner_task_error)
                planner_noop_error = _validate_exhausted_backlog_planner_progress(
                    start_snapshot,
                    workspace.snapshot,
                    role_name,
                    reported_planning_complete=handoff.planning_complete,
                )
                if planner_noop_error is not None:
                    raise HandoffError(planner_noop_error)
                _apply_planner_workflow_state(
                    workspace,
                    handoff,
                    planning_update=planner_generation_update,
                )
                if role_name == "planner" and spec_status is not None:
                    _workflow_state, spec_status = _load_workflow_and_spec_status(root)
        except HandoffError as exc:
            message = _handoff_error_message(ctx, str(exc), config_log)
            logger.error("Invalid handoff produced by %s: %s. Stopping.", role_name, message)
            logger.info(_failed_session_cleanup_hint())
            metadata = _build_session_metadata(
                ctx,
                agent_result,
                resolved_agent_configs,
                route.task_id,
                executable_config,
            )
            ctx.write_session_metadata(metadata)
            return _error_result(
                sessions_run, SessionError("handoff_validation", message, 1)
            )

        commit_message = _commit_message(workspace.snapshot, handoff)
        process_result = process_handoff(
            handoff,
            workspace,
            command=requested_command,
            session_id=ctx.invocation_id,
            task_id=route.task_id,
            milestone_id=route.milestone_id,
        )
        validation_run: ValidationRun | None = None
        repeated_validation_failure = False
        accepted_result = load_session_result(result_path)
        if (
            role_name == "developer"
            and route.task is not None
            and accepted_result.candidate.outcome == "completed"
            and process_result.clarification_id is None
        ):
            profile = (
                profile_from_snapshot(
                    frozen_profiles, route.task.profile, root=root
                )
                if frozen_profiles is not None
                else load_profile(root, route.task.profile)
            )
            validation = effective_validation(route.task, profile)
            validation_run = run_validation_commands(
                root,
                role_name=role_name,
                task_id=route.task.id,
                session_id=ctx.invocation_id,
                commands=validation.commands,
                source=validation.source,
                timeout=profile.environment.timeouts.setup,
            )
            if validation_run.outcome in {
                "failed",
                "timeout",
                "infrastructure_error",
            } and validation.source == "task":
                failed = validation_run.commands[-1]
                workspace.tasks().get(route.task.id).record_validation_failure(
                    f"{failed.command!r} ({failed.outcome}); see {failed.log_path}"
                )
                logger.warning(
                    "Task %s validation %s; returned to development",
                    route.task.id,
                    validation_run.outcome,
                )
                repeated_validation_failure = prior_validation_failure is not None
            elif validation_run.outcome in {
                "failed",
                "timeout",
                "infrastructure_error",
            }:
                logger.warning(
                    "Task %s profile validation %s; recorded as a soft task-level "
                    "warning",
                    route.task.id,
                    validation_run.outcome,
                )
            elif validation_run.outcome == "missing_tool":
                logger.warning(
                    "Task %s validation prerequisite is missing; leaving it unverified",
                    route.task.id,
                )
        if planning_only and not plan_started_recorded and role_name in {"architect", "planner"}:
            append_workflow_event(
                root,
                "plan_started",
                mode=planning_event_mode,
                generation=active_generation(root),
            )
            plan_started_recorded = True
        if (
            planning_only
            and role_name == "planner"
            and process_result.clarification_id is None
        ):
            append_workflow_event(
                root,
                "plan_completed",
                mode=planning_event_mode,
                generation=active_generation(root),
                planning_complete=workspace.snapshot.workflow_state().planning.complete,
            )
        if (
            active_resume is not None
            and active_resume.command == requested_command
            and process_result.clarification_id is None
        ):
            clear_resume_state(root)
            workspace.did_mutate()
            active_resume = None
        progress = _classify_session_progress(
            root, progress_baseline, workspace.snapshot, process_result
        )
        append_workflow_event(
            root,
            "session_progress",
            role=role_name,
            task=route.task_id or "",
            milestone=route.milestone_id or "",
            progress=progress.value,
        )
        metadata = _build_session_metadata(
            ctx,
            agent_result,
            resolved_agent_configs,
            route.task_id,
            executable_config,
            progress,
        )
        ctx.write_session_metadata(metadata)
        if non_advancing_recovery and progress == SessionProgress.NON_ADVANCING:
            message = (
                f"developer recovery for task {route.task_id or 'unknown'} did not "
                "advance product or workflow state"
            )
            logger.error("%s. Stopping.", message)
            return _error_result(
                sessions_run + 1,
                SessionError("non_advancing_session", message, 1),
                reason=RunStopReason.DEVELOPER_NON_ADVANCING,
            )
        if repeated_validation_failure:
            message = (
                f"task {route.task_id or 'unknown'} repeated a failing validation "
                "outcome after one bounded developer recovery"
            )
            logger.error("%s. Stopping.", message)
            return _error_result(
                sessions_run + 1,
                SessionError("task_validation", message, 1),
                reason=RunStopReason.VALIDATION_FAILED,
            )
        if automatic_version_control:
            try:
                workspace.sync()
                committed = commit_all(root, commit_message)
                if committed:
                    logger.info("Committed session changes: %s", commit_message)
                if process_result.integrated_milestone is not None:
                    tag_name = _milestone_tag_name(process_result.integrated_milestone)
                    create_git_tag(
                        root,
                        tag_name,
                        f"DevLab milestone {process_result.integrated_milestone} integrated",
                    )
                    logger.info(
                        "Tagged integrated milestone %s as %s",
                        process_result.integrated_milestone,
                        tag_name,
                    )
            except VersionControlError as exc:
                logger.error("%s. Stopping.", exc)
                return _error_result(
                    sessions_run, SessionError("version_control", str(exc), 1)
                )
        finish_context = session_finish_context(
            workspace.snapshot,
            role_name,
            task_id=route.task_id,
            milestone_id=route.milestone_id,
        )
        duration = agent_result.duration_seconds
        duration_info = f" duration={duration:.1f}s" if duration is not None else ""
        logger.info(
            "Finished session %s: %s %s%s",
            ctx.session_number,
            role_name,
            finish_context,
            duration_info,
        )
        _notify_session_progress(session_progress, "finish", ctx.session_number, role_name)
        sessions_run += 1
        if process_result.clarification_id is not None:
            if clarification_mode == "operator":
                logger.info(
                    "Answer and resume with: devlab clarify answer %s --resume",
                    process_result.clarification_id,
                )
                clarification_error = _blocking_clarification_error(workspace.snapshot)
                return _stop_result(
                    sessions_run,
                    RunStopReason.CLARIFICATION_BLOCKED,
                    (clarification_error,) if clarification_error is not None else (),
                )
            if sessions_run >= max_sessions:
                error = SessionError(
                    "clarification_resolver",
                    "Clarification resolver could not run because max_sessions was reached.",
                    1,
                )
                logger.error("%s. Stopping.", error.message)
                return _error_result(sessions_run, error)
            resolver_error, counted = _invoke_clarification_resolver(
                root,
                clarification_id=process_result.clarification_id,
                session_number=sessions_run + 1,
                agent_providers=agent_providers,
                role_agent_providers=role_agent_providers,
                blocked_role=role_name,
                retain_prompts=retain_prompts,
                session_progress=session_progress,
            )
            if counted:
                sessions_run += 1
            if resolver_error is not None:
                logger.error("%s. Stopping.", resolver_error.message)
                return _error_result(sessions_run, resolver_error)
            if automatic_version_control:
                try:
                    committed = commit_all(
                        root,
                        f"Answer DevLab clarification {process_result.clarification_id}",
                    )
                    if committed:
                        logger.info(
                            "Committed clarification answer: %s",
                            process_result.clarification_id,
                        )
                except VersionControlError as exc:
                    logger.error("%s. Stopping.", exc)
                    return _error_result(
                        sessions_run, SessionError("version_control", str(exc), 1)
                    )
            workspace = Workspace(root)
            active_resume = load_workflow_state(root).resume
            continue

        if (
            planning_only
            and (revise_plan or fresh_generation_plan or adopt_existing)
            and sessions_run >= len(forced_planning_roles)
        ):
            logger.info("Planning revision complete; stopping before implementation roles.")
            return _stop_result(sessions_run, RunStopReason.COMMAND_COMPLETE)

    logger.info("Orchestrator finished after %s session(s).", sessions_run)
    workspace.sync()
    clarification_error = _blocking_clarification_error(workspace.snapshot)
    if clarification_error is not None:
        return _stop_result(
            sessions_run,
            RunStopReason.CLARIFICATION_BLOCKED,
            (clarification_error,),
        )
    next_role = workspace.snapshot.assess_state()
    if next_role is None:
        reason = (
            RunStopReason.NO_ELIGIBLE_ROLE
            if workspace.snapshot.blocked_tasks()
            else RunStopReason.WORKFLOW_COMPLETE
        )
        return _stop_result(sessions_run, reason)
    if (
        planning_only
        and not revise_plan
        and not fresh_generation_plan
        and not adopt_existing
        and next_role not in {"architect", "planner"}
    ):
        return _stop_result(sessions_run, RunStopReason.COMMAND_COMPLETE)
    return _stop_result(sessions_run, RunStopReason.SESSION_LIMIT)

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from collections.abc import Callable
from contextlib import ExitStack
from enum import StrEnum
from pathlib import Path
from typing import cast

from devlab._logging import logger
from devlab.agent_config import (
    AGENTS_CONFIG,
    ResolvedAgentConfig,
    find_agent_executable_problems,
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
from devlab.dependency_diagnostics import (
    DependencySnapshot,
    introduced_dependencies,
    snapshot_direct_dependencies,
)
from devlab.environment import (
    EnvironmentCommandError,
    EnvironmentManager,
    TestServiceError,
    ValidationRun,
    run_validation_commands,
    test_service_lock,
)
from devlab.executable_config import (
    ExecutableConfigSnapshot,
    build_executable_config_snapshot,
)
from devlab.findings import Finding
from devlab.generations import active_generation, archive_active_generation, has_active_plan
from devlab.git import VersionControlError, run_git
from devlab.handoffs import (
    HANDOFF_CANDIDATE_FILE,
    HANDOFF_FILE,
    MAX_SUBMISSION_ATTEMPTS,
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
from devlab.milestones import (
    MilestoneVerification,
    MilestoneVerificationCommand,
)
from devlab.prerequisites import (
    FilePrerequisiteTracker,
    Prerequisite,
    PrerequisiteOperation,
    PrerequisiteResult,
    resolve_prerequisites,
)
from devlab.profiles import (
    EffectiveMilestoneValidation,
    Profile,
    ProfileNotFoundError,
    effective_milestone_validation,
    effective_validation,
    load_profile,
    load_profiles,
    profile_from_snapshot,
)
from devlab.prompt_resources import read_prompt_resource
from devlab.prompts import (
    build_base_prompt,
    build_clarification_resolver_prompt,
    build_researcher_prompt,
    build_session_prompt,
)
from devlab.research import Research, ResearchStatus, parse_research_result_candidate
from devlab.roles import ROLES, RoleConfig
from devlab.session_logging import (
    SessionContext,
    SessionMetadata,
    agent_log_path,
    build_session_context,
    session_finish_context,
    session_start_context,
)
from devlab.session_logging import (
    session_timestamp as _timestamp,
)
from devlab.spec_reconciliation import (
    SpecReconciliationStatus,
    inspect_spec_reconciliation,
)
from devlab.task_tracker import DEVELOPABLE_STATUSES, Task, TaskStatus
from devlab.version_control import (
    assert_clean_worktree,
    commit_all,
    commit_prerequisite_preparation,
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
RESEARCHER_ROLE = "researcher"
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
    EXECUTABLE_CONFIG_CHANGED = "executable_config_changed"
    SESSION_LIMIT = "session_limit"
    CLARIFICATION_BLOCKED = "clarification_blocked"
    RESEARCH_PENDING = "research_pending"
    RESEARCH_COMPLETED = "research_completed"
    NO_ELIGIBLE_ROLE = "no_eligible_role"
    DEVELOPER_NON_ADVANCING = "developer_non_advancing"
    TASK_CONTRACT_INVALID = "task_contract_invalid"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_PREREQUISITE_MISSING = "validation_prerequisite_missing"
    VALIDATION_INFRASTRUCTURE_ERROR = "validation_infrastructure_error"
    PREREQUISITE_BLOCKED = "prerequisite_blocked"
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
    test_service_duration_seconds: float = 0


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
        RunStopReason.EXECUTABLE_CONFIG_CHANGED,
    }
    return RunResult(sessions_run, completed, 0, errors, reason)


class SessionProgress(StrEnum):
    """Observed repository/workflow effect of one accepted role session."""

    PRODUCT_CHANGE = "product_change"
    WORKFLOW_ADVANCE = "workflow_advance"
    LEGITIMATE_STOP = "legitimate_stop"
    NON_ADVANCING = "non_advancing"


@dataclasses.dataclass(frozen=True)
class SessionProgressBaseline:
    tasks: dict[str, tuple[object, ...]]
    milestones: dict[str, object]
    workflow_state: WorkflowState
    findings: tuple[tuple[object, ...], ...]


@dataclasses.dataclass(frozen=True)
class SessionRoute:
    """Trusted workflow identity selected for one role session."""

    role_name: str
    task: Task | None = None
    milestone_id: str | None = None

    @property
    def task_id(self) -> str | None:
        return self.task.id if self.task is not None else None


def _select_session_route(snapshot: WorkspaceSnapshot, role_name: str) -> SessionRoute:
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


def _select_resume_route(snapshot: WorkspaceSnapshot, resume: ResumeState) -> SessionRoute:
    return SessionRoute(
        role_name=resume.role,
        task=_task_by_id(snapshot, resume.task) if resume.task else None,
        milestone_id=resume.milestone or None,
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
        invocation.role_name,
        result.return_code,
        duration_info,
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
            and candidate.outcome == "completed"
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
        record_submission_attempt(resolved_envelope, accepted=False, issues=exc.issues)
        raise
    except HandoffError as exc:
        record_submission_attempt(resolved_envelope, accepted=False, issues=(str(exc),))
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
            "failed, needs_clarification, or needs_research",
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
        f"completed developer result left acceptance criteria incomplete for {task.id}: {detail}",
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
            raise HandoffError(planner_error, reason=HandoffFailureReason.REFERENCE)
    if handoff.role_name == "reviewer":
        reviewer_error = _validate_reviewer_outcome(snapshot, handoff)
        if reviewer_error:
            raise HandoffError(reviewer_error, reason=HandoffFailureReason.SEMANTIC_CONFLICT)


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
    research_id: str | None = None
    stop_reason: RunStopReason | None = None
    stop_message: str = ""


def process_handoff(
    handoff: Handoff,
    workspace: Workspace,
    *,
    command: str = "",
    session_id: str = "",
    task_id: str | None = None,
    milestone_id: str | None = None,
    milestone_validation: ValidationRun | None = None,
    milestone_validation_contract: EffectiveMilestoneValidation | None = None,
) -> ProcessResult:
    research_request = handoff.research_request
    if research_request is not None:
        _validate_research_request_route(
            research_request.scope,
            command=command,
            role=handoff.role_name,
            task_id=task_id,
            milestone_id=milestone_id,
        )
    archived = archive_handoff(workspace.root, handoff.role_name)
    logger.info("Handoff archived to %s", archived.name)

    if research_request is not None:
        return _process_research_request(
            handoff,
            workspace,
            command=command,
            session_id=session_id,
            task_id=task_id,
            milestone_id=milestone_id,
        )

    clarification_request = handoff.clarification_request
    if clarification_request is not None:
        return _process_clarification_request(
            handoff,
            workspace,
            command=command,
            session_id=session_id,
            task_id=task_id,
            milestone_id=milestone_id,
        )

    if handoff.role_name == "architect":
        return _process_architect_handoff(
            handoff, workspace, archived, session_id=session_id, milestone_id=milestone_id
        )
    if handoff.role_name == "developer":
        return _process_developer_handoff(workspace, task_id=task_id)
    if handoff.role_name == "planner":
        _mark_addressed_findings_planned(workspace, handoff)
        return ProcessResult()
    if handoff.role_name == "reviewer":
        return _process_reviewer_handoff(handoff, workspace)
    if handoff.role_name == "integrator":
        return _process_integrator_handoff(
            handoff,
            workspace,
            archived,
            milestone_validation=milestone_validation,
            milestone_validation_contract=milestone_validation_contract,
        )
    return ProcessResult()


def _process_research_request(
    handoff: Handoff,
    workspace: Workspace,
    *,
    command: str,
    session_id: str,
    task_id: str | None,
    milestone_id: str | None,
) -> ProcessResult:
    request = handoff.research_request
    if request is None:
        raise RuntimeError("research request processing requires a request")
    research = workspace.research().create(
        title=request.title,
        asking_role=handoff.role_name,
        asking_session_id=session_id,
        command=command,
        scope=request.scope,
        task=task_id or "",
        milestone=milestone_id or "",
        question=request.question,
        context=request.context,
        desired_outcome=request.desired_outcome,
        acceptance_criteria=request.acceptance_criteria,
    )
    set_resume_state(
        workspace.root,
        ResumeState(
            blocked_by=research.id,
            blocked_kind="research",
            command=command,
            role=handoff.role_name,
            task=task_id or "",
            milestone=milestone_id or "",
        ),
    )
    workspace.did_mutate()
    append_workflow_event(
        workspace.root,
        "research_requested",
        research=research.id,
        role=handoff.role_name,
        command=command,
        task=task_id or "",
        milestone=milestone_id or "",
    )
    logger.info("Workflow stopped: research required: %s %s", research.id, research.title)
    return ProcessResult(research_id=research.id)


def _process_clarification_request(
    handoff: Handoff,
    workspace: Workspace,
    *,
    command: str,
    session_id: str,
    task_id: str | None,
    milestone_id: str | None,
) -> ProcessResult:
    request = handoff.clarification_request
    if request is None:
        raise RuntimeError("clarification request processing requires a request")
    clarification = workspace.clarifications().create(
        title=request.title,
        asking_role=handoff.role_name,
        session_id=session_id,
        scope=request.scope,
        blocks=request.blocks,
        answer_shape=request.answer_shape,
        recommended_option=request.recommended_option,
        body=_clarification_body(request.title, request.details),
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


def _process_architect_handoff(
    handoff: Handoff,
    workspace: Workspace,
    archived: Path,
    *,
    session_id: str,
    milestone_id: str | None,
) -> ProcessResult:
    milestone = milestone_id or workspace.snapshot.select_architecture_review_milestone()
    if milestone is None:
        return ProcessResult()
    if handoff.has_open_issues:
        workspace.findings().create_from_handoff(
            source="architect", milestone=milestone, handoff_path=archived
        )
        logger.info("Architecture review reported open issues; finding created")
    workspace.milestones().get(milestone).mark_architecture_reviewed(archived)
    verification = workspace.snapshot.milestone_verification(milestone)
    if verification is not None:
        milestone_findings = tuple(
            finding
            for finding in workspace.snapshot.list_findings()
            if finding.milestone == milestone
        )
        workspace.milestones().get(milestone).write_verification(
            dataclasses.replace(
                verification,
                architecture_session=session_id,
                architecture_handoff=archived.name,
                design_drift=handoff.design_drift,
                finding_ids=tuple(finding.id for finding in milestone_findings),
                finding_statuses=tuple(
                    f"{finding.id}:{finding.status.value}" for finding in milestone_findings
                ),
            )
        )
    logger.info("Milestone %s marked architecture-reviewed", milestone)
    return ProcessResult()


def _process_developer_handoff(workspace: Workspace, *, task_id: str | None) -> ProcessResult:
    task = (
        _task_by_id(workspace.snapshot, task_id)
        if task_id is not None
        else workspace.snapshot.select_next_development_task()
    )
    if task and task.acceptance_criteria_complete:
        task_handle = workspace.tasks().get(task.id)
        task_handle.mark_in_review()
        logger.info(
            "Task %s completed by developer; status set to in_review", task_handle.path.name
        )
    return ProcessResult()


def _process_reviewer_handoff(handoff: Handoff, workspace: Workspace) -> ProcessResult:
    task = workspace.snapshot.select_next_review_task()
    if task and task.review_approved and not handoff.has_open_issues:
        task_handle = workspace.tasks().get(task.id)
        task_handle.close()
        logger.info("Task %s closed by reviewer; status set to closed", task_handle.path.name)
        task_handle.resolve_addressed_findings()
    elif task:
        task_handle = workspace.tasks().get(task.id)
        task_handle.mark_changes_requested()
        if not handoff.has_open_issues and not task.review_approved:
            logger.warning(
                "Task %s: reviewer reports no open issues but review approval checkbox "
                "is missing; defaulting to changes_requested",
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


def _process_integrator_handoff(
    handoff: Handoff,
    workspace: Workspace,
    archived: Path,
    *,
    milestone_validation: ValidationRun | None,
    milestone_validation_contract: EffectiveMilestoneValidation | None,
) -> ProcessResult:
    milestone = workspace.snapshot.select_integration_milestone()
    if milestone is None:
        return ProcessResult()
    if milestone_validation is None or milestone_validation_contract is None:
        raise RuntimeError("integrator processing requires milestone validation facts")
    if handoff.has_open_issues or milestone_validation.outcome == "failed":
        finding = _create_integration_finding(
            workspace,
            milestone=milestone,
            handoff=handoff,
            handoff_path=archived,
            validation=milestone_validation,
        )
        workspace.milestones().get(milestone).mark_integration_failed(finding.id)
        _write_milestone_verification(
            workspace,
            milestone,
            archived,
            handoff,
            milestone_validation_contract,
            milestone_validation,
            state="blocked_product_failure",
        )
        logger.info("Integration reported open issues; finding created for planner follow-up")
        return ProcessResult()
    if milestone_validation.outcome in {"missing_tool", "timeout", "infrastructure_error"}:
        state = (
            "blocked_prerequisite"
            if milestone_validation.outcome == "missing_tool"
            else "blocked_infrastructure"
        )
        _write_milestone_verification(
            workspace,
            milestone,
            archived,
            handoff,
            milestone_validation_contract,
            milestone_validation,
            state=state,
        )
        reason = (
            RunStopReason.VALIDATION_PREREQUISITE_MISSING
            if milestone_validation.outcome == "missing_tool"
            else RunStopReason.VALIDATION_INFRASTRUCTURE_ERROR
        )
        return ProcessResult(
            stop_reason=reason,
            stop_message=(
                f"milestone {milestone} validation {milestone_validation.outcome}; "
                "integration was not recorded"
            ),
        )
    state = (
        "unverified_not_configured"
        if milestone_validation.outcome == "not_configured"
        else "verified"
    )
    workspace.milestones().get(milestone).mark_integrated(archived)
    _write_milestone_verification(
        workspace,
        milestone,
        archived,
        handoff,
        milestone_validation_contract,
        milestone_validation,
        state=state,
    )
    logger.info("Milestone %s marked integrated", milestone)
    return ProcessResult(integrated_milestone=milestone)


def _validate_research_request_route(
    scope: str,
    *,
    command: str,
    role: str,
    task_id: str | None,
    milestone_id: str | None,
) -> None:
    if role not in {"architect", "planner", "developer"}:
        raise HandoffError(f"role {role} may not request research")
    if command not in {"plan", "implement"}:
        raise HandoffError("research request requires an active plan or implement command")
    expected_scope = (
        f"task:{task_id}"
        if task_id is not None
        else f"milestone:{milestone_id}"
        if milestone_id is not None
        else "planning"
        if command == "plan"
        else "workspace"
    )
    if scope != expected_scope:
        raise HandoffError(
            f"research scope {scope!r} does not match the active route scope {expected_scope!r}"
        )


def _create_integration_finding(
    workspace: Workspace,
    *,
    milestone: str,
    handoff: Handoff,
    handoff_path: Path,
    validation: ValidationRun,
) -> Finding:
    issues = handoff.open_issues.strip() if handoff.has_open_issues else "- None"
    validation_text = ""
    if validation.outcome == "failed" and validation.commands:
        failed = validation.commands[-1]
        validation_text = (
            "\n\n## Mechanical Validation Failure\n"
            f"- `{failed.command}` exited with {failed.return_code}; see `{failed.log_path}`."
        )
    return workspace.findings().create(
        title=f"{milestone} integration validation failed",
        source="integrator",
        milestone=milestone,
        handoff=handoff_path.name,
        body=(
            f"# {milestone} integration validation failed\n\n"
            f"## Finding\n{issues}{validation_text}\n\n"
            "## Requested Planning\nCreate all required follow-up task(s) for this "
            "finding. Each task must list this finding in `addresses_findings`.\n"
        ),
    )


def _write_milestone_verification(
    workspace: Workspace,
    milestone: str,
    archived: Path,
    handoff: Handoff,
    contract: EffectiveMilestoneValidation,
    run: ValidationRun,
    *,
    state: str,
) -> None:
    results = {result.command: result for result in run.commands}
    commands: list[MilestoneVerificationCommand] = []
    for resolved in contract.commands:
        result = results.get(resolved.command)
        commands.append(
            MilestoneVerificationCommand(
                command=resolved.command,
                task_ids=resolved.task_ids,
                sources=resolved.sources,
                outcome=result.outcome if result is not None else "not_run",
                exit_code=result.return_code if result is not None else None,
                duration_seconds=result.duration_seconds if result is not None else 0.0,
                output_summary=result.output_summary if result is not None else "",
                log_path=result.log_path if result is not None else "",
            )
        )
    tasks = workspace.snapshot.tasks_for_milestone(milestone)
    finding_ids = tuple(
        finding.id
        for finding in workspace.snapshot.list_findings()
        if finding.milestone == milestone
    )
    finding_statuses = tuple(
        f"{finding.id}:{finding.status.value}"
        for finding in workspace.snapshot.list_findings()
        if finding.milestone == milestone
    )
    workspace.milestones().get(milestone).write_verification(
        MilestoneVerification(
            milestone_id=milestone,
            state=state,
            repository_revision=run.repository_revision,
            closed_task_ids=tuple(task.id for task in tasks if task.status == TaskStatus.CLOSED),
            commands=tuple(commands),
            integration_session=run.session_id,
            integration_handoff=archived.name,
            finding_ids=finding_ids,
            finding_statuses=finding_statuses,
            semantic_integration_concerns=handoff.semantic_integration_concerns,
            untested_claims=handoff.untested_claims,
        )
    )
    append_workflow_event(
        workspace.root,
        "milestone_validation",
        milestone=milestone,
        session=run.session_id,
        outcome=run.outcome,
        state=state,
    )


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
    assigned_task: Task | None = None,
) -> EnvironmentManager:
    task = assigned_task or _task_for_role(snapshot, role_name)
    profile_id = task.profile if task is not None else None
    profile = (
        profile_from_snapshot(profiles, profile_id, root=root)
        if profiles is not None
        else load_profile(root, profile_id)
    )
    return EnvironmentManager(root, profile.environment)


def _profiles_for_route(
    root: Path,
    snapshot: WorkspaceSnapshot,
    route: SessionRoute,
    profiles: dict[str, Profile],
) -> tuple[Profile, ...]:
    profile_ids: list[str | None]
    if route.task is not None:
        profile_ids = [route.task.profile]
    elif route.milestone_id is not None:
        profile_ids = [task.profile for task in snapshot.tasks_for_milestone(route.milestone_id)]
    else:
        profile_ids = []
    resolved: list[Profile] = []
    for profile_id in profile_ids:
        profile = profile_from_snapshot(profiles, profile_id, root=root)
        if all(item.id != profile.id for item in resolved):
            resolved.append(profile)
    return tuple(resolved)


def _resolve_profile_prerequisites(
    root: Path,
    profiles: tuple[Profile, ...],
    operation: PrerequisiteOperation,
    environ: dict[str, str] | None = None,
) -> tuple[PrerequisiteResult, ...]:
    results: list[PrerequisiteResult] = []
    preparations_recorded = False
    seen: set[tuple[str, str]] = set()
    for profile in profiles:
        prerequisites = profile.prerequisites
        applicable = tuple(item for item in prerequisites if operation in item.required_for)
        _validate_preparation_contracts(root, profile, applicable, operation)
        for prerequisite in applicable:
            before = _git_visible_preparation_state(root)
            resolution = resolve_prerequisites(
                root,
                (prerequisite,),
                operation,
                environ={**os.environ, **(environ or {})},
                redact_output=bool(environ),
            )
            after = _git_visible_preparation_state(root)
            for preparation in resolution.preparations:
                append_workflow_event(
                    root,
                    "prerequisite_prepared",
                    profile=profile.id,
                    prerequisite=preparation.prerequisite.id,
                    operation=operation.value,
                    outcome=preparation.outcome,
                    return_code=preparation.return_code,
                    duration_seconds=preparation.duration_seconds,
                    log_path=preparation.log_path,
                )
                preparations_recorded = True
            if resolution.preparations and after != before:
                commit_prerequisite_preparation(root)
                changed = ", ".join(sorted(after.symmetric_difference(before)))
                raise ValueError(
                    "prerequisite preparation changed Git-visible workspace state; "
                    f"preparation outputs must be ignored runtime artifacts: {changed}"
                )
            for result in resolution.results:
                identity = (result.prerequisite.profile_id, result.prerequisite.id)
                if identity not in seen:
                    seen.add(identity)
                    results.append(result)
    if preparations_recorded:
        commit_prerequisite_preparation(root)
    return tuple(results)


def _validate_preparation_contracts(
    root: Path,
    profile: Profile,
    prerequisites: tuple[Prerequisite, ...],
    operation: PrerequisiteOperation,
) -> None:
    for prerequisite in prerequisites:
        if not prerequisite.prepare:
            continue
        if prerequisite.prepare_kind == "workspace_local":
            for output in prerequisite.prepare_outputs:
                tracked = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "--", output],
                    cwd=root,
                    capture_output=True,
                    check=False,
                )
                ignored = subprocess.run(
                    ["git", "check-ignore", "-q", "--", output],
                    cwd=root,
                    check=False,
                )
                if tracked.returncode == 0 or ignored.returncode != 0:
                    raise ValueError(
                        f"prerequisite {prerequisite.reference} preparation output "
                        f"must be ignored and untracked: {output}"
                    )
        elif not any(
            operation.value in reference.required_for for reference in profile.test_services
        ):
            raise ValueError(
                f"prerequisite {prerequisite.reference} owned_service preparation "
                f"requires a managed service for {operation.value}"
            )


def _git_visible_preparation_state(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return {
        line
        for line in result.stdout.splitlines()
        if ".devlab/logs/environment/prerequisite-" not in line
        and ".devlab/workflow-events.jsonl" not in line
    }


def _record_prerequisite_blocker(
    workspace: Workspace,
    route: SessionRoute,
    operation: PrerequisiteOperation,
    results: tuple[PrerequisiteResult, ...],
    *,
    command: str = "implement",
    commit: bool = True,
) -> str:
    blocked = tuple(item for item in results if item.blocks)
    changed = workspace.prerequisites().record_blocker(
        command=command,
        role=route.role_name,
        task=route.task_id or "",
        milestone=route.milestone_id or "",
        operation=operation,
        results=blocked,
    )
    if changed:
        append_workflow_event(
            workspace.root,
            "prerequisite_blocked",
            command=command,
            role=route.role_name,
            task=route.task_id or "",
            milestone=route.milestone_id or "",
            operation=operation.value,
            prerequisites=[item.prerequisite.reference for item in blocked],
        )
        if commit:
            commit_all(workspace.root, "Record blocked workflow prerequisites")
    references = ", ".join(item.prerequisite.reference for item in blocked)
    return (
        f"{operation.value} prerequisites are not satisfied for "
        f"{route.task_id or route.milestone_id or route.role_name}: {references}"
    )


def _clear_resolved_prerequisite_blocker(
    workspace: Workspace, route: SessionRoute, operation: PrerequisiteOperation
) -> None:
    blocker = FilePrerequisiteTracker(workspace.root).read_blocker()
    if blocker is None:
        return
    if (
        blocker.role == route.role_name
        and blocker.task == (route.task_id or "")
        and blocker.milestone == (route.milestone_id or "")
        and blocker.operation == operation
    ):
        workspace.prerequisites().clear_blocker()
        append_workflow_event(
            workspace.root,
            "prerequisite_resolved",
            role=route.role_name,
            task=route.task_id or "",
            milestone=route.milestone_id or "",
            operation=operation.value,
        )
        commit_all(workspace.root, "Record resolved workflow prerequisites")


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
    return any(task.status != TaskStatus.CLOSED for task in snapshot.current_generation_tasks())


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


def _agent_error_message(ctx: SessionContext, result: AgentResult, config_log: Path | None) -> str:
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
    if result.inactivity_timeout_seconds is not None:
        details.append(f"inactivity_timeout_seconds={result.inactivity_timeout_seconds}")
    if result.timeout_kind is not None:
        details.append(f"timeout_kind={result.timeout_kind}")
    if result.inactive_seconds_at_stop is not None:
        details.append(f"inactive_at_stop={result.inactive_seconds_at_stop:.1f}s")
    details.extend(_log_path_details(ctx.stdout_log, ctx.stderr_log, config_log))
    details.extend(_log_command_details(ctx.stdout_log, ctx.stderr_log, config_log))
    return "; ".join(details)


def _handoff_error_message(ctx: SessionContext, error: str, config_log: Path | None) -> str:
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


def _changed_snapshot_paths(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
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
        stdout_log=agent_log_path(ctx.root, correction_id, "stdout.log"),
        stderr_log=agent_log_path(ctx.root, correction_id, "stderr.log"),
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
        edit_instruction = f"Edit only {ARTIFACTS_DIR}/{ctx.role_name}/{HANDOFF_CANDIDATE_FILE}"
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
        'run `"$DEVLAB_PYTHON" -m devlab.cli session handoff submit`. '
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
            if task_before is not None and _only_acceptance_boxes_checked(task_before, task_after):
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
    dependency_baseline: DependencySnapshot | None = None,
) -> SessionMetadata:
    provider = ""
    model = ""
    provider_version = ""
    inactivity_timeout_seconds = agent_result.inactivity_timeout_seconds
    max_session_duration_seconds = agent_result.max_session_duration_seconds
    if resolved_agent_configs is not None and ctx.role_name in resolved_agent_configs:
        config = resolved_agent_configs[ctx.role_name]
        provider = config.provider
        model = config.model
        provider_version = config.provider_version
        if inactivity_timeout_seconds is None:
            inactivity_timeout_seconds = config.inactivity_timeout_seconds
        if max_session_duration_seconds is None:
            max_session_duration_seconds = config.max_session_duration_seconds
    return SessionMetadata(
        invocation_id=ctx.invocation_id,
        test_service_instances=ctx.service_instances,
        session_number=ctx.session_number,
        role_name=ctx.role_name,
        provider=provider,
        model=model,
        return_code=agent_result.return_code,
        failure_kind=agent_result.failure_kind,
        duration_seconds=agent_result.duration_seconds,
        task_id=task_id or "",
        timeout_kind=agent_result.timeout_kind or "",
        inactivity_timeout_seconds=inactivity_timeout_seconds,
        max_session_duration_seconds=max_session_duration_seconds,
        inactive_seconds_at_stop=agent_result.inactive_seconds_at_stop,
        provider_version=provider_version,
        executable_config_digest=(
            executable_config.digest if executable_config is not None else ""
        ),
        executable_config_authorization=(
            executable_config.authorization.source.value
            if executable_config is not None and executable_config.authorization is not None
            else ""
        ),
        progress=progress.value if progress is not None else "",
        dependency_introductions=tuple(
            dataclasses.asdict(item)
            for item in introduced_dependencies(
                dependency_baseline,
                snapshot_direct_dependencies(ctx.root),
            )
        )
        if dependency_baseline is not None
        else (),
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
    if process_result.research_id is not None:
        return SessionProgress.LEGITIMATE_STOP
    after_tasks = {task.id: _task_progress_state(task) for task in after.list_tasks()}
    after_milestones = {milestone.id: milestone for milestone in after.list_milestones()}
    after_findings = tuple(_finding_progress_state(item) for item in after.list_findings())
    if (
        before.tasks != after_tasks
        or before.milestones != after_milestones
        or before.workflow_state != after.workflow_state()
        or before.findings != after_findings
    ):
        return SessionProgress.WORKFLOW_ADVANCE
    return SessionProgress.NON_ADVANCING


def _session_progress_baseline(snapshot: WorkspaceSnapshot) -> SessionProgressBaseline:
    return SessionProgressBaseline(
        tasks={task.id: _task_progress_state(task) for task in snapshot.list_tasks()},
        milestones={milestone.id: milestone for milestone in snapshot.list_milestones()},
        workflow_state=snapshot.workflow_state(),
        findings=tuple(_finding_progress_state(item) for item in snapshot.list_findings()),
    )


def _task_progress_state(task: Task) -> tuple[object, ...]:
    """Return task facts that change its executable workflow contract or state."""
    return (
        task.title,
        task.status,
        task.milestone,
        task.profile,
        task.domain,
        task.depends_on,
        task.addresses_findings,
        task.validation,
        task.acceptance_criteria_complete,
        task.review_approved,
    )


def _finding_progress_state(finding: Finding) -> tuple[object, ...]:
    """Ignore prose-only finding edits while retaining lifecycle transitions."""
    return (
        finding.id,
        finding.title,
        finding.status,
        finding.source,
        finding.milestone,
        finding.handoff,
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


def _latest_validation_record(root: Path, task_id: str) -> dict[str, object] | None:
    records = sorted((root / ".devlab/verification/tasks" / task_id).glob("*.json"))
    for path in reversed(records):
        try:
            return cast("dict[str, object]", json.loads(path.read_text()))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    return None


def _latest_validation_failure(root: Path, task_id: str) -> dict[str, object] | None:
    data = _latest_validation_record(root, task_id)
    if data is not None and data.get("source") == "task" and data.get("outcome") == "failed":
        return data
    return None


def _retry_unverified_task_validation(
    workspace: Workspace,
    profiles: dict[str, Profile],
    services: _TestServicePreparation,
) -> tuple[RunStopReason, str] | None:
    task = workspace.snapshot.select_next_review_task()
    if task is None:
        return None
    previous = _latest_validation_record(workspace.root, task.id)
    blocker = FilePrerequisiteTracker(workspace.root).read_blocker()
    prerequisite_retry = (
        blocker is not None
        and blocker.task == task.id
        and blocker.operation == PrerequisiteOperation.VALIDATION
    )
    retry_profile = profile_from_snapshot(profiles, task.profile, root=workspace.root)
    required_services = {
        ref.service.id for ref in retry_profile.test_services if "validation" in ref.required_for
    }
    service_retry = any(
        record["service"] in required_services and record["state"] == "failed"
        for record in workspace.snapshot.test_service_records()
    )
    if (
        not prerequisite_retry
        and not service_retry
        and (
            previous is None
            or previous.get("outcome")
            not in {
                "missing_tool",
                "timeout",
                "infrastructure_error",
            }
        )
    ):
        return None
    profile = profile_from_snapshot(profiles, task.profile, root=workspace.root)
    route = SessionRoute("developer", task=task)
    service_environment = services.prepare((profile,), ("validation",))
    prerequisite_results = _resolve_profile_prerequisites(
        workspace.root, (profile,), PrerequisiteOperation.VALIDATION, service_environment
    )
    if any(item.blocks for item in prerequisite_results):
        message = _record_prerequisite_blocker(
            workspace, route, PrerequisiteOperation.VALIDATION, prerequisite_results
        )
        return RunStopReason.PREREQUISITE_BLOCKED, message
    _clear_resolved_prerequisite_blocker(workspace, route, PrerequisiteOperation.VALIDATION)
    validation = effective_validation(task, profile)
    run = run_validation_commands(
        workspace.root,
        role_name="orchestrator",
        task_id=task.id,
        session_id=f"{_timestamp()}_validation_retry",
        commands=validation.commands,
        source=validation.source,
        timeout=profile.environment.timeouts.setup,
        environ=service_environment,
        recovery_of=str(previous.get("session_id") or "") if previous is not None else "",
    )
    if run.outcome in {"passed", "not_configured"}:
        return None
    if run.outcome == "failed":
        if validation.source == "task" and run.commands:
            failed = run.commands[-1]
            workspace.tasks().get(task.id).record_validation_failure(
                f"{failed.command!r} ({failed.outcome}); see {failed.log_path}"
            )
        return None
    reason = (
        RunStopReason.VALIDATION_PREREQUISITE_MISSING
        if run.outcome == "missing_tool"
        else RunStopReason.VALIDATION_INFRASTRUCTURE_ERROR
    )
    return reason, f"task {task.id} validation {run.outcome}"


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
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
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
    return f"clarification resolver changed paths outside its allowed file-edit set: {joined}"


def _resolver_repair_guidance(clarification_id: str, command: str) -> str:
    return (
        f"Clarification {clarification_id} remains pending with its resume pointer. "
        f"Repair the resolver output and rerun `devlab {command} --unattended`, or "
        f"answer it with `devlab clarify answer {clarification_id} --resume`."
    )


def _parse_resolver_answer(root: Path, path: Path, clarification: Clarification) -> str:
    if not path.exists():
        raise HandoffError(
            f"clarification resolver did not write {path.relative_to(root).as_posix()}"
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
            f"clarification resolver answer.json clarification_id must be {clarification.id!r}"
        )
    answer_shape = clarification.answer_shape.value
    if data.get("answer_shape") != answer_shape:
        raise HandoffError(
            f"clarification resolver answer.json answer_shape must be {answer_shape!r}"
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

    ctx = build_session_context(
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
        guidance = _resolver_repair_guidance(clarification_id, workflow_state.resume.command)
        return SessionError("clarification_resolver", f"{edit_error}. {guidance}", 1), True
    if not agent_result.succeeded:
        message = _agent_error_message(ctx, agent_result, None)
        guidance = _resolver_repair_guidance(clarification_id, workflow_state.resume.command)
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
        message = _resolver_repair_guidance(clarification_id, workflow_state.resume.command)
        return SessionError("clarification_resolver", f"{exc}. {message}", 1), True

    _notify_session_progress(
        session_progress, "finish", ctx.session_number, CLARIFICATION_RESOLVER_ROLE
    )
    logger.info("Finished session %s: %s", ctx.session_number, CLARIFICATION_RESOLVER_ROLE)
    return None, True


def _research_result_path(root: Path) -> Path:
    return root / ARTIFACTS_DIR / RESEARCHER_ROLE / "result.json"


def _researcher_file_contents(root: Path) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    exclusions = (".git/", f"{AGENT_LOG_DIR}/", f"{ARTIFACTS_DIR}/{RESEARCHER_ROLE}/")
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if any(
            relative == prefix.rstrip("/") or relative.startswith(prefix) for prefix in exclusions
        ):
            continue
        contents[relative] = path.read_bytes()
    return contents


def _restore_researcher_edits(root: Path, before: dict[str, bytes]) -> tuple[str, ...]:
    after = _researcher_file_contents(root)
    changed = tuple(
        sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    )
    for relative in changed:
        path = root / relative
        original = before.get(relative)
        if original is None:
            if path.exists() or path.is_symlink():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                path.unlink()
            path.write_bytes(original)
    return changed


def _researcher_provider(
    blocked_role: str,
    agent_providers: dict[str, AgentProvider],
    role_agent_providers: dict[str, str] | None,
) -> tuple[AgentProvider, str]:
    selected_role = (
        RESEARCHER_ROLE
        if role_agent_providers is not None and RESEARCHER_ROLE in role_agent_providers
        else blocked_role
    )
    provider = provider_for_role(selected_role, agent_providers, role_agent_providers)
    provider_name = (
        role_agent_providers.get(selected_role, "default")
        if role_agent_providers is not None
        else "default"
    )
    return provider, provider_name


def _invoke_researcher(
    root: Path,
    *,
    research_id: str,
    session_number: int,
    agent_providers: dict[str, AgentProvider],
    role_agent_providers: dict[str, str] | None,
    resolved_agent_configs: dict[str, ResolvedAgentConfig] | None,
    retain_prompts: bool,
    session_progress: SessionProgressCallback | None,
    executable_config: ExecutableConfigSnapshot | None,
) -> SessionError | None:
    workspace = Workspace(root)
    resume = load_workflow_state(root).resume
    if resume is None or resume.blocked_kind != "research" or resume.blocked_by != research_id:
        return SessionError(
            "researcher", "Cannot run researcher without its matching resume pointer.", 1
        )
    try:
        research = workspace.snapshot.get_research(research_id)
    except KeyError:
        return SessionError("researcher", f"Cannot resolve unknown research {research_id}.", 1)
    if research.status != ResearchStatus.REQUESTED:
        return SessionError("researcher", f"Research {research_id} is not requested.", 1)

    artifacts_dir = root / ARTIFACTS_DIR / RESEARCHER_ROLE
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    ctx = build_session_context(
        root, session_number, RESEARCHER_ROLE, retain_prompts=retain_prompts
    )
    base_prompt = read_prompt_resource("role-researcher.md")
    session_prompt = build_researcher_prompt(workspace.snapshot, research, resume)
    ctx.write_prompt_logs(base_prompt, session_prompt)
    invocation = ctx.build_invocation(base_prompt, session_prompt)
    agent_provider, fallback_provider_name = _researcher_provider(
        resume.role, agent_providers, role_agent_providers
    )
    selected_config = None
    if resolved_agent_configs is not None:
        selected_config = resolved_agent_configs.get(
            RESEARCHER_ROLE
        ) or resolved_agent_configs.get(resume.role)
    config_log = ctx.log_resolved_config(selected_config) if selected_config is not None else None
    if selected_config is not None:
        preflight_error = _preflight_agent_executable(RESEARCHER_ROLE, selected_config)
        if preflight_error is not None:
            return preflight_error
    try:
        before = _researcher_file_contents(root)
    except OSError as exc:
        return SessionError("researcher", f"Cannot snapshot workspace before researcher: {exc}", 1)

    logger.info("Starting session %s: %s", ctx.session_number, RESEARCHER_ROLE)
    _notify_session_progress(session_progress, "start", ctx.session_number, RESEARCHER_ROLE)
    try:
        agent_result = invoke_session(invocation, agent_provider=agent_provider)
    except ProviderError as exc:
        agent_result = AgentResult(
            return_code=1,
            failure_kind="provider_error",
            message=f"agent provider error: {exc}",
        )
    metadata_configs = {RESEARCHER_ROLE: selected_config} if selected_config is not None else None
    ctx.write_session_metadata(
        _build_session_metadata(ctx, agent_result, metadata_configs, None, executable_config)
    )
    try:
        changed = _restore_researcher_edits(root, before)
    except OSError as exc:
        return SessionError("researcher", f"Cannot validate researcher file edits: {exc}", 1)
    if changed:
        return SessionError(
            "researcher",
            "researcher changed forbidden workspace path(s), which were restored: "
            + ", ".join(changed),
            1,
        )
    if not agent_result.succeeded:
        return SessionError(
            "researcher",
            _agent_error_message(ctx, agent_result, config_log),
            agent_result.return_code or 1,
        )
    try:
        result = parse_research_result_candidate(
            _research_result_path(root), research_id=research_id
        )
        provider_name = (
            selected_config.provider if selected_config is not None else fallback_provider_name
        )
        model_name = selected_config.model if selected_config is not None else ""
        workspace.research().get(research_id).complete(
            result,
            researcher_session_id=ctx.invocation_id,
            researcher_provider=provider_name,
            researcher_model=model_name,
        )
        append_workflow_event(
            root,
            "research_completed",
            research=research_id,
            role=resume.role,
            command=resume.command,
            task=resume.task,
            milestone=resume.milestone,
        )
    except (OSError, ValueError) as exc:
        return SessionError("researcher", str(exc), 1)
    _notify_session_progress(session_progress, "finish", ctx.session_number, RESEARCHER_ROLE)
    logger.info("Finished session %s: %s", ctx.session_number, RESEARCHER_ROLE)
    return None


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
        repair = f"{reason} Run `devlab plan --revise` to reconcile workflow state."
        if resume.blocked_kind == "clarification":
            repair += (
                " Or supersede the clarification with `devlab clarify supersede "
                f"{resume.blocked_by} --reason ...` if the interrupted work is obsolete."
            )
        return SessionError(
            f"{resume.blocked_kind}_resume",
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
            return error(f"Interrupted task {resume.task} is {task.status.value}, not in_review.")
        if role_name != resume.role:
            selected = role_name or "no role"
            return error(
                f"Current workflow selection is {selected}, so DevLab will not "
                "resume a different route."
            )
        if task_id != resume.task:
            selected = task_id or "none"
            return error(f"Next review task is {selected}, not interrupted task {resume.task}.")

    elif resume.role in {"integrator", "architect"} and resume.milestone:
        current_milestone = (
            snapshot.select_integration_milestone()
            if resume.role == "integrator"
            else snapshot.select_architecture_review_milestone()
        )
        if current_milestone != resume.milestone:
            selected = current_milestone or "none"
            return error(
                f"Current eligible milestone is {selected}, not interrupted "
                f"milestone {resume.milestone}."
            )
        if role_name != resume.role:
            selected = role_name or "no role"
            return error(
                f"Current workflow selection is {selected}, so DevLab will not "
                "resume a different route."
            )
        if milestone_id != resume.milestone:
            selected = milestone_id or "none"
            return error(
                f"Selected milestone is {selected}, not interrupted milestone {resume.milestone}."
            )

    elif role_name != resume.role:
        selected = role_name or "no role"
        return error(
            f"Current workflow selection is {selected}, so DevLab will not resume "
            "a different route."
        )

    return None


def _research_record_resume_error(research: Research, resume: ResumeState) -> SessionError | None:
    pairs = (
        ("command", research.command, resume.command),
        ("role", research.asking_role, resume.role),
        ("task", research.task, resume.task),
        ("milestone", research.milestone, resume.milestone),
    )
    for field, record_value, pointer_value in pairs:
        if record_value != pointer_value:
            return SessionError(
                "research_resume",
                f"research {research.id} {field} {record_value!r} does not match "
                f"resume pointer value {pointer_value!r}",
                1,
            )
    expected_scope = (
        f"task:{resume.task}"
        if resume.task
        else f"milestone:{resume.milestone}"
        if resume.milestone
        else "planning"
        if resume.command == "plan"
        else "workspace"
    )
    if research.scope != expected_scope:
        return SessionError(
            "research_resume",
            f"research {research.id} scope {research.scope!r} does not match "
            f"resume route scope {expected_scope!r}",
            1,
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
                dataclasses.replace(agent_result, message=f"agent provider error: {exc}"),
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


class _TestServicePreparation:
    def __init__(
        self, root: Path, stack: ExitStack, config: ExecutableConfigSnapshot | None
    ) -> None:
        self.root = root
        self.stack = stack
        self.config = config
        self.locked = False
        self.sessions_run = 0
        self.exports: dict[str, dict[str, str]] = {}
        self.duration_seconds = 0.0

    def prepare(
        self,
        profiles: tuple[Profile, ...],
        operations: tuple[str, ...],
        role_name: str | None = None,
    ) -> dict[str, str]:
        services = {}
        for profile in profiles:
            applicable = set(operations)
            if role_name is not None and role_name not in profile.environment.managed_roles:
                applicable.discard("setup")
            for ref in profile.test_services:
                if applicable.intersection(ref.required_for):
                    services[ref.service.id] = ref.service
        if not services:
            return {}
        if (
            self.config is None
            or self.config.authorization is None
            or (self.config.authorization.digest != self.config.digest)
        ):
            raise TestServiceError(
                "managed test services require authorized executable configuration"
            )
        if self.config.root.resolve() != self.root.resolve():
            raise TestServiceError("test service authorization belongs to another workspace")
        names: set[str] = set()
        for service in services.values():
            if self.config.test_services.get(service.id) != service:
                raise TestServiceError("test service is absent from the authorized snapshot")
            if names.intersection(service.exports):
                raise TestServiceError("conflicting exports from required test services")
            names.update(service.exports)
        if not self.locked:
            self.stack.enter_context(test_service_lock(self.root))
            self.locked = True
        started = time.monotonic()
        try:
            for service_id, service in sorted(services.items()):
                self.exports[service_id] = Workspace(self.root).test_services().ensure(service)
        except (OSError, VersionControlError) as exc:
            raise TestServiceError(
                f"test service infrastructure failed: {type(exc).__name__}"
            ) from exc
        finally:
            self.duration_seconds += time.monotonic() - started
        return self.environment(tuple(services))

    def environment(self, service_ids: tuple[str, ...]) -> dict[str, str]:
        return {
            key: value
            for service_id in service_ids
            for key, value in self.exports[service_id].items()
        }


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
    """Keep owned test services locked across preparation and dependent execution."""
    with ExitStack() as stack:
        services = _TestServicePreparation(root, stack, executable_config)
        try:
            result = _run_loop(
                root,
                services=services,
                max_sessions=max_sessions,
                provider=provider,
                model=model,
                effort=effort,
                retain_prompts=retain_prompts,
                agent_providers=agent_providers,
                role_agent_providers=role_agent_providers,
                planning_only=planning_only,
                revise_plan=revise_plan,
                replace_plan=replace_plan,
                adopt_existing=adopt_existing,
                mark_specs_planned=mark_specs_planned,
                clarification_mode=clarification_mode,
                handoff_correction=handoff_correction,
                session_progress=session_progress,
                executable_config=executable_config,
            )
        except TestServiceError as exc:
            result = _error_result(
                services.sessions_run, SessionError("test_service", str(exc), 1)
            )
        return dataclasses.replace(
            result, test_service_duration_seconds=round(services.duration_seconds, 3)
        )


def _run_loop(
    root: Path,
    *,
    max_sessions: int,
    services: _TestServicePreparation,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    retain_prompts: bool = False,
    agent_providers: dict[str, AgentProvider] | None = None,
    role_agent_providers: dict[str, str] | None = None,
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
    """Run the Git-backed orchestrator loop, returning a structured result."""
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
    last_completed_task_id: str | None = None
    spec_status: SpecReconciliationStatus
    workflow_state: WorkflowState
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
    if not planning_only and spec_status.changed:
        error = _stale_specs_error(spec_status)
        logger.error("%s. Stopping.", error.message)
        return _error_result(0, error)

    if mark_specs_planned:
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
    completed_resume_research: Research | None = None
    if active_resume is not None and active_resume.blocked_kind == "research":
        try:
            research = workspace.snapshot.get_research(active_resume.blocked_by)
        except KeyError:
            message = f"research resume pointer references missing {active_resume.blocked_by}"
            return _error_result(0, SessionError("research_resume", message, 1))
        record_resume_error = _research_record_resume_error(research, active_resume)
        if record_resume_error is not None:
            return _error_result(0, record_resume_error)
        if research.status == ResearchStatus.COMPLETED:
            completed_resume_research = research
        else:
            try:
                commit_all(root, f"Record DevLab research request {research.id}")
            except VersionControlError as exc:
                return _error_result(0, SessionError("version_control", str(exc), 1))
        if completed_resume_research is None:
            researcher_error = _invoke_researcher(
                root,
                research_id=research.id,
                session_number=1,
                agent_providers=agent_providers,
                role_agent_providers=role_agent_providers,
                resolved_agent_configs=resolved_agent_configs,
                retain_prompts=retain_prompts,
                session_progress=session_progress,
                executable_config=executable_config,
            )
            if researcher_error is not None:
                return _error_result(1, researcher_error)
            try:
                commit_all(root, f"Complete DevLab research {research.id}")
            except VersionControlError as exc:
                return _error_result(1, SessionError("version_control", str(exc), 1))
            sessions_run = 1
            workspace = Workspace(root)
            active_resume = load_workflow_state(root).resume
            completed_resume_research = workspace.snapshot.get_research(research.id)
            if sessions_run >= max_sessions:
                return _stop_result(sessions_run, RunStopReason.RESEARCH_COMPLETED)

    reconcile_plan = spec_status.changed
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
                spec_baseline=spec_status.baseline_spec_commit,
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
            committed = commit_all(root, f"Archive DevLab generation {manifest.generation}")
            if committed:
                logger.info("Committed DevLab generation archive")
        except OSError as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(0, SessionError("generation_archive", str(exc), 1))
    forced_planning_roles = (
        ("architect", "planner") if revise_plan or fresh_generation_plan or adopt_existing else ()
    )
    # Supporting sessions consume the invocation budget, but only completed
    # planning roles advance this sequence. Resume from the durable route.
    completed_planning_roles = (
        forced_planning_roles.index(active_resume.role)
        if active_resume is not None
        and active_resume.command == requested_command == "plan"
        and active_resume.role in forced_planning_roles
        else 0
    )
    planning_update = PlanningStateUpdate(
        last_planned_spec_commit=(
            spec_status.latest_spec_commit
            if planning_only or not spec_status.baseline_exists
            else None
        ),
    )
    plan_started_recorded = False

    while sessions_run < max_sessions:
        prior_task_still_active = last_completed_task_id is not None and any(
            task.id == last_completed_task_id and task.status != TaskStatus.CLOSED
            for task in workspace.snapshot.list_tasks()
        )
        if sessions_run > 0 and not prior_task_still_active and executable_config is not None:
            try:
                current_executable_config = build_executable_config_snapshot(
                    root,
                    config_path=(
                        None
                        if executable_config.config_path == (root / AGENTS_CONFIG).resolve()
                        else executable_config.config_path
                    ),
                    provider=executable_config.provider_override,
                    model=executable_config.model_override,
                    effort=executable_config.effort_override,
                )
            except (OSError, ValueError, KeyError) as exc:
                message = f"executable configuration changed and is now invalid: {exc}"
                logger.error("%s. Stopping before another session.", message)
                return _error_result(
                    sessions_run,
                    SessionError("executable_configuration", message, 1),
                )
            if current_executable_config.digest != executable_config.digest:
                logger.info(
                    "Executable configuration changed from %s to %s. "
                    "Stopping before another session for renewed authorization.",
                    executable_config.digest,
                    current_executable_config.digest,
                )
                return _stop_result(
                    sessions_run,
                    RunStopReason.EXECUTABLE_CONFIG_CHANGED,
                )
        try:
            assert_clean_worktree(root)
        except VersionControlError as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(sessions_run, SessionError("version_control", str(exc), 1))
        if not planning_only:
            retry_profiles = (
                frozen_profiles if frozen_profiles is not None else load_profiles(root)
            )
            retry_stop = _retry_unverified_task_validation(workspace, retry_profiles, services)
            if retry_stop is not None:
                reason, message = retry_stop
                logger.error("%s. Stopping.", message)
                return _error_result(
                    sessions_run,
                    SessionError("task_validation", message, 1),
                    reason=reason,
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
        research_resume_active = (
            completed_resume_research is not None
            and active_resume is not None
            and active_resume.blocked_kind == "research"
        )
        if research_resume_active:
            role_name = active_resume.role
        elif (
            planning_only and not revise_plan and not fresh_generation_plan and not adopt_existing
        ):
            role_name = workspace.snapshot.assess_state()
        else:
            workspace.sync()
            role_name = (
                forced_planning_roles[completed_planning_roles]
                if completed_planning_roles < len(forced_planning_roles)
                else workspace.snapshot.assess_state()
            )
        selected_task = (
            _task_by_id(workspace.snapshot, active_resume.task)
            if research_resume_active and active_resume.task
            else _task_for_role(workspace.snapshot, role_name)
            if role_name
            else None
        )
        selected_task_id = selected_task.id if selected_task is not None else None
        selected_milestone_id = (
            active_resume.milestone or None
            if research_resume_active
            else workspace.snapshot.select_integration_milestone()
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
                    "No task is eligible; remaining development tasks are blocked by dependencies."
                )
                reason = RunStopReason.NO_ELIGIBLE_ROLE
            else:
                logger.info("All milestones complete or no task can proceed.")
                reason = RunStopReason.WORKFLOW_COMPLETE
            logger.info("Stopping.")
            return _stop_result(sessions_run, reason)

        if (
            not planning_only
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
                if not spec_status.baseline_exists:
                    try:
                        update_workflow_state(
                            root,
                            last_planned_spec_commit=spec_status.latest_spec_commit,
                        )
                        workspace.did_mutate()
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
            and completed_planning_roles >= len(forced_planning_roles)
        ):
            logger.info("Planning revision complete; stopping before implementation roles.")
            return _stop_result(sessions_run, RunStopReason.COMMAND_COMPLETE)

        if resolved_agent_configs is not None:
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
            if role_name == "planner" and (planning_only or not spec_status.baseline_exists)
            else None
        )
        route = (
            _select_resume_route(start_snapshot, active_resume)
            if research_resume_active
            else _select_session_route(start_snapshot, role_name)
        )
        progress_baseline = _session_progress_baseline(start_snapshot)
        non_advancing_recovery = role_name == "developer" and _is_non_advancing_recovery(
            root, route
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
        try:
            available_profiles = (
                frozen_profiles if frozen_profiles is not None else load_profiles(root)
            )
            route_profiles = _profiles_for_route(root, start_snapshot, route, available_profiles)
            services.sessions_run = sessions_run
            service_operations = ["session"]
            if role.needs_environment:
                service_operations.append("setup")
            if role_name in {"developer", "integrator"}:
                service_operations.append("validation")
            service_environment = services.prepare(
                route_profiles, tuple(service_operations), role_name
            )

            prerequisite_results = _resolve_profile_prerequisites(
                root, route_profiles, PrerequisiteOperation.SESSION, service_environment
            )
        except TestServiceError:
            raise
        except ProfileNotFoundError as exc:
            return _error_result(sessions_run, SessionError("profile_resolution", str(exc), 1))
        except (OSError, ValueError) as exc:
            return _error_result(
                sessions_run, SessionError("prerequisite_configuration", str(exc), 1)
            )
        if any(item.blocks for item in prerequisite_results):
            try:
                message = _record_prerequisite_blocker(
                    workspace,
                    route,
                    PrerequisiteOperation.SESSION,
                    prerequisite_results,
                    command=requested_command,
                )
            except (OSError, ValueError, VersionControlError) as exc:
                return _error_result(
                    sessions_run, SessionError("prerequisite_recording", str(exc), 1)
                )
            logger.info("%s. Stopping before agent invocation.", message)
            return _stop_result(
                sessions_run,
                RunStopReason.PREREQUISITE_BLOCKED,
                (SessionError("prerequisite", message, 0),),
            )
        _clear_resolved_prerequisite_blocker(workspace, route, PrerequisiteOperation.SESSION)
        setup_results = (
            _resolve_profile_prerequisites(
                root,
                tuple(
                    profile
                    for profile in route_profiles
                    if role.needs_environment and role_name in profile.environment.managed_roles
                ),
                PrerequisiteOperation.SETUP,
                service_environment,
            )
            if role.needs_environment
            else ()
        )
        if any(item.blocks for item in setup_results):
            try:
                message = _record_prerequisite_blocker(
                    workspace,
                    route,
                    PrerequisiteOperation.SETUP,
                    setup_results,
                    command=requested_command,
                )
            except (OSError, ValueError, VersionControlError) as exc:
                return _error_result(
                    sessions_run, SessionError("prerequisite_recording", str(exc), 1)
                )
            logger.info("%s. Stopping before environment setup.", message)
            return _stop_result(
                sessions_run,
                RunStopReason.PREREQUISITE_BLOCKED,
                (SessionError("prerequisite", message, 0),),
            )
        _clear_resolved_prerequisite_blocker(workspace, route, PrerequisiteOperation.SETUP)
        validation_results = (
            _resolve_profile_prerequisites(
                root, route_profiles, PrerequisiteOperation.VALIDATION, service_environment
            )
            if role_name in {"developer", "integrator"}
            else ()
        )
        if any(item.blocks for item in validation_results):
            try:
                message = _record_prerequisite_blocker(
                    workspace,
                    route,
                    PrerequisiteOperation.VALIDATION,
                    validation_results,
                    command=requested_command,
                )
            except (OSError, ValueError, VersionControlError) as exc:
                return _error_result(
                    sessions_run, SessionError("prerequisite_recording", str(exc), 1)
                )
            logger.info("%s. Stopping before agent invocation.", message)
            return _stop_result(
                sessions_run,
                RunStopReason.PREREQUISITE_BLOCKED,
                (SessionError("prerequisite", message, 0),),
            )
        _clear_resolved_prerequisite_blocker(workspace, route, PrerequisiteOperation.VALIDATION)
        ctx = build_session_context(
            root,
            sessions_run + 1,
            role_name,
            retain_prompts=retain_prompts,
        )
        ctx = dataclasses.replace(
            ctx,
            service_environment=service_environment,
            service_instances={
                record["service"]: record["instance"]
                for record in Workspace(root).snapshot.test_service_records()
                if record["service"]
                in {
                    ref.service.id
                    for profile in route_profiles
                    for ref in profile.test_services
                    if set(service_operations).intersection(ref.required_for)
                }
            },
        )
        config_log: Path | None = None

        try:
            snapshot = workspace.snapshot
            base_prompt = build_base_prompt(root, role, snapshot=snapshot, role_name=role_name)
            session_prompt = build_session_prompt(
                snapshot,
                role_name,
                completed_research=(completed_resume_research if research_resume_active else None),
                assigned_task=route.task,
                assigned_milestone=route.milestone_id,
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
                session_prompt += "\n\n" + _validation_recovery_prompt(prior_validation_failure)
            environment = _environment_for_session(
                root,
                snapshot,
                role_name,
                frozen_profiles,
                route.task,
            )
        except ProfileNotFoundError as exc:
            logger.error("%s. Stopping.", exc)
            return _error_result(sessions_run, SessionError("profile_resolution", str(exc), 1))
        environment.environ = service_environment
        agent_provider = provider_for_role(role_name, agent_providers, role_agent_providers)

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
                protected_active_tasks=tuple(task.id for task in start_snapshot.active_tasks()),
                incremental_planning_required=(
                    role_name == "planner" and _needs_incremental_planning(start_snapshot)
                ),
                allow_active_task_replacement=fresh_generation_plan,
            ),
        )
        ctx.write_prompt_logs(base_prompt, session_prompt)
        dependency_baseline = snapshot_direct_dependencies(root)

        lifecycle = _invoke_role_agent(
            ctx,
            role,
            environment,
            agent_provider,
            base_prompt,
            session_prompt,
            config_log,
        )
        services.sessions_run = sessions_run + 1
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
                dependency_baseline=dependency_baseline,
            )
            ctx.write_session_metadata(metadata)
            return _error_result(sessions_run, primary_error, *lifecycle.errors[1:])

        workspace.did_mutate()

        result_path = artifacts_dir / SESSION_RESULT_FILE
        if not result_path.exists():
            submission_issues: tuple[str, ...]
            submission_reason = HandoffFailureReason.CONTRACT
            try:
                submit_session_handoff(root, envelope_path=artifacts_dir / SESSION_ENVELOPE_FILE)
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
                        dependency_baseline=dependency_baseline,
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
            if handoff.clarification_request is None and handoff.research_request is None:
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
                if role_name == "planner":
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
                dependency_baseline=dependency_baseline,
            )
            ctx.write_session_metadata(metadata)
            return _error_result(sessions_run, SessionError("handoff_validation", message, 1))

        commit_message = _commit_message(workspace.snapshot, handoff)
        milestone_validation: ValidationRun | None = None
        milestone_validation_contract: EffectiveMilestoneValidation | None = None
        if role_name == "integrator" and route.milestone_id is not None:
            profiles = frozen_profiles if frozen_profiles is not None else load_profiles(root)
            milestone_tasks = workspace.snapshot.tasks_for_milestone(route.milestone_id)
            milestone_validation_contract = effective_milestone_validation(
                milestone_tasks, profiles, root=root
            )
            service_validation_error = ""
            try:
                service_environment = services.prepare(route_profiles, ("validation",))
            except TestServiceError as exc:
                service_validation_error = str(exc)
            boundary_results = (
                ()
                if service_validation_error
                else _resolve_profile_prerequisites(
                    root, route_profiles, PrerequisiteOperation.VALIDATION, service_environment
                )
            )
            if any(item.blocks for item in boundary_results):
                archive_handoff(root, role_name)
                workspace.did_mutate()
                message = _record_prerequisite_blocker(
                    workspace,
                    route,
                    PrerequisiteOperation.VALIDATION,
                    boundary_results,
                    command=requested_command,
                    commit=False,
                )
                progress = _classify_session_progress(
                    root, progress_baseline, workspace.snapshot, ProcessResult()
                )
                append_workflow_event(
                    root,
                    "session_progress",
                    role=role_name,
                    task=route.task_id or "",
                    milestone=route.milestone_id,
                    progress=progress.value,
                )
                ctx.write_session_metadata(
                    _build_session_metadata(
                        ctx,
                        agent_result,
                        resolved_agent_configs,
                        route.task_id,
                        executable_config,
                        progress,
                        dependency_baseline,
                    )
                )
                try:
                    workspace.sync()
                    commit_all(root, "Record blocked milestone validation prerequisite")
                except VersionControlError as exc:
                    return _error_result(
                        sessions_run + 1,
                        SessionError("version_control", str(exc), 1),
                    )
                logger.info("%s. Stopping before milestone validation.", message)
                return _stop_result(
                    sessions_run + 1,
                    RunStopReason.PREREQUISITE_BLOCKED,
                    (SessionError("prerequisite", message, 0),),
                )
            timeouts = [
                profile_from_snapshot(profiles, task.profile, root=root).environment.timeouts.setup
                for task in milestone_tasks
            ]
            milestone_validation = run_validation_commands(
                root,
                role_name=role_name,
                milestone_id=route.milestone_id,
                session_id=ctx.invocation_id,
                commands=tuple(item.command for item in milestone_validation_contract.commands),
                source="milestone",
                infrastructure_error=service_validation_error,
                command_environments=(
                    None
                    if service_validation_error
                    else tuple(
                        services.environment(item.service_ids)
                        for item in milestone_validation_contract.commands
                    )
                ),
                timeout=max(timeouts, default=600),
            )
        process_result = process_handoff(
            handoff,
            workspace,
            command=requested_command,
            session_id=ctx.invocation_id,
            task_id=route.task_id,
            milestone_id=route.milestone_id,
            milestone_validation=milestone_validation,
            milestone_validation_contract=milestone_validation_contract,
        )
        validation_run: ValidationRun | None = None
        repeated_validation_failure = False
        task_validation_stop: tuple[RunStopReason, str] | None = None
        accepted_result = load_session_result(result_path)
        if (
            role_name == "developer"
            and route.task is not None
            and accepted_result.candidate.outcome == "completed"
            and process_result.clarification_id is None
        ):
            profile = (
                profile_from_snapshot(frozen_profiles, route.task.profile, root=root)
                if frozen_profiles is not None
                else load_profile(root, route.task.profile)
            )
            service_validation_error = ""
            try:
                service_environment = services.prepare((profile,), ("validation",))
            except TestServiceError as exc:
                service_validation_error = str(exc)
            boundary_results = (
                ()
                if service_validation_error
                else _resolve_profile_prerequisites(
                    root, (profile,), PrerequisiteOperation.VALIDATION, service_environment
                )
            )
            if any(item.blocks for item in boundary_results):
                message = _record_prerequisite_blocker(
                    workspace,
                    route,
                    PrerequisiteOperation.VALIDATION,
                    boundary_results,
                    command=requested_command,
                    commit=False,
                )
                progress = _classify_session_progress(
                    root, progress_baseline, workspace.snapshot, process_result
                )
                append_workflow_event(
                    root,
                    "session_progress",
                    role=role_name,
                    task=route.task_id,
                    milestone=route.milestone_id or "",
                    progress=progress.value,
                )
                ctx.write_session_metadata(
                    _build_session_metadata(
                        ctx,
                        agent_result,
                        resolved_agent_configs,
                        route.task_id,
                        executable_config,
                        progress,
                        dependency_baseline,
                    )
                )
                try:
                    workspace.sync()
                    commit_all(root, "Record blocked task validation prerequisite")
                except VersionControlError as exc:
                    return _error_result(
                        sessions_run + 1,
                        SessionError("version_control", str(exc), 1),
                    )
                logger.info("%s. Stopping before task validation.", message)
                return _stop_result(
                    sessions_run + 1,
                    RunStopReason.PREREQUISITE_BLOCKED,
                    (SessionError("prerequisite", message, 0),),
                )
            validation = effective_validation(route.task, profile)
            validation_run = run_validation_commands(
                root,
                role_name=role_name,
                task_id=route.task.id,
                session_id=ctx.invocation_id,
                commands=validation.commands,
                source=validation.source,
                infrastructure_error=service_validation_error,
                environ=service_environment,
                timeout=profile.environment.timeouts.setup,
                recovery_of=(
                    str(prior_validation_failure.get("session_id") or "")
                    if prior_validation_failure is not None
                    else ""
                ),
            )
            if validation_run.outcome == "failed" and validation.source == "task":
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
            elif validation_run.outcome == "failed":
                logger.warning(
                    "Task %s profile validation %s; recorded as a soft task-level warning",
                    route.task.id,
                    validation_run.outcome,
                )
            elif validation_run.outcome == "missing_tool":
                logger.warning(
                    "Task %s validation prerequisite is missing; leaving it unverified",
                    route.task.id,
                )
                task_validation_stop = (
                    RunStopReason.VALIDATION_PREREQUISITE_MISSING,
                    f"task {route.task.id} validation prerequisite is missing",
                )
            elif validation_run.outcome in {"timeout", "infrastructure_error"}:
                task_validation_stop = (
                    RunStopReason.VALIDATION_INFRASTRUCTURE_ERROR,
                    f"task {route.task.id} validation {validation_run.outcome}",
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
            and process_result.research_id is None
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
            and process_result.research_id is None
        ):
            if active_resume.blocked_kind == "research":
                append_workflow_event(
                    root,
                    "research_resume_completed",
                    research=active_resume.blocked_by,
                    role=active_resume.role,
                    command=active_resume.command,
                    task=active_resume.task,
                    milestone=active_resume.milestone,
                )
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
            dependency_baseline,
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
        if task_validation_stop is not None:
            reason, message = task_validation_stop
            logger.error("%s. Stopping.", message)
            try:
                workspace.sync()
                commit_all(root, "Record blocked task validation")
            except VersionControlError as exc:
                return _error_result(
                    sessions_run + 1,
                    SessionError("version_control", str(exc), 1),
                )
            return _error_result(
                sessions_run + 1,
                SessionError("task_validation", message, 1),
                reason=reason,
            )
        if process_result.stop_reason is not None:
            logger.error("%s. Stopping.", process_result.stop_message)
            try:
                workspace.sync()
                commit_all(root, "Record blocked milestone validation")
            except VersionControlError as exc:
                return _error_result(
                    sessions_run + 1,
                    SessionError("version_control", str(exc), 1),
                )
            return _error_result(
                sessions_run + 1,
                SessionError("milestone_validation", process_result.stop_message, 1),
                reason=process_result.stop_reason,
            )
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
            return _error_result(sessions_run, SessionError("version_control", str(exc), 1))
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
        last_completed_task_id = route.task_id
        if process_result.research_id is not None:
            if sessions_run >= max_sessions:
                return _stop_result(sessions_run, RunStopReason.RESEARCH_PENDING)
            researcher_error = _invoke_researcher(
                root,
                research_id=process_result.research_id,
                session_number=sessions_run + 1,
                agent_providers=agent_providers,
                role_agent_providers=role_agent_providers,
                resolved_agent_configs=resolved_agent_configs,
                retain_prompts=retain_prompts,
                session_progress=session_progress,
                executable_config=executable_config,
            )
            sessions_run += 1
            if researcher_error is not None:
                return _error_result(sessions_run, researcher_error)
            try:
                committed = commit_all(
                    root,
                    f"Complete DevLab research {process_result.research_id}",
                )
                if committed:
                    logger.info(
                        "Committed completed research: %s",
                        process_result.research_id,
                    )
            except VersionControlError as exc:
                return _error_result(sessions_run, SessionError("version_control", str(exc), 1))
            workspace = Workspace(root)
            active_resume = load_workflow_state(root).resume
            completed_resume_research = workspace.snapshot.get_research(process_result.research_id)
            if sessions_run >= max_sessions:
                return _stop_result(sessions_run, RunStopReason.RESEARCH_COMPLETED)
            continue
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
                return _error_result(sessions_run, SessionError("version_control", str(exc), 1))
            workspace = Workspace(root)
            active_resume = load_workflow_state(root).resume
            continue

        if (
            completed_planning_roles < len(forced_planning_roles)
            and role_name == forced_planning_roles[completed_planning_roles]
            and accepted_result.candidate.outcome == "completed"
        ):
            completed_planning_roles += 1
        if (
            planning_only
            and (revise_plan or fresh_generation_plan or adopt_existing)
            and completed_planning_roles >= len(forced_planning_roles)
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
    if completed_planning_roles < len(forced_planning_roles):
        return _stop_result(sessions_run, RunStopReason.SESSION_LIMIT)
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

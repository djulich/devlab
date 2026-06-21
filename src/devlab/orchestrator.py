from __future__ import annotations

import dataclasses
import json
import shutil
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

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
from devlab.environment import EnvironmentCommandError, EnvironmentManager
from devlab.generations import archive_active_generation, has_active_plan
from devlab.git import VersionControlError
from devlab.handoffs import Handoff, HandoffError, parse_handoff
from devlab.profiles import ProfileNotFoundError, load_profile
from devlab.prompts import build_base_prompt, build_session_prompt
from devlab.session_logging import session_finish_context, session_start_context
from devlab.spec_reconciliation import (
    SpecReconciliationStatus,
    inspect_spec_reconciliation,
)
from devlab.task_tracker import Task, TaskStatus
from devlab.version_control import (
    assert_clean_worktree,
    commit_all,
    ensure_git_repository,
)
from devlab.version_control import (
    tag as create_git_tag,
)
from devlab.workflow_state import WorkflowState, load_workflow_state, update_workflow_state
from devlab.workspace import (
    AGENT_LOG_DIR,
    ARTIFACTS_DIR,
    HISTORY_DIR,
    ROLES,
    Workspace,
    WorkspaceSnapshot,
)

DEFAULT_PROJECT_ROOT = Path.cwd()

SessionProgressCallback = Callable[[str, int, str], None]


@dataclasses.dataclass(frozen=True)
class SessionError:
    """An error that stopped the orchestrator loop."""

    phase: str
    message: str
    exit_code: int


@dataclasses.dataclass(frozen=True)
class RunResult:
    """Outcome of a run_loop execution.

    Callers inspect ``completed`` to determine whether the workflow finished
    normally (all milestones done, max sessions reached, or user quit) or was
    stopped by an error.
    """

    sessions_run: int
    completed: bool
    exit_code: int
    errors: tuple[SessionError, ...]


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
        return AgentInvocation(
            root=self.root,
            role_name=self.role_name,
            system_prompt=base_prompt,
            session_prompt=session_prompt,
            invocation_id=self.invocation_id,
            stdout_log=self.stdout_log,
            stderr_log=self.stderr_log,
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


def validate_handoff(
    handoff: Handoff,
    snapshot: WorkspaceSnapshot,
) -> None:
    if "unrecoverable" in handoff.open_issues.lower():
        raise HandoffError("handoff reports an unrecoverable issue")
    if handoff.role_name == "planner":
        planner_error = _validate_planner_addressed_findings(snapshot, handoff)
        if planner_error:
            raise HandoffError(planner_error)
    if handoff.role_name == "reviewer":
        reviewer_error = _validate_reviewer_outcome(snapshot, handoff)
        if reviewer_error:
            raise HandoffError(reviewer_error)


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


def process_handoff(handoff: Handoff, workspace: Workspace) -> ProcessResult:
    archived = archive_handoff(workspace.root, handoff.role_name)
    logger.info("Handoff archived to %s", archived.name)

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
    root: Path, snapshot: WorkspaceSnapshot, role_name: str
) -> EnvironmentManager:
    task = _task_for_role(snapshot, role_name)
    profile = load_profile(root, task.profile if task is not None else None)
    return EnvironmentManager(root, profile.environment)




def _validate_exhausted_backlog_planner_progress(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
    role_name: str,
) -> str | None:
    if role_name != "planner" or not _needs_incremental_planning(before):
        return None
    if after.workflow_state().planning.complete:
        return None
    if _has_actionable_or_planned_work(after):
        return None
    return (
        "planner was invoked because the backlog was exhausted while "
        ".devlab/workflow.toml has planning.complete = false, but it neither created "
        "new durable work nor reported planning_complete = true"
    )


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
    return "; ".join(details)


def _handoff_error_message(
    ctx: SessionContext, error: str, config_log: Path | None
) -> str:
    details = [error]
    details.extend(_log_path_details(ctx.stdout_log, ctx.stderr_log, config_log))
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


def _build_session_metadata(
    ctx: SessionContext,
    agent_result: AgentResult,
    resolved_agent_configs: dict[str, ResolvedAgentConfig] | None,
    task_id: str | None,
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
    )


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


def _load_workflow_and_spec_status(
    root: Path,
) -> tuple[WorkflowState, SpecReconciliationStatus]:
    workflow_state = load_workflow_state(root)
    return workflow_state, inspect_spec_reconciliation(root, workflow_state)


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
    session_progress: SessionProgressCallback | None = None,
) -> RunResult:
    """Run the orchestrator loop, returning a structured result."""
    if revise_plan and not planning_only:
        raise ValueError("revise_plan requires planning_only")
    if replace_plan and not planning_only:
        raise ValueError("replace_plan requires planning_only")
    if adopt_existing and not planning_only:
        raise ValueError("adopt_existing requires planning_only")
    if replace_plan and adopt_existing:
        return RunResult(
            0,
            False,
            2,
            (
                SessionError(
                    "planning_mode",
                    "devlab plan cannot combine --replace-plan and --adopt-existing",
                    2,
                ),
            ),
        )
    sessions_run = 0
    spec_status: SpecReconciliationStatus | None = None
    workflow_state: WorkflowState
    active_plan_exists = has_active_plan(root)
    if planning_only and adopt_existing and active_plan_exists:
        return RunResult(
            0,
            False,
            2,
            (
                SessionError(
                    "planning_mode",
                    "--adopt-existing is only allowed when no active DevLab plan exists",
                    2,
                ),
            ),
        )
    if planning_only and replace_plan and not active_plan_exists:
        return RunResult(
            0,
            False,
            2,
            (
                SessionError(
                    "planning_mode",
                    "--replace-plan requires an active DevLab plan to archive",
                    2,
                ),
            ),
        )
    if automatic_version_control:
        try:
            ensure_git_repository(root)
            workflow_state, spec_status = _load_workflow_and_spec_status(root)
            if planning_only and spec_status.dirty_spec_paths:
                error = _dirty_spec_error(spec_status.dirty_spec_paths)
                logger.error("%s. Stopping.", error.message)
                return RunResult(0, False, error.exit_code, (error,))
            assert_clean_worktree(root)
        except VersionControlError as exc:
            logger.error("%s. Stopping.", exc)
            return RunResult(0, False, 1, (SessionError("version_control", str(exc), 1),))
        except (OSError, ValueError) as exc:
            logger.error("%s. Stopping.", exc)
            return RunResult(0, False, 1, (SessionError("workflow_state", str(exc), 1),))
        if not planning_only and spec_status is not None and spec_status.changed:
            error = _stale_specs_error(spec_status)
            logger.error("%s. Stopping.", error.message)
            return RunResult(0, False, error.exit_code, (error,))
    else:
        try:
            workflow_state = load_workflow_state(root)
        except (OSError, ValueError) as exc:
            logger.error("%s. Stopping.", exc)
            return RunResult(0, False, 1, (SessionError("workflow_state", str(exc), 1),))

    workspace = Workspace(root)
    resolved_agent_configs = None
    if agent_providers is None:
        try:
            agent_configuration = load_agent_configuration(
                root,
                provider=provider,
                model=model,
                effort=effort,
                discover_provider_versions=True,
            )
        except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
            logger.error("%s. Stopping.", exc)
            return RunResult(
                0,
                False,
                1,
                (SessionError("agent_configuration", str(exc), 1),),
            )
        agent_providers = agent_configuration.providers
        role_agent_providers = agent_configuration.role_providers
        resolved_agent_configs = agent_configuration.resolved

    reconcile_plan = bool(spec_status and spec_status.changed)
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
            workspace = Workspace(root)
            logger.info("Archived active DevLab generation %s", manifest.generation)
            if automatic_version_control:
                committed = commit_all(root, f"Archive DevLab generation {manifest.generation}")
                if committed:
                    logger.info("Committed DevLab generation archive")
        except OSError as exc:
            logger.error("%s. Stopping.", exc)
            return RunResult(
                0,
                False,
                1,
                (SessionError("generation_archive", str(exc), 1),),
            )
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

    while sessions_run < max_sessions:
        if automatic_version_control:
            try:
                assert_clean_worktree(root)
            except VersionControlError as exc:
                logger.error("%s. Stopping.", exc)
                return RunResult(
                    sessions_run,
                    False,
                    1,
                    (SessionError("version_control", str(exc), 1),),
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
        if role_name is None:
            if workspace.snapshot.blocked_tasks():
                logger.info(
                    "No task is eligible; remaining development tasks"
                    " are blocked by dependencies."
                )
            else:
                logger.info("All milestones complete or no task can proceed.")
            logger.info("Stopping.")
            break

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
            return RunResult(sessions_run, False, error.exit_code, (error,))

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
                        return RunResult(
                            sessions_run,
                            False,
                            1,
                            (SessionError("version_control", str(exc), 1),),
                        )
            else:
                logger.info("Planning complete; stopping before implementation roles.")
            logger.info("Stopping before %s session.", role_name)
            break
        if (
            planning_only
            and (revise_plan or fresh_generation_plan or adopt_existing)
            and sessions_run >= len(forced_planning_roles)
        ):
            logger.info("Planning revision complete; stopping before implementation roles.")
            break

        if automatic_version_control and resolved_agent_configs is not None:
            agent_config_error = _preflight_agent_executable(
                role_name, resolved_agent_configs[role_name]
            )
            if agent_config_error is not None:
                logger.error("%s. Stopping.", agent_config_error.message)
                return RunResult(
                    sessions_run,
                    False,
                    agent_config_error.exit_code,
                    (agent_config_error,),
                )

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
        session_task = _task_for_role(start_snapshot, role_name)
        session_task_id = session_task.id if session_task is not None else None
        session_milestone_id = (
            start_snapshot.select_integration_milestone()
            if role_name == "integrator"
            else start_snapshot.select_architecture_review_milestone()
            if role_name == "architect"
            else None
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
            session_start_context(start_snapshot, role_name, session_task),
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

        try:
            snapshot = workspace.snapshot
            base_prompt = build_base_prompt(
                root, role, snapshot=snapshot, role_name=role_name
            )
            session_prompt = build_session_prompt(
                snapshot,
                role_name,
                planning_revision=planning_only
                and (revise_plan or fresh_generation_plan or adopt_existing),
                adopt_existing=planning_only and adopt_existing,
                fresh_generation=planning_only and fresh_generation_plan,
                spec_reconciliation=reconcile_plan,
            )
            ctx.write_prompt_logs(base_prompt, session_prompt)
            environment = _environment_for_session(root, workspace.snapshot, role_name)
        except ProfileNotFoundError as exc:
            logger.error("%s. Stopping.", exc)
            return RunResult(sessions_run, False, 1,
                             (SessionError("profile_resolution", str(exc), 1),))

        manage_environment = role.needs_environment and environment.manages_role(role_name)
        if manage_environment:
            try:
                logger.info("Preparing environment for %s session", role_name)
                environment.pre_session(role_name)
                environment.setup(role_name)
            except EnvironmentCommandError as exc:
                logger.error("%s. Stopping.", exc)
                logger.info(_failed_session_cleanup_hint())
                return RunResult(sessions_run, False, 1,
                                 (SessionError("environment_setup", str(exc), 1),))

        agent_result = AgentResult(return_code=1, failure_kind="provider_error")
        agent_error: SessionError | None = None
        invocation = ctx.build_invocation(base_prompt, session_prompt)
        agent_provider = provider_for_role(role_name, agent_providers, role_agent_providers)
        try:
            agent_result = invoke_session(invocation, agent_provider=agent_provider)
        except ProviderError as exc:
            agent_error = SessionError(
                "agent_invocation",
                _agent_error_message(
                    ctx,
                    AgentResult(
                        return_code=1,
                        failure_kind="provider_error",
                        message=f"agent provider error: {exc}",
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
                logger.info("Tearing down environment for %s session", role_name)
                environment.post_session(role_name)
            except EnvironmentCommandError as exc:
                logger.error("%s. Stopping.", exc)
                teardown_error = SessionError("environment_teardown", str(exc), 1)

        if agent_error is not None:
            logger.error("%s. Stopping.", agent_error.message)
            logger.info(_failed_session_cleanup_hint())
            metadata = _build_session_metadata(
                ctx, agent_result, resolved_agent_configs, session_task_id,
            )
            ctx.write_session_metadata(metadata)
            errors = (agent_error,) + ((teardown_error,) if teardown_error else ())
            return RunResult(sessions_run, False, agent_error.exit_code, errors)
        if teardown_error is not None:
            logger.info(_failed_session_cleanup_hint())
            metadata = _build_session_metadata(
                ctx, agent_result, resolved_agent_configs, session_task_id,
            )
            ctx.write_session_metadata(metadata)
            return RunResult(
                sessions_run, False, agent_result.return_code or 1, (teardown_error,)
            )

        workspace.did_mutate()

        handoff_path = artifacts_dir / "handoff.md"
        try:
            handoff = parse_handoff(handoff_path, role_name)
            validate_handoff(handoff, workspace.snapshot)
            _apply_planner_workflow_state(
                workspace,
                handoff,
                planning_update=planner_generation_update,
            )
            if role_name == "planner" and spec_status is not None:
                workflow_state, spec_status = _load_workflow_and_spec_status(root)
            planner_noop_error = _validate_exhausted_backlog_planner_progress(
                start_snapshot,
                workspace.snapshot,
                role_name,
            )
            if planner_noop_error is not None:
                raise HandoffError(planner_noop_error)
        except HandoffError as exc:
            message = _handoff_error_message(ctx, str(exc), config_log)
            logger.error("Invalid handoff produced by %s: %s. Stopping.", role_name, message)
            logger.info(_failed_session_cleanup_hint())
            metadata = _build_session_metadata(
                ctx, agent_result, resolved_agent_configs, session_task_id,
            )
            ctx.write_session_metadata(metadata)
            return RunResult(
                sessions_run, False, 1, (SessionError("handoff_validation", message, 1),)
            )

        commit_message = _commit_message(workspace.snapshot, handoff)
        process_result = process_handoff(handoff, workspace)
        metadata = _build_session_metadata(
            ctx, agent_result, resolved_agent_configs, session_task_id,
        )
        ctx.write_session_metadata(metadata)
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
                return RunResult(
                    sessions_run,
                    False,
                    1,
                    (SessionError("version_control", str(exc), 1),),
                )
        finish_context = session_finish_context(
            workspace.snapshot,
            role_name,
            task_id=session_task_id,
            milestone_id=session_milestone_id,
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

        if (
            planning_only
            and (revise_plan or fresh_generation_plan or adopt_existing)
            and sessions_run >= len(forced_planning_roles)
        ):
            logger.info("Planning revision complete; stopping before implementation roles.")
            break

    logger.info("Orchestrator finished after %s session(s).", sessions_run)
    return RunResult(sessions_run, True, 0, ())

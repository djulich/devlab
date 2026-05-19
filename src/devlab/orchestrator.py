from __future__ import annotations

import dataclasses
import shutil
from datetime import UTC, datetime
from pathlib import Path

from devlab._logging import logger
from devlab.agent_config import (
    ResolvedAgentConfig,
    format_resolved_agent_config,
    load_agent_configuration,
)
from devlab.agents import AgentInvocation, AgentProvider, AgentResult, provider_for_role
from devlab.environment import EnvironmentCommandError, EnvironmentManager
from devlab.handoffs import Handoff, HandoffError, parse_handoff
from devlab.profiles import ProfileNotFoundError, load_profile
from devlab.prompts import build_session_prompt, build_system_prompt
from devlab.task_tracker import Task
from devlab.workspace import (
    AGENT_LOG_DIR,
    ARTIFACTS_DIR,
    HISTORY_DIR,
    ROLES,
    Workspace,
    WorkspaceSnapshot,
    read_file,
)

DEFAULT_PROJECT_ROOT = Path.cwd()

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


def _log_resolved_agent_config(
    root: Path,
    config: ResolvedAgentConfig,
    *,
    invocation_id: str,
    stdout_log: Path,
    stderr_log: Path,
) -> Path:
    path = _agent_log_path(root, invocation_id, "config.toml")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = format_resolved_agent_config(config)
    text += f'stdout_log = "{stdout_log.as_posix()}"\n'
    text += f'stderr_log = "{stderr_log.as_posix()}"\n'
    path.write_text(text)
    return path


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
    logger.info("%s session exited with code %s", invocation.role_name, result.return_code)
    return result


# ---------------------------------------------------------------------------
# Post-session processing
# ---------------------------------------------------------------------------


def validate_handoff(
    handoff_path: Path,
    *,
    role_name: str | None = None,
    snapshot: WorkspaceSnapshot | None = None,
) -> tuple[bool, str]:
    try:
        handoff = parse_handoff(handoff_path, role_name or "")
    except HandoffError as exc:
        return False, str(exc)
    if "unrecoverable" in handoff.open_issues.lower():
        return False, "handoff reports an unrecoverable issue"
    if role_name == "planner" and snapshot is not None:
        planner_error = _validate_planner_addressed_findings(snapshot, handoff)
        if planner_error:
            return False, planner_error
    if role_name == "reviewer" and snapshot is not None:
        reviewer_error = _validate_reviewer_outcome(snapshot, handoff)
        if reviewer_error:
            return False, reviewer_error
    return True, ""


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
    task = workspace.task_from_path(task_path)
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
    if handoff.has_open_issues and task.review_approved:
        return "reviewer handoff reports open issues but task review is approved"
    if not handoff.has_open_issues and not task.review_approved:
        return "reviewer handoff reports no open issues but task review is not approved"
    return ""


def _mark_addressed_findings_planned(workspace: Workspace, handoff: Handoff) -> None:
    for finding_id in handoff.addressed_finding_tasks():
        workspace.finding(finding_id).mark_planned()
        workspace.finding(finding_id).resolve_if_complete()


def process_handoff(workspace: Workspace, role_name: str) -> None:
    archived = archive_handoff(workspace.root, role_name)
    handoff = parse_handoff(archived, role_name)
    logger.info("Handoff archived to %s", archived.name)

    if role_name == "architect":
        milestone = workspace.snapshot.select_architecture_review_milestone()
        if milestone is not None:
            if handoff.has_open_issues:
                workspace.create_finding_from_handoff(
                    source="architect",
                    milestone=milestone,
                    handoff_path=archived,
                )
                logger.info("Architecture review reported open issues; finding created")
            workspace.milestone(milestone).mark_architecture_reviewed(archived)
            logger.info("Milestone %s marked architecture-reviewed", milestone)
    elif role_name == "developer":
        task = workspace.snapshot.select_next_development_task()
        if task and task.acceptance_criteria_complete:
            task_handle = workspace.task(task.id)
            task_handle.mark_in_review()
            logger.info(
                "Task %s completed by developer; status set to in_review",
                task_handle.path.name,
            )
    elif role_name == "planner":
        _mark_addressed_findings_planned(workspace, handoff)
    elif role_name == "reviewer":
        task = workspace.snapshot.select_next_review_task()
        if task and task.review_approved and not handoff.has_open_issues:
            task_handle = workspace.task(task.id)
            task_handle.close()
            logger.info(
                "Task %s closed by %s; status set to closed", task_handle.path.name, role_name
            )
            task_handle.resolve_addressed_findings()
        elif task and handoff.has_open_issues:
            task_handle = workspace.task(task.id)
            task_handle.mark_changes_requested()
            logger.info(
                "Task %s rejected by reviewer; status set to changes_requested",
                task_handle.path.name,
            )
    elif role_name == "integrator":
        milestone = workspace.snapshot.select_integration_milestone()
        if handoff.has_open_issues:
            finding = workspace.create_finding_from_handoff(
                source="integrator",
                milestone=milestone,
                handoff_path=archived,
            )
            if milestone is not None:
                workspace.milestone(milestone).mark_integration_failed(finding.id)
            logger.info(
                "Integration reported open issues; finding created for planner follow-up"
            )
            return
        if milestone is not None:
            workspace.milestone(milestone).mark_integrated(archived)
            logger.info("Milestone %s marked integrated", milestone)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _task_for_role(snapshot: WorkspaceSnapshot, role_name: str) -> Task | None:
    if role_name == "developer":
        return snapshot.select_next_development_task()
    if role_name == "reviewer":
        return snapshot.select_next_review_task()
    return None


def _environment_for_session(
    root: Path, snapshot: WorkspaceSnapshot, role_name: str
) -> EnvironmentManager:
    task = _task_for_role(snapshot, role_name)
    profile = load_profile(root, task.profile if task is not None else None)
    return EnvironmentManager(root, profile.environment)


def _agent_error_message(
    role_name: str, result: AgentResult, config_log: Path | None
) -> str:
    details = [
        f"{role_name} session failed ({result.failure_kind})",
        f"exit_code={result.return_code}",
    ]
    if result.message:
        details.append(result.message)
    if result.command:
        details.append("command=" + " ".join(result.command))
    if result.timeout_seconds is not None:
        details.append(f"timeout_seconds={result.timeout_seconds}")
    details.extend(_log_path_details(result.stdout_log, result.stderr_log, config_log))
    return "; ".join(details)


def _handoff_error_message(
    error: str, stdout_log: Path, stderr_log: Path, config_log: Path | None
) -> str:
    details = [error]
    details.extend(_log_path_details(stdout_log, stderr_log, config_log))
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


def run_loop(
    root: Path,
    *,
    auto: bool,
    max_sessions: int,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    dangerous_skip_permissions: bool = False,
    agent_providers: dict[str, AgentProvider] | None = None,
    role_agent_providers: dict[str, str] | None = None,
) -> RunResult:
    """Run the orchestrator loop, returning a structured result."""
    sessions_run = 0
    workspace = Workspace(root)
    resolved_agent_configs = None
    if agent_providers is None:
        agent_configuration = load_agent_configuration(
            root,
            provider=provider,
            model=model,
            effort=effort,
            dangerous_skip_permissions=dangerous_skip_permissions,
        )
        agent_providers = agent_configuration.providers
        role_agent_providers = agent_configuration.role_providers
        resolved_agent_configs = agent_configuration.resolved

    while sessions_run < max_sessions:
        workspace.sync()
        role_name = workspace.snapshot.assess_state()
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

        if role_name == "integrator":
            milestone = workspace.snapshot.select_integration_milestone()
            if milestone is not None:
                workspace.milestone(milestone).mark_ready_for_integration()

        role = ROLES[role_name]
        session_number = sessions_run + 1
        invocation_id = _agent_invocation_id(session_number, role_name)
        stdout_log = _agent_log_path(root, invocation_id, "stdout.log")
        stderr_log = _agent_log_path(root, invocation_id, "stderr.log")
        config_log: Path | None = None

        logger.info("Session %s: selecting role '%s'", session_number, role_name)
        if resolved_agent_configs is not None:
            config_log = _log_resolved_agent_config(
                root,
                resolved_agent_configs[role_name],
                invocation_id=invocation_id,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
            )
            logger.debug("Resolved agent config written to %s", config_log)
            logger.debug("Agent stdout log: %s", stdout_log)
            logger.debug("Agent stderr log: %s", stderr_log)

        artifacts_dir = root / ARTIFACTS_DIR / role_name
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        try:
            system_prompt = build_system_prompt(root, role)
            session_prompt = build_session_prompt(workspace.snapshot, role_name)
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
                return RunResult(sessions_run, False, 1,
                                 (SessionError("environment_setup", str(exc), 1),))

        agent_result = AgentResult(return_code=1, failure_kind="provider_error")
        agent_error: SessionError | None = None
        invocation = AgentInvocation(
            root=root,
            role_name=role_name,
            system_prompt=system_prompt,
            session_prompt=session_prompt,
            invocation_id=invocation_id,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
        )
        try:
            agent_result = invoke_session(
                invocation,
                agent_provider=provider_for_role(role_name, agent_providers, role_agent_providers),
            )
        except Exception as exc:
            agent_error = SessionError(
                "agent_invocation",
                _agent_error_message(
                    role_name,
                    AgentResult(
                        return_code=1,
                        failure_kind="provider_error",
                        message=f"agent provider error: {exc}",
                        role_name=role_name,
                        stdout_log=stdout_log,
                        stderr_log=stderr_log,
                    ),
                    config_log,
                ),
                1,
            )
        else:
            if not agent_result.succeeded:
                agent_error = SessionError(
                    "agent_invocation",
                    _agent_error_message(role_name, agent_result, config_log),
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
            errors = (agent_error,) + ((teardown_error,) if teardown_error else ())
            return RunResult(sessions_run, False, agent_error.exit_code, errors)
        if teardown_error is not None:
            return RunResult(
                sessions_run, False, agent_result.return_code or 1, (teardown_error,)
            )

        workspace.did_mutate()

        handoff_path = artifacts_dir / "handoff.md"
        is_valid, error = validate_handoff(
            handoff_path, role_name=role_name, snapshot=workspace.snapshot,
        )
        if not is_valid:
            message = _handoff_error_message(error, stdout_log, stderr_log, config_log)
            logger.error("Invalid handoff produced by %s: %s. Stopping.", role_name, message)
            return RunResult(
                sessions_run, False, 1, (SessionError("handoff_validation", message, 1),)
            )

        process_handoff(workspace, role_name)
        sessions_run += 1

        if not auto:
            handoff_text = read_file(handoff_path)
            print(f"\n{'- ' * 30}")
            print(handoff_text[:2000])
            print(f"{'- ' * 30}")
            answer = input("Continue? [Y/n]: ").strip().lower()
            if answer in ("n", "q"):
                print("Stopped by user.")
                break

    logger.info("Orchestrator finished after %s session(s).", sessions_run)
    return RunResult(sessions_run, True, 0, ())



from __future__ import annotations

import dataclasses
from pathlib import Path

from devlab.executable_config import (
    ExecutableConfigSnapshot,
    build_executable_config_snapshot,
    executable_config_is_trusted,
)
from devlab.orchestrator import RunResult, RunStopReason
from devlab.task_tracker import Task
from devlab.workflow_state_report import build_workflow_state_report
from devlab.workspace import Workspace, WorkspaceSnapshot


@dataclasses.dataclass(frozen=True)
class RunTaskSummary:
    id: str
    title: str
    status: str


@dataclasses.dataclass(frozen=True)
class RunMilestoneSummary:
    id: str
    title: str


@dataclasses.dataclass(frozen=True)
class RunClarificationSummary:
    id: str
    title: str
    asking_role: str
    blocks: str


@dataclasses.dataclass(frozen=True)
class RunExecutableConfigSummary:
    state: str
    digest: str
    changed: bool
    error: str = ""


@dataclasses.dataclass(frozen=True)
class RunSummary:
    command: str
    stop_reason: RunStopReason
    sessions_run: int
    next_role: str | None
    task: RunTaskSummary | None
    milestone: RunMilestoneSummary | None
    clarification: RunClarificationSummary | None
    executable_config: RunExecutableConfigSummary
    errors: tuple[str, ...]
    next_commands: tuple[str, ...]


def build_run_summary(
    root: Path,
    *,
    command: str,
    result: RunResult,
    initial_executable_config: ExecutableConfigSnapshot | None,
) -> RunSummary:
    """Build read-only operator guidance from a completed bounded run."""
    workspace = Workspace(root)
    snapshot = workspace.snapshot
    next_role = snapshot.assess_state()
    task = _next_task(snapshot, next_role)
    milestone = _next_milestone(snapshot, next_role)
    blockers = snapshot.blocking_clarifications()
    clarification = (
        RunClarificationSummary(
            blockers[0].id,
            blockers[0].title,
            blockers[0].asking_role,
            blockers[0].blocks,
        )
        if blockers
        else None
    )
    executable_config = _executable_config_summary(root, initial_executable_config)
    report = build_workflow_state_report(root)
    next_commands = _next_commands(
        command=command,
        result=result,
        next_role=next_role,
        clarification=clarification,
        executable_config=executable_config,
        dirty_specs=bool(report.specs.dirty_spec_paths),
        changed_specs=report.specs.specs_changed_since_baseline is True,
    )
    return RunSummary(
        command=command,
        stop_reason=result.stop_reason,
        sessions_run=result.sessions_run,
        next_role=next_role,
        task=_task_summary(task),
        milestone=milestone,
        clarification=clarification,
        executable_config=executable_config,
        errors=tuple(error.message for error in result.errors),
        next_commands=next_commands,
    )


def format_run_summary(summary: RunSummary) -> str:
    lines = [f"DevLab stopped: {_stop_reason_text(summary.stop_reason)}"]
    lines.append(f"Sessions completed: {summary.sessions_run}")
    lines.extend(["", "Current workflow:"])
    lines.append(f"- Next role: {summary.next_role or 'none'}")
    if summary.task is not None:
        lines.append(f"- Task: {summary.task.id} — {summary.task.title}")
        lines.append(f"- Task status: {summary.task.status.replace('_', ' ')}")
    if summary.milestone is not None:
        lines.append(f"- Milestone: {summary.milestone.id} — {summary.milestone.title}")
    lines.append(
        "- Operator clarification: "
        + (summary.clarification.id if summary.clarification is not None else "none")
    )

    attention: list[str] = []
    if summary.clarification is not None:
        clarification = summary.clarification
        attention.extend(
            [
                f"- {clarification.id}: {clarification.title}",
                f"- Asked by: {clarification.asking_role}",
                f"- Blocks: {clarification.blocks}",
            ]
        )
    config = summary.executable_config
    if config.state == "invalid":
        attention.append(f"- Executable configuration is invalid: {config.error}")
    elif config.state == "untrusted":
        qualifier = " changed during this run and" if config.changed else ""
        attention.append(
            f"- Executable configuration{qualifier} is not trusted ({config.digest})."
        )
    if summary.errors:
        attention.extend(f"- Error: {message}" for message in summary.errors)
    if attention:
        lines.extend(["", "Operator attention:", *attention])

    lines.extend(["", "Next action:"])
    if summary.next_commands:
        lines.extend(f"  {command}" for command in summary.next_commands)
    else:
        lines.append("  No workflow action is currently required.")
    return "\n".join(lines)


def _next_task(snapshot: WorkspaceSnapshot, next_role: str | None) -> Task | None:
    if next_role == "developer":
        return snapshot.select_next_development_task()
    if next_role == "reviewer":
        return snapshot.select_next_review_task()
    return None


def _task_summary(task: Task | None) -> RunTaskSummary | None:
    if task is None:
        return None
    return RunTaskSummary(task.id, task.title, task.status.value)


def _next_milestone(
    snapshot: WorkspaceSnapshot, next_role: str | None
) -> RunMilestoneSummary | None:
    milestone_id = (
        snapshot.select_integration_milestone()
        if next_role == "integrator"
        else snapshot.select_architecture_review_milestone()
        if next_role == "architect"
        else None
    )
    if milestone_id is None:
        return None
    milestone = next(
        item for item in snapshot.current_generation_milestones() if item.id == milestone_id
    )
    return RunMilestoneSummary(milestone.id, milestone.title)


def _executable_config_summary(
    root: Path, initial: ExecutableConfigSnapshot | None
) -> RunExecutableConfigSummary:
    try:
        current = build_executable_config_snapshot(
            root,
            provider=initial.provider_override if initial is not None else None,
            model=initial.model_override if initial is not None else None,
            effort=initial.effort_override if initial is not None else None,
        )
    except (OSError, ValueError, KeyError) as exc:
        return RunExecutableConfigSummary("invalid", "", False, str(exc))
    return RunExecutableConfigSummary(
        "trusted" if executable_config_is_trusted(current) else "untrusted",
        current.digest,
        initial is not None and current.digest != initial.digest,
    )


def _next_commands(
    *,
    command: str,
    result: RunResult,
    next_role: str | None,
    clarification: RunClarificationSummary | None,
    executable_config: RunExecutableConfigSummary,
    dirty_specs: bool,
    changed_specs: bool,
) -> tuple[str, ...]:
    if clarification is not None:
        return (
            f"devlab clarify show {clarification.id}",
            f"devlab clarify answer {clarification.id} ...",
            "devlab resume",
        )
    if result.stop_reason in {
        RunStopReason.ERROR,
        RunStopReason.DEVELOPER_NON_ADVANCING,
        RunStopReason.TASK_CONTRACT_INVALID,
        RunStopReason.VALIDATION_FAILED,
        RunStopReason.VALIDATION_PREREQUISITE_MISSING,
        RunStopReason.VALIDATION_INFRASTRUCTURE_ERROR,
    }:
        return ("Inspect the errors above and run devlab doctor before retrying.",)
    if executable_config.state == "invalid":
        return ("devlab doctor",)
    if executable_config.state == "untrusted":
        continuation = "devlab plan" if command == "plan" else "devlab implement"
        return (
            "devlab trust executable-config --show",
            "devlab trust executable-config",
            continuation,
        )
    if dirty_specs:
        return ("Commit or revert dirty specification files, then run devlab plan.",)
    if changed_specs:
        return ("devlab plan",)
    if next_role is None:
        return ()
    if command == "implement":
        return ("devlab implement",)
    return ("devlab implement" if next_role not in {"architect", "planner"} else "devlab plan",)


def _stop_reason_text(reason: RunStopReason) -> str:
    return {
        RunStopReason.WORKFLOW_COMPLETE: "workflow complete",
        RunStopReason.COMMAND_COMPLETE: "command completed at its intended boundary",
        RunStopReason.EXECUTABLE_CONFIG_CHANGED: (
            "executable configuration changed; a fresh authorized run is required"
        ),
        RunStopReason.SESSION_LIMIT: "session limit reached; work remains",
        RunStopReason.CLARIFICATION_BLOCKED: "operator clarification required",
        RunStopReason.NO_ELIGIBLE_ROLE: "no eligible workflow role",
        RunStopReason.DEVELOPER_NON_ADVANCING: "developer recovery made no progress",
        RunStopReason.TASK_CONTRACT_INVALID: "task contract is invalid",
        RunStopReason.VALIDATION_FAILED: "task validation failed after bounded recovery",
        RunStopReason.VALIDATION_PREREQUISITE_MISSING: ("validation prerequisite is missing"),
        RunStopReason.VALIDATION_INFRASTRUCTURE_ERROR: ("validation infrastructure failed"),
        RunStopReason.ERROR: "workflow error",
    }[reason]

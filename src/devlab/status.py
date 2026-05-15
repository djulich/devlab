from __future__ import annotations

from pathlib import Path

from devlab.agent_config import AGENTS_CONFIG, ResolvedAgentConfig, load_agent_configuration
from devlab.milestones import Milestone, sync_milestones_from_tasks
from devlab.task_tracker import FileTaskTracker, Task, TaskStatus
from devlab.workspace import PROJECT_PLAN, assess_state, read_file


def format_status(root: Path, *, verbose: bool = False) -> str:
    lines: list[str] = []
    role_name = assess_state(root)
    if role_name is None:
        lines.append("No role selected; workflow is complete or blocked.")
    else:
        lines.append(f"Next role: {role_name}")

    if verbose:
        lines.extend(["", *_format_agent_configuration(root)])
        lines.extend(["", *_format_milestone_status(root)])
    return "\n".join(lines)


def _format_agent_configuration(root: Path) -> list[str]:
    config = load_agent_configuration(root)
    source = root / AGENTS_CONFIG
    lines = ["Agent configuration:"]
    if source.exists():
        lines.append(f"Source: {AGENTS_CONFIG}")
    else:
        lines.append("Source: built-in fallback defaults")
    for role_name in sorted(config.resolved):
        lines.append(_format_role_agent(config.resolved[role_name]))
    return lines


def _format_milestone_status(root: Path) -> list[str]:
    milestones = sync_milestones_from_tasks(
        root,
        project_plan_text=read_file(root / PROJECT_PLAN),
    )
    if not milestones:
        return ["Milestones: none"]
    tasks = FileTaskTracker(root).list_tasks()
    lines = ["Milestones:"]
    for milestone in milestones:
        lines.extend(_format_milestone(milestone, tasks))
    return lines


def _format_milestone(milestone: Milestone, tasks: list[Task]) -> list[str]:
    milestone_tasks = [task for task in tasks if task.milestone == milestone.id]
    closed = sum(1 for task in milestone_tasks if task.status == TaskStatus.CLOSED)
    active = len(milestone_tasks) - closed
    lines = [
        f"- {milestone.id}: {milestone.title}",
        f"  status: {milestone.status.value}",
        f"  tasks: {len(milestone_tasks)} total, {closed} closed, {active} active",
        f"  integration_required: {_bool_text(milestone.integration_required)}",
        f"  integrated: {_bool_text(milestone.integrated)}",
        f"  architecture_approved: {_bool_text(milestone.architecture_approved)}",
    ]
    if milestone.integration_handoff:
        lines.append(f"  integration_handoff: {milestone.integration_handoff}")
    if milestone.architecture_review_handoff:
        lines.append(f"  architecture_review_handoff: {milestone.architecture_review_handoff}")
    if milestone.findings:
        lines.append("  findings: " + ", ".join(milestone.findings))
    else:
        lines.append("  findings: none")
    return lines



def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _format_role_agent(config: ResolvedAgentConfig) -> str:
    timeout = "none" if config.timeout_seconds is None else str(config.timeout_seconds)
    command = "[" + ", ".join(repr(part) for part in config.command) + "]"
    stdin = "true" if config.uses_stdin else "false"
    return (
        f"- {config.role_name}: {config.provider} "
        f'model="{config.model}" '
        f'effort="{config.effort}" '
        f"timeout={timeout} "
        f"command={command} "
        f"stdin={stdin}"
    )

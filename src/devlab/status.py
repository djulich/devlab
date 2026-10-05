from __future__ import annotations

import tomllib
from pathlib import Path

from devlab._console import wrap_prose
from devlab.agent_config import AGENTS_CONFIG, ResolvedAgentConfig, load_agent_configuration
from devlab.clarifications import Clarification
from devlab.findings import Finding
from devlab.milestones import Milestone, MilestoneVerification
from devlab.prerequisites import FilePrerequisiteTracker
from devlab.prompt_context import PromptContextReport, build_prompt_context_report
from devlab.task_tracker import Task, TaskStatus
from devlab.workflow_state_report import (
    build_workflow_state_report,
    format_workflow_state_provenance,
    format_workflow_state_report,
)
from devlab.workspace import Workspace, WorkspaceSnapshot


def format_status(root: Path, *, verbose: bool = False, width: int | None = None) -> str:
    report = build_workflow_state_report(root)
    lines = format_workflow_state_report(report, width=width).splitlines()
    if report.lifecycle_phase == "uninitialized":
        return "\n".join(lines)

    snapshot = Workspace(root).snapshot
    prerequisite_blocker = FilePrerequisiteTracker(root).read_blocker()
    if prerequisite_blocker is not None:
        references = ", ".join(
            result.prerequisite.reference for result in prerequisite_blocker.results
        )
        lines.append(
            f"Prerequisite blocker: {prerequisite_blocker.operation.value} — {references}"
        )
        lines.append("- inspect: devlab prerequisite blocked")

    for record in snapshot.test_service_records():
        lines.append(f"Test service {record['service']}: {record['state']} (last observed)")

    if verbose:
        lines.extend(["", *format_workflow_state_provenance(report).splitlines()])
        lines.extend(["", *_format_agent_configuration(root)])
        lines.extend(["", *_format_prompt_context(snapshot, width=width)])
        lines.extend(["", *_format_clarification_status(snapshot, width=width)])
        lines.extend(["", *_format_milestone_status(snapshot, width=width)])
        lines.extend(["", *_format_finding_status(snapshot, width=width)])
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


def _format_prompt_context(snapshot: WorkspaceSnapshot, *, width: int | None = None) -> list[str]:
    report = build_prompt_context_report(snapshot)
    return _format_prompt_context_report(report, width=width)


def _format_prompt_context_report(
    report: PromptContextReport, *, width: int | None = None
) -> list[str]:
    lines = ["Prompt context:"]
    for role in report.roles:
        if role.status == "ok":
            status_text = "OK"
        elif role.status == "warning":
            status_text = f"WARNING over {_format_count(role.thresholds.warning_tokens)}"
        else:
            status_text = f"CRITICAL over {_format_count(role.thresholds.critical_tokens)}"
        lines.append(
            f"- {role.role_name}: total ~{_format_count(role.total.estimated_tokens)} tokens "
            f"(base ~{_format_count(role.base.estimated_tokens)}, "
            f"session ~{_format_count(role.session.estimated_tokens)}) {status_text}"
        )
    return [wrap_prose(line, width) for line in lines]


def _format_milestone_status(
    snapshot: WorkspaceSnapshot, *, width: int | None = None
) -> list[str]:
    milestones = snapshot.list_milestones()
    tasks = snapshot.list_tasks()
    missing_milestones = sorted(
        {task.milestone for task in tasks if task.milestone is not None}
        - {milestone.id for milestone in milestones}
    )
    if not milestones and not missing_milestones:
        return ["Milestones: none"]
    lines = ["Milestones:"]
    for milestone in milestones:
        try:
            verification = snapshot.milestone_verification(milestone.id)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            lines.extend(_format_milestone(milestone, tasks, width=width))
            lines.append(wrap_prose(f"  verification: invalid ({exc})", width))
        else:
            lines.extend(_format_milestone(milestone, tasks, verification, width=width))
    for milestone_id in missing_milestones:
        task_ids = [task.id for task in tasks if task.milestone == milestone_id]
        lines.extend(
            [
                wrap_prose(f"- {milestone_id}: missing milestone state file", width),
                "  referenced_by_tasks: " + ", ".join(task_ids),
                wrap_prose("  note: run devlab implement to advance workflow state", width),
            ]
        )
    return lines


def _format_milestone(
    milestone: Milestone,
    tasks: list[Task],
    verification: MilestoneVerification | None = None,
    *,
    width: int | None = None,
) -> list[str]:
    milestone_tasks = [task for task in tasks if task.milestone == milestone.id]
    closed = sum(1 for task in milestone_tasks if task.status == TaskStatus.CLOSED)
    active = len(milestone_tasks) - closed
    lines = [
        wrap_prose(f"- {milestone.id}: {milestone.title}", width),
        f"  status: {milestone.status.value}",
        f"  tasks: {len(milestone_tasks)} total, {closed} closed, {active} active",
        f"  integration_required: {_bool_text(milestone.integration_required)}",
        f"  integrated: {_bool_text(milestone.integrated)}",
        f"  architecture_reviewed: {_bool_text(milestone.architecture_reviewed)}",
    ]
    if milestone.integration_handoff:
        lines.append(f"  integration_handoff: {milestone.integration_handoff}")
    if milestone.architecture_review_handoff:
        lines.append(f"  architecture_review_handoff: {milestone.architecture_review_handoff}")
    if milestone.findings:
        lines.append("  findings: " + ", ".join(milestone.findings))
    else:
        lines.append("  findings: none")
    if verification is not None:
        lines.extend(
            (
                f"  verification: {verification.state}",
                f"  verification_revision: {verification.repository_revision or 'unknown'}",
                f"  verification_commands: {len(verification.commands)}",
                f"  untested_claims: {len(verification.untested_claims)}",
                f"  design_drift: {len(verification.design_drift)}",
            )
        )
    return lines


def _format_finding_status(snapshot: WorkspaceSnapshot, *, width: int | None = None) -> list[str]:
    findings = snapshot.list_findings()
    if not findings:
        return ["Findings: none"]
    tasks = snapshot.list_tasks()
    lines = ["Findings:"]
    for finding in findings:
        lines.extend(_format_finding(finding, tasks, width=width))
    return lines


def _format_finding(finding: Finding, tasks: list[Task], *, width: int | None = None) -> list[str]:
    addressing_tasks = [task.id for task in tasks if finding.id in task.addresses_findings]
    lines = [
        wrap_prose(f"- {finding.id}: {finding.title}", width),
        f"  status: {finding.status.value}",
        f"  source: {finding.source}",
    ]
    if finding.milestone:
        lines.append(f"  milestone: {finding.milestone}")
    if finding.handoff:
        lines.append(f"  handoff: {finding.handoff}")
    if addressing_tasks:
        lines.append("  addressing_tasks: " + ", ".join(addressing_tasks))
    else:
        lines.append("  addressing_tasks: none")
    return lines


def _format_clarification_status(
    snapshot: WorkspaceSnapshot, *, width: int | None = None
) -> list[str]:
    clarifications = snapshot.list_clarifications()
    if not clarifications:
        return ["Clarifications: none"]
    lines = ["Clarifications:"]
    for clarification in clarifications:
        lines.extend(_format_clarification(clarification, width=width))
    return lines


def _format_clarification(clarification: Clarification, *, width: int | None = None) -> list[str]:
    return [
        wrap_prose(f"- {clarification.id}: {clarification.title}", width),
        f"  status: {clarification.status.value}",
        f"  blocks: {clarification.blocks}",
        f"  scope: {clarification.scope}",
        f"  asking_role: {clarification.asking_role}",
    ]


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _format_count(value: int) -> str:
    return f"{value:,}"


def _format_role_agent(config: ResolvedAgentConfig) -> str:
    inactivity = (
        "none"
        if config.inactivity_timeout_seconds is None
        else str(config.inactivity_timeout_seconds)
    )
    maximum = (
        "none"
        if config.max_session_duration_seconds is None
        else str(config.max_session_duration_seconds)
    )
    command = "[" + ", ".join(repr(part) for part in config.command) + "]"
    stdin = "true" if config.uses_stdin else "false"
    return (
        f"- {config.role_name}: {config.provider} "
        f'model="{config.model}" '
        f'effort="{config.effort}" '
        f"inactivity_timeout={inactivity} "
        f"max_duration={maximum} "
        f"command={command} "
        f"stdin={stdin}"
    )

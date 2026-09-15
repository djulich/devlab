from __future__ import annotations

import tomllib
from pathlib import Path

from devlab.agent_config import AGENTS_CONFIG, ResolvedAgentConfig, load_agent_configuration
from devlab.clarifications import Clarification
from devlab.findings import Finding
from devlab.generations import active_generation, archived_generation_numbers
from devlab.milestones import Milestone, MilestoneVerification
from devlab.prerequisites import FilePrerequisiteTracker
from devlab.prompt_context import PromptContextReport, build_prompt_context_report
from devlab.task_tracker import Task, TaskStatus
from devlab.workspace import Workspace, WorkspaceSnapshot


def format_status(root: Path, *, verbose: bool = False) -> str:
    lines: list[str] = []
    snapshot = Workspace(root).snapshot
    role_name = snapshot.assess_state()
    if role_name is None:
        lines.append("No role selected; workflow is complete or blocked.")
    else:
        lines.append(f"Next role: {role_name}")
    lines.append(f"Active generation: {active_generation(root)}")
    archived = archived_generation_numbers(root)
    lines.append(
        "Archived generations: "
        + (", ".join(str(number) for number in archived) if archived else "none")
    )
    blockers = snapshot.blocking_clarifications()
    if blockers:
        lines.append(f"Pending clarification blockers: {len(blockers)}")
        for clarification in blockers[:3]:
            lines.append(f"- {clarification.id}: {clarification.title}")
    lines.extend(_format_active_research(snapshot))
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
        lines.extend(["", *_format_agent_configuration(root)])
        lines.extend(["", *_format_prompt_context(snapshot)])
        lines.extend(["", *_format_clarification_status(snapshot)])
        lines.extend(["", *_format_milestone_status(snapshot)])
        lines.extend(["", *_format_finding_status(snapshot)])
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


def _format_prompt_context(snapshot: WorkspaceSnapshot) -> list[str]:
    report = build_prompt_context_report(snapshot)
    return _format_prompt_context_report(report)


def _format_prompt_context_report(report: PromptContextReport) -> list[str]:
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
    return lines


def _format_milestone_status(snapshot: WorkspaceSnapshot) -> list[str]:
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
            lines.extend(_format_milestone(milestone, tasks))
            lines.append(f"  verification: invalid ({exc})")
        else:
            lines.extend(_format_milestone(milestone, tasks, verification))
    for milestone_id in missing_milestones:
        task_ids = [task.id for task in tasks if task.milestone == milestone_id]
        lines.extend(
            [
                f"- {milestone_id}: missing milestone state file",
                "  referenced_by_tasks: " + ", ".join(task_ids),
                "  note: run devlab implement to advance workflow state",
            ]
        )
    return lines


def _format_milestone(
    milestone: Milestone,
    tasks: list[Task],
    verification: MilestoneVerification | None = None,
) -> list[str]:
    milestone_tasks = [task for task in tasks if task.milestone == milestone.id]
    closed = sum(1 for task in milestone_tasks if task.status == TaskStatus.CLOSED)
    active = len(milestone_tasks) - closed
    lines = [
        f"- {milestone.id}: {milestone.title}",
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


def _format_finding_status(snapshot: WorkspaceSnapshot) -> list[str]:
    findings = snapshot.list_findings()
    if not findings:
        return ["Findings: none"]
    tasks = snapshot.list_tasks()
    lines = ["Findings:"]
    for finding in findings:
        lines.extend(_format_finding(finding, tasks))
    return lines


def _format_finding(finding: Finding, tasks: list[Task]) -> list[str]:
    addressing_tasks = [task.id for task in tasks if finding.id in task.addresses_findings]
    lines = [
        f"- {finding.id}: {finding.title}",
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


def _format_clarification_status(snapshot: WorkspaceSnapshot) -> list[str]:
    clarifications = snapshot.list_clarifications()
    if not clarifications:
        return ["Clarifications: none"]
    lines = ["Clarifications:"]
    for clarification in clarifications:
        lines.extend(_format_clarification(clarification))
    return lines


def _format_clarification(clarification: Clarification) -> list[str]:
    return [
        f"- {clarification.id}: {clarification.title}",
        f"  status: {clarification.status.value}",
        f"  blocks: {clarification.blocks}",
        f"  scope: {clarification.scope}",
        f"  asking_role: {clarification.asking_role}",
    ]


def _format_active_research(snapshot: WorkspaceSnapshot) -> list[str]:
    resume = snapshot.workflow_state().resume
    if resume is None or resume.blocked_kind != "research":
        return []
    try:
        research = snapshot.get_research(resume.blocked_by)
    except KeyError:
        return [f"Research resume: missing {resume.blocked_by} (run devlab doctor)"]
    action = (
        "researcher invocation"
        if research.status.value == "requested"
        else "resumed-role execution"
    )
    return [
        f"Research: {research.id}: {research.title}",
        f"- state: {research.status.value}",
        f"- route: devlab {resume.command}; role={resume.role}; "
        f"task={resume.task or 'none'}; milestone={resume.milestone or 'none'}",
        f"- next: {action} via devlab {resume.command}",
    ]


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _format_count(value: int) -> str:
    return f"{value:,}"


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

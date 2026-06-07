"""Workflow diagnostics facade.

Collects metrics from workspace state and provides the public
build_workflow_diagnostics entry point.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from devlab.artifact_hygiene import (
    LARGE_IGNORED_BYTES_WARNING,
    LARGE_IGNORED_FILES_WARNING,
    ArtifactContributor,
    ArtifactHygiene,
    collect_artifact_hygiene,
    has_large_ignored_artifacts,
)
from devlab.findings import FindingStatus
from devlab.profiles import DEFAULT_PROFILE, PROFILES_DIR, load_profile
from devlab.task_tracker import TaskStatus
from devlab.workflow_history import (
    IntegratorReworkSummary,
    SessionRecord,
    TaskCycleMetrics,
    TaskReworkSummary,
    derive_integrator_rework_summary,
    derive_review_rejections,
    derive_session_records,
    derive_task_cycle_metrics,
    derive_task_rework_summary,
)
from devlab.workspace import Workspace, WorkspaceSnapshot

HIGH_SESSIONS_PER_CLOSED_TASK_WARNING = 6


class DiagnosticCheck(Protocol):
    passed: bool


@dataclasses.dataclass(frozen=True)
class TaskItem:
    id: str
    title: str
    status: str
    milestone: str
    domain: str


@dataclasses.dataclass(frozen=True)
class TaskMetrics:
    total: int
    by_status: dict[str, int]
    items: list[TaskItem]


@dataclasses.dataclass(frozen=True)
class ProfileItem:
    id: str
    title: str
    path: str
    default_validation_count: int
    managed_roles: list[str]
    valid: bool


@dataclasses.dataclass(frozen=True)
class ProfileMetrics:
    count: int
    ids: list[str]
    non_default_ids: list[str]
    items: list[ProfileItem]
    tasks_by_profile: dict[str, list[str]]


@dataclasses.dataclass(frozen=True)
class AgentLogMetrics:
    stdout_count: int
    stderr_count: int
    config_count: int
    metadata_count: int


@dataclasses.dataclass(frozen=True)
class PromptLogMetrics:
    system_count: int
    session_count: int
    max_system_prompt_bytes: int
    max_session_prompt_bytes: int


@dataclasses.dataclass(frozen=True)
class QualitySummary:
    correctness_checked: bool
    correctness_passed: bool | None
    all_tasks_closed: bool
    has_flagged_artifacts: bool
    session_count: int
    warnings: list[str]


@dataclasses.dataclass(frozen=True)
class WorkflowDiagnostics:
    sessions: list[SessionRecord]
    roles: list[str]
    tasks: TaskMetrics
    task_cycles: TaskCycleMetrics
    task_rework: TaskReworkSummary
    findings_created: int
    findings_resolved: int
    review_rejections: int
    integrator_rework: IntegratorReworkSummary
    profiles: ProfileMetrics
    artifact_hygiene: ArtifactHygiene
    agent_logs: AgentLogMetrics
    prompt_logs: PromptLogMetrics
    quality: QualitySummary

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


def build_workflow_diagnostics(root: Path) -> WorkflowDiagnostics:
    snapshot = Workspace(root).snapshot
    findings = snapshot.list_findings()
    sessions = derive_session_records(root)
    task_metrics = collect_task_metrics(root, snapshot=snapshot)
    artifact_hygiene = collect_artifact_hygiene(root)
    task_cycles = derive_task_cycle_metrics(root, sessions, snapshot=snapshot)
    task_rework = derive_task_rework_summary(task_cycles)
    integrator_rework = derive_integrator_rework_summary(findings)
    return WorkflowDiagnostics(
        sessions=sessions,
        roles=[session.role for session in sessions],
        tasks=task_metrics,
        task_cycles=task_cycles,
        task_rework=task_rework,
        findings_created=len(findings),
        findings_resolved=sum(
            1 for finding in findings if finding.status == FindingStatus.RESOLVED
        ),
        review_rejections=derive_review_rejections(root),
        integrator_rework=integrator_rework,
        profiles=collect_profile_metrics(root, snapshot=snapshot),
        artifact_hygiene=artifact_hygiene,
        agent_logs=collect_agent_log_metrics(root),
        prompt_logs=collect_prompt_log_metrics(root),
        quality=quality_summary(
            checks=[],
            task_metrics=task_metrics,
            artifact_hygiene=artifact_hygiene,
            sessions_run=len(sessions),
            task_rework=task_rework,
            integrator_rework=integrator_rework,
        ),
    )


def collect_task_metrics(
    root: Path, *, snapshot: WorkspaceSnapshot | None = None
) -> TaskMetrics:
    tasks = (snapshot or Workspace(root).snapshot).list_tasks()
    by_status: dict[str, int] = {}
    for task in tasks:
        by_status[task.status.value] = by_status.get(task.status.value, 0) + 1
    return TaskMetrics(
        total=len(tasks),
        by_status=by_status,
        items=[
            TaskItem(
                id=task.id,
                title=task.title,
                status=task.status.value,
                milestone=task.milestone or "",
                domain=task.domain,
            )
            for task in tasks
        ],
    )


def collect_profile_metrics(
    root: Path, *, snapshot: WorkspaceSnapshot | None = None
) -> ProfileMetrics:
    profiles: list[ProfileItem] = []
    profiles_path = root / PROFILES_DIR
    for path in sorted(profiles_path.glob("*.toml")):
        profile_id = path.stem
        try:
            profile = load_profile(root, profile_id)
        except (OSError, ValueError):
            profiles.append(
                ProfileItem(
                    id=profile_id,
                    title=profile_id,
                    path=path.relative_to(root).as_posix(),
                    default_validation_count=0,
                    managed_roles=[],
                    valid=False,
                )
            )
            continue
        profiles.append(
            ProfileItem(
                id=profile.id,
                title=profile.title,
                path=path.relative_to(root).as_posix(),
                default_validation_count=len(profile.tooling.default_validation),
                managed_roles=list(profile.environment.managed_roles),
                valid=True,
            )
        )

    tasks = (snapshot or Workspace(root).snapshot).list_tasks()
    tasks_by_profile: dict[str, list[str]] = {}
    for task in tasks:
        profile_id = task.profile or DEFAULT_PROFILE
        tasks_by_profile.setdefault(profile_id, []).append(task.id)

    ids = [item.id for item in profiles]
    return ProfileMetrics(
        count=len(profiles),
        ids=ids,
        non_default_ids=[profile_id for profile_id in ids if profile_id != DEFAULT_PROFILE],
        items=profiles,
        tasks_by_profile={
            key: sorted(value) for key, value in sorted(tasks_by_profile.items())
        },
    )


def collect_agent_log_metrics(root: Path) -> AgentLogMetrics:
    log_dir = root / ".devlab/logs/agents"
    return AgentLogMetrics(
        stdout_count=len(list(log_dir.glob("*.stdout.log"))),
        stderr_count=len(list(log_dir.glob("*.stderr.log"))),
        config_count=len(list(log_dir.glob("*.config.toml"))),
        metadata_count=len(list(log_dir.glob("*.metadata.json"))),
    )


def collect_prompt_log_metrics(root: Path) -> PromptLogMetrics:
    log_dir = root / ".devlab/logs/agents"
    system_logs = list(log_dir.glob("*.system-prompt.md"))
    session_logs = list(log_dir.glob("*.session-prompt.md"))
    return PromptLogMetrics(
        system_count=len(system_logs),
        session_count=len(session_logs),
        max_system_prompt_bytes=max((path.stat().st_size for path in system_logs), default=0),
        max_session_prompt_bytes=max((path.stat().st_size for path in session_logs), default=0),
    )


def quality_summary(
    *,
    checks: Sequence[DiagnosticCheck],
    task_metrics: TaskMetrics,
    artifact_hygiene: ArtifactHygiene,
    sessions_run: int,
    task_rework: TaskReworkSummary | None = None,
    integrator_rework: IntegratorReworkSummary | None = None,
) -> QualitySummary:
    closed = task_metrics.by_status.get(TaskStatus.CLOSED.value, 0)
    all_tasks_closed = task_metrics.total == closed
    warnings = [f"flagged artifact path: {path}" for path in artifact_hygiene.flagged_paths]
    if task_rework is not None:
        warnings.extend(
            f"task rework detected: {task_id}" for task_id in task_rework.tasks_with_rework
        )
    if integrator_rework is not None and integrator_rework.findings_created:
        warnings.append(f"integrator findings created: {integrator_rework.findings_created}")
    if closed and sessions_run / closed > HIGH_SESSIONS_PER_CLOSED_TASK_WARNING:
        warnings.append(f"high session count per closed task: {sessions_run}/{closed}")
    if artifact_hygiene.ignored_total_bytes > LARGE_IGNORED_BYTES_WARNING:
        warnings.append(
            f"large ignored artifact footprint: {artifact_hygiene.ignored_total_bytes} bytes"
        )
    if artifact_hygiene.ignored_file_count > LARGE_IGNORED_FILES_WARNING:
        warnings.append(
            f"large ignored artifact file count: {artifact_hygiene.ignored_file_count}"
        )
    correctness_checked = bool(checks)
    correctness_passed = all(check.passed for check in checks) if correctness_checked else None
    return QualitySummary(
        correctness_checked=correctness_checked,
        correctness_passed=correctness_passed,
        all_tasks_closed=all_tasks_closed,
        has_flagged_artifacts=bool(artifact_hygiene.flagged_paths),
        session_count=sessions_run,
        warnings=warnings,
    )


def format_workflow_diagnostics(root: Path, *, verbose: bool = False) -> str:
    diagnostics = build_workflow_diagnostics(root)
    lines = ["Workflow diagnostics:"]
    lines.append(f"Sessions: {len(diagnostics.sessions)}")
    lines.append(
        "Role sequence: " + (" -> ".join(diagnostics.roles) if diagnostics.roles else "none")
    )
    lines.append(_format_task_summary(diagnostics.tasks))
    lines.append(_format_rework_summary(diagnostics.task_rework))
    lines.append(_format_integrator_summary(diagnostics.integrator_rework))
    lines.append(_format_profile_summary(diagnostics.profiles))
    lines.append(_format_artifact_hygiene_summary(diagnostics.artifact_hygiene))
    if diagnostics.quality.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in diagnostics.quality.warnings)
        if has_large_ignored_artifacts(diagnostics.artifact_hygiene):
            lines.append("Top ignored artifact contributors:")
            lines.extend(
                _format_artifact_contributor(contributor)
                for contributor in diagnostics.artifact_hygiene.ignored_top_contributors[:3]
            )
    else:
        lines.append("Warnings: none")

    if verbose:
        lines.extend(["", *_format_verbose_sections(diagnostics)])
    return "\n".join(lines)


def _format_task_summary(tasks: TaskMetrics) -> str:
    if not tasks.by_status:
        return f"Tasks: {tasks.total} total"
    status_parts = ", ".join(
        f"{count} {status}" for status, count in sorted(tasks.by_status.items())
    )
    return f"Tasks: {tasks.total} total ({status_parts})"


def _format_rework_summary(task_rework: TaskReworkSummary) -> str:
    if task_rework.tasks_with_rework:
        return "Task rework: " + ", ".join(task_rework.tasks_with_rework)
    return "Task rework: none"


def _format_integrator_summary(integrator_rework: IntegratorReworkSummary) -> str:
    return (
        "Integrator findings: "
        f"{integrator_rework.findings_created} created, "
        f"{integrator_rework.findings_resolved} resolved, "
        f"{integrator_rework.findings_open} open, "
        f"{integrator_rework.findings_planned} planned"
    )


def _format_profile_summary(profiles: ProfileMetrics) -> str:
    if profiles.ids:
        return "Profiles: " + ", ".join(profiles.ids)
    return "Profiles: none"


def _format_artifact_hygiene_summary(artifact_hygiene: ArtifactHygiene) -> str:
    return (
        "Artifact hygiene: "
        f"{artifact_hygiene.product_file_count} product files, "
        f"{artifact_hygiene.ignored_file_count} ignored files, "
        f"{len(artifact_hygiene.flagged_paths)} flagged paths"
    )


def _format_artifact_contributor(contributor: ArtifactContributor) -> str:
    return f"- {contributor.path}: {contributor.file_count} files, {contributor.total_bytes} bytes"


def _format_verbose_sections(diagnostics: WorkflowDiagnostics) -> list[str]:
    lines = ["Sessions:"]
    if diagnostics.sessions:
        for session in diagnostics.sessions:
            task_text = f" task={session.task_id}" if session.task_id else ""
            lines.append(
                f"- {session.index}: {session.role}{task_text} "
                f"source={session.task_id_source}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Task cycles:")
    if diagnostics.task_cycles.tasks:
        for task_id, entry in sorted(diagnostics.task_cycles.tasks.items()):
            lines.append(
                f"- {task_id}: developer_sessions={entry.developer_sessions} "
                f"reviewer_sessions={entry.reviewer_sessions} "
                f"rework={_bool_text(entry.has_rework)}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Profiles:")
    if diagnostics.profiles.items:
        for item in diagnostics.profiles.items:
            managed_roles = ", ".join(item.managed_roles) or "none"
            lines.append(
                f"- {item.id}: validation_commands={item.default_validation_count} "
                f"managed_roles={managed_roles} "
                f"valid={_bool_text(item.valid)}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Logs:")
    lines.append(
        "- agent: "
        f"stdout={diagnostics.agent_logs.stdout_count} "
        f"stderr={diagnostics.agent_logs.stderr_count} "
        f"config={diagnostics.agent_logs.config_count} "
        f"metadata={diagnostics.agent_logs.metadata_count}"
    )
    lines.append(
        "- prompts: "
        f"system={diagnostics.prompt_logs.system_count} "
        f"session={diagnostics.prompt_logs.session_count} "
        f"max_system_bytes={diagnostics.prompt_logs.max_system_prompt_bytes} "
        f"max_session_bytes={diagnostics.prompt_logs.max_session_prompt_bytes}"
    )

    lines.append("")
    lines.append("Artifact contributors:")
    lines.extend(
        _format_artifact_contributor_group(
            "product", diagnostics.artifact_hygiene.product_top_contributors,
        )
    )
    lines.extend(
        _format_artifact_contributor_group(
            "ignored", diagnostics.artifact_hygiene.ignored_top_contributors,
        )
    )
    lines.extend(
        _format_artifact_contributor_group(
            "devlab", diagnostics.artifact_hygiene.devlab_top_contributors,
        )
    )
    return lines


def _format_artifact_contributor_group(
    label: str, contributors: list[ArtifactContributor]
) -> list[str]:
    if not contributors:
        return [f"- {label}: none"]
    return [
        f"- {label}: {contributor.path}: "
        f"{contributor.file_count} files, {contributor.total_bytes} bytes"
        for contributor in contributors[:3]
    ]


def _bool_text(value: bool) -> str:
    return "true" if value else "false"

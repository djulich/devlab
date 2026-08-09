"""Workflow diagnostics facade.

Collects metrics from workspace state and provides the public
build_workflow_diagnostics entry point.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from datetime import datetime
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
from devlab.clarifications import ClarificationStatus
from devlab.findings import FindingStatus
from devlab.generations import active_generation, archived_generation_numbers
from devlab.profiles import DEFAULT_PROFILE, PROFILES_DIR, load_profile
from devlab.task_tracker import TaskStatus
from devlab.workflow_events import WorkflowEvent, load_workflow_events
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
    contract_warnings: list[str]


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
    base_count: int
    session_count: int
    max_base_prompt_bytes: int
    max_session_prompt_bytes: int


@dataclasses.dataclass(frozen=True)
class SessionProgressMetrics:
    classified: int
    unclassified: int
    by_kind: dict[str, int]


@dataclasses.dataclass(frozen=True)
class MilestoneVerificationMetrics:
    total: int
    by_state: dict[str, int]
    untested_claims: int
    design_drift: int


@dataclasses.dataclass(frozen=True)
class GenerationMetrics:
    active: int
    archived: list[int]


@dataclasses.dataclass(frozen=True)
class ClarificationMetrics:
    stops_total: int
    stops_by_role: dict[str, int]
    pending: int
    answered: int
    superseded: int
    answered_latency_seconds_avg: float | None
    repeated_roles: list[str]
    repeated_scopes: list[str]


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
    generations: GenerationMetrics
    clarifications: ClarificationMetrics
    artifact_hygiene: ArtifactHygiene
    agent_logs: AgentLogMetrics
    prompt_logs: PromptLogMetrics
    session_progress: SessionProgressMetrics
    milestone_verification: MilestoneVerificationMetrics
    quality: QualitySummary

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


def build_workflow_diagnostics(root: Path) -> WorkflowDiagnostics:
    snapshot = Workspace(root).snapshot
    findings = snapshot.list_findings()
    events = load_workflow_events(root)
    sessions = derive_session_records(root)
    task_metrics = collect_task_metrics(root, snapshot=snapshot)
    artifact_hygiene = collect_artifact_hygiene(root)
    task_cycles = derive_task_cycle_metrics(root, sessions, snapshot=snapshot)
    task_rework = derive_task_rework_summary(task_cycles)
    integrator_rework = derive_integrator_rework_summary(findings)
    clarification_metrics = collect_clarification_metrics(root, snapshot=snapshot, events=events)
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
        generations=collect_generation_metrics(root),
        clarifications=clarification_metrics,
        artifact_hygiene=artifact_hygiene,
        agent_logs=collect_agent_log_metrics(root),
        prompt_logs=collect_prompt_log_metrics(root),
        session_progress=collect_session_progress_metrics(root),
        milestone_verification=collect_milestone_verification_metrics(snapshot),
        quality=quality_summary(
            checks=[],
            task_metrics=task_metrics,
            artifact_hygiene=artifact_hygiene,
            sessions_run=len(sessions),
            task_rework=task_rework,
            task_cycles=task_cycles,
            integrator_rework=integrator_rework,
            clarification_metrics=clarification_metrics,
        ),
    )


def collect_milestone_verification_metrics(
    snapshot: WorkspaceSnapshot,
) -> MilestoneVerificationMetrics:
    records = [
        record
        for milestone in snapshot.list_milestones()
        if (record := snapshot.milestone_verification(milestone.id)) is not None
    ]
    by_state: dict[str, int] = {}
    for record in records:
        by_state[record.state] = by_state.get(record.state, 0) + 1
    return MilestoneVerificationMetrics(
        total=len(records),
        by_state=by_state,
        untested_claims=sum(len(record.untested_claims) for record in records),
        design_drift=sum(len(record.design_drift) for record in records),
    )


def collect_generation_metrics(root: Path) -> GenerationMetrics:
    return GenerationMetrics(
        active=active_generation(root),
        archived=list(archived_generation_numbers(root)),
    )


def collect_clarification_metrics(
    root: Path,
    *,
    snapshot: WorkspaceSnapshot | None = None,
    events: list[WorkflowEvent] | None = None,
) -> ClarificationMetrics:
    snapshot = snapshot or Workspace(root).snapshot
    events = events if events is not None else load_workflow_events(root)
    requested_events = [event for event in events if event.type == "clarification_requested"]
    stops_by_role: dict[str, int] = {}
    for event in requested_events:
        role = str(event.data.get("role") or "unknown")
        stops_by_role[role] = stops_by_role.get(role, 0) + 1

    clarifications = snapshot.list_clarifications()
    scope_counts: dict[str, int] = {}
    for clarification in clarifications:
        scope_counts[clarification.scope] = scope_counts.get(clarification.scope, 0) + 1
    latencies: list[float] = []
    for clarification in clarifications:
        if clarification.status != ClarificationStatus.ANSWERED:
            continue
        if clarification.answered_at is None:
            continue
        created = _parse_timestamp(clarification.created_at)
        answered = _parse_timestamp(clarification.answered_at)
        if created is None or answered is None:
            continue
        latencies.append((answered - created).total_seconds())

    return ClarificationMetrics(
        stops_total=len(requested_events),
        stops_by_role=dict(sorted(stops_by_role.items())),
        pending=sum(1 for item in clarifications if item.status == ClarificationStatus.PENDING),
        answered=sum(1 for item in clarifications if item.status == ClarificationStatus.ANSWERED),
        superseded=sum(
            1 for item in clarifications if item.status == ClarificationStatus.SUPERSEDED
        ),
        answered_latency_seconds_avg=(sum(latencies) / len(latencies) if latencies else None),
        repeated_roles=sorted(role for role, count in stops_by_role.items() if count > 1),
        repeated_scopes=sorted(scope for scope, count in scope_counts.items() if count > 1),
    )


def collect_task_metrics(root: Path, *, snapshot: WorkspaceSnapshot | None = None) -> TaskMetrics:
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
                contract_warnings=list(task.contract_warnings),
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
        tasks_by_profile={key: sorted(value) for key, value in sorted(tasks_by_profile.items())},
    )


def collect_agent_log_metrics(root: Path) -> AgentLogMetrics:
    log_dir = root / ".devlab/logs/agents"
    return AgentLogMetrics(
        stdout_count=len(list(log_dir.glob("*.stdout.log"))),
        stderr_count=len(list(log_dir.glob("*.stderr.log"))),
        config_count=len(list(log_dir.glob("*.config.toml"))),
        metadata_count=len(list(log_dir.glob("*.metadata.json"))),
    )


def collect_session_progress_metrics(root: Path) -> SessionProgressMetrics:
    """Collect progress classifications from durable session metadata."""
    by_kind: dict[str, int] = {}
    unclassified = 0
    for path in (root / ".devlab/logs/agents").glob("*.metadata.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            unclassified += 1
            continue
        progress = data.get("progress")
        if not isinstance(progress, str) or not progress:
            unclassified += 1
            continue
        by_kind[progress] = by_kind.get(progress, 0) + 1
    return SessionProgressMetrics(
        classified=sum(by_kind.values()),
        unclassified=unclassified,
        by_kind=dict(sorted(by_kind.items())),
    )


def collect_prompt_log_metrics(root: Path) -> PromptLogMetrics:
    log_dir = root / ".devlab/logs/agents"
    base_logs = list(log_dir.glob("*.base-prompt.md"))
    session_logs = list(log_dir.glob("*.session-prompt.md"))
    return PromptLogMetrics(
        base_count=len(base_logs),
        session_count=len(session_logs),
        max_base_prompt_bytes=max((path.stat().st_size for path in base_logs), default=0),
        max_session_prompt_bytes=max((path.stat().st_size for path in session_logs), default=0),
    )


def quality_summary(
    *,
    checks: Sequence[DiagnosticCheck],
    task_metrics: TaskMetrics,
    artifact_hygiene: ArtifactHygiene,
    sessions_run: int,
    task_rework: TaskReworkSummary | None = None,
    task_cycles: TaskCycleMetrics | None = None,
    integrator_rework: IntegratorReworkSummary | None = None,
    clarification_metrics: ClarificationMetrics | None = None,
) -> QualitySummary:
    closed = task_metrics.by_status.get(TaskStatus.CLOSED.value, 0)
    all_tasks_closed = task_metrics.total == closed
    warnings = [f"flagged artifact path: {path}" for path in artifact_hygiene.flagged_paths]
    warnings.extend(
        f"task quality warning {item.id}: {warning}"
        for item in task_metrics.items
        for warning in item.contract_warnings
    )
    if task_rework is not None:
        warnings.extend(
            f"task rework detected: {task_id}" for task_id in task_rework.tasks_with_rework
        )
    if task_cycles is not None:
        conflicts = task_cycles.attribution_sources.get("conflicting_task_sources", 0)
        if conflicts:
            warnings.append(f"conflicting task attribution sources: {conflicts}")
        if task_cycles.unattributed_developer_reviewer_sessions:
            warnings.append(
                "unattributed developer/reviewer sessions: "
                f"{task_cycles.unattributed_developer_reviewer_sessions}"
            )
    if integrator_rework is not None and integrator_rework.findings_created:
        warnings.append(f"integrator findings created: {integrator_rework.findings_created}")
    if clarification_metrics is not None:
        warnings.extend(
            f"repeated clarification requests by role: {role}"
            for role in clarification_metrics.repeated_roles
        )
        warnings.extend(
            f"repeated clarification requests for scope: {scope}"
            for scope in clarification_metrics.repeated_scopes
        )
    if closed and sessions_run / closed > HIGH_SESSIONS_PER_CLOSED_TASK_WARNING:
        warnings.append(f"high session count per closed task: {sessions_run}/{closed}")
    if artifact_hygiene.other_ignored_total_bytes > LARGE_IGNORED_BYTES_WARNING:
        warnings.append(
            "large other ignored artifact footprint: "
            f"{artifact_hygiene.other_ignored_total_bytes} bytes"
        )
    if artifact_hygiene.other_ignored_file_count > LARGE_IGNORED_FILES_WARNING:
        warnings.append(
            "large other ignored artifact file count: "
            f"{artifact_hygiene.other_ignored_file_count}"
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
    lines.append(_format_task_attribution_summary(diagnostics.task_cycles))
    lines.append(_format_rework_summary(diagnostics.task_rework))
    lines.append(_format_integrator_summary(diagnostics.integrator_rework))
    lines.append(_format_clarification_summary(diagnostics.clarifications))
    lines.append(_format_profile_summary(diagnostics.profiles))
    lines.append(_format_generation_summary(diagnostics.generations))
    lines.append(_format_artifact_hygiene_summary(diagnostics.artifact_hygiene))
    lines.append(_format_session_progress_summary(diagnostics.session_progress))
    if diagnostics.quality.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in diagnostics.quality.warnings)
        if has_large_ignored_artifacts(diagnostics.artifact_hygiene):
            lines.append("Top other ignored artifact contributors:")
            lines.extend(
                _format_artifact_contributor(contributor)
                for contributor in diagnostics.artifact_hygiene.other_ignored_top_contributors[:3]
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


def _format_task_attribution_summary(task_cycles: TaskCycleMetrics) -> str:
    sources = task_cycles.attribution_sources
    return (
        "Task attribution: "
        f"{sources.get('structured_result', 0)} structured, "
        f"{sources.get('changed_task_artifact_fallback', 0)} legacy fallback, "
        f"{sources.get('conflicting_task_sources', 0)} conflicting, "
        f"{task_cycles.unattributed_developer_reviewer_sessions} unattributed"
    )


def _format_integrator_summary(integrator_rework: IntegratorReworkSummary) -> str:
    return (
        "Integrator findings: "
        f"{integrator_rework.findings_created} created, "
        f"{integrator_rework.findings_resolved} resolved, "
        f"{integrator_rework.findings_open} open, "
        f"{integrator_rework.findings_planned} planned"
    )


def _format_clarification_summary(clarifications: ClarificationMetrics) -> str:
    latency = (
        f"{clarifications.answered_latency_seconds_avg:.0f}s"
        if clarifications.answered_latency_seconds_avg is not None
        else "unknown"
    )
    roles = (
        ", ".join(f"{role}={count}" for role, count in clarifications.stops_by_role.items())
        if clarifications.stops_by_role
        else "none"
    )
    return (
        "Clarifications: "
        f"{clarifications.stops_total} stops, "
        f"{clarifications.pending} pending, "
        f"{clarifications.answered} answered, "
        f"{clarifications.superseded} superseded, "
        f"avg answer latency {latency}, "
        f"by role: {roles}"
    )


def _format_profile_summary(profiles: ProfileMetrics) -> str:
    if profiles.ids:
        return "Profiles: " + ", ".join(profiles.ids)
    return "Profiles: none"


def _format_generation_summary(generations: GenerationMetrics) -> str:
    archived = (
        ", ".join(str(number) for number in generations.archived)
        if generations.archived
        else "none"
    )
    return f"Generations: active {generations.active}, archived {archived}"


def _format_artifact_hygiene_summary(artifact_hygiene: ArtifactHygiene) -> str:
    return (
        "Artifact hygiene: "
        f"{artifact_hygiene.product_file_count} product files, "
        f"{artifact_hygiene.ignored_file_count} ignored files "
        f"({artifact_hygiene.conventional_ignored_file_count} conventional, "
        f"{artifact_hygiene.other_ignored_file_count} other), "
        f"{len(artifact_hygiene.flagged_paths)} flagged paths"
    )


def _format_session_progress_summary(progress: SessionProgressMetrics) -> str:
    kinds = ", ".join(f"{kind}={count}" for kind, count in progress.by_kind.items()) or "none"
    return f"Session progress: {kinds}; unclassified={progress.unclassified}"


def _format_artifact_contributor(contributor: ArtifactContributor) -> str:
    return f"- {contributor.path}: {contributor.file_count} files, {contributor.total_bytes} bytes"


def _format_verbose_sections(diagnostics: WorkflowDiagnostics) -> list[str]:
    lines = ["Sessions:"]
    if diagnostics.sessions:
        for session in diagnostics.sessions:
            task_text = f" task={session.task_id}" if session.task_id else ""
            lines.append(
                f"- {session.index}: {session.role}{task_text} source={session.task_id_source}"
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
        f"base={diagnostics.prompt_logs.base_count} "
        f"session={diagnostics.prompt_logs.session_count} "
        f"max_base_bytes={diagnostics.prompt_logs.max_base_prompt_bytes} "
        f"max_session_bytes={diagnostics.prompt_logs.max_session_prompt_bytes}"
    )

    lines.append("")
    lines.append("Clarifications:")
    lines.append(f"- stops: {diagnostics.clarifications.stops_total}")
    lines.append(f"- by_role: {diagnostics.clarifications.stops_by_role or {}}")
    lines.append(
        "- records: "
        f"pending={diagnostics.clarifications.pending} "
        f"answered={diagnostics.clarifications.answered} "
        f"superseded={diagnostics.clarifications.superseded}"
    )
    latency = diagnostics.clarifications.answered_latency_seconds_avg
    lines.append(
        "- avg_answer_latency_seconds: " + (f"{latency:.0f}" if latency is not None else "unknown")
    )
    repeated_roles = ", ".join(diagnostics.clarifications.repeated_roles) or "none"
    repeated_scopes = ", ".join(diagnostics.clarifications.repeated_scopes) or "none"
    lines.append(f"- repeated_roles: {repeated_roles}")
    lines.append(f"- repeated_scopes: {repeated_scopes}")

    lines.append("")
    lines.append("Artifact contributors:")
    lines.extend(
        _format_artifact_contributor_group(
            "product",
            diagnostics.artifact_hygiene.product_top_contributors,
        )
    )
    lines.extend(
        _format_artifact_contributor_group(
            "conventional ignored",
            diagnostics.artifact_hygiene.conventional_ignored_top_contributors,
        )
    )
    lines.extend(
        _format_artifact_contributor_group(
            "other ignored",
            diagnostics.artifact_hygiene.other_ignored_top_contributors,
        )
    )
    lines.extend(
        _format_artifact_contributor_group(
            "devlab",
            diagnostics.artifact_hygiene.devlab_top_contributors,
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


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

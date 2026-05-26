from __future__ import annotations

import dataclasses
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from devlab.findings import FileFindingTracker, Finding, FindingStatus
from devlab.handoffs import HandoffError, parse_handoff
from devlab.profiles import DEFAULT_PROFILE, PROFILES_DIR, load_profile
from devlab.task_tracker import FileTaskTracker, TaskStatus

_HANDOFF_FILENAME_RE = re.compile(r"^(\d{8}T\d{6})(?:_(\d+))?_([a-z_]+)_handoff\.md$")
_TASK_ARTIFACT_RE = re.compile(r"\.devlab/tasks/(T\d{3,5})[^\s`)]*\.md")
LARGE_IGNORED_BYTES_WARNING = 100_000_000
LARGE_IGNORED_FILES_WARNING = 5_000
HIGH_SESSIONS_PER_CLOSED_TASK_WARNING = 6


class DiagnosticCheck(Protocol):
    passed: bool


@dataclasses.dataclass(frozen=True)
class SessionRecord:
    index: int
    timestamp: str
    counter: int
    role: str
    handoff: str
    task_id: str
    task_id_source: str


@dataclasses.dataclass(frozen=True)
class TaskCycleEntry:
    developer_sessions: int
    reviewer_sessions: int
    has_rework: bool


@dataclasses.dataclass(frozen=True)
class TaskCycleMetrics:
    tasks: dict[str, TaskCycleEntry]
    unattributed_developer_reviewer_sessions: int


@dataclasses.dataclass(frozen=True)
class IntegratorReworkSummary:
    findings_created: int
    findings_resolved: int
    findings_open: int
    findings_planned: int
    finding_ids: list[str]
    has_integrator_rework: bool


@dataclasses.dataclass(frozen=True)
class TaskReworkSummary:
    tasks_with_rework: list[str]
    has_task_rework: bool
    max_developer_sessions_per_task: int
    max_reviewer_sessions_per_task: int
    unattributed_developer_reviewer_sessions: int


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
class ArtifactContributor:
    path: str
    file_count: int
    total_bytes: int


@dataclasses.dataclass(frozen=True)
class ArtifactHygiene:
    file_count: int
    total_bytes: int
    product_file_count: int
    product_total_bytes: int
    ignored_file_count: int
    ignored_total_bytes: int
    devlab_file_count: int
    devlab_total_bytes: int
    flagged_paths: list[str]
    source_files: list[str]
    test_files: list[str]
    ignored_top_contributors: list[ArtifactContributor] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class AgentLogMetrics:
    stdout_count: int
    stderr_count: int
    config_count: int


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
    findings = FileFindingTracker(root).list_findings()
    sessions = derive_session_records(root)
    task_metrics = collect_task_metrics(root)
    artifact_hygiene = collect_artifact_hygiene(root)
    task_cycles = derive_task_cycle_metrics(root, sessions)
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
        profiles=collect_profile_metrics(root),
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
        if _has_large_ignored_artifacts(diagnostics.artifact_hygiene):
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


def derive_role_sequence(root: Path) -> list[str]:
    return [session.role for session in derive_session_records(root)]


def derive_session_records(root: Path) -> list[SessionRecord]:
    parsed: list[tuple[str, int, str, Path]] = []
    for path in (root / ".devlab/history").glob("*_handoff.md"):
        match = _HANDOFF_FILENAME_RE.match(path.name)
        if match:
            counter = int(match.group(2) or "1")
            parsed.append((match.group(1), counter, match.group(3), path))

    sessions: list[SessionRecord] = []
    for index, (timestamp, counter, role, path) in enumerate(sorted(parsed), start=1):
        task_id, task_id_source = _task_id_for_session(path, role)
        sessions.append(
            SessionRecord(
                index=index,
                timestamp=timestamp,
                counter=counter,
                role=role,
                handoff=path.relative_to(root).as_posix(),
                task_id=task_id,
                task_id_source=task_id_source,
            )
        )
    return sessions


def _task_id_for_session(path: Path, role: str) -> tuple[str, str]:
    if role not in {"developer", "reviewer"}:
        return "", "not_task_role"
    try:
        handoff = parse_handoff(path, role)
    except HandoffError:
        return "", "unparseable_handoff"
    changed_artifacts = handoff.section("Changed Artifacts")
    task_ids = sorted(set(_TASK_ARTIFACT_RE.findall(changed_artifacts)))
    if len(task_ids) == 1:
        return task_ids[0], "changed_task_artifact"
    if len(task_ids) > 1:
        return "", "ambiguous_changed_task_artifacts"
    return "", "no_changed_task_artifact"


def derive_task_cycle_metrics(
    root: Path,
    sessions: list[SessionRecord] | None = None,
) -> TaskCycleMetrics:
    session_records = sessions if sessions is not None else derive_session_records(root)
    counts: dict[str, list[int]] = {
        task.id: [0, 0]
        for task in FileTaskTracker(root).list_tasks()
    }
    unattributed = 0
    for session in session_records:
        if session.role not in {"developer", "reviewer"}:
            continue
        if not session.task_id:
            unattributed += 1
            continue
        if session.task_id not in counts:
            counts[session.task_id] = [0, 0]
        idx = 0 if session.role == "developer" else 1
        counts[session.task_id][idx] += 1

    return TaskCycleMetrics(
        tasks={
            task_id: TaskCycleEntry(
                developer_sessions=c[0],
                reviewer_sessions=c[1],
                has_rework=c[0] > 1 or c[1] > 1,
            )
            for task_id, c in counts.items()
        },
        unattributed_developer_reviewer_sessions=unattributed,
    )


def derive_integrator_rework_summary(findings: Sequence[Finding]) -> IntegratorReworkSummary:
    integrator_findings = [finding for finding in findings if finding.source == "integrator"]
    by_status: dict[str, int] = {}
    finding_ids: list[str] = []
    for finding in integrator_findings:
        by_status[finding.status.value] = by_status.get(finding.status.value, 0) + 1
        finding_ids.append(finding.id)
    return IntegratorReworkSummary(
        findings_created=len(integrator_findings),
        findings_resolved=by_status.get(FindingStatus.RESOLVED.value, 0),
        findings_open=by_status.get(FindingStatus.OPEN.value, 0),
        findings_planned=by_status.get(FindingStatus.PLANNED.value, 0),
        finding_ids=sorted(finding_id for finding_id in finding_ids if finding_id),
        has_integrator_rework=bool(integrator_findings),
    )


def derive_task_rework_summary(task_cycles: TaskCycleMetrics) -> TaskReworkSummary:
    tasks_with_rework = [
        task_id
        for task_id, entry in sorted(task_cycles.tasks.items())
        if entry.has_rework
    ]
    return TaskReworkSummary(
        tasks_with_rework=tasks_with_rework,
        has_task_rework=bool(tasks_with_rework),
        max_developer_sessions_per_task=max(
            (entry.developer_sessions for entry in task_cycles.tasks.values()),
            default=0,
        ),
        max_reviewer_sessions_per_task=max(
            (entry.reviewer_sessions for entry in task_cycles.tasks.values()),
            default=0,
        ),
        unattributed_developer_reviewer_sessions=task_cycles.unattributed_developer_reviewer_sessions,
    )


def derive_review_rejections(root: Path) -> int:
    rejections = 0
    for path in (root / ".devlab/history").glob("*_reviewer_handoff.md"):
        try:
            handoff = parse_handoff(path, "reviewer")
        except HandoffError:
            continue
        if handoff.has_open_issues:
            rejections += 1
    return rejections


def collect_task_metrics(root: Path) -> TaskMetrics:
    tasks = FileTaskTracker(root).list_tasks()
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


def collect_profile_metrics(root: Path) -> ProfileMetrics:
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

    tasks = FileTaskTracker(root).list_tasks()
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


def collect_artifact_hygiene(root: Path) -> ArtifactHygiene:
    product_files = [
        path
        for path in _git_ls_files(
            root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
        )
        if not path.startswith(".devlab/")
    ]
    ignored_files = [
        path
        for path in _git_ls_files(
            root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        )
        if not path.startswith(".devlab/")
    ]
    devlab_files = [
        path.relative_to(root).as_posix()
        for path in root.rglob(".devlab/**/*")
        if path.is_file()
    ]
    product_total_bytes = _total_bytes(root, product_files)
    ignored_total_bytes = _total_bytes(root, ignored_files)
    devlab_total_bytes = _total_bytes(root, devlab_files)
    source_files = [path for path in product_files if Path(path).suffix == ".py"]
    test_files = [
        path
        for path in product_files
        if Path(path).name.startswith("test_") or Path(path).name.endswith("_test.py")
    ]
    return ArtifactHygiene(
        file_count=len(product_files),
        total_bytes=product_total_bytes,
        product_file_count=len(product_files),
        product_total_bytes=product_total_bytes,
        ignored_file_count=len(ignored_files),
        ignored_total_bytes=ignored_total_bytes,
        devlab_file_count=len(devlab_files),
        devlab_total_bytes=devlab_total_bytes,
        flagged_paths=[],
        source_files=sorted(source_files),
        test_files=sorted(test_files),
        ignored_top_contributors=_top_artifact_contributors(root, ignored_files),
    )


def collect_agent_log_metrics(root: Path) -> AgentLogMetrics:
    log_dir = root / ".devlab/logs/agents"
    return AgentLogMetrics(
        stdout_count=len(list(log_dir.glob("*.stdout.log"))),
        stderr_count=len(list(log_dir.glob("*.stderr.log"))),
        config_count=len(list(log_dir.glob("*.config.toml"))),
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


def _has_large_ignored_artifacts(artifact_hygiene: ArtifactHygiene) -> bool:
    return (
        artifact_hygiene.ignored_total_bytes > LARGE_IGNORED_BYTES_WARNING
        or artifact_hygiene.ignored_file_count > LARGE_IGNORED_FILES_WARNING
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
        f"config={diagnostics.agent_logs.config_count}"
    )
    lines.append(
        "- prompts: "
        f"system={diagnostics.prompt_logs.system_count} "
        f"session={diagnostics.prompt_logs.session_count} "
        f"max_system_bytes={diagnostics.prompt_logs.max_system_prompt_bytes} "
        f"max_session_bytes={diagnostics.prompt_logs.max_session_prompt_bytes}"
    )
    return lines


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "git command failed: "
            f"git -C {root.as_posix()} {' '.join(args)}\n{result.stderr}"
        )
    return result


def _git_ls_files(root: Path, *args: str) -> list[str]:
    output = _run_git(root, *args).stdout
    return sorted(path for path in output.split("\0") if path)


def _top_artifact_contributors(
    root: Path, relative_paths: Sequence[str], *, limit: int = 5
) -> list[ArtifactContributor]:
    grouped: dict[str, list[int]] = {}
    for relative_path in relative_paths:
        path = root / relative_path
        if not path.is_file():
            continue
        key = _ignored_artifact_contributor_key(root, relative_path)
        entry = grouped.setdefault(key, [0, 0])
        entry[0] += 1
        entry[1] += path.stat().st_size
    return [
        ArtifactContributor(path=key, file_count=count, total_bytes=total_bytes)
        for key, (count, total_bytes) in sorted(
            grouped.items(), key=lambda item: (-item[1][1], item[0])
        )[:limit]
    ]


def _ignored_artifact_contributor_key(root: Path, relative_path: str) -> str:
    parts = Path(relative_path).parts
    for index in range(1, len(parts) + 1):
        candidate = Path(*parts[:index]).as_posix()
        if _is_git_ignored(root, candidate):
            path = root / candidate
            return candidate + "/" if path.is_dir() else candidate
    if len(parts) <= 1:
        return relative_path
    return f"{parts[0]}/"


def _is_git_ignored(root: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", root.as_posix(), "check-ignore", "-q", "--", relative_path],
        check=False,
    )
    return result.returncode == 0


def _total_bytes(root: Path, relative_paths: Sequence[str]) -> int:
    total = 0
    for relative_path in relative_paths:
        path = root / relative_path
        if path.is_file():
            total += path.stat().st_size
    return total


def _bool_text(value: bool) -> str:
    return "true" if value else "false"

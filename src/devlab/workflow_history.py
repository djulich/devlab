"""Workflow history derivation from handoff files.

Derives session records, task cycles, rework metrics, and review
rejections from archived handoff files in .devlab/history/.
"""

from __future__ import annotations

import dataclasses
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from devlab.findings import Finding, FindingStatus
from devlab.handoffs import HandoffError, load_session_result, parse_handoff
from devlab.workspace import Workspace, WorkspaceSnapshot

_HANDOFF_FILENAME_RE = re.compile(r"^(\d{8}T\d{6})(?:_(\d+))?_([a-z_]+)_handoff\.md$")
_TASK_ARTIFACT_RE = re.compile(r"\.devlab/tasks/(T\d{3,5})[^\s`)]*\.md")


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
    attribution_sources: dict[str, int] = dataclasses.field(default_factory=dict)


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
    artifact_task_ids = _task_ids_from_changed_artifacts(path, role)
    result_path = path.with_name(path.name.removesuffix("_handoff.md") + "_result.toml")
    if result_path.exists():
        try:
            result = load_session_result(result_path)
        except HandoffError:
            return "", "unparseable_structured_result"
        if result.envelope.role != role or not result.envelope.task:
            return "", "invalid_structured_result_identity"
        result_task_id = result.envelope.task
        if artifact_task_ids and artifact_task_ids != {result_task_id}:
            return "", "conflicting_task_sources"
        return result_task_id, "structured_result"

    if len(artifact_task_ids) == 1:
        return next(iter(artifact_task_ids)), "changed_task_artifact_fallback"
    if len(artifact_task_ids) > 1:
        return "", "ambiguous_changed_task_artifacts"
    return "", "missing_structured_result"


def _task_ids_from_changed_artifacts(path: Path, role: str) -> set[str]:
    try:
        handoff = parse_handoff(path, role)
    except HandoffError:
        return set()
    changed_artifacts = handoff.section("Changed Artifacts")
    return set(_TASK_ARTIFACT_RE.findall(changed_artifacts))


def derive_task_cycle_metrics(
    root: Path,
    sessions: list[SessionRecord] | None = None,
    *,
    snapshot: WorkspaceSnapshot | None = None,
) -> TaskCycleMetrics:
    session_records = sessions if sessions is not None else derive_session_records(root)
    tasks = (snapshot or Workspace(root).snapshot).list_tasks()
    counts: dict[str, list[int]] = {task.id: [0, 0] for task in tasks}
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
        attribution_sources=dict(
            sorted(
                Counter(
                    session.task_id_source
                    for session in session_records
                    if session.role in {"developer", "reviewer"}
                ).items()
            )
        ),
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

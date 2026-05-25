from __future__ import annotations

import dataclasses
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

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
class WorkflowDiagnostics:
    sessions: list[dict[str, object]]
    roles: list[str]
    tasks: dict[str, object]
    task_cycles: dict[str, object]
    task_rework: dict[str, object]
    findings_created: int
    findings_resolved: int
    review_rejections: int
    integrator_rework: dict[str, object]
    profiles: dict[str, object]
    artifact_hygiene: dict[str, object]
    agent_logs: dict[str, object]
    prompt_logs: dict[str, object]
    quality: dict[str, object]

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
        roles=[str(session["role"]) for session in sessions],
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
    warnings = diagnostics.quality.get("warnings", [])
    warning_list = [str(warning) for warning in warnings] if isinstance(warnings, list) else []
    if warning_list:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in warning_list)
    else:
        lines.append("Warnings: none")

    if verbose:
        lines.extend(["", *_format_verbose_sections(diagnostics)])
    return "\n".join(lines)


def derive_role_sequence(root: Path) -> list[str]:
    return [str(session["role"]) for session in derive_session_records(root)]


def derive_session_records(root: Path) -> list[dict[str, object]]:
    parsed: list[tuple[str, int, str, Path]] = []
    for path in (root / ".devlab/history").glob("*_handoff.md"):
        match = _HANDOFF_FILENAME_RE.match(path.name)
        if match:
            counter = int(match.group(2) or "1")
            parsed.append((match.group(1), counter, match.group(3), path))

    sessions: list[dict[str, object]] = []
    for index, (timestamp, counter, role, path) in enumerate(sorted(parsed), start=1):
        task_id, task_id_source = _task_id_for_session(path, role)
        sessions.append(
            {
                "index": index,
                "timestamp": timestamp,
                "counter": counter,
                "role": role,
                "handoff": path.relative_to(root).as_posix(),
                "task_id": task_id,
                "task_id_source": task_id_source,
            }
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
    sessions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    session_records = sessions if sessions is not None else derive_session_records(root)
    metrics: dict[str, dict[str, int | bool]] = {
        task.id: {
            "developer_sessions": 0,
            "reviewer_sessions": 0,
            "has_rework": False,
        }
        for task in FileTaskTracker(root).list_tasks()
    }
    unattributed = 0
    for session in session_records:
        role = session.get("role")
        if role not in {"developer", "reviewer"}:
            continue
        task_id = session.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            unattributed += 1
            continue
        if task_id not in metrics:
            metrics[task_id] = {
                "developer_sessions": 0,
                "reviewer_sessions": 0,
                "has_rework": False,
            }
        key = "developer_sessions" if role == "developer" else "reviewer_sessions"
        metrics_for_task = metrics[task_id]
        metrics_for_task[key] = metrics_for_task[key] + 1

    for metrics_for_task in metrics.values():
        metrics_for_task["has_rework"] = (
            metrics_for_task["developer_sessions"] > 1
            or metrics_for_task["reviewer_sessions"] > 1
        )

    return {
        "tasks": metrics,
        "unattributed_developer_reviewer_sessions": unattributed,
    }


def derive_integrator_rework_summary(findings: Sequence[Finding]) -> dict[str, object]:
    integrator_findings = [finding for finding in findings if finding.source == "integrator"]
    by_status: dict[str, int] = {}
    finding_ids: list[str] = []
    for finding in integrator_findings:
        by_status[finding.status.value] = by_status.get(finding.status.value, 0) + 1
        finding_ids.append(finding.id)
    return {
        "findings_created": len(integrator_findings),
        "findings_resolved": by_status.get(FindingStatus.RESOLVED.value, 0),
        "findings_open": by_status.get(FindingStatus.OPEN.value, 0),
        "findings_planned": by_status.get(FindingStatus.PLANNED.value, 0),
        "finding_ids": sorted(finding_id for finding_id in finding_ids if finding_id),
        "has_integrator_rework": bool(integrator_findings),
    }


def derive_task_rework_summary(task_cycles: dict[str, object]) -> dict[str, object]:
    raw_tasks = task_cycles.get("tasks", {})
    tasks = (
        cast("dict[str, dict[str, int | bool]]", raw_tasks)
        if isinstance(raw_tasks, dict)
        else {}
    )
    tasks_with_rework = [
        task_id for task_id, metrics in sorted(tasks.items()) if bool(metrics.get("has_rework"))
    ]
    max_developer_sessions = max(
        (cast("int", metrics.get("developer_sessions", 0)) for metrics in tasks.values()),
        default=0,
    )
    max_reviewer_sessions = max(
        (cast("int", metrics.get("reviewer_sessions", 0)) for metrics in tasks.values()),
        default=0,
    )
    return {
        "tasks_with_rework": tasks_with_rework,
        "has_task_rework": bool(tasks_with_rework),
        "max_developer_sessions_per_task": max_developer_sessions,
        "max_reviewer_sessions_per_task": max_reviewer_sessions,
        "unattributed_developer_reviewer_sessions": task_cycles.get(
            "unattributed_developer_reviewer_sessions", 0
        ),
    }


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


def collect_task_metrics(root: Path) -> dict[str, object]:
    tasks = FileTaskTracker(root).list_tasks()
    by_status: dict[str, int] = {}
    for task in tasks:
        by_status[task.status.value] = by_status.get(task.status.value, 0) + 1
    return {
        "total": len(tasks),
        "by_status": by_status,
        "items": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status.value,
                "milestone": task.milestone or "",
                "domain": task.domain,
            }
            for task in tasks
        ],
    }


def collect_profile_metrics(root: Path) -> dict[str, object]:
    profiles = []
    profiles_path = root / PROFILES_DIR
    for path in sorted(profiles_path.glob("*.toml")):
        profile_id = path.stem
        try:
            profile = load_profile(root, profile_id)
        except (OSError, ValueError):
            profiles.append(
                {
                    "id": profile_id,
                    "title": profile_id,
                    "path": path.relative_to(root).as_posix(),
                    "default_validation_count": 0,
                    "managed_roles": [],
                    "valid": False,
                }
            )
            continue
        profiles.append(
            {
                "id": profile.id,
                "title": profile.title,
                "path": path.relative_to(root).as_posix(),
                "default_validation_count": len(profile.tooling.default_validation),
                "managed_roles": list(profile.environment.managed_roles),
                "valid": True,
            }
        )

    tasks = FileTaskTracker(root).list_tasks()
    tasks_by_profile: dict[str, list[str]] = {}
    for task in tasks:
        profile_id = task.profile or DEFAULT_PROFILE
        tasks_by_profile.setdefault(profile_id, []).append(task.id)

    ids = [str(profile["id"]) for profile in profiles]
    return {
        "count": len(profiles),
        "ids": ids,
        "non_default_ids": [profile_id for profile_id in ids if profile_id != DEFAULT_PROFILE],
        "items": profiles,
        "tasks_by_profile": {
            key: sorted(value) for key, value in sorted(tasks_by_profile.items())
        },
    }


def collect_artifact_hygiene(root: Path) -> dict[str, object]:
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
    return {
        "file_count": len(product_files),
        "total_bytes": product_total_bytes,
        "product_file_count": len(product_files),
        "product_total_bytes": product_total_bytes,
        "ignored_file_count": len(ignored_files),
        "ignored_total_bytes": ignored_total_bytes,
        "devlab_file_count": len(devlab_files),
        "devlab_total_bytes": devlab_total_bytes,
        "flagged_paths": [],
        "source_files": sorted(source_files),
        "test_files": sorted(test_files),
    }


def collect_agent_log_metrics(root: Path) -> dict[str, object]:
    log_dir = root / ".devlab/logs/agents"
    return {
        "stdout_count": len(list(log_dir.glob("*.stdout.log"))),
        "stderr_count": len(list(log_dir.glob("*.stderr.log"))),
        "config_count": len(list(log_dir.glob("*.config.toml"))),
    }


def collect_prompt_log_metrics(root: Path) -> dict[str, object]:
    log_dir = root / ".devlab/logs/agents"
    system_logs = list(log_dir.glob("*.system-prompt.md"))
    session_logs = list(log_dir.glob("*.session-prompt.md"))
    return {
        "system_count": len(system_logs),
        "session_count": len(session_logs),
        "max_system_prompt_bytes": max((path.stat().st_size for path in system_logs), default=0),
        "max_session_prompt_bytes": max((path.stat().st_size for path in session_logs), default=0),
    }


def quality_summary(
    *,
    checks: Sequence[DiagnosticCheck],
    task_metrics: dict[str, object],
    artifact_hygiene: dict[str, object],
    sessions_run: int,
    task_rework: dict[str, object] | None = None,
    integrator_rework: dict[str, object] | None = None,
) -> dict[str, object]:
    raw_by_status = task_metrics.get("by_status", {})
    by_status = cast("dict[str, int]", raw_by_status) if isinstance(raw_by_status, dict) else {}
    closed = by_status.get(TaskStatus.CLOSED.value, 0)
    all_tasks_closed = task_metrics.get("total") == closed
    flagged_paths = artifact_hygiene.get("flagged_paths", [])
    flagged_list = list(flagged_paths) if isinstance(flagged_paths, list) else []
    warnings = [f"flagged artifact path: {path}" for path in flagged_list]
    task_rework = task_rework or {}
    integrator_rework = integrator_rework or {}
    reworked_tasks = task_rework.get("tasks_with_rework", [])
    if isinstance(reworked_tasks, list):
        warnings.extend(f"task rework detected: {task_id}" for task_id in reworked_tasks)
    integrator_findings = integrator_rework.get("findings_created", 0)
    if isinstance(integrator_findings, int) and integrator_findings:
        warnings.append(f"integrator findings created: {integrator_findings}")
    if closed and sessions_run / closed > HIGH_SESSIONS_PER_CLOSED_TASK_WARNING:
        warnings.append(f"high session count per closed task: {sessions_run}/{closed}")
    ignored_file_count = artifact_hygiene.get("ignored_file_count", 0)
    ignored_total_bytes = artifact_hygiene.get("ignored_total_bytes", 0)
    if isinstance(ignored_total_bytes, int) and ignored_total_bytes > LARGE_IGNORED_BYTES_WARNING:
        warnings.append(f"large ignored artifact footprint: {ignored_total_bytes} bytes")
    if isinstance(ignored_file_count, int) and ignored_file_count > LARGE_IGNORED_FILES_WARNING:
        warnings.append(f"large ignored artifact file count: {ignored_file_count}")
    correctness_checked = bool(checks)
    correctness_passed = all(check.passed for check in checks) if correctness_checked else None
    return {
        "correctness_checked": correctness_checked,
        "correctness_passed": correctness_passed,
        "all_tasks_closed": all_tasks_closed,
        "has_flagged_artifacts": bool(flagged_list),
        "session_count": sessions_run,
        "warnings": warnings,
    }


def _format_task_summary(tasks: dict[str, object]) -> str:
    total = tasks.get("total", 0)
    by_status = tasks.get("by_status", {})
    if not isinstance(by_status, dict) or not by_status:
        return f"Tasks: {total} total"
    status_parts = ", ".join(
        f"{count} {status}" for status, count in sorted(by_status.items())
    )
    return f"Tasks: {total} total ({status_parts})"


def _format_rework_summary(task_rework: dict[str, object]) -> str:
    tasks = task_rework.get("tasks_with_rework", [])
    if isinstance(tasks, list) and tasks:
        return "Task rework: " + ", ".join(str(task_id) for task_id in tasks)
    return "Task rework: none"


def _format_integrator_summary(integrator_rework: dict[str, object]) -> str:
    created = integrator_rework.get("findings_created", 0)
    resolved = integrator_rework.get("findings_resolved", 0)
    open_count = integrator_rework.get("findings_open", 0)
    planned = integrator_rework.get("findings_planned", 0)
    return (
        "Integrator findings: "
        f"{created} created, {resolved} resolved, {open_count} open, {planned} planned"
    )


def _format_profile_summary(profiles: dict[str, object]) -> str:
    ids = profiles.get("ids", [])
    if isinstance(ids, list) and ids:
        return "Profiles: " + ", ".join(str(profile_id) for profile_id in ids)
    return "Profiles: none"


def _format_artifact_hygiene_summary(artifact_hygiene: dict[str, object]) -> str:
    return (
        "Artifact hygiene: "
        f"{artifact_hygiene.get('product_file_count', 0)} product files, "
        f"{artifact_hygiene.get('ignored_file_count', 0)} ignored files, "
        f"{len(cast('list[object]', artifact_hygiene.get('flagged_paths', [])))} flagged paths"
    )


def _format_verbose_sections(diagnostics: WorkflowDiagnostics) -> list[str]:
    lines = ["Sessions:"]
    if diagnostics.sessions:
        for session in diagnostics.sessions:
            task_id = str(session.get("task_id") or "")
            task_text = f" task={task_id}" if task_id else ""
            source = session.get("task_id_source", "")
            lines.append(
                f"- {session.get('index')}: {session.get('role')}{task_text} source={source}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Task cycles:")
    raw_tasks = diagnostics.task_cycles.get("tasks", {})
    task_cycles = (
        cast("dict[str, dict[str, object]]", raw_tasks) if isinstance(raw_tasks, dict) else {}
    )
    if task_cycles:
        for task_id, metrics in sorted(task_cycles.items()):
            lines.append(
                f"- {task_id}: developer_sessions={metrics.get('developer_sessions', 0)} "
                f"reviewer_sessions={metrics.get('reviewer_sessions', 0)} "
                f"rework={_bool_text(bool(metrics.get('has_rework')))}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Profiles:")
    profile_items = diagnostics.profiles.get("items", [])
    if isinstance(profile_items, list) and profile_items:
        for item in profile_items:
            if not isinstance(item, dict):
                continue
            profile = cast("dict[str, object]", item)
            managed_roles = ", ".join(
                cast("list[str]", profile.get("managed_roles", []))
            ) or "none"
            lines.append(
                f"- {profile.get('id')}: validation_commands="
                f"{profile.get('default_validation_count', 0)} "
                f"managed_roles={managed_roles} "
                f"valid={_bool_text(bool(profile.get('valid')))}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Logs:")
    lines.append(
        "- agent: "
        f"stdout={diagnostics.agent_logs.get('stdout_count', 0)} "
        f"stderr={diagnostics.agent_logs.get('stderr_count', 0)} "
        f"config={diagnostics.agent_logs.get('config_count', 0)}"
    )
    lines.append(
        "- prompts: "
        f"system={diagnostics.prompt_logs.get('system_count', 0)} "
        f"session={diagnostics.prompt_logs.get('session_count', 0)} "
        f"max_system_bytes={diagnostics.prompt_logs.get('max_system_prompt_bytes', 0)} "
        f"max_session_bytes={diagnostics.prompt_logs.get('max_session_prompt_bytes', 0)}"
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


def _total_bytes(root: Path, relative_paths: Sequence[str]) -> int:
    total = 0
    for relative_path in relative_paths:
        path = root / relative_path
        if path.is_file():
            total += path.stat().st_size
    return total


def _bool_text(value: bool) -> str:
    return "true" if value else "false"

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from devlab.findings import Finding, FindingStatus
from devlab.handoffs import HandoffError, parse_handoff
from devlab.profiles import DEFAULT_PROFILE, PROFILES_DIR, load_profile
from devlab.task_tracker import FileTaskTracker, TaskStatus
from tests.evaluations.checks import CheckResult

_HANDOFF_FILENAME_RE = re.compile(r"^(\d{8}T\d{6})(?:_(\d+))?_([a-z_]+)_handoff\.md$")
_TASK_ARTIFACT_RE = re.compile(r"\.devlab/tasks/(T\d{3,5})[^\s`)]*\.md")


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
    checks: list[CheckResult],
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
    if closed and sessions_run / closed > 6:
        warnings.append(f"high session count per closed task: {sessions_run}/{closed}")
    ignored_file_count = artifact_hygiene.get("ignored_file_count", 0)
    ignored_total_bytes = artifact_hygiene.get("ignored_total_bytes", 0)
    if isinstance(ignored_total_bytes, int) and ignored_total_bytes > 100_000_000:
        warnings.append(f"large ignored artifact footprint: {ignored_total_bytes} bytes")
    if isinstance(ignored_file_count, int) and ignored_file_count > 5_000:
        warnings.append(f"large ignored artifact file count: {ignored_file_count}")
    return {
        "correctness_passed": all(check.passed for check in checks),
        "all_tasks_closed": all_tasks_closed,
        "has_flagged_artifacts": bool(flagged_list),
        "session_count": sessions_run,
        "warnings": warnings,
    }


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

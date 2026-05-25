from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from devlab.agents import AgentInvocation, MockProvider
from devlab.findings import FileFindingTracker, Finding, FindingStatus
from devlab.handoffs import HandoffError, parse_handoff
from devlab.init import init_workspace
from devlab.orchestrator import RunResult, run_loop
from devlab.task_tracker import FileTaskTracker, TaskStatus


@dataclasses.dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str = ""


BlackBoxCheck = Callable[[Path], CheckResult]


class ScriptedAgent(Protocol):
    roles: list[str]
    review_rejections: int
    prompt_chars: list[int]

    def on_invoke(self, invocation: AgentInvocation) -> None: ...

    def handoff_for(self, invocation: AgentInvocation) -> str: ...


@dataclasses.dataclass(frozen=True)
class EvaluationScenario:
    id: str
    title: str
    system_spec: str
    max_sessions: int
    checks: tuple[BlackBoxCheck, ...]
    deployment_spec: str = ""
    scripted_agent: ScriptedAgent | None = None
    expected_roles: tuple[str, ...] = ()
    expected_sessions: int | None = None
    expected_rejections: int = 0
    expected_findings: int = 0


@dataclasses.dataclass
class EvaluationDiagnostics:
    scenario_id: str
    provider_mode: str
    sessions_run: int
    completed: bool
    exit_code: int
    roles: list[str]
    findings_created: int
    findings_resolved: int
    review_rejections: int
    duration_seconds: float
    max_prompt_chars: int
    checks: list[dict[str, object]]
    artifacts: list[str]
    timestamp: str
    target_root: str
    agent_log_dir: str
    git_commit: str = ""
    provider: str = ""
    model: str = ""
    effort: str = ""
    tasks: dict[str, object] = dataclasses.field(default_factory=dict)
    artifact_hygiene: dict[str, object] = dataclasses.field(default_factory=dict)
    agent_logs: dict[str, object] = dataclasses.field(default_factory=dict)
    prompt_logs: dict[str, object] = dataclasses.field(default_factory=dict)
    quality: dict[str, object] = dataclasses.field(default_factory=dict)
    sessions: list[dict[str, object]] = dataclasses.field(default_factory=list)
    task_cycles: dict[str, object] = dataclasses.field(default_factory=dict)
    task_rework: dict[str, object] = dataclasses.field(default_factory=dict)
    integrator_rework: dict[str, object] = dataclasses.field(default_factory=dict)

    def write(self, root: Path) -> Path:
        path = root / ".devlab/evaluations" / f"{self.scenario_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataclasses.asdict(self), indent=2, sort_keys=True))
        _export_diagnostics(path, self.scenario_id, self.provider_mode)
        return path


def run_scripted_evaluation(root: Path, scenario: EvaluationScenario) -> EvaluationDiagnostics:
    if scenario.scripted_agent is None:
        raise ValueError("scripted scenario requires scripted_agent")
    init_target_workspace(root, scenario.system_spec, deployment_spec=scenario.deployment_spec)
    provider = MockProvider(
        on_invoke=scenario.scripted_agent.on_invoke,
        handoff_text=scenario.scripted_agent.handoff_for,
    )
    started = time.monotonic()
    result = run_loop(
        root,
        auto=True,
        max_sessions=scenario.max_sessions,
        agent_providers={"default": provider},
        automatic_version_control=True,
    )
    duration = time.monotonic() - started
    checks = [check(root) for check in scenario.checks]
    diagnostics = diagnostics_for(
        root,
        scenario,
        result,
        checks,
        duration,
        provider_mode="scripted",
        roles=scenario.scripted_agent.roles,
        review_rejections=scenario.scripted_agent.review_rejections,
        prompt_chars=scenario.scripted_agent.prompt_chars,
    )
    path = diagnostics.write(root)
    assert path.exists()
    return diagnostics


def run_live_evaluation(
    root: Path,
    scenario: EvaluationScenario,
    *,
    provider: str | None,
    model: str | None,
    effort: str | None,
    agent_config: Path | None,
    max_sessions: int,
) -> EvaluationDiagnostics:
    init_target_workspace(root, scenario.system_spec, deployment_spec=scenario.deployment_spec)
    if agent_config is not None:
        shutil.copyfile(agent_config, root / ".devlab/config/agents.toml")
        _run_git(root, "add", ".devlab/config/agents.toml")
        _run_git(root, "commit", "-m", "Configure live evaluation agents")
    started = time.monotonic()
    result = run_loop(
        root,
        auto=True,
        max_sessions=max_sessions,
        provider=provider,
        model=model,
        effort=effort,
        retain_prompts=os.environ.get("DEVLAB_LIVE_RETAIN_PROMPTS") == "1",
        automatic_version_control=True,
        session_progress=_print_live_session_progress,
    )
    duration = time.monotonic() - started
    checks = [check(root) for check in scenario.checks]
    diagnostics = diagnostics_for(
        root,
        scenario,
        result,
        checks,
        duration,
        provider_mode="live",
        roles=derive_role_sequence(root),
        review_rejections=derive_review_rejections(root),
        prompt_chars=[],
        provider=provider or "",
        model=model or "",
        effort=effort or "",
    )
    path = diagnostics.write(root)
    assert path.exists()
    return diagnostics


def _print_live_session_progress(event: str, session_number: int, role_name: str) -> None:
    timestamp = datetime.now(UTC).strftime("%H:%M:%S")
    print(
        f"[{timestamp}] live eval session {session_number} {event}: {role_name}",
        file=sys.stderr,
        flush=True,
    )


def diagnostics_for(
    root: Path,
    scenario: EvaluationScenario,
    result: RunResult,
    checks: list[CheckResult],
    duration: float,
    *,
    provider_mode: str,
    roles: list[str],
    review_rejections: int,
    prompt_chars: list[int],
    provider: str = "",
    model: str = "",
    effort: str = "",
) -> EvaluationDiagnostics:
    findings = FileFindingTracker(root).list_findings()
    task_metrics = collect_task_metrics(root)
    artifact_hygiene = collect_artifact_hygiene(root)
    agent_logs = collect_agent_log_metrics(root)
    prompt_logs = collect_prompt_log_metrics(root)
    sessions = derive_session_records(root)
    task_cycles = derive_task_cycle_metrics(root, sessions)
    task_rework = derive_task_rework_summary(task_cycles)
    integrator_rework = derive_integrator_rework_summary(findings)
    return EvaluationDiagnostics(
        scenario_id=scenario.id,
        provider_mode=provider_mode,
        sessions_run=result.sessions_run,
        completed=result.completed,
        exit_code=result.exit_code,
        roles=list(roles),
        findings_created=len(findings),
        findings_resolved=sum(
            1 for finding in findings if finding.status == FindingStatus.RESOLVED
        ),
        review_rejections=review_rejections,
        duration_seconds=duration,
        max_prompt_chars=max(prompt_chars, default=0),
        checks=[dataclasses.asdict(check) for check in checks],
        artifacts=list_artifacts(root),
        timestamp=datetime.now(UTC).isoformat(),
        target_root=root.as_posix(),
        agent_log_dir=(root / ".devlab/logs/agents").as_posix(),
        git_commit=_git_commit(),
        provider=provider,
        model=model,
        effort=effort,
        tasks=task_metrics,
        artifact_hygiene=artifact_hygiene,
        agent_logs=agent_logs,
        prompt_logs=prompt_logs,
        quality=quality_summary(
            checks=checks,
            task_metrics=task_metrics,
            artifact_hygiene=artifact_hygiene,
            sessions_run=result.sessions_run,
        ),
        sessions=sessions,
        task_cycles=task_cycles,
        task_rework=task_rework,
        integrator_rework=integrator_rework,
    )


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
) -> dict[str, object]:
    raw_by_status = task_metrics.get("by_status", {})
    by_status = cast("dict[str, int]", raw_by_status) if isinstance(raw_by_status, dict) else {}
    closed = by_status.get(TaskStatus.CLOSED.value, 0)
    all_tasks_closed = task_metrics.get("total") == closed
    flagged_paths = artifact_hygiene.get("flagged_paths", [])
    flagged_list = list(flagged_paths) if isinstance(flagged_paths, list) else []
    return {
        "correctness_passed": all(check.passed for check in checks),
        "all_tasks_closed": all_tasks_closed,
        "has_flagged_artifacts": bool(flagged_list),
        "session_count": sessions_run,
        "warnings": [f"flagged artifact path: {path}" for path in flagged_list],
    }


def require_git() -> None:
    result = subprocess.run(
        ["git", "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("workflow evaluations require git on PATH")


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    require_git()
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


def init_target_workspace(
    root: Path,
    system_spec: str,
    *,
    deployment_spec: str = "",
) -> None:
    init_workspace(root, automatic_git=True)
    (root / ".devlab/specs/system/README.md").write_text(
        f"# System Specification\n\n{system_spec}\n"
    )
    if deployment_spec:
        (root / ".devlab/specs/deployment/README.md").write_text(
            f"# Deployment Specification\n\n{deployment_spec}\n"
        )
    (root / ".devlab/config/profiles/default.toml").write_text(
        'version = 1\n'
        'id = "default"\n'
        'title = "Default evaluation profile"\n'
        '\n[tooling]\n'
        'summary = "Evaluation profile with no environment commands."\n'
        'default_validation = []\n'
        '\n[environment]\n'
        'managed_roles = []\n'
    )
    if _run_git(root, "status", "--porcelain").stdout.strip():
        _run_git(root, "add", ".")
        _run_git(root, "commit", "-m", "Configure evaluation workspace")




def list_artifacts(root: Path) -> list[str]:
    ignored = (root / ".devlab/logs", root / ".devlab/evaluations")
    return [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not any(path.is_relative_to(prefix) for prefix in ignored)
    ]


def command_check(name: str, args: Sequence[str], expected_stdout: str) -> BlackBoxCheck:
    def check(root: Path) -> CheckResult:
        result = subprocess.run(
            [sys.executable, *args],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        passed = result.returncode == 0 and result.stdout.strip() == expected_stdout
        return CheckResult(
            name=name,
            passed=passed,
            message=(
                ""
                if passed
                else f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            ),
        )

    return check


def command_fails_check(name: str, args: Sequence[str]) -> BlackBoxCheck:
    def check(root: Path) -> CheckResult:
        result = subprocess.run(
            [sys.executable, *args],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        passed = result.returncode != 0
        return CheckResult(
            name=name,
            passed=passed,
            message="" if passed else f"expected nonzero exit; stdout={result.stdout!r}",
        )

    return check


def file_contains_check(name: str, relative_path: str, expected_text: str) -> BlackBoxCheck:
    def check(root: Path) -> CheckResult:
        path = root / relative_path
        if not path.exists():
            return CheckResult(name, False, f"missing {relative_path}")
        text = path.read_text()
        passed = expected_text in text
        return CheckResult(name, passed, "" if passed else f"{expected_text!r} not found")

    return check



def _export_diagnostics(path: Path, scenario_id: str, provider_mode: str) -> None:
    results_dir = os.environ.get("DEVLAB_EVAL_RESULTS_DIR")
    if not results_dir:
        return
    destination_dir = Path(results_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    shutil.copyfile(path, destination_dir / f"{timestamp}_{scenario_id}_{provider_mode}.json")


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        text=True,
        capture_output=True,
        timeout=2,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()

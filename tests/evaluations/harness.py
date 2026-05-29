from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from devlab._logging import configure_logging
from devlab.agents import AgentInvocation, AgentProvider, MockProvider
from devlab.artifact_hygiene import ArtifactHygiene, collect_artifact_hygiene
from devlab.findings import FileFindingTracker, FindingStatus
from devlab.git import VersionControlError, run_git
from devlab.init import init_workspace
from devlab.orchestrator import RunResult, run_loop
from devlab.workflow_diagnostics import (
    AgentLogMetrics,
    ProfileMetrics,
    PromptLogMetrics,
    QualitySummary,
    TaskMetrics,
    collect_agent_log_metrics,
    collect_profile_metrics,
    collect_prompt_log_metrics,
    collect_task_metrics,
    quality_summary,
)
from devlab.workflow_history import (
    IntegratorReworkSummary,
    SessionRecord,
    TaskCycleMetrics,
    TaskReworkSummary,
    derive_integrator_rework_summary,
    derive_review_rejections,
    derive_role_sequence,
    derive_session_records,
    derive_task_cycle_metrics,
    derive_task_rework_summary,
)
from tests.evaluations.checks import BlackBoxCheck, CheckResult

__all__ = [
    "EvaluationDiagnostics",
    "EvaluationScenario",
    "ScriptedAgent",
    "init_target_workspace",
    "run_live_evaluation",
    "run_scripted_evaluation",
]


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
    expected_milestone_tags: tuple[str, ...] = ("devlab/milestone/M1",)


@dataclasses.dataclass
class GitMetrics:
    repository: bool
    clean_worktree: bool
    baseline_commit_count: int
    commit_count: int
    session_commit_count: int
    head_commit: str
    milestone_tags: list[str]
    expected_milestone_tags: list[str]
    missing_milestone_tags: list[str]
    tag_targets: dict[str, str]


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
    checks: list[CheckResult]
    artifacts: list[str]
    timestamp: str
    target_root: str
    agent_log_dir: str
    git_commit: str = ""
    git: GitMetrics = dataclasses.field(
        default_factory=lambda: GitMetrics(
            repository=False,
            clean_worktree=False,
            baseline_commit_count=0,
            commit_count=0,
            session_commit_count=0,
            head_commit="",
            milestone_tags=[],
            expected_milestone_tags=[],
            missing_milestone_tags=[],
            tag_targets={},
        )
    )
    provider: str = ""
    model: str = ""
    effort: str = ""
    tasks: TaskMetrics = dataclasses.field(
        default_factory=lambda: TaskMetrics(total=0, by_status={}, items=[])
    )
    artifact_hygiene: ArtifactHygiene = dataclasses.field(
        default_factory=lambda: ArtifactHygiene(
            file_count=0, total_bytes=0, product_file_count=0, product_total_bytes=0,
            ignored_file_count=0, ignored_total_bytes=0, devlab_file_count=0,
            devlab_total_bytes=0, flagged_paths=[],
        )
    )
    agent_logs: AgentLogMetrics = dataclasses.field(
        default_factory=lambda: AgentLogMetrics(
            stdout_count=0, stderr_count=0, config_count=0,
        )
    )
    prompt_logs: PromptLogMetrics = dataclasses.field(
        default_factory=lambda: PromptLogMetrics(
            system_count=0, session_count=0,
            max_system_prompt_bytes=0, max_session_prompt_bytes=0,
        )
    )
    quality: QualitySummary = dataclasses.field(
        default_factory=lambda: QualitySummary(
            correctness_checked=False, correctness_passed=None,
            all_tasks_closed=False, has_flagged_artifacts=False,
            session_count=0, warnings=[],
        )
    )
    sessions: list[SessionRecord] = dataclasses.field(default_factory=list)
    task_cycles: TaskCycleMetrics = dataclasses.field(
        default_factory=lambda: TaskCycleMetrics(
            tasks={}, unattributed_developer_reviewer_sessions=0,
        )
    )
    task_rework: TaskReworkSummary = dataclasses.field(
        default_factory=lambda: TaskReworkSummary(
            tasks_with_rework=[], has_task_rework=False,
            max_developer_sessions_per_task=0, max_reviewer_sessions_per_task=0,
            unattributed_developer_reviewer_sessions=0,
        )
    )
    integrator_rework: IntegratorReworkSummary = dataclasses.field(
        default_factory=lambda: IntegratorReworkSummary(
            findings_created=0, findings_resolved=0, findings_open=0,
            findings_planned=0, finding_ids=[], has_integrator_rework=False,
        )
    )
    profiles: ProfileMetrics = dataclasses.field(
        default_factory=lambda: ProfileMetrics(
            count=0, ids=[], non_default_ids=[], items=[], tasks_by_profile={},
        )
    )

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
    baseline_commit_count = _commit_count(root)
    result, duration = _run_evaluation_loop(
        root,
        max_sessions=scenario.max_sessions,
        agent_providers={"default": provider},
    )
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
        baseline_commit_count=baseline_commit_count,
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
        run_git(root, "add", ".devlab/config/agents.toml")
        run_git(root, "commit", "-m", "Configure live evaluation agents")
    configure_logging(logging.INFO)
    baseline_commit_count = _commit_count(root)
    result, duration = _run_evaluation_loop(
        root,
        max_sessions=max_sessions,
        provider=provider,
        model=model,
        effort=effort,
        retain_prompts=os.environ.get("DEVLAB_LIVE_RETAIN_PROMPTS") == "1",
    )
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
        baseline_commit_count=baseline_commit_count,
    )
    path = diagnostics.write(root)
    assert path.exists()
    return diagnostics


def _run_evaluation_loop(
    root: Path,
    *,
    max_sessions: int,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    retain_prompts: bool = False,
    agent_providers: dict[str, AgentProvider] | None = None,
) -> tuple[RunResult, float]:
    started = time.monotonic()
    result = run_loop(
        root,
        auto=True,
        max_sessions=max_sessions,
        provider=provider,
        model=model,
        effort=effort,
        retain_prompts=retain_prompts,
        agent_providers=agent_providers,
        automatic_version_control=True,
    )
    return result, time.monotonic() - started


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
    baseline_commit_count: int = 0,
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
    profile_metrics = collect_profile_metrics(root)
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
        checks=checks,
        artifacts=list_artifacts(root),
        timestamp=datetime.now(UTC).isoformat(),
        target_root=root.as_posix(),
        agent_log_dir=(root / ".devlab/logs/agents").as_posix(),
        git_commit=_git_commit(root),
        git=collect_git_metrics(
            root,
            scenario.expected_milestone_tags,
            baseline_commit_count=baseline_commit_count,
        ),
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
            task_rework=task_rework,
            integrator_rework=integrator_rework,
        ),
        sessions=sessions,
        task_cycles=task_cycles,
        task_rework=task_rework,
        integrator_rework=integrator_rework,
        profiles=profile_metrics,
    )




def collect_git_metrics(
    root: Path,
    expected_milestone_tags: tuple[str, ...],
    *,
    baseline_commit_count: int = 0,
) -> GitMetrics:
    try:
        run_git(root, "rev-parse", "--git-dir")
    except VersionControlError:
        return GitMetrics(
            repository=False,
            clean_worktree=False,
            baseline_commit_count=baseline_commit_count,
            commit_count=0,
            session_commit_count=0,
            head_commit="",
            milestone_tags=[],
            expected_milestone_tags=list(expected_milestone_tags),
            missing_milestone_tags=list(expected_milestone_tags),
            tag_targets={},
        )

    status = run_git(root, "status", "--porcelain").stdout.strip()
    commit_count = int(run_git(root, "rev-list", "--count", "HEAD").stdout.strip())
    head_commit = run_git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    milestone_tags = run_git(root, "tag", "--list", "devlab/milestone/*").stdout.splitlines()
    missing_milestone_tags = [
        tag for tag in expected_milestone_tags if tag not in set(milestone_tags)
    ]
    tag_targets = {
        tag: run_git(root, "rev-parse", f"{tag}^{{}}").stdout.strip()
        for tag in sorted(set(milestone_tags).union(expected_milestone_tags))
        if tag not in missing_milestone_tags
    }
    return GitMetrics(
        repository=True,
        clean_worktree=not status,
        baseline_commit_count=baseline_commit_count,
        commit_count=commit_count,
        session_commit_count=max(commit_count - baseline_commit_count, 0),
        head_commit=head_commit,
        milestone_tags=sorted(milestone_tags),
        expected_milestone_tags=list(expected_milestone_tags),
        missing_milestone_tags=missing_milestone_tags,
        tag_targets=tag_targets,
    )



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
    if run_git(root, "status", "--porcelain").stdout.strip():
        run_git(root, "add", ".")
        run_git(root, "commit", "-m", "Configure evaluation workspace")




def list_artifacts(root: Path) -> list[str]:
    ignored = (root / ".devlab/logs", root / ".devlab/evaluations")
    return [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not any(path.is_relative_to(prefix) for prefix in ignored)
    ]


def _export_diagnostics(path: Path, scenario_id: str, provider_mode: str) -> None:
    results_dir = os.environ.get("DEVLAB_EVAL_RESULTS_DIR")
    if not results_dir:
        return
    destination_dir = Path(results_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    shutil.copyfile(path, destination_dir / f"{timestamp}_{scenario_id}_{provider_mode}.json")


def _commit_count(root: Path) -> int:
    try:
        return int(run_git(root, "rev-list", "--count", "HEAD").stdout.strip())
    except VersionControlError:
        return 0


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", root.as_posix(), "rev-parse", "--short", "HEAD"],
        text=True,
        capture_output=True,
        timeout=2,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()

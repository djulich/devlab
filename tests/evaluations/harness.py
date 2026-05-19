from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from devlab.agents import AgentInvocation, MockProvider
from devlab.findings import FileFindingTracker, FindingStatus
from devlab.init import init_workspace
from devlab.orchestrator import RunResult, run_loop


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

    def write(self, root: Path) -> Path:
        path = root / ".devlab/evaluations" / f"{self.scenario_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataclasses.asdict(self), indent=2, sort_keys=True))
        _export_diagnostics(path, self.scenario_id, self.provider_mode)
        return path


def run_scripted_evaluation(root: Path, scenario: EvaluationScenario) -> EvaluationDiagnostics:
    if scenario.scripted_agent is None:
        raise ValueError("scripted scenario requires scripted_agent")
    init_target_workspace(root, scenario.system_spec)
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
    init_target_workspace(root, scenario.system_spec)
    if agent_config is not None:
        shutil.copyfile(agent_config, root / ".devlab/config/agents.toml")
    started = time.monotonic()
    result = run_loop(
        root,
        auto=True,
        max_sessions=max_sessions,
        provider=provider,
        model=model,
        effort=effort,
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
        roles=[],
        review_rejections=0,
        prompt_chars=[],
        provider=provider or "",
        model=model or "",
        effort=effort or "",
    )
    path = diagnostics.write(root)
    assert path.exists()
    return diagnostics


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
    )


def init_target_workspace(root: Path, system_spec: str) -> None:
    init_workspace(root)
    (root / ".devlab/specs/system/README.md").write_text(
        f"# System Specification\n\n{system_spec}\n"
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


def file_contains_check(name: str, relative_path: str, expected_text: str) -> BlackBoxCheck:
    def check(root: Path) -> CheckResult:
        path = root / relative_path
        if not path.exists():
            return CheckResult(name, False, f"missing {relative_path}")
        text = path.read_text()
        passed = expected_text in text
        return CheckResult(name, passed, "" if passed else f"{expected_text!r} not found")

    return check


def handoff(
    role_name: str,
    *,
    changed: str = "- Repository artifacts updated.",
    open_issues: str = "- None",
    addressed: str = "- None",
) -> str:
    return (
        f"# Handoff: {role_name}\n"
        "## Done\n"
        "- Scripted evaluation session completed.\n"
        "## Changed Artifacts\n"
        f"{changed}\n"
        "## Open Issues\n"
        f"{open_issues}\n"
        "## Addressed Findings\n"
        f"{addressed}\n"
        "## Next Session Hint\n"
        "Continue.\n"
    )


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

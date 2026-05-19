from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from devlab.agents import AgentInvocation, MockProvider
from devlab.findings import FileFindingTracker, FindingStatus
from devlab.init import init_workspace
from devlab.milestones import FileMilestoneTracker, MilestoneStatus
from devlab.orchestrator import RunResult, run_loop
from devlab.task_tracker import FileTaskTracker, TaskStatus


@dataclasses.dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str = ""


BlackBoxCheck = Callable[[Path], CheckResult]


@dataclasses.dataclass(frozen=True)
class EvaluationScenario:
    id: str
    title: str
    system_spec: str
    max_sessions: int
    scripted_agent: CalculatorScriptedAgent
    checks: tuple[BlackBoxCheck, ...]
    expected_roles: tuple[str, ...]
    expected_sessions: int
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

    def write(self, root: Path) -> Path:
        path = root / ".devlab/evaluations" / f"{self.scenario_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataclasses.asdict(self), indent=2, sort_keys=True))
        return path


class CalculatorScriptedAgent:
    def __init__(self, *, reject_first_review: bool = False, require_smoke_finding: bool = False):
        self.reject_first_review = reject_first_review
        self.require_smoke_finding = require_smoke_finding
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        role = invocation.role_name
        if role == "architect":
            self._architect(invocation.root)
        elif role == "planner":
            self._planner(invocation.root)
        elif role == "developer":
            self._developer(invocation.root)
        elif role == "reviewer":
            self._reviewer(invocation.root)
        elif role == "integrator":
            pass

    def handoff_for(self, invocation: AgentInvocation) -> str:
        role = invocation.role_name
        if role == "reviewer" and self._should_reject_review():
            self.review_rejections += 1
            return _handoff(role, open_issues="- Subtraction is missing from the calculator CLI.")
        if role == "integrator" and self._should_raise_smoke_finding(invocation.root):
            return _handoff(
                role,
                open_issues="- The calculator milestone lacks a committed smoke test artifact.",
            )
        if role == "planner" and _finding_exists(invocation.root, "F0001"):
            return _handoff(role, addressed="- F0001: T0002")
        return _handoff(role)

    def _architect(self, root: Path) -> None:
        _design_plan(root).write_text(
            "# Design Plan\n\n"
            "Build a small Python calculator CLI with add and subtract subcommands.\n"
        )

    def _planner(self, root: Path) -> None:
        if _finding_exists(root, "F0001"):
            _project_plan(root).write_text(
                "# Project Plan\n\n"
                "## M1: Calculator CLI\n"
                "- T0001: Implement calculator CLI\n"
                "- T0002: Add calculator smoke test\n"
            )
            _write_task(
                root,
                "T0002",
                "Add calculator smoke test",
                "M1",
                depends_on=["T0001"],
                addresses_findings=["F0001"],
            )
            return
        _project_plan(root).write_text(
            "# Project Plan\n\n"
            "## M1: Calculator CLI\n"
            "- T0001: Implement calculator CLI\n"
        )
        _write_task(root, "T0001", "Implement calculator CLI", "M1")

    def _developer(self, root: Path) -> None:
        task = FileTaskTracker(root).select_next_development_task()
        assert task is not None
        _complete_acceptance(task.path)
        if task.id == "T0001":
            complete = not self.reject_first_review or self.role_counts["developer"] > 1
            _write_calculator(root, include_subtract=complete)
        elif task.id == "T0002":
            (root / "test_calculator_smoke.py").write_text(
                "from calculator import calculate\n\n\n"
                "def test_smoke_add_and_subtract():\n"
                "    assert calculate('add', 2, 3) == 5\n"
                "    assert calculate('subtract', 7, 4) == 3\n"
            )

    def _reviewer(self, root: Path) -> None:
        if self._should_reject_review():
            return
        task = FileTaskTracker(root).select_next_review_task()
        assert task is not None
        task.path.write_text(task.path.read_text() + "\n## Review\n- [x] Approved\n")

    def _should_reject_review(self) -> bool:
        return self.reject_first_review and self.role_counts.get("reviewer", 0) == 1

    def _should_raise_smoke_finding(self, root: Path) -> bool:
        return (
            self.require_smoke_finding
            and self.role_counts.get("integrator", 0) == 1
            and not _finding_exists(root, "F0001")
        )


def test_scripted_cli_calculator_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-happy-path",
        title="CLI calculator happy path",
        system_spec="Build a Python CLI calculator with add and subtract commands.",
        max_sessions=10,
        scripted_agent=CalculatorScriptedAgent(),
        checks=(
            _command_check("add command", ["calculator.py", "add", "2", "3"], "5"),
            _command_check("subtract command", ["calculator.py", "subtract", "7", "4"], "3"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = _run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario)


def test_scripted_cli_calculator_reviewer_rework_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-reviewer-rework",
        title="CLI calculator reviewer rework",
        system_spec="Build a Python CLI calculator with add and subtract commands.",
        max_sessions=12,
        scripted_agent=CalculatorScriptedAgent(reject_first_review=True),
        checks=(
            _command_check("add command", ["calculator.py", "add", "2", "3"], "5"),
            _command_check("subtract command", ["calculator.py", "subtract", "7", "4"], "3"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "developer", "reviewer",
            "integrator", "architect",
        ),
        expected_sessions=8,
        expected_rejections=1,
    )

    diagnostics = _run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario)


def test_scripted_cli_calculator_integration_finding_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-integration-finding",
        title="CLI calculator integration finding",
        system_spec=(
            "Build a Python CLI calculator with add and subtract commands and keep a smoke "
            "test artifact in the repository."
        ),
        max_sessions=14,
        scripted_agent=CalculatorScriptedAgent(require_smoke_finding=True),
        checks=(
            _command_check("add command", ["calculator.py", "add", "2", "3"], "5"),
            _command_check("subtract command", ["calculator.py", "subtract", "7", "4"], "3"),
            _file_contains_check("smoke test artifact", "test_calculator_smoke.py", "test_smoke"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "planner",
            "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=10,
        expected_findings=1,
    )

    diagnostics = _run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario)
    finding = FileFindingTracker(tmp_path).get("F0001")
    assert finding.status == FindingStatus.RESOLVED
    task = FileTaskTracker(tmp_path).get("T0002")
    assert task.addresses_findings == ("F0001",)


def _run_scripted_evaluation(root: Path, scenario: EvaluationScenario) -> EvaluationDiagnostics:
    _init_target_workspace(root, scenario.system_spec)
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
    diagnostics = _diagnostics(root, scenario, result, checks, duration)
    path = diagnostics.write(root)
    assert path.exists()
    return diagnostics


def _diagnostics(
    root: Path,
    scenario: EvaluationScenario,
    result: RunResult,
    checks: list[CheckResult],
    duration: float,
) -> EvaluationDiagnostics:
    findings = FileFindingTracker(root).list_findings()
    artifacts = [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.is_relative_to(root / ".devlab/logs")
        and not path.is_relative_to(root / ".devlab/evaluations")
    ]
    return EvaluationDiagnostics(
        scenario_id=scenario.id,
        provider_mode="scripted",
        sessions_run=result.sessions_run,
        completed=result.completed,
        exit_code=result.exit_code,
        roles=list(scenario.scripted_agent.roles),
        findings_created=len(findings),
        findings_resolved=sum(
            1 for finding in findings if finding.status == FindingStatus.RESOLVED
        ),
        review_rejections=scenario.scripted_agent.review_rejections,
        duration_seconds=duration,
        max_prompt_chars=max(scenario.scripted_agent.prompt_chars, default=0),
        checks=[dataclasses.asdict(check) for check in checks],
        artifacts=artifacts,
    )


def _assert_diagnostics(
    root: Path, diagnostics: EvaluationDiagnostics, scenario: EvaluationScenario
) -> None:
    diagnostics_path = root / ".devlab/evaluations" / f"{scenario.id}.json"
    assert diagnostics.completed is True, diagnostics_path.read_text()
    assert diagnostics.exit_code == 0, diagnostics_path.read_text()
    assert diagnostics.sessions_run == scenario.expected_sessions
    assert tuple(diagnostics.roles) == scenario.expected_roles
    assert diagnostics.review_rejections == scenario.expected_rejections
    assert diagnostics.findings_created == scenario.expected_findings
    assert all(check["passed"] for check in diagnostics.checks), diagnostics.checks
    assert diagnostics.max_prompt_chars > 0
    assert "calculator.py" in diagnostics.artifacts
    task = FileTaskTracker(root).get("T0001")
    assert task.status == TaskStatus.CLOSED
    milestone = FileMilestoneTracker(root).get("M1")
    assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED


def _init_target_workspace(root: Path, system_spec: str) -> None:
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


def _write_task(
    root: Path,
    task_id: str,
    title: str,
    milestone: str,
    *,
    depends_on: list[str] | None = None,
    addresses_findings: list[str] | None = None,
) -> None:
    depends_on = depends_on or []
    addresses_findings = addresses_findings or []
    depends = ", ".join(f'"{dependency}"' for dependency in depends_on)
    findings = ", ".join(f'"{finding_id}"' for finding_id in addresses_findings)
    slug = title.lower().replace(" ", "-")
    path = root / ".devlab/tasks" / f"{task_id}_{slug}.md"
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{title}"\n'
        'status = "open"\n'
        f'milestone = "{milestone}"\n'
        'profile = "default"\n'
        f'depends_on = [{depends}]\n'
        f'addresses_findings = [{findings}]\n'
        'validation = []\n'
        "+++\n\n"
        f"# {task_id}: {title}\n\n"
        "## Goal\n"
        f"Complete {title}.\n\n"
        "## Acceptance Criteria\n"
        "- [ ] Calculator behavior is implemented.\n"
    )


def _complete_acceptance(task_path: Path) -> None:
    task_path.write_text(task_path.read_text().replace("- [ ]", "- [x]"))


def _write_calculator(root: Path, *, include_subtract: bool) -> None:
    subtract_block = (
        "    if operation == 'subtract':\n"
        "        return left - right\n"
        if include_subtract
        else ""
    )
    root.joinpath("calculator.py").write_text(
        "from __future__ import annotations\n\n"
        "import argparse\n\n\n"
        "def calculate(operation: str, left: int, right: int) -> int:\n"
        "    if operation == 'add':\n"
        "        return left + right\n"
        f"{subtract_block}"
        "    raise ValueError(f'unsupported operation: {operation}')\n\n\n"
        "def main() -> None:\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('operation', choices=['add', 'subtract'])\n"
        "    parser.add_argument('left', type=int)\n"
        "    parser.add_argument('right', type=int)\n"
        "    args = parser.parse_args()\n"
        "    print(calculate(args.operation, args.left, args.right))\n\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )


def _command_check(name: str, args: list[str], expected_stdout: str) -> BlackBoxCheck:
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


def _file_contains_check(name: str, relative_path: str, expected_text: str) -> BlackBoxCheck:
    def check(root: Path) -> CheckResult:
        path = root / relative_path
        if not path.exists():
            return CheckResult(name, False, f"missing {relative_path}")
        text = path.read_text()
        return CheckResult(name, expected_text in text, f"{expected_text!r} not found")

    return check


def _design_plan(root: Path) -> Path:
    return root / ".devlab/plans/design-plan.md"


def _project_plan(root: Path) -> Path:
    return root / ".devlab/plans/project-plan.md"


def _finding_exists(root: Path, finding_id: str) -> bool:
    return any(finding.id == finding_id for finding in FileFindingTracker(root).list_findings())


def _handoff(
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

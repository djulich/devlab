from __future__ import annotations

from pathlib import Path

from devlab.findings import FileFindingTracker, FindingStatus
from devlab.milestones import FileMilestoneTracker, MilestoneStatus
from devlab.task_tracker import FileTaskTracker, TaskStatus
from tests.evaluations.harness import (
    EvaluationDiagnostics,
    EvaluationScenario,
    command_check,
    command_fails_check,
    file_contains_check,
    run_scripted_evaluation,
)
from tests.evaluations.scripted_agents import (
    CalculatorScriptedAgent,
    HttpApiScriptedAgent,
    stdlib_http_api_check,
)


def test_scripted_cli_calculator_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-happy-path",
        title="CLI calculator happy path",
        system_spec="Build a Python CLI calculator with add and subtract commands.",
        max_sessions=10,
        scripted_agent=CalculatorScriptedAgent(),
        checks=_calculator_checks(),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="calculator.py")


def test_scripted_cli_calculator_reviewer_rework_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-reviewer-rework",
        title="CLI calculator reviewer rework",
        system_spec="Build a Python CLI calculator with add and subtract commands.",
        max_sessions=12,
        scripted_agent=CalculatorScriptedAgent(reject_first_review=True),
        checks=_calculator_checks(),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "developer", "reviewer",
            "integrator", "architect",
        ),
        expected_sessions=8,
        expected_rejections=1,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="calculator.py")


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
            *_calculator_checks(),
            file_contains_check("smoke test artifact", "test_calculator_smoke.py", "test_smoke"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "planner",
            "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=10,
        expected_findings=1,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="calculator.py")
    finding = FileFindingTracker(tmp_path).get("F0001")
    assert finding.status == FindingStatus.RESOLVED
    task = FileTaskTracker(tmp_path).get("T0002")
    assert task.addresses_findings == ("F0001",)


def test_scripted_tiny_http_api_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="tiny-http-api-happy-path",
        title="Tiny HTTP API happy path",
        system_spec=(
            "Build a tiny Python standard-library HTTP API with /health returning ok and "
            "/echo?value=TEXT returning TEXT."
        ),
        max_sessions=10,
        scripted_agent=HttpApiScriptedAgent(),
        checks=(stdlib_http_api_check,),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="app.py")


def _calculator_checks():
    return (
        command_check("add command", ["calculator.py", "add", "2", "3"], "5"),
        command_check("subtract command", ["calculator.py", "subtract", "7", "4"], "3"),
        command_check("add negative command", ["calculator.py", "add", "-2", "5"], "3"),
        command_check("subtract negative result", ["calculator.py", "subtract", "2", "5"], "-3"),
        command_fails_check("missing args exits nonzero", ["calculator.py"]),
    )


def _assert_diagnostics(
    root: Path,
    diagnostics: EvaluationDiagnostics,
    scenario: EvaluationScenario,
    *,
    expected_artifact: str,
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
    assert expected_artifact in diagnostics.artifacts
    assert diagnostics.agent_log_dir.endswith(".devlab/logs/agents")
    assert isinstance(diagnostics.tasks["total"], int)
    assert diagnostics.tasks["total"] >= 1
    assert diagnostics.quality["correctness_passed"] is True
    assert diagnostics.quality["all_tasks_closed"] is True
    assert "file_count" in diagnostics.artifact_hygiene
    assert "stdout_count" in diagnostics.agent_logs
    task = FileTaskTracker(root).get("T0001")
    assert task.status == TaskStatus.CLOSED
    milestone = FileMilestoneTracker(root).get("M1")
    assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED

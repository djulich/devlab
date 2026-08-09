from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from devlab.agents import MockProvider
from devlab.artifact_hygiene import ArtifactHygiene, collect_artifact_hygiene
from devlab.clarifications import FileClarificationTracker
from devlab.findings import FileFindingTracker, FindingStatus
from devlab.generations import (
    active_generation,
    archived_generation_numbers,
    load_generation_manifest,
)
from devlab.git import run_git
from devlab.milestones import FileMilestoneTracker, MilestoneStatus
from devlab.orchestrator import run_loop
from devlab.task_tracker import FileTaskTracker, TaskStatus
from devlab.workflow_diagnostics import (
    TaskMetrics,
    collect_profile_metrics,
    format_workflow_diagnostics,
    quality_summary,
)
from devlab.workflow_history import (
    IntegratorReworkSummary,
    TaskCycleEntry,
    TaskReworkSummary,
    derive_integrator_rework_summary,
    derive_review_rejections,
    derive_role_sequence,
    derive_session_records,
    derive_task_cycle_metrics,
    derive_task_rework_summary,
)
from tests.evaluations.checks import (
    BlackBoxCheck,
    CheckResult,
    command_check,
    command_fails_check,
    compose_deployment_artifacts_check,
    deployment_artifacts_check,
    file_contains_check,
    optional_docker_compose_config_check,
    optional_make_target_check,
    react_vite_browser_integration_check,
    react_vite_container_build_check,
    react_vite_frontend_check,
    stateful_todo_api_check,
    static_frontend_check,
    stdlib_http_api_check,
    toolchain_command_check,
)
from tests.evaluations.generated_products import write_stateful_todo_api
from tests.evaluations.harness import (
    EvaluationDiagnostics,
    EvaluationError,
    EvaluationScenario,
    copy_live_agent_config,
    init_target_workspace,
    run_scripted_evaluation,
)
from tests.evaluations.scripted_agents import (
    AdoptExistingScriptedAgent,
    CalculatorScriptedAgent,
    ClarificationCalculatorScriptedAgent,
    CompiledLanguageScriptedAgent,
    ComposeDeploymentScriptedAgent,
    DeploymentWebApiScriptedAgent,
    HttpApiScriptedAgent,
    MixedLanguageScriptedAgent,
    SpecReconciliationScriptedAgent,
    StatefulWebApiScriptedAgent,
    StaticFrontendScriptedAgent,
)


def _compiled_language_scenario(
    language: str,
    artifact: str,
    extra_checks: tuple[BlackBoxCheck, ...] = (),
) -> EvaluationScenario:
    return EvaluationScenario(
        id=f"{language}-cli-happy-path",
        title=f"{language} CLI happy path",
        system_spec=f"Build a minimal {language} CLI with project-owned validation.",
        max_sessions=8,
        scripted_agent=CompiledLanguageScriptedAgent(language),
        checks=(file_contains_check("toolchain artifact", artifact, ""), *extra_checks),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )


def _require_tools(tools: tuple[str, ...]) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"requires tools on PATH: {', '.join(missing)}")


@pytest.mark.parametrize(
    ("language", "artifact"),
    [
        ("rust", "Cargo.toml"),
        ("go", "go.mod"),
        ("c", "CMakeLists.txt"),
        ("cpp", "CMakeLists.txt"),
    ],
)
def test_scripted_compiled_language_workflow_evaluation(
    tmp_path: Path, language: str, artifact: str
) -> None:
    scenario = _compiled_language_scenario(language, artifact)

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact=artifact)
    assert diagnostics.profiles.items[0].default_validation_count >= 2
    if language == "rust":
        assert "version = 3" in (tmp_path / "Cargo.lock").read_text()


@pytest.mark.parametrize(
    ("language", "artifact", "required_tools", "checks"),
    [
        (
            "rust",
            "Cargo.toml",
            ("cargo", "rustfmt", "rustc"),
            (
                toolchain_command_check("cargo format", ["cargo", "fmt", "--check"]),
                toolchain_command_check("cargo test", ["cargo", "test"]),
                toolchain_command_check(
                    "rust CLI output", ["cargo", "run", "--quiet"],
                    expected_stdout="hello from rust",
                ),
            ),
        ),
        (
            "go",
            "go.mod",
            ("gofmt", "go"),
            (
                toolchain_command_check(
                    "Go format", ["gofmt", "-l", "."], expected_stdout=""
                ),
                toolchain_command_check("go test", ["go", "test", "./..."]),
                toolchain_command_check(
                    "go CLI output", ["go", "run", "."], expected_stdout="hello from go"
                ),
            ),
        ),
        (
            "c",
            "CMakeLists.txt",
            ("cmake", "ctest", "make", "cc"),
            (
                toolchain_command_check("C configure", ["cmake", "--preset", "dev"]),
                toolchain_command_check(
                    "C build", ["cmake", "--build", "--preset", "dev"]
                ),
                toolchain_command_check("C test", ["ctest", "--preset", "dev"]),
            ),
        ),
        (
            "cpp",
            "CMakeLists.txt",
            ("cmake", "ctest", "make", "c++"),
            (
                toolchain_command_check("C++ configure", ["cmake", "--preset", "dev"]),
                toolchain_command_check(
                    "C++ build", ["cmake", "--build", "--preset", "dev"]
                ),
                toolchain_command_check("C++ test", ["ctest", "--preset", "dev"]),
            ),
        ),
    ],
)
def test_compiled_language_toolchain_verification(
    tmp_path: Path,
    language: str,
    artifact: str,
    required_tools: tuple[str, ...],
    checks: tuple[BlackBoxCheck, ...],
) -> None:
    _require_tools(required_tools)
    scenario = _compiled_language_scenario(language, artifact, checks)

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact=artifact)


def test_scripted_mixed_language_workflow_evaluation(tmp_path: Path) -> None:
    scenario = _mixed_language_scenario()

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="Makefile")
    assert diagnostics.profiles.tasks_by_profile == {
        "go": ["T0002"],
        "integration": ["T0003"],
        "rust": ["T0001"],
    }


def test_mixed_language_toolchain_verification(tmp_path: Path) -> None:
    _require_tools(("make", "cargo", "rustc", "go"))
    scenario = _mixed_language_scenario(
        (
            toolchain_command_check("cross-component validation", ["make", "check"]),
        )
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="Makefile")


def _mixed_language_scenario(
    extra_checks: tuple[BlackBoxCheck, ...] = (),
) -> EvaluationScenario:
    scenario = EvaluationScenario(
        id="mixed-rust-go-happy-path",
        title="Mixed Rust and Go workspace",
        system_spec=(
            "Build independently testable Rust and Go components with one root "
            "integration command."
        ),
        max_sessions=12,
        scripted_agent=MixedLanguageScriptedAgent(),
        checks=(
            file_contains_check("Rust component", "rust-component/Cargo.toml", "[package]"),
            file_contains_check("Go component", "go-component/go.mod", "module "),
            *extra_checks,
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "developer", "reviewer",
            "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=10,
    )

    return scenario


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


def test_scripted_cli_calculator_unattended_clarification_evaluation(
    tmp_path: Path,
) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-unattended-clarification",
        title="CLI calculator unattended clarification",
        system_spec="Build a Python CLI calculator with add and subtract commands.",
        max_sessions=10,
        scripted_agent=ClarificationCalculatorScriptedAgent(),
        checks=_calculator_checks(),
        expected_roles=(
            "architect",
            "planner",
            "developer",
            "clarification-resolver",
            "developer",
            "reviewer",
            "integrator",
            "architect",
        ),
        expected_sessions=8,
        clarification_mode="agent",
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="calculator.py")
    clarification = FileClarificationTracker(tmp_path).get("CL0001")
    assert clarification.status.value == "answered"
    assert clarification.metadata["answered_by"].startswith(
        "agent:clarification-resolver:"
    )


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
    assert diagnostics.integrator_rework == IntegratorReworkSummary(
        findings_created=1,
        findings_resolved=1,
        findings_open=0,
        findings_planned=0,
        finding_ids=["F0001"],
        has_integrator_rework=True,
    )
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


def test_scripted_stateful_web_api_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="stateful-web-api-happy-path",
        title="Stateful web API happy path",
        system_spec=(
            "Build a small Python JSON HTTP API for todo items. It must expose /health, "
            "create todos, list todos, delete todos by id, keep data in memory, and "
            "provide project-owned run/test commands."
        ),
        max_sessions=10,
        scripted_agent=StatefulWebApiScriptedAgent(),
        checks=(
            stateful_todo_api_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
            file_contains_check("usage docs", "README.md", "GET /todos"),
            file_contains_check("python cache gitignore", ".gitignore", "__pycache__/"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(
        tmp_path,
        diagnostics,
        scenario,
        expected_artifact="src/todo_api/server.py",
    )


def test_scripted_static_frontend_todo_app_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="static-frontend-todo-app-happy-path",
        title="Static frontend todo app happy path",
        system_spec=(
            "Build a small Python standard-library JSON HTTP API for todo items plus a "
            "static vanilla HTML/CSS/JS frontend. Do not use React, Vite, npm, or a "
            "frontend build step. Implement the API in src/todo_api/server.py, runnable "
            "from the repository root with python -m src.todo_api.server --port <port>. "
            "The API must expose GET /health, POST /todos, GET /todos, and "
            "DELETE /todos/{id} with the exact stateful todo API response contract. "
            "Place frontend files at static/index.html, static/app.js, and "
            "static/styles.css. The UI must list todos, add todos, delete todos, display "
            "validation errors, and call the API routes directly. Provide project-owned "
            "run/test commands and README usage instructions."
        ),
        max_sessions=12,
        scripted_agent=StaticFrontendScriptedAgent(),
        checks=(
            stateful_todo_api_check,
            static_frontend_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(
        tmp_path,
        diagnostics,
        scenario,
        expected_artifact="static/index.html",
    )


def test_scripted_deployable_web_api_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="deployable-web-api-happy-path",
        title="Deployable web API happy path",
        system_spec=(
            "Build a small Python JSON HTTP API for todo items and include "
            "project-owned local container deployment artifacts."
        ),
        deployment_spec=(
            "Deployment target: local OCI-compatible container image for the todo API. "
            "Provide a Containerfile, Makefile targets to build and verify deployment "
            "artifacts, and README deployment instructions. Do not deploy to production."
        ),
        max_sessions=12,
        scripted_agent=DeploymentWebApiScriptedAgent(),
        checks=(
            stateful_todo_api_check,
            deployment_artifacts_check,
            optional_make_target_check("deployment artifact command", "deployment-check"),
            file_contains_check(
                "deployment task domain",
                ".devlab/tasks/T0002_add-container-deployment-artifacts.md",
                "domain = \"deployment\"",
            ),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "developer", "reviewer",
            "integrator", "architect",
        ),
        expected_sessions=8,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(
        tmp_path,
        diagnostics,
        scenario,
        expected_artifact="Containerfile",
    )


def test_optional_make_target_check_is_skipped_unless_enabled(tmp_path: Path) -> None:
    check = optional_make_target_check("deployment artifact command", "deployment-check")

    result = check(tmp_path)

    assert result.passed is True
    assert "skipped" in result.message
    assert "DEVLAB_EVAL_DEPLOYMENT_TOOLS=1" in result.message


def test_optional_make_target_check_reports_missing_make_as_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_EVAL_DEPLOYMENT_TOOLS", "1")
    monkeypatch.setattr("tests.evaluations.checks.shutil.which", lambda _name: None)
    check = optional_make_target_check("deployment artifact command", "deployment-check")

    result = check(tmp_path)

    assert result.passed is True
    assert "unverified" in result.message
    assert "make" in result.message


def test_optional_make_target_check_runs_enabled_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_EVAL_DEPLOYMENT_TOOLS", "1")
    (tmp_path / "Makefile").write_text(
        ".PHONY: deployment-check\n"
        "deployment-check:\n"
        "\ttest -f Containerfile\n"
    )
    (tmp_path / "Containerfile").write_text("FROM scratch\n")
    check = optional_make_target_check("deployment artifact command", "deployment-check")

    result = check(tmp_path)

    assert result.passed is True
    assert result.message == ""


def test_optional_make_target_check_fails_enabled_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_EVAL_DEPLOYMENT_TOOLS", "1")
    (tmp_path / "Makefile").write_text(
        ".PHONY: deployment-check\n"
        "deployment-check:\n"
        "\ttest -f Missingfile\n"
    )
    check = optional_make_target_check("deployment artifact command", "deployment-check")

    result = check(tmp_path)

    assert result.passed is False
    assert "make deployment-check exited" in result.message


def test_scripted_compose_deployment_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="compose-deployment-happy-path",
        title="Compose deployment happy path",
        system_spec=(
            "Build a small Python JSON HTTP API for todo items and include "
            "project-owned Docker Compose deployment artifacts."
        ),
        deployment_spec=(
            "Deployment target: local Docker Compose deployment for the todo API. "
            "Provide compose.yaml, .env.example, Makefile targets named exactly "
            "compose-check, deploy-local, and undeploy-local, a scripts/smoke-test.sh "
            "smoke test, and README deployment instructions. Do not deploy to production."
        ),
        max_sessions=12,
        scripted_agent=ComposeDeploymentScriptedAgent(),
        checks=(
            stateful_todo_api_check,
            compose_deployment_artifacts_check,
            optional_make_target_check("compose artifact command", "compose-check"),
            optional_docker_compose_config_check(),
            file_contains_check(
                "deployment task domain",
                ".devlab/tasks/T0002_add-compose-deployment-artifacts.md",
                "domain = \"deployment\"",
            ),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "developer", "reviewer",
            "integrator", "architect",
        ),
        expected_sessions=8,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(
        tmp_path,
        diagnostics,
        scenario,
        expected_artifact="compose.yaml",
    )


def test_scripted_spec_reconciliation_archives_and_replans(tmp_path: Path) -> None:
    init_target_workspace(
        tmp_path,
        "Build a Python CLI calculator in calculator.py with an add command.",
    )
    agent = SpecReconciliationScriptedAgent()
    provider = MockProvider(on_invoke=agent.on_invoke, handoff_text=agent.handoff_for)

    initial = run_loop(
        tmp_path,
        max_sessions=8,
        agent_providers={"default": provider},
        automatic_version_control=True,
    )

    assert initial.completed is True
    assert initial.exit_code == 0
    assert agent.roles == [
        "architect",
        "planner",
        "developer",
        "reviewer",
        "integrator",
        "architect",
    ]
    assert active_generation(tmp_path) == 1
    assert FileTaskTracker(tmp_path).get("T0001").title == "Implement calculator CLI"
    assert FileMilestoneTracker(tmp_path).get("M1").status == (
        MilestoneStatus.ARCHITECTURE_REVIEWED
    )

    spec_path = tmp_path / ".devlab/specs/system/README.md"
    spec_path.write_text(
        "# System Specification\n\n"
        "Build a Python CLI greeter in greeter.py. It prints 'hello <name>'.\n"
    )
    run_git(tmp_path, "add", ".devlab/specs/system/README.md")
    run_git(tmp_path, "commit", "-m", "Change system spec to greeter")

    blocked = run_loop(
        tmp_path,
        max_sessions=1,
        agent_providers={"default": provider},
        automatic_version_control=True,
    )

    assert blocked.completed is False
    assert blocked.exit_code == 1
    assert blocked.errors[0].phase == "spec_reconciliation"

    planned = run_loop(
        tmp_path,
        max_sessions=2,
        agent_providers={"default": provider},
        automatic_version_control=True,
        planning_only=True,
    )

    assert planned.completed is True
    assert planned.exit_code == 0
    assert active_generation(tmp_path) == 2
    assert archived_generation_numbers(tmp_path) == (1,)
    manifest = load_generation_manifest(tmp_path / ".devlab/generations/0001/generation.toml")
    assert manifest.reason == "spec_reconciliation"
    assert (tmp_path / ".devlab/generations/0001/tasks/T0001_implement-calculator-cli.md").exists()
    assert (tmp_path / ".devlab/generations/0001/milestones/M1.toml").exists()
    assert not (tmp_path / ".devlab/tasks/T0001_implement-calculator-cli.md").exists()
    assert FileTaskTracker(tmp_path).get("T0001").title == "Implement greeter CLI"
    assert FileMilestoneTracker(tmp_path).get("M1").task_ids == ("T0001",)

    final = run_loop(
        tmp_path,
        max_sessions=8,
        agent_providers={"default": provider},
        automatic_version_control=True,
    )

    assert final.completed is True
    assert final.exit_code == 0
    assert agent.roles == [
        "architect",
        "planner",
        "developer",
        "reviewer",
        "integrator",
        "architect",
        "architect",
        "planner",
        "developer",
        "reviewer",
        "integrator",
        "architect",
    ]
    assert FileTaskTracker(tmp_path).get("T0001").status == TaskStatus.CLOSED
    assert FileTaskTracker(tmp_path).get("T0001").title == "Implement greeter CLI"
    assert FileMilestoneTracker(tmp_path).get("M1").status == (
        MilestoneStatus.ARCHITECTURE_REVIEWED
    )
    assert (tmp_path / "calculator.py").exists()
    assert (tmp_path / "greeter.py").exists()
    assert run_git(tmp_path, "status", "--porcelain").stdout.strip() == ""
    assert run_git(tmp_path, "tag", "--list", "devlab/milestone/M1").stdout.strip() == (
        "devlab/milestone/M1"
    )


def test_scripted_adopt_existing_creates_current_state_design_baseline(
    tmp_path: Path,
) -> None:
    (tmp_path / "calculator.py").write_text(
        "import sys\n\n"
        "def calculate(command: str, left: int, right: int) -> int:\n"
        "    if command == 'add':\n"
        "        return left + right\n"
        "    raise ValueError(command)\n\n"
        "if __name__ == '__main__':\n"
        "    print(calculate(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])))\n"
    )
    (tmp_path / "test_calculator.py").write_text(
        "from calculator import calculate\n\n\n"
        "def test_add():\n"
        "    assert calculate('add', 2, 3) == 5\n"
    )
    init_target_workspace(
        tmp_path,
        "Add a subtract command to the existing Python calculator CLI.",
    )
    (tmp_path / ".devlab/plans/design-plan.md").unlink()
    (tmp_path / ".devlab/plans/project-plan.md").unlink()
    run_git(tmp_path, "add", ".devlab/plans")
    run_git(tmp_path, "commit", "-m", "Remove starter planning artifacts")
    agent = AdoptExistingScriptedAgent()
    provider = MockProvider(
        on_invoke=agent.on_invoke,
        handoff_text=agent.handoff_for,
    )

    result = run_loop(
        tmp_path,
        max_sessions=2,
        planning_only=True,
        adopt_existing=True,
        automatic_version_control=True,
        agent_providers={"default": provider},
    )

    assert result.completed is True
    assert result.exit_code == 0
    assert agent.roles == ["architect", "planner"]
    design = (tmp_path / ".devlab/plans/design-plan.md").read_text()
    assert "## Current-State Design Baseline" in design
    assert "calculator.py" in design
    assert "test_calculator.py" in design
    assert "does not support subtraction" in design
    project = (tmp_path / ".devlab/plans/project-plan.md").read_text()
    assert "Add subtract command to existing calculator CLI" in project
    task = FileTaskTracker(tmp_path).get("T0001")
    assert task.title == "Add subtract command to existing calculator CLI"
    assert _git(tmp_path, "status", "--porcelain").stdout.strip() == ""


def test_stateful_todo_api_check_accepts_any_successful_create_status(
    tmp_path: Path,
) -> None:
    write_stateful_todo_api(tmp_path)
    server = tmp_path / "src/todo_api/server.py"
    server.write_text(server.read_text().replace("self._json(201,", "self._json(200,"))

    result = stateful_todo_api_check(tmp_path)

    assert result.passed is True


def test_compose_deployment_check_accepts_docs_deployment_markdown(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(
        "services:\n  todo-api:\n    build: .\n    ports:\n      - '8000:8000'\n"
    )
    (tmp_path / ".env.example").write_text("IMAGE=todo-api:local\nPORT=8000\n")
    (tmp_path / "Makefile").write_text(
        "compose-check:\n\ttest -f compose.yaml\n"
        "deploy-local:\n\tdocker compose up -d\n"
        "undeploy-local:\n\tdocker compose down\n"
    )
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "smoke-test.sh").write_text("curl /health\n")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "deployment.md").write_text(
        "# Compose deployment\n\n"
        "Run `make compose-check`, `make deploy-local`, and `make undeploy-local` "
        "for teardown.\n"
    )

    result = compose_deployment_artifacts_check(tmp_path)

    assert result.passed is True


def test_optional_docker_compose_config_check_is_skipped_unless_enabled(tmp_path: Path) -> None:
    check = optional_docker_compose_config_check()

    result = check(tmp_path)

    assert result.passed is True
    assert "skipped" in result.message
    assert "DEVLAB_EVAL_DEPLOYMENT_TOOLS=1" in result.message


def test_optional_docker_compose_config_reports_missing_docker_as_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_EVAL_DEPLOYMENT_TOOLS", "1")
    monkeypatch.setattr("tests.evaluations.checks.shutil.which", lambda _name: None)
    check = optional_docker_compose_config_check()

    result = check(tmp_path)

    assert result.passed is True
    assert "unverified" in result.message
    assert "docker" in result.message


def test_static_frontend_check_accepts_served_static_frontend_docs(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        '<link rel="stylesheet" href="styles.css">\n'
        '<form><input name="title"></form><ul></ul>\n'
        '<p id="error"></p><script src="app.js"></script>\n'
    )
    (static_dir / "app.js").write_text(
        "async function load(){ await fetch('/todos'); }\n"
        "async function add(){ await fetch('/todos', {method: 'POST'}); }\n"
        "async function remove(id){ await fetch(`/todos/${id}`, {method: 'DELETE'}); }\n"
        "function showError(error){ console.log(error); }\n"
    )
    (static_dir / "styles.css").write_text("body { font-family: sans-serif; }\n")
    (tmp_path / "README.md").write_text(
        "# Todo API and Static Frontend\n\n"
        "Open the static frontend at http://127.0.0.1:8000/. The same server "
        "serves /index.html, /app.js, and /styles.css.\n"
    )

    result = static_frontend_check(tmp_path)

    assert result.passed is True


def test_static_frontend_check_rejects_frontend_build_artifacts(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        '<link rel="stylesheet" href="styles.css">\n'
        '<form><input name="title"></form><ul></ul>\n'
        '<p id="error"></p><script src="app.js"></script>\n'
    )
    (static_dir / "app.js").write_text(
        "fetch('/todos', {method: 'POST'});\n"
        "fetch('/todos/1', {method: 'DELETE'});\n"
    )
    (static_dir / "styles.css").write_text("body {}\n")
    (tmp_path / "README.md").write_text("Static frontend instructions.\n")
    (tmp_path / "package.json").write_text("{}\n")

    result = static_frontend_check(tmp_path)

    assert result.passed is False
    assert "package.json" in result.message


def test_react_vite_frontend_check_accepts_react_vite_contract(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (tmp_path / "package.json").write_text(
        "{\n"
        '  "scripts": {"dev": "vite", "build": "vite build"},\n'
        '  "dependencies": {"@vitejs/plugin-react": "^latest", "vite": "^latest", '
        '"react": "^latest", "react-dom": "^latest"}\n'
        "}\n"
    )
    (tmp_path / "index.html").write_text(
        '<div id="root"></div><script type="module" src="/src/main.jsx"></script>\n'
    )
    (src_dir / "main.jsx").write_text(
        "import { createRoot } from 'react-dom/client';\n"
        "import App from './App.jsx';\n"
        "createRoot(document.getElementById('root')).render(<App />);\n"
    )
    (src_dir / "App.jsx").write_text(
        "export default function App(){\n"
        "  return <form onSubmit={async () => fetch('/todos', {method: 'POST'})}>\n"
        "    <input aria-label=\"todo\" />\n"
        "    <button onClick={() => fetch('/todos/1', {method: 'DELETE'})}>Delete</button>\n"
        "    <p role=\"alert\">error</p>\n"
        "  </form>;\n"
        "}\n"
        "fetch('/todos');\n"
    )
    (src_dir / "App.css").write_text(".app { display: grid; }\n")
    (tmp_path / "README.md").write_text("Run `npm run dev`; verify with `npm run build`.\n")

    result = react_vite_frontend_check(tmp_path)

    assert result.passed is True


def test_react_vite_frontend_check_requires_vite_build_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"dev": "vite"}, "dependencies": {"react": "latest"}}\n'
    )
    (tmp_path / "index.html").write_text('<div id="root"></div>\n')

    result = react_vite_frontend_check(tmp_path)

    assert result.passed is False
    assert "scripts.build" in result.message


def test_react_vite_container_build_check_runs_podman_copy_in_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"build": "vite build"}}\n')
    captured_args: list[str] = []
    captured_kwargs: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_args[:] = args
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "built\n", "")

    monkeypatch.setattr("tests.evaluations.checks.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tests.evaluations.checks.subprocess.run", fake_run)

    result = react_vite_container_build_check(tmp_path)

    assert result.passed is True
    assert captured_args[:4] == ["podman", "run", "--rm", "--pull=missing"]
    assert f"{tmp_path.resolve()}:/workspace:ro" in captured_args
    script = captured_args[-1]
    assert isinstance(script, str)
    assert "cp -R /workspace/. /tmp/work" in script
    assert "if [ -f package-lock.json ]; then npm ci; else npm install; fi" in script
    assert "npm run build" in script
    assert captured_kwargs["capture_output"] is True
    assert captured_kwargs["check"] is False


def test_react_vite_container_build_check_reports_container_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"build": "vite build"}}\n')

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "stdout", "vite failed")

    monkeypatch.setattr("tests.evaluations.checks.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tests.evaluations.checks.subprocess.run", fake_run)

    result = react_vite_container_build_check(tmp_path)

    assert result.passed is False
    assert "container-local /tmp/work" in result.message
    assert "vite failed" in result.message


def test_react_vite_browser_integration_check_requires_podman(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tests.evaluations.checks.shutil.which", lambda _name: None)

    result = react_vite_browser_integration_check(tmp_path)

    assert result.passed is False
    assert "podman" in result.message
    assert "PATH" in result.message


def test_react_vite_browser_integration_check_runs_read_only_container_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"build": "vite build"}}\n')
    captured_args: list[str] = []
    captured_kwargs: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_args[:] = args
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr("tests.evaluations.checks.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tests.evaluations.checks.subprocess.run", fake_run)

    result = react_vite_browser_integration_check(tmp_path)

    assert result.passed is True
    assert captured_args[:4] == ["podman", "run", "--rm", "--pull=missing"]
    assert f"{tmp_path.resolve()}:/workspace:ro" in captured_args
    assert "mcr.microsoft.com/playwright:v1.53.1-jammy" in captured_args
    script = captured_args[-1]
    assert isinstance(script, str)
    assert "cp -R /workspace/. /tmp/work" in script
    assert "if [ -f package-lock.json ]; then npm ci; else npm install; fi" in script
    assert "npm run build" in script
    assert "src.todo_api.server --port" in script
    assert "npm run dev -- --host 127.0.0.1 --port" in script
    assert "require('playwright')" in script
    assert "write browser eval" in script
    assert captured_kwargs == {
        "text": True,
        "capture_output": True,
        "timeout": 360,
        "check": False,
    }


def test_react_vite_browser_integration_check_reports_container_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"build": "vite build"}}\n')

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 9, "browser flow failed", "console error")

    monkeypatch.setattr("tests.evaluations.checks.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tests.evaluations.checks.subprocess.run", fake_run)

    result = react_vite_browser_integration_check(tmp_path)

    assert result.passed is False
    assert "podman browser integration exited 9" in result.message
    assert "/workspace" in result.message
    assert "/tmp/work" in result.message
    assert "API startup, Vite startup, and browser flow" in result.message
    assert "browser flow failed" in result.message
    assert "console error" in result.message


def test_integrator_rework_summary_counts_integrator_findings(tmp_path: Path) -> None:
    tracker = FileFindingTracker(tmp_path)
    integrator_open = tracker.create(
        title="Integrator open",
        source="integrator",
        milestone="M1",
        body="# Finding\n",
    )
    integrator_resolved = tracker.create(
        title="Integrator resolved",
        source="integrator",
        milestone="M1",
        body="# Finding\n",
    )
    tracker.mark_resolved(integrator_resolved.id)
    tracker.create(
        title="Architect finding",
        source="architect",
        milestone="M1",
        body="# Finding\n",
    )

    summary = derive_integrator_rework_summary(tracker.list_findings())

    assert summary == IntegratorReworkSummary(
        findings_created=2,
        findings_resolved=1,
        findings_open=1,
        findings_planned=0,
        finding_ids=[integrator_open.id, integrator_resolved.id],
        has_integrator_rework=True,
    )


def test_integrator_rework_summary_reports_clean_integration(tmp_path: Path) -> None:
    tracker = FileFindingTracker(tmp_path)
    tracker.create(
        title="Architect finding",
        source="architect",
        milestone="M1",
        body="# Finding\n",
    )

    summary = derive_integrator_rework_summary(tracker.list_findings())

    assert summary == IntegratorReworkSummary(
        findings_created=0,
        findings_resolved=0,
        findings_open=0,
        findings_planned=0,
        finding_ids=[],
        has_integrator_rework=False,
    )


def test_task_cycle_metrics_distinguish_planned_tasks_from_rework(tmp_path: Path) -> None:
    tasks_dir = tmp_path / ".devlab/tasks"
    history = tmp_path / ".devlab/history"
    tasks_dir.mkdir(parents=True)
    history.mkdir(parents=True)
    _write_minimal_task(tasks_dir / "T0001_first.md", "T0001", "First")
    _write_minimal_task(tasks_dir / "T0002_second.md", "T0002", "Second")
    _write_handoff(
        history / "20260519T091112_developer_handoff.md",
        "developer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091113_reviewer_handoff.md",
        "reviewer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091114_developer_handoff.md",
        "developer",
        ".devlab/tasks/T0002_second.md",
    )
    _write_handoff(
        history / "20260519T091115_reviewer_handoff.md",
        "reviewer",
        ".devlab/tasks/T0002_second.md",
    )

    sessions = derive_session_records(tmp_path)
    task_cycles = derive_task_cycle_metrics(tmp_path, sessions)
    rework = derive_task_rework_summary(task_cycles)

    assert [session.task_id for session in sessions] == [
        "T0001",
        "T0001",
        "T0002",
        "T0002",
    ]
    assert task_cycles.tasks["T0001"] == TaskCycleEntry(
        developer_sessions=1, reviewer_sessions=1, has_rework=False,
    )
    assert task_cycles.tasks["T0002"] == TaskCycleEntry(
        developer_sessions=1, reviewer_sessions=1, has_rework=False,
    )
    assert rework.tasks_with_rework == []
    assert rework.has_task_rework is False


def test_task_cycle_metrics_detect_repeated_same_task_cycles(tmp_path: Path) -> None:
    tasks_dir = tmp_path / ".devlab/tasks"
    history = tmp_path / ".devlab/history"
    tasks_dir.mkdir(parents=True)
    history.mkdir(parents=True)
    _write_minimal_task(tasks_dir / "T0001_first.md", "T0001", "First")
    _write_handoff(
        history / "20260519T091112_developer_handoff.md",
        "developer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091113_reviewer_handoff.md",
        "reviewer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091114_developer_handoff.md",
        "developer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091115_reviewer_handoff.md",
        "reviewer",
        ".devlab/tasks/T0001_first.md",
    )

    task_cycles = derive_task_cycle_metrics(tmp_path)
    rework = derive_task_rework_summary(task_cycles)

    assert task_cycles.tasks["T0001"] == TaskCycleEntry(
        developer_sessions=2, reviewer_sessions=2, has_rework=True,
    )
    assert rework.tasks_with_rework == ["T0001"]
    assert rework.has_task_rework is True
    assert rework.max_developer_sessions_per_task == 2
    assert rework.max_reviewer_sessions_per_task == 2


def test_task_cycle_metrics_count_unattributed_task_sessions(tmp_path: Path) -> None:
    history = tmp_path / ".devlab/history"
    history.mkdir(parents=True)
    _write_handoff(history / "20260519T091112_developer_handoff.md", "developer", "README.md")

    task_cycles = derive_task_cycle_metrics(tmp_path)

    assert task_cycles.unattributed_developer_reviewer_sessions == 1


def test_task_cycle_metrics_use_structured_result_without_task_artifact(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / ".devlab/tasks"
    history = tmp_path / ".devlab/history"
    tasks_dir.mkdir(parents=True)
    history.mkdir(parents=True)
    _write_minimal_task(tasks_dir / "T0001_first.md", "T0001", "First")
    handoff = history / "20260519T091112_developer_handoff.md"
    _write_handoff(handoff, "developer", "src/app.py")
    _write_session_result(handoff, "developer", "T0001", outcome="failed")

    sessions = derive_session_records(tmp_path)
    task_cycles = derive_task_cycle_metrics(tmp_path, sessions)

    assert sessions[0].task_id == "T0001"
    assert sessions[0].task_id_source == "structured_result"
    assert task_cycles.tasks["T0001"].developer_sessions == 1
    assert task_cycles.unattributed_developer_reviewer_sessions == 0


def test_task_cycle_metrics_reject_conflicting_structured_and_artifact_tasks(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / ".devlab/tasks"
    history = tmp_path / ".devlab/history"
    tasks_dir.mkdir(parents=True)
    history.mkdir(parents=True)
    _write_minimal_task(tasks_dir / "T0001_first.md", "T0001", "First")
    _write_minimal_task(tasks_dir / "T0002_second.md", "T0002", "Second")
    handoff = history / "20260519T091112_reviewer_handoff.md"
    _write_handoff(handoff, "reviewer", ".devlab/tasks/T0002_second.md")
    _write_session_result(handoff, "reviewer", "T0001")

    sessions = derive_session_records(tmp_path)
    task_cycles = derive_task_cycle_metrics(tmp_path, sessions)

    assert sessions[0].task_id == ""
    assert sessions[0].task_id_source == "conflicting_task_sources"
    assert task_cycles.unattributed_developer_reviewer_sessions == 1
    assert task_cycles.attribution_sources == {"conflicting_task_sources": 1}


def test_live_review_rejections_count_reviewer_handoffs_with_open_issues(
    tmp_path: Path,
) -> None:
    history = tmp_path / ".devlab/history"
    history.mkdir(parents=True)
    (history / "20260519T091112_reviewer_handoff.md").write_text(
        "# Handoff: reviewer\n"
        "## Done\n- Reviewed.\n"
        "## Changed Artifacts\n- None\n"
        "## Open Issues\n- Response shape is wrong.\n"
        "## Addressed Findings\n- None\n"
        "## Next Session Hint\nFix response shape.\n"
    )
    (history / "20260519T091113_reviewer_handoff.md").write_text(
        "# Handoff: reviewer\n"
        "## Done\n- Reviewed.\n"
        "## Changed Artifacts\n- None\n"
        "## Open Issues\n- None\n"
        "## Addressed Findings\n- None\n"
        "## Next Session Hint\nContinue.\n"
    )

    assert derive_review_rejections(tmp_path) == 1


def test_live_role_sequence_handles_archive_collision_filenames(tmp_path: Path) -> None:
    history = tmp_path / ".devlab/history"
    history.mkdir(parents=True)
    (history / "20260519T091112_reviewer_handoff.md").write_text("reviewer")
    (history / "20260519T091112_2_developer_handoff.md").write_text("developer")

    assert derive_role_sequence(tmp_path) == ["reviewer", "developer"]


def test_collect_profile_metrics_lists_profiles_and_task_usage(tmp_path: Path) -> None:
    profiles_dir = tmp_path / ".devlab/config/profiles"
    tasks_dir = tmp_path / ".devlab/tasks"
    profiles_dir.mkdir(parents=True)
    tasks_dir.mkdir(parents=True)
    (profiles_dir / "default.toml").write_text(
        'version = 1\nid = "default"\ntitle = "Default"\n\n'
        '[tooling]\ndefault_validation = []\n\n'
        '[environment]\nmanaged_roles = []\n'
    )
    (profiles_dir / "python-app.toml").write_text(
        'version = 1\nid = "python-app"\ntitle = "Python App"\n\n'
        '[tooling]\ndefault_validation = ["uv run pytest"]\n\n'
        '[environment]\nmanaged_roles = ["developer"]\n'
    )
    _write_minimal_task(tasks_dir / "T0001_default.md", "T0001", "Default")
    _write_minimal_task(
        tasks_dir / "T0002_python.md",
        "T0002",
        "Python",
        profile="python-app",
    )

    metrics = collect_profile_metrics(tmp_path)

    assert metrics.count == 2
    assert metrics.ids == ["default", "python-app"]
    assert metrics.non_default_ids == ["python-app"]
    assert metrics.tasks_by_profile == {"default": ["T0001"], "python-app": ["T0002"]}
    assert metrics.items[1].default_validation_count == 1
    assert metrics.items[1].managed_roles == ["developer"]


def test_quality_summary_warns_for_rework_and_large_ignored_artifacts() -> None:
    summary = quality_summary(
        checks=[CheckResult("ok", True)],
        task_metrics=TaskMetrics(total=1, by_status={"closed": 1}, items=[]),
        artifact_hygiene=ArtifactHygiene(
            file_count=0, total_bytes=0, product_file_count=0, product_total_bytes=0,
            ignored_file_count=5_001, ignored_total_bytes=100_000_001,
            devlab_file_count=0, devlab_total_bytes=0,
            flagged_paths=[],
            other_ignored_file_count=5_001,
            other_ignored_total_bytes=100_000_001,
        ),
        sessions_run=7,
        task_rework=TaskReworkSummary(
            tasks_with_rework=["T0001"], has_task_rework=True,
            max_developer_sessions_per_task=0, max_reviewer_sessions_per_task=0,
            unattributed_developer_reviewer_sessions=0,
        ),
        integrator_rework=IntegratorReworkSummary(
            findings_created=1, findings_resolved=0, findings_open=1,
            findings_planned=0, finding_ids=[], has_integrator_rework=True,
        ),
    )

    assert summary.correctness_passed is True
    assert "task rework detected: T0001" in summary.warnings
    assert "integrator findings created: 1" in summary.warnings
    assert "high session count per closed task: 7/1" in summary.warnings
    assert "large other ignored artifact footprint: 100000001 bytes" in summary.warnings
    assert "large other ignored artifact file count: 5001" in summary.warnings


def test_artifact_hygiene_splits_git_product_ignored_and_devlab_files(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text(".venv/\n.pytest_cache/\n__pycache__/\n")
    (tmp_path / ".devlab/tasks").mkdir(parents=True)
    (tmp_path / ".devlab/tasks/T0001_task.md").write_text("workflow")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('ok')\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_app.py").write_text("def test_ok(): pass\n")
    (tmp_path / ".venv/lib").mkdir(parents=True)
    (tmp_path / ".venv/lib/site.py").write_text("ignored\n")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache/cache.txt").write_text("ignored\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/app.pyc").write_bytes(b"ignored")

    hygiene = collect_artifact_hygiene(tmp_path)

    assert hygiene.product_file_count == 3
    assert hygiene.ignored_file_count == 3
    assert hygiene.conventional_ignored_file_count == 3
    assert hygiene.other_ignored_file_count == 0
    assert hygiene.devlab_file_count == 1
    assert hygiene.flagged_paths == []
    assert {item.path for item in hygiene.product_top_contributors} == {
        ".gitignore", "src/", "tests/",
    }
    assert [(item.path, item.file_count) for item in hygiene.devlab_top_contributors] == [
        (".devlab/tasks/", 1),
    ]
    contributors = [
        (item.path, item.file_count, item.total_bytes)
        for item in hygiene.ignored_top_contributors
    ]
    assert contributors == [
        (".pytest_cache/", 1, 8),
        (".venv/", 1, 8),
        ("__pycache__/", 1, 7),
    ]


def test_diagnostics_verbose_reports_product_ignored_and_devlab_contributors(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text("cache/\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.txt").write_text("product\n")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache/data.bin").write_text("ignored\n")
    (tmp_path / ".devlab/logs").mkdir(parents=True)
    (tmp_path / ".devlab/logs/session.log").write_text("devlab\n")

    output = format_workflow_diagnostics(tmp_path, verbose=True)

    assert "Artifact contributors:" in output
    assert "- product: src/: 1 files, 8 bytes" in output
    assert "- other ignored: cache/: 1 files, 8 bytes" in output
    assert "- devlab: .devlab/logs/: 1 files, 7 bytes" in output


def test_diagnostics_reports_top_ignored_artifact_contributors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text("build/\ncache/\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build/large.bin").write_bytes(b"x" * 10)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache/small.bin").write_bytes(b"x" * 5)
    monkeypatch.setattr("devlab.artifact_hygiene.LARGE_IGNORED_BYTES_WARNING", 1)
    monkeypatch.setattr("devlab.workflow_diagnostics.LARGE_IGNORED_BYTES_WARNING", 1)

    output = format_workflow_diagnostics(tmp_path)

    assert "large other ignored artifact footprint: 15 bytes" in output
    assert "Top other ignored artifact contributors:" in output
    assert "- build/: 1 files, 10 bytes" in output
    assert "- cache/: 1 files, 5 bytes" in output


def test_diagnostics_treats_large_conventional_cache_as_informational(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text(".venv/\n")
    (tmp_path / ".venv/lib").mkdir(parents=True)
    (tmp_path / ".venv/lib/site.py").write_bytes(b"x" * 10)
    monkeypatch.setattr("devlab.artifact_hygiene.LARGE_IGNORED_BYTES_WARNING", 1)
    monkeypatch.setattr("devlab.workflow_diagnostics.LARGE_IGNORED_BYTES_WARNING", 1)

    output = format_workflow_diagnostics(tmp_path)

    assert "1 ignored files (1 conventional, 0 other)" in output
    assert "large other ignored artifact footprint" not in output


def test_artifact_hygiene_counts_unignored_files_as_product(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".venv/lib").mkdir(parents=True)
    (tmp_path / ".venv/lib/site.py").write_text("not ignored\n")

    hygiene = collect_artifact_hygiene(tmp_path)

    assert hygiene.product_file_count == 1
    assert hygiene.ignored_file_count == 0
    assert hygiene.flagged_paths == []


def test_evaluation_init_creates_git_repo_when_absent(tmp_path: Path) -> None:
    init_target_workspace(tmp_path, "Build something small.")

    assert (tmp_path / ".git").exists()
    assert _git(tmp_path, "rev-parse", "--verify", "HEAD").returncode == 0


def test_evaluation_init_commits_existing_git_repo_setup(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "devlab-eval@example.invalid")
    _git(tmp_path, "config", "user.name", "DevLab Eval")
    _git(tmp_path, "commit", "--allow-empty", "-m", "Existing baseline")
    before = int(_git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip())

    init_target_workspace(tmp_path, "Build something small.")

    after = int(_git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip())
    assert after > before
    assert _git(tmp_path, "status", "--porcelain").stdout.strip() == ""


def test_copy_live_agent_config_reports_missing_path(tmp_path: Path) -> None:
    init_target_workspace(tmp_path, "Build something small.")
    missing = tmp_path / "missing.agents.toml"

    with pytest.raises(ValueError, match="DEVLAB_LIVE_AGENTS_TOML points to a missing file"):
        copy_live_agent_config(tmp_path, missing)


def test_copy_live_agent_config_requires_file(tmp_path: Path) -> None:
    init_target_workspace(tmp_path, "Build something small.")
    directory = tmp_path / "agent-config-dir"
    directory.mkdir()

    with pytest.raises(ValueError, match="DEVLAB_LIVE_AGENTS_TOML must point to a file"):
        copy_live_agent_config(tmp_path, directory)


def test_copy_live_agent_config_copies_and_commits(tmp_path: Path) -> None:
    init_target_workspace(tmp_path, "Build something small.")
    agent_config = tmp_path / "live.agents.toml"
    agent_config.write_text(
        "[providers.mock]\n"
        'command = "mock-agent"\n'
        "\n"
        "[roles.default]\n"
        'provider = "mock"\n'
    )
    before = int(_git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip())

    copy_live_agent_config(tmp_path, agent_config)

    copied = tmp_path / ".devlab/config/agents.toml"
    assert copied.read_text() == agent_config.read_text()
    after = int(_git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip())
    assert after == before + 1
    assert _git(tmp_path, "status", "--porcelain").stdout.strip() == "?? live.agents.toml"


def test_live_agent_config_env_failure_has_no_pytest_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.evaluations import test_live_workflow_evaluations as live_tests

    monkeypatch.setenv("DEVLAB_LIVE_AGENTS_TOML", "missing.agents.toml")

    with pytest.raises(pytest.fail.Exception) as exc_info:
        live_tests._live_agent_config()

    assert "DEVLAB_LIVE_AGENTS_TOML points to a missing file" in str(exc_info.value)


def test_live_failure_context_summarizes_errors_without_full_json(tmp_path: Path) -> None:
    from tests.evaluations import test_live_workflow_evaluations as live_tests

    scenario = EvaluationScenario(
        id="live-failure",
        title="Live failure",
        system_spec="Build something small.",
        max_sessions=1,
        checks=(),
    )
    diagnostics = EvaluationDiagnostics(
        scenario_id=scenario.id,
        provider_mode="live",
        sessions_run=3,
        completed=False,
        exit_code=1,
        stop_reason="error",
        roles=["architect", "planner", "developer"],
        findings_created=0,
        findings_resolved=0,
        review_rejections=0,
        duration_seconds=1.0,
        max_prompt_chars=0,
        checks=[CheckResult("api", False, "missing server")],
        artifacts=[],
        timestamp="2026-06-25T00:00:00+00:00",
        target_root=tmp_path.as_posix(),
        agent_log_dir=(tmp_path / ".devlab/logs/agents").as_posix(),
        errors=[
            EvaluationError(
                "agent_invocation",
                "agent exited with code 1; "
                f"stdout_log={tmp_path / '.devlab/logs/agents/reviewer.stdout.log'}; "
                f"stderr_log={tmp_path / '.devlab/logs/agents/reviewer.stderr.log'}",
                1,
            )
        ],
    )

    context = live_tests._live_failure_context(tmp_path, scenario, diagnostics)

    assert "errors:" in context
    assert "full_diagnostics_command=cat" in context
    assert "agent_logs_command=ls -1" in context
    assert "agent_log_commands:" in context
    assert f"stdout_log: cat {tmp_path / '.devlab/logs/agents/reviewer.stdout.log'}" in context
    assert f"stderr_log: cat {tmp_path / '.devlab/logs/agents/reviewer.stderr.log'}" in context
    assert "agent_invocation exit=1" in context
    assert "failed_checks:" in context
    assert "api: missing server" in context
    assert "diagnostics_json={" not in context


def _write_minimal_task(
    path: Path,
    task_id: str,
    title: str,
    *,
    profile: str | None = None,
) -> None:
    profile_line = f'profile = "{profile}"\n' if profile else ""
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{title}"\n'
        'status = "closed"\n'
        f"{profile_line}"
        'domain = "general"\n'
        "depends_on = []\n"
        "addresses_findings = []\n"
        "+++\n\n"
        f"# {task_id}: {title}\n"
    )


def _write_handoff(path: Path, role: str, changed_artifact: str) -> None:
    path.write_text(
        f"# Handoff: {role}\n"
        "## Done\n- Done.\n"
        f"## Changed Artifacts\n- `{changed_artifact}` (modified)\n"
        "## Open Issues\n- None\n"
        "## Addressed Findings\n- None\n"
        "## Next Session Hint\nContinue.\n"
    )


def _write_session_result(
    handoff_path: Path,
    role: str,
    task_id: str,
    *,
    outcome: str = "completed",
) -> None:
    result_path = handoff_path.with_name(
        handoff_path.name.removesuffix("_handoff.md") + "_result.toml"
    )
    open_issues = '["More work remains."]' if outcome == "failed" else "[]"
    result_path.write_text(
        "schema_version = 1\n"
        'session_id = "session-1"\n'
        f'role = "{role}"\n'
        f'task = "{task_id}"\n'
        'milestone = ""\n'
        f'protected_active_tasks = ["{task_id}"]\n'
        "incremental_planning_required = false\n"
        "allow_active_task_replacement = false\n"
        f'outcome = "{outcome}"\n'
        'commit_message = "Test result"\n'
        'done = ["Done."]\n'
        'changed_artifacts = []\n'
        f"open_issues = {open_issues}\n"
        "addressed_findings = []\n"
        'next_session_hint = "Continue."\n'
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        text=True,
        capture_output=True,
        check=False,
    )


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
    assert diagnostics.stop_reason == "workflow_complete", diagnostics_path.read_text()
    assert diagnostics.exit_code == 0, diagnostics_path.read_text()
    assert diagnostics.sessions_run == scenario.expected_sessions
    assert tuple(diagnostics.roles) == scenario.expected_roles
    assert diagnostics.review_rejections == scenario.expected_rejections
    assert diagnostics.findings_created == scenario.expected_findings
    assert all(check.passed for check in diagnostics.checks), diagnostics.checks
    assert diagnostics.max_prompt_chars > 0
    assert expected_artifact in diagnostics.artifacts
    assert diagnostics.agent_log_dir.endswith(".devlab/logs/agents")
    assert diagnostics.tasks.total >= 1
    assert diagnostics.quality.correctness_passed is True
    assert diagnostics.quality.all_tasks_closed is True
    assert diagnostics.artifact_hygiene.file_count >= 0
    assert diagnostics.agent_logs.stdout_count >= 0
    assert scenario.expected_sessions is not None
    assert diagnostics.git.repository is True
    assert diagnostics.git.clean_worktree is True
    assert diagnostics.git.commit_count > diagnostics.git.baseline_commit_count
    assert diagnostics.git.session_commit_count >= scenario.expected_sessions
    assert diagnostics.git.missing_milestone_tags == []
    assert "devlab/milestone/M1" in diagnostics.git.milestone_tags
    assert diagnostics.git.tag_targets["devlab/milestone/M1"]
    task = FileTaskTracker(root).get("T0001")
    assert task.status == TaskStatus.CLOSED
    milestone = FileMilestoneTracker(root).get("M1")
    assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED

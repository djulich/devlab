from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from devlab.generations import active_generation, archived_generation_numbers
from devlab.git import run_git
from devlab.milestones import FileMilestoneTracker
from devlab.orchestrator import run_loop
from devlab.task_tracker import FileTaskTracker
from tests.evaluations.checks import (
    TODO_API_ENDPOINTS,
    BlackBoxCheck,
    CheckResult,
    built_executable_output_check,
    command_check,
    command_fails_check,
    deployment_artifacts_check,
    endpoint_documentation_check,
    file_contains_check,
    react_vite_browser_integration_check,
    react_vite_container_build_check,
    react_vite_frontend_check,
    stateful_todo_api_check,
    static_frontend_check,
    toolchain_command_check,
)
from tests.evaluations.harness import (
    EvaluationDiagnostics,
    EvaluationScenario,
    copy_live_agent_config,
    init_target_workspace,
    run_live_evaluation,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_EVALS") != "1",
    reason="live DevLab evaluations require DEVLAB_LIVE_EVALS=1",
)


def _live_agent_config() -> Path | None:
    agent_config = os.environ.get("DEVLAB_LIVE_AGENTS_TOML")
    if not agent_config:
        return None
    path = Path(agent_config)
    if not path.exists():
        pytest.fail(
            "DEVLAB_LIVE_AGENTS_TOML points to a missing file: "
            f"{path}. Set it to an existing agents.toml file or unset it to use the "
            "target's default generated agent configuration.",
            pytrace=False,
        )
    if not path.is_file():
        pytest.fail(
            "DEVLAB_LIVE_AGENTS_TOML must point to a file, not a directory or special "
            f"path: {path}",
            pytrace=False,
        )
    return path


def _run_live_scenario(tmp_path: Path, scenario: EvaluationScenario) -> EvaluationDiagnostics:
    return run_live_evaluation(
        tmp_path,
        scenario,
        provider=os.environ.get("DEVLAB_LIVE_PROVIDER"),
        model=os.environ.get("DEVLAB_LIVE_MODEL"),
        effort=os.environ.get("DEVLAB_LIVE_EFFORT"),
        agent_config=_live_agent_config(),
        max_sessions=scenario.max_sessions,
    )


def _configure_live_agents(root: Path) -> None:
    agent_config = _live_agent_config()
    if agent_config is None:
        return
    copy_live_agent_config(root, agent_config)


def _run_live_loop(
    root: Path,
    *,
    max_sessions: int,
    planning_only: bool = False,
    adopt_existing: bool = False,
):
    return run_loop(
        root,
        max_sessions=max_sessions,
        provider=os.environ.get("DEVLAB_LIVE_PROVIDER"),
        model=os.environ.get("DEVLAB_LIVE_MODEL"),
        effort=os.environ.get("DEVLAB_LIVE_EFFORT"),
        retain_prompts=os.environ.get("DEVLAB_LIVE_RETAIN_PROMPTS") == "1",
        planning_only=planning_only,
        adopt_existing=adopt_existing,
    )


def _assert_live_diagnostics(
    tmp_path: Path,
    scenario: EvaluationScenario,
    diagnostics: EvaluationDiagnostics,
) -> None:
    failure_context = _live_failure_context(tmp_path, scenario, diagnostics)
    assert diagnostics.completed is True, failure_context
    assert diagnostics.exit_code == 0, failure_context
    assert all(check.passed for check in diagnostics.checks), failure_context
    assert diagnostics.roles, failure_context
    assert diagnostics.tasks.total >= 1, failure_context
    assert diagnostics.quality.correctness_passed is True, failure_context
    assert diagnostics.git.repository is True, failure_context
    assert diagnostics.git.clean_worktree is True, failure_context
    assert diagnostics.git.commit_count > diagnostics.git.baseline_commit_count, failure_context
    assert diagnostics.git.session_commit_count >= diagnostics.sessions_run, failure_context
    assert not diagnostics.git.missing_milestone_tags, failure_context


def _live_failure_context(
    tmp_path: Path,
    scenario: EvaluationScenario,
    diagnostics: EvaluationDiagnostics,
) -> str:
    diagnostics_path = tmp_path / ".devlab/evaluations" / f"{scenario.id}.json"
    lines = [
        f"target_root={tmp_path}",
        f"diagnostics={diagnostics_path}",
        f"agent_logs={tmp_path / '.devlab/logs/agents'}",
        f"full_diagnostics_command=cat {diagnostics_path}",
        f"agent_logs_command=ls -1 {tmp_path / '.devlab/logs/agents'}",
        f"completed={diagnostics.completed} exit_code={diagnostics.exit_code} "
        f"sessions_run={diagnostics.sessions_run} roles={diagnostics.roles!r}",
    ]
    if diagnostics.errors:
        lines.append("errors:")
        for error in diagnostics.errors:
            lines.append(
                f"- {error.phase} exit={error.exit_code}: {_shorten(error.message, 1200)}"
            )
        log_commands = _agent_log_commands(diagnostics)
        if log_commands:
            lines.append("agent_log_commands:")
            lines.extend(log_commands)
    failed_checks = [check for check in diagnostics.checks if not check.passed]
    if failed_checks:
        lines.append("failed_checks:")
        for check in failed_checks:
            lines.append(f"- {check.name}: {_shorten(check.message, 500)}")
    if diagnostics.git.missing_milestone_tags:
        lines.append(f"missing_milestone_tags={diagnostics.git.missing_milestone_tags!r}")
    return "\n".join(lines)


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _agent_log_commands(diagnostics: EvaluationDiagnostics) -> list[str]:
    commands: list[str] = []
    for error in diagnostics.errors:
        for key in ("stdout_log", "stderr_log", "config_log"):
            match = re.search(rf"{key}=([^;]+)", error.message)
            if match is not None:
                commands.append(f"- {key}: cat {match.group(1).strip()}")
    return commands


def _target_command_check(
    name: str,
    args: list[str],
    expected_text: str,
) -> BlackBoxCheck:
    def check(root: Path) -> CheckResult:
        result = subprocess.run(
            args,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        output = result.stdout + result.stderr
        passed = result.returncode == 0 and expected_text in output
        return CheckResult(
            name,
            passed,
            "" if passed else f"exit={result.returncode} output={output!r}",
        )

    return check


def _require_live_tools(tools: tuple[str, ...]) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"requires operator-installed tools on PATH: {', '.join(missing)}")


def _assert_live_task_profile(
    root: Path,
    diagnostics: EvaluationDiagnostics,
    profile_id: str,
    *,
    minimum_validation_commands: int,
) -> None:
    profile = next(
        (item for item in diagnostics.profiles.items if item.id == profile_id),
        None,
    )
    assert profile is not None
    assert profile.valid is True
    assert profile.default_validation_count >= minimum_validation_commands
    assigned_tasks = diagnostics.profiles.tasks_by_profile.get(profile_id, [])
    assert assigned_tasks
    verification = FileMilestoneTracker(root).read_verification("M1")
    assert verification is not None
    assert verification.state == "verified"
    profile_commands = [
        command
        for command in verification.commands
        if "profile" in command.sources and set(command.task_ids).intersection(assigned_tasks)
    ]
    assert len(profile_commands) >= minimum_validation_commands
    assert all(command.outcome == "passed" for command in profile_commands)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_ADOPT_EXISTING") != "1",
    reason="adopt-existing live evaluation requires DEVLAB_LIVE_ADOPT_EXISTING=1",
)
def test_live_adopt_existing_current_state_baseline_and_feature_work(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "adopt-existing-calculator"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.12"\n'
        "\n"
        "[dependency-groups]\n"
        'dev = ["pytest"]\n'
    )
    (tmp_path / ".gitignore").write_text(".venv/\n__pycache__/\n.pytest_cache/\n")
    (tmp_path / "calculator.py").write_text(
        "import sys\n\n"
        "def calculate(command: str, left: int, right: int) -> int:\n"
        "    if command == 'add':\n"
        "        return left + right\n"
        "    raise ValueError(command)\n\n"
        "def main() -> None:\n"
        "    if len(sys.argv) != 4:\n"
        "        raise SystemExit(2)\n"
        "    print(calculate(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])))\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    (tmp_path / "test_calculator.py").write_text(
        "from calculator import calculate\n\n\n"
        "def test_add():\n"
        "    assert calculate('add', 2, 3) == 5\n"
    )
    init_target_workspace(
        tmp_path,
        "Add a subtract command to the existing Python calculator CLI. Preserve the "
        "existing add command and keep the CLI runnable from the repository root as "
        "python calculator.py <command> <left> <right>. The command must print only "
        "the numeric result. Update the existing tests or add adjacent tests for the "
        "new subtract behavior. The target-owned validation command is "
        "`uv run pytest`; do not use bare `pytest` because the evaluation must not "
        "rely on globally installed or harness-inherited tools. Treat the current "
        "repository as an already-started project, not a greenfield project.",
    )
    tooling_path = tmp_path / ".devlab/config/tooling.md"
    tooling_path.write_text(
        tooling_path.read_text() + "\n\n## Existing-Project Evaluation Validation\n\n"
        "This target owns its Python test environment through `pyproject.toml` and "
        "uv dependency groups. Use `uv run pytest` for task validation. Do not use "
        "bare `pytest`, because that can accidentally resolve to the DevLab harness "
        "environment instead of target-owned tooling.\n"
    )
    profile_path = tmp_path / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        "version = 1\n"
        'id = "default"\n'
        'title = "Default evaluation profile"\n'
        "\n[tooling]\n"
        'summary = "Target-owned Python validation through uv and pyproject.toml."\n'
        'default_validation = ["uv run pytest"]\n'
        "\n[environment]\n"
        "managed_roles = []\n"
    )
    lock_result = subprocess.run(
        ["uv", "--cache-dir", "/tmp/uv-cache", "lock"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert lock_result.returncode == 0, lock_result.stderr
    run_git(
        tmp_path,
        "add",
        ".gitignore",
        "pyproject.toml",
        "uv.lock",
        ".devlab/config/tooling.md",
        ".devlab/config/profiles/default.toml",
    )
    run_git(tmp_path, "commit", "-m", "Configure target-owned validation")
    _configure_live_agents(tmp_path)
    failure_context = f"target_root={tmp_path}\nagent_logs={tmp_path / '.devlab/logs/agents'}"

    planned = _run_live_loop(
        tmp_path,
        max_sessions=2,
        planning_only=True,
        adopt_existing=True,
    )

    assert planned.completed is True, failure_context
    assert planned.exit_code == 0, failure_context
    design = (tmp_path / ".devlab/plans/design-plan.md").read_text().lower()
    assert "calculator.py" in design, failure_context
    assert "add" in design, failure_context
    assert "subtract" in design, failure_context
    assert "current-state" in design or "current state" in design or "existing" in design, (
        failure_context
    )
    tasks = FileTaskTracker(tmp_path).list_tasks()
    assert tasks, failure_context
    planned_validation = {
        command for task in tasks if task.validation is not None for command in task.validation
    }
    assert "pytest" not in planned_validation, failure_context
    assert any("uv run pytest" in command for command in planned_validation) or any(
        task.validation is None for task in tasks
    ), failure_context

    final = _run_live_loop(
        tmp_path,
        max_sessions=int(os.environ.get("DEVLAB_LIVE_ADOPT_EXISTING_MAX_SESSIONS", "8")),
    )

    assert final.completed is True, failure_context
    assert final.exit_code == 0, failure_context
    add_check = command_check("existing add command", ["calculator.py", "add", "2", "3"], "5")(
        tmp_path
    )
    subtract_check = command_check(
        "new subtract command", ["calculator.py", "subtract", "7", "4"], "3"
    )(tmp_path)
    assert add_check.passed is True, add_check.message + "\n" + failure_context
    assert subtract_check.passed is True, subtract_check.message + "\n" + failure_context
    validation = _target_command_check("target-owned pytest", ["uv", "run", "pytest"], "passed")(
        tmp_path
    )
    assert validation.passed is True, validation.message + "\n" + failure_context
    assert run_git(tmp_path, "status", "--porcelain").stdout.strip() == "", failure_context


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_SPEC_RECONCILIATION") != "1",
    reason="spec reconciliation live evaluation requires DEVLAB_LIVE_SPEC_RECONCILIATION=1",
)
def test_live_spec_reconciliation_archives_and_replans(tmp_path: Path) -> None:
    init_target_workspace(
        tmp_path,
        "Build a Python CLI calculator in calculator.py. It must work from the "
        "repository root as python calculator.py add <left> <right> and print only "
        "the numeric sum. Keep the implementation dependency-free.",
    )
    _configure_live_agents(tmp_path)
    failure_context = f"target_root={tmp_path}\nagent_logs={tmp_path / '.devlab/logs/agents'}"

    initial = _run_live_loop(
        tmp_path,
        max_sessions=int(os.environ.get("DEVLAB_LIVE_SPEC_RECONCILIATION_INITIAL_MAX", "10")),
    )

    assert initial.completed is True, failure_context
    assert initial.exit_code == 0, failure_context
    initial_check = command_check("calculator add", ["calculator.py", "add", "2", "3"], "5")(
        tmp_path
    )
    assert initial_check.passed is True, initial_check.message + "\n" + failure_context
    assert active_generation(tmp_path) == 1, failure_context

    spec_path = tmp_path / ".devlab/specs/system/README.md"
    spec_path.write_text(
        "# System Specification\n\n"
        "Replace the current product plan with a Python CLI greeter in greeter.py. "
        "It must work from the repository root as python greeter.py <name> and print "
        "exactly hello <name>. Keep the implementation dependency-free.\n"
    )
    run_git(tmp_path, "add", ".devlab/specs/system/README.md")
    run_git(tmp_path, "commit", "-m", "Change system spec to greeter")

    blocked = _run_live_loop(tmp_path, max_sessions=1)

    assert blocked.completed is False, failure_context
    assert blocked.exit_code == 1, failure_context
    assert blocked.errors[0].phase == "spec_reconciliation", failure_context

    planned = _run_live_loop(tmp_path, max_sessions=2, planning_only=True)

    assert planned.completed is True, failure_context
    assert planned.exit_code == 0, failure_context
    assert active_generation(tmp_path) == 2, failure_context
    assert archived_generation_numbers(tmp_path) == (1,), failure_context
    assert list((tmp_path / ".devlab/generations/0001/tasks").glob("*.md")), failure_context
    assert FileTaskTracker(tmp_path).list_tasks(), failure_context

    final = _run_live_loop(
        tmp_path,
        max_sessions=int(os.environ.get("DEVLAB_LIVE_SPEC_RECONCILIATION_FINAL_MAX", "10")),
    )

    assert final.completed is True, failure_context
    assert final.exit_code == 0, failure_context
    final_check = command_check("greeter", ["greeter.py", "Ada"], "hello Ada")(tmp_path)
    assert final_check.passed is True, final_check.message + "\n" + failure_context
    assert run_git(tmp_path, "status", "--porcelain").stdout.strip() == "", failure_context


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_SIMPLE_CLI") != "1",
    reason="simple cli live evaluation requires DEVLAB_LIVE_SIMPLE_CLI=1",
)
def test_live_cli_calculator_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="live-cli-calculator-happy-path",
        title="Live CLI calculator happy path",
        system_spec=(
            "Build a Python CLI calculator in calculator.py with add and subtract commands. "
            "It must work when run directly from the repository root as "
            "python calculator.py <command> <left> <right>, without installing the project "
            "or setting PYTHONPATH. The commands must print only the numeric result. "
            "Do not treat the placeholder deployment specification as a deployment requirement."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_MAX_SESSIONS", "10")),
        checks=(
            command_check("add command", ["calculator.py", "add", "2", "3"], "5"),
            command_check("subtract command", ["calculator.py", "subtract", "7", "4"], "3"),
            command_check("add negative command", ["calculator.py", "add", "-2", "5"], "3"),
            command_check(
                "subtract negative result", ["calculator.py", "subtract", "2", "5"], "-3"
            ),
            command_fails_check("missing args exits nonzero", ["calculator.py"]),
        ),
    )
    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_STATEFUL_WEB_API") != "1",
    reason="stateful live web API evaluation requires DEVLAB_LIVE_STATEFUL_WEB_API=1",
)
def test_live_stateful_web_api_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="live-stateful-web-api-happy-path",
        title="Live stateful web API happy path",
        system_spec=(
            "Build a small Python standard-library JSON HTTP API for todo items. "
            "Do not use third-party runtime dependencies. Implement the server in "
            "src/todo_api/server.py and make it runnable from the repository root with "
            "python -m src.todo_api.server --port <port>. It must expose GET /health "
            'returning HTTP 200 with JSON {"status": "ok"}, POST /todos with JSON '
            '{"title": "..."} to create an in-memory item and return a top-level '
            "JSON object with integer id and title fields using any successful 2xx status, "
            'GET /todos to return HTTP 200 with JSON {"todos": [<items>]}, DELETE '
            '/todos/{id} to return HTTP 200 with JSON {"deleted": <id>}. POST /todos '
            "must return a 4xx client error "
            "for invalid JSON, missing title, empty title, or blank title. Return 404 "
            "for unknown routes. "
            "Also provide a Makefile "
            "with run and test targets and a .gitignore covering Python caches and local "
            "runtime artifacts. The defined API endpoints are "
            f"{', '.join(f'`{endpoint}`' for endpoint in TODO_API_ENDPOINTS)}. The README "
            "must contain an endpoint reference listing every defined method/path pair "
            "using the exact notation above."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_STATEFUL_MAX_SESSIONS", "18")),
        checks=(
            stateful_todo_api_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
            endpoint_documentation_check(TODO_API_ENDPOINTS),
            file_contains_check("python cache gitignore", ".gitignore", "__pycache__/"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_RUST") != "1",
    reason="Rust live evaluation requires DEVLAB_LIVE_RUST=1",
)
def test_live_rust_cli_happy_path_evaluation(tmp_path: Path) -> None:
    _require_live_tools(("cargo", "rustc", "rustfmt"))
    scenario = EvaluationScenario(
        id="live-rust-cli-happy-path",
        title="Live Rust CLI happy path",
        system_spec=(
            "Build a dependency-free Rust CLI named devlab-live-rust-cli. The command "
            "must accept exactly `add <left> <right>`, parse signed 64-bit integers, "
            "print only their sum followed by a newline on success, and exit nonzero "
            "with a useful stderr message for invalid commands, arity, or integers. "
            "Use the stable Rust toolchain and edition 2021 or newer. Include focused "
            "automated tests, Cargo.lock, README usage instructions, and a .gitignore "
            "covering /target/. Project-owned validation is `cargo fmt --check` and "
            "`cargo test`; do not install or bootstrap Rust tools. Create a dedicated "
            "DevLab task profile with id `rust`, put both commands in its "
            "default_validation list, and assign product implementation tasks to it."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_RUST_MAX_SESSIONS", "12")),
        checks=(
            file_contains_check("Rust package", "Cargo.toml", "devlab-live-rust-cli"),
            toolchain_command_check("Rust format", ["cargo", "fmt", "--check"]),
            toolchain_command_check("Rust tests", ["cargo", "test"]),
            toolchain_command_check(
                "Rust CLI output",
                ["cargo", "run", "--quiet", "--", "add", "-7", "12"],
                expected_stdout="5",
            ),
            file_contains_check("Rust usage docs", "README.md", "cargo run"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)
    _assert_live_task_profile(tmp_path, diagnostics, "rust", minimum_validation_commands=2)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_GO") != "1",
    reason="Go live evaluation requires DEVLAB_LIVE_GO=1",
)
def test_live_go_cli_happy_path_evaluation(tmp_path: Path) -> None:
    _require_live_tools(("go", "gofmt"))
    scenario = EvaluationScenario(
        id="live-go-cli-happy-path",
        title="Live Go CLI happy path",
        system_spec=(
            "Build a dependency-free Go CLI module named devlab-live-go-cli. The "
            "command must accept exactly `subtract <left> <right>`, parse signed 64-bit "
            "integers, print only their difference followed by a newline on success, "
            "and exit nonzero with a useful stderr message for invalid commands, arity, "
            "or integers. Use the operator-installed stable Go toolchain and standard "
            "library only. Include focused automated tests, go.mod, README usage "
            "instructions, and a .gitignore covering generated binaries. Project-owned "
            'validation is `test -z "$(gofmt -l .)"` and `go test ./...`; do not '
            "install or bootstrap Go tools. Create a dedicated DevLab task profile with "
            "id `go`, put both commands in its default_validation list, and assign "
            "product implementation tasks to it."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_GO_MAX_SESSIONS", "12")),
        checks=(
            file_contains_check("Go module", "go.mod", "devlab-live-go-cli"),
            toolchain_command_check("Go format", ["gofmt", "-l", "."], expected_stdout=""),
            toolchain_command_check("Go tests", ["go", "test", "./..."]),
            toolchain_command_check(
                "Go CLI output",
                ["go", "run", ".", "subtract", "-7", "12"],
                expected_stdout="-19",
            ),
            file_contains_check("Go usage docs", "README.md", "go run"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)
    _assert_live_task_profile(tmp_path, diagnostics, "go", minimum_validation_commands=2)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_C") != "1",
    reason="C live evaluation requires DEVLAB_LIVE_C=1",
)
def test_live_c_cmake_cli_happy_path_evaluation(tmp_path: Path) -> None:
    _require_live_tools(("cmake", "ctest", "make", "cc"))
    scenario = EvaluationScenario(
        id="live-c-cmake-cli-happy-path",
        title="Live C/CMake CLI happy path",
        system_spec=(
            "Build a dependency-free C17 CLI named devlab-live-c. The command must "
            "accept exactly `subtract <left> <right>`, parse signed integers, print only "
            "their difference followed by a newline on success, and exit nonzero with a "
            "useful stderr message for invalid commands, arity, integers, or arithmetic "
            "overflow. Use CMake 3.20 or newer and CTest. Provide CMakePresets.json with "
            "configure, build, and test presets all named `dev`; the configure preset "
            "must use Unix Makefiles and build under the ignored /build/ directory. "
            "Include focused automated tests and README usage instructions. "
            "Project-owned validation is `cmake --preset dev`, `cmake --build --preset "
            "dev`, and `ctest --preset dev`; do not install or bootstrap C, CMake, CTest, "
            "or Make. Create a dedicated DevLab task profile with id `c`, put all three "
            "commands in its default_validation list, and assign product implementation "
            "tasks to it."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_C_MAX_SESSIONS", "12")),
        checks=(
            file_contains_check("C project", "CMakeLists.txt", "devlab-live-c"),
            toolchain_command_check("C configure", ["cmake", "--preset", "dev"]),
            toolchain_command_check("C build", ["cmake", "--build", "--preset", "dev"]),
            toolchain_command_check("C tests", ["ctest", "--preset", "dev"]),
            built_executable_output_check(
                "C CLI output",
                "build",
                "devlab-live-c",
                ["subtract", "-6", "7"],
                expected_stdout="-13",
            ),
            file_contains_check("C usage docs", "README.md", "cmake --preset dev"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)
    _assert_live_task_profile(tmp_path, diagnostics, "c", minimum_validation_commands=3)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_CPP") != "1",
    reason="C++ live evaluation requires DEVLAB_LIVE_CPP=1",
)
def test_live_cpp_cmake_cli_happy_path_evaluation(tmp_path: Path) -> None:
    _require_live_tools(("cmake", "ctest", "make", "c++"))
    scenario = EvaluationScenario(
        id="live-cpp-cmake-cli-happy-path",
        title="Live C++/CMake CLI happy path",
        system_spec=(
            "Build a dependency-free C++20 CLI named devlab-live-cpp. The command must "
            "accept exactly `multiply <left> <right>`, parse signed integers, print only "
            "their product followed by a newline on success, and exit nonzero with a "
            "useful stderr message for invalid commands, arity, or integers. Use CMake "
            "3.20 or newer and CTest. Provide CMakePresets.json with configure, build, "
            "and test presets all named `dev`; the configure preset must use Unix "
            "Makefiles and build under the ignored /build/ directory. Include focused "
            "automated tests and README usage instructions. Project-owned validation is "
            "`cmake --preset dev`, `cmake --build --preset dev`, and `ctest --preset "
            "dev`; do not install or bootstrap C++, CMake, CTest, or Make. Create a "
            "dedicated DevLab task profile with id `cpp`, put all three commands in its "
            "default_validation list, and assign product implementation tasks to it."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_CPP_MAX_SESSIONS", "12")),
        checks=(
            file_contains_check("C++ project", "CMakeLists.txt", "devlab-live-cpp"),
            toolchain_command_check("C++ configure", ["cmake", "--preset", "dev"]),
            toolchain_command_check("C++ build", ["cmake", "--build", "--preset", "dev"]),
            toolchain_command_check("C++ tests", ["ctest", "--preset", "dev"]),
            built_executable_output_check(
                "C++ CLI output",
                "build",
                "devlab-live-cpp",
                ["multiply", "-6", "7"],
                expected_stdout="-42",
            ),
            file_contains_check("C++ usage docs", "README.md", "cmake --preset dev"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)
    _assert_live_task_profile(tmp_path, diagnostics, "cpp", minimum_validation_commands=3)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_STATIC_FRONTEND") != "1",
    reason="static frontend live evaluation requires DEVLAB_LIVE_STATIC_FRONTEND=1",
)
def test_live_static_frontend_todo_app_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="live-static-frontend-todo-app-happy-path",
        title="Live static frontend todo app happy path",
        system_spec=(
            "Build a small Python standard-library JSON HTTP API for todo items plus a "
            "static vanilla HTML/CSS/JS frontend. Do not use React, Vite, npm, or a "
            "frontend build step. Implement the API in src/todo_api/server.py and make "
            "it runnable from the repository root with python -m src.todo_api.server "
            "--port <port>. It must expose GET /health returning HTTP 200 with JSON "
            '{"status": "ok"}, POST /todos with JSON {"title": "..."} to '
            "create an in-memory item and return a top-level JSON object with integer id "
            "and title fields using any successful 2xx status, GET /todos to return HTTP "
            '200 with JSON {"todos": [<items>]}, DELETE /todos/{id} to return HTTP 200 '
            'with JSON {"deleted": <id>}. '
            "POST /todos must return a 4xx client error for invalid JSON, missing "
            "title, empty title, or blank title. Return 404 for unknown routes. Place "
            "frontend files at exactly static/index.html, static/app.js, and "
            "static/styles.css. The UI must list todos, add todos, delete todos, display "
            "validation errors, and make direct GET, POST, and DELETE calls to the "
            "/todos routes from static/app.js. Provide a Makefile "
            "with run and test targets and README instructions for running the API and "
            "using the static frontend."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_STATIC_FRONTEND_MAX_SESSIONS", "20")),
        checks=(
            stateful_todo_api_check,
            static_frontend_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
            file_contains_check("usage docs", "README.md", "static"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_REACT_VITE_FRONTEND") != "1",
    reason="React/Vite frontend live evaluation requires DEVLAB_LIVE_REACT_VITE_FRONTEND=1",
)
def test_live_react_vite_todo_app_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="live-react-vite-todo-app-happy-path",
        title="Live React/Vite todo app happy path",
        system_spec=(
            "Build a small Python standard-library JSON HTTP API for todo items plus a "
            "React frontend using Vite. Implement the API in src/todo_api/server.py and "
            "make it runnable from the repository root with python -m src.todo_api.server "
            "--port <port>. It must expose GET /health returning HTTP 200 with JSON "
            '{"status": "ok"}, POST /todos with JSON {"title": "..."} to '
            "create an in-memory item and return a top-level JSON object with integer id "
            "and title fields using any successful 2xx status, GET /todos to return HTTP "
            '200 with JSON {"todos": [<items>]}, DELETE /todos/{id} to return HTTP 200 '
            'with JSON {"deleted": <id>}. '
            "POST /todos must return a 4xx client error for invalid JSON, missing "
            "title, empty title, or blank title. Return 404 for unknown routes. Use "
            "Vite with React for the browser UI; include react, react-dom, vite, and "
            "@vitejs/plugin-react in package.json. Provide index.html, a src/main "
            "React entrypoint, a src/App component, and CSS under src/. The React UI "
            "must list todos, add todos, delete todos, display validation errors, and "
            "work in a browser when the API runs on a separate localhost port during "
            "development. The UI must expose a todo title input with an accessible name "
            "containing todo or title, an add/submit button, delete/remove buttons for "
            "rendered todos, and a visible validation error for empty submissions. It "
            "may call same-origin /todos routes through a Vite dev-server proxy, or use "
            "a Vite-exposed API base URL such as VITE_API_BASE_URL. The Vite app must "
            "run with npm run dev -- --host 127.0.0.1 --port <port>. Provide a "
            "Makefile with run and test targets and README instructions for running the "
            "API and the React app with npm run dev and npm run build. Do not require "
            "the evaluation harness to install npm dependencies on the host."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_REACT_VITE_FRONTEND_MAX_SESSIONS", "24")),
        checks=(
            stateful_todo_api_check,
            react_vite_frontend_check,
            react_vite_container_build_check,
            react_vite_browser_integration_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
            file_contains_check("usage docs", "README.md", "npm run dev"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)


@pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_DEPLOYMENT") != "1",
    reason="deployment live evaluation requires DEVLAB_LIVE_DEPLOYMENT=1",
)
def test_live_deployable_web_api_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="live-deployable-web-api-happy-path",
        title="Live deployable web API happy path",
        system_spec=(
            "Build a small Python standard-library JSON HTTP API for todo items. "
            "Do not use third-party runtime dependencies. Implement the server in "
            "src/todo_api/server.py and make it runnable from the repository root with "
            "python -m src.todo_api.server --port <port>. It must expose GET /health "
            'returning HTTP 200 with JSON {"status": "ok"}, POST /todos with JSON '
            '{"title": "..."} to create an in-memory item and return a top-level '
            "JSON object with integer id and title fields using any successful 2xx status, "
            'GET /todos to return HTTP 200 with JSON {"todos": [<items>]}, DELETE '
            '/todos/{id} to return HTTP 200 with JSON {"deleted": <id>}. POST /todos '
            "must return a 4xx client error "
            "for invalid JSON, missing title, empty title, or blank title. Return 404 "
            "for unknown routes. Also provide a Makefile with run and test targets and a "
            ".gitignore covering Python caches and local runtime artifacts. The defined "
            "API endpoints are "
            f"{', '.join(f'`{endpoint}`' for endpoint in TODO_API_ENDPOINTS)}. The README "
            "must contain an endpoint reference listing every defined method/path pair "
            "using the exact notation above. Deployment support is explicitly in "
            "scope: provide project-owned local container deployment artifacts and "
            "verification instructions, but do not deploy to production. The Makefile "
            "must include an image target named exactly `image` and a deployment "
            "artifact verification target named exactly `deployment-check`."
        ),
        deployment_spec=(
            "Deployment target: local OCI-compatible container image for the todo API. "
            "Deployment environment: local developer machine or CI runner with an "
            "OCI-compatible image builder such as Podman or Docker. Required project "
            "artifacts: Containerfile, Makefile target named exactly `image` to build "
            "the image, Makefile target named exactly `deployment-check` to verify "
            "deployment artifacts without requiring production deployment, and "
            "README deployment instructions. The container must run the API on port 8000 "
            "using python -m src.todo_api.server --port 8000."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_DEPLOYMENT_MAX_SESSIONS", "22")),
        checks=(
            stateful_todo_api_check,
            deployment_artifacts_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
            endpoint_documentation_check(TODO_API_ENDPOINTS),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)

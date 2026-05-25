from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.evaluations.harness import (
    EvaluationDiagnostics,
    EvaluationScenario,
    command_check,
    command_fails_check,
    file_contains_check,
    run_live_evaluation,
)
from tests.evaluations.scripted_agents import (
    deployment_artifacts_check,
    stateful_todo_api_check,
    static_frontend_check,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_EVALS") != "1",
    reason="live DevLab evaluations require DEVLAB_LIVE_EVALS=1",
)


def _live_agent_config() -> Path | None:
    agent_config = os.environ.get("DEVLAB_LIVE_AGENTS_TOML")
    return Path(agent_config) if agent_config else None


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


def _assert_live_diagnostics(
    tmp_path: Path,
    scenario: EvaluationScenario,
    diagnostics: EvaluationDiagnostics,
) -> None:
    diagnostics_path = tmp_path / ".devlab/evaluations" / f"{scenario.id}.json"
    failure_context = (
        f"target_root={tmp_path}\n"
        f"diagnostics={diagnostics_path}\n"
        f"agent_logs={tmp_path / '.devlab/logs/agents'}\n"
        f"diagnostics_json={diagnostics_path.read_text()}"
    )
    assert diagnostics.completed is True, failure_context
    assert diagnostics.exit_code == 0, failure_context
    assert all(check["passed"] for check in diagnostics.checks), failure_context
    assert diagnostics.roles, failure_context
    assert isinstance(diagnostics.tasks["total"], int)
    assert diagnostics.tasks["total"] >= 1, failure_context
    assert diagnostics.quality["correctness_passed"] is True, failure_context


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
            "returning JSON {\"status\": \"ok\"}, POST /todos with JSON "
            "{\"title\": \"...\"} to create an in-memory item and return a top-level "
            "JSON object with integer id and title fields, GET /todos to return "
            "JSON {\"todos\": [<items>]}, DELETE /todos/{id} to delete an item and return "
            "JSON {\"deleted\": <id>}. POST /todos must return a 4xx client error "
            "for invalid JSON, missing title, empty title, or blank title. Return 404 "
            "for unknown routes. "
            "Also provide a Makefile "
            "with run and test targets, a README documenting usage and endpoints, and a "
            ".gitignore covering Python caches and local runtime artifacts."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_STATEFUL_MAX_SESSIONS", "18")),
        checks=(
            stateful_todo_api_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
            file_contains_check("usage docs", "README.md", "GET /todos"),
            file_contains_check("python cache gitignore", ".gitignore", "__pycache__/"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)


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
            "--port <port>. It must expose GET /health returning JSON "
            "{\"status\": \"ok\"}, POST /todos with JSON {\"title\": \"...\"} to "
            "create an in-memory item and return a top-level JSON object with integer "
            "id and title fields, GET /todos to return JSON {\"todos\": [<items>]}, "
            "DELETE /todos/{id} to delete an item and return JSON {\"deleted\": <id>}. "
            "POST /todos must return a 4xx client error for invalid JSON, missing "
            "title, empty title, or blank title. Return 404 for unknown routes. Place "
            "frontend files at exactly static/index.html, static/app.js, and "
            "static/styles.css. The UI must list todos, add todos, delete todos, display "
            "validation errors, and call the API routes directly. Provide a Makefile "
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
            "returning JSON {\"status\": \"ok\"}, POST /todos with JSON "
            "{\"title\": \"...\"} to create an in-memory item and return a top-level "
            "JSON object with integer id and title fields, GET /todos to return "
            "JSON {\"todos\": [<items>]}, DELETE /todos/{id} to delete an item and return "
            "JSON {\"deleted\": <id>}. POST /todos must return a 4xx client error "
            "for invalid JSON, missing title, empty title, or blank title. Return 404 "
            "for unknown routes. Also provide a Makefile with run and test targets, "
            "a README documenting usage and endpoints, and a .gitignore covering Python "
            "caches and local runtime artifacts. Deployment support is explicitly in "
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
            file_contains_check("usage docs", "README.md", "GET /todos"),
        ),
    )

    diagnostics = _run_live_scenario(tmp_path, scenario)

    _assert_live_diagnostics(tmp_path, scenario, diagnostics)

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import cast
from urllib.parse import quote

from devlab.agents import AgentInvocation
from devlab.findings import FileFindingTracker
from devlab.task_tracker import FileTaskTracker
from tests.evaluations.checks import CheckResult
from tests.evaluations.generated_products import (
    write_calculator,
    write_compose_deployment_artifacts,
    write_container_deployment_artifacts,
    write_http_app,
    write_stateful_todo_api,
    write_static_frontend,
)
from tests.helpers import (
    approve_review_task,
    complete_acceptance,
    handoff,
    write_task,
)


class CalculatorScriptedAgent:
    def __init__(self, *, reject_first_review: bool = False, require_smoke_finding: bool = False):
        self.reject_first_review = reject_first_review
        self.require_smoke_finding = require_smoke_finding
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self._record(invocation)
        role = invocation.role_name
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python calculator CLI with add and subtract subcommands.\n"
            )
        elif role == "planner":
            self._planner(invocation.root)
        elif role == "developer":
            self._developer(invocation.root)
        elif role == "reviewer":
            self._reviewer(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        role = invocation.role_name
        if role == "reviewer" and self._should_reject_review():
            self.review_rejections += 1
            return handoff(role, open_issues="- Subtraction is missing from the calculator CLI.")
        if role == "integrator" and self._should_raise_smoke_finding(invocation.root):
            return handoff(
                role,
                open_issues="- The calculator milestone lacks a committed smoke test artifact.",
            )
        if role == "planner" and finding_exists(invocation.root, "F0001"):
            return handoff(role, addressed="- F0001: T0002")
        return handoff(role)

    def _record(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))

    def _planner(self, root: Path) -> None:
        if finding_exists(root, "F0001"):
            _project_plan(root).write_text(
                "# Project Plan\n\n"
                "## M1: Calculator CLI\n"
                "- T0001: Implement calculator CLI\n"
                "- T0002: Add calculator smoke test\n"
            )
            write_task(
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
        write_task(root, "T0001", "Implement calculator CLI", "M1")

    def _developer(self, root: Path) -> None:
        task = FileTaskTracker(root).select_next_development_task()
        assert task is not None
        complete_acceptance(root, task.id)
        if task.id == "T0001":
            complete = not self.reject_first_review or self.role_counts["developer"] > 1
            write_calculator(root, include_subtract=complete)
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
        approve_review_task(root)

    def _should_reject_review(self) -> bool:
        return self.reject_first_review and self.role_counts.get("reviewer", 0) == 1

    def _should_raise_smoke_finding(self, root: Path) -> bool:
        return (
            self.require_smoke_finding
            and self.role_counts.get("integrator", 0) == 1
            and not finding_exists(root, "F0001")
        )


class HttpApiScriptedAgent:
    def __init__(self) -> None:
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
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\nBuild a tiny stdlib HTTP API with health and echo endpoints.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: HTTP API\n"
                "- T0001: Implement stdlib HTTP API\n"
            )
            write_task(invocation.root, "T0001", "Implement stdlib HTTP API", "M1")
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            write_http_app(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class DeploymentWebApiScriptedAgent:
    def __init__(self) -> None:
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
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python JSON todo API with project-owned deployment "
                "artifacts. The deployment path uses a Containerfile, Makefile targets, "
                "and README verification instructions.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Deployable todo API\n"
                "- T0001: Implement stateful todo API\n"
                "- T0002: Add container deployment artifacts\n"
            )
            write_task(invocation.root, "T0001", "Implement stateful todo API", "M1")
            write_task(
                invocation.root,
                "T0002",
                "Add container deployment artifacts",
                "M1",
                depends_on=["T0001"],
                domain="deployment",
            )
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            if task.id == "T0001":
                write_stateful_todo_api(invocation.root)
            elif task.id == "T0002":
                write_container_deployment_artifacts(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class ComposeDeploymentScriptedAgent:
    def __init__(self) -> None:
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
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python JSON todo API with Docker Compose deployment "
                "artifacts, project-owned local deploy/teardown commands, a smoke-test "
                "script, and README deployment instructions.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Compose deployable todo API\n"
                "- T0001: Implement stateful todo API\n"
                "- T0002: Add Compose deployment artifacts\n"
            )
            write_task(invocation.root, "T0001", "Implement stateful todo API", "M1")
            write_task(
                invocation.root,
                "T0002",
                "Add Compose deployment artifacts",
                "M1",
                depends_on=["T0001"],
                domain="deployment",
            )
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            if task.id == "T0001":
                write_stateful_todo_api(invocation.root)
                write_container_deployment_artifacts(invocation.root)
            elif task.id == "T0002":
                write_compose_deployment_artifacts(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class StaticFrontendScriptedAgent:
    def __init__(self) -> None:
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
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python JSON todo API and a static vanilla HTML/CSS/JS "
                "frontend in static/. The frontend calls the API endpoints directly and "
                "has no frontend package manager or build step.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Static todo application\n"
                "- T0001: Implement todo API and static frontend\n"
            )
            write_task(invocation.root, "T0001", "Implement todo API and static frontend", "M1")
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            write_stateful_todo_api(invocation.root)
            write_static_frontend(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class StatefulWebApiScriptedAgent:
    def __init__(self) -> None:
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
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python JSON HTTP API for in-memory todo items. "
                "Expose health, create, list, and delete endpoints plus project-owned "
                "run/test commands and usage documentation.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Stateful todo API\n"
                "- T0001: Implement stateful todo API\n"
            )
            write_task(invocation.root, "T0001", "Implement stateful todo API", "M1")
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            write_stateful_todo_api(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


def http_api_check() -> CheckResult:
    return CheckResult("http api", False, "check must be called with root")


def stdlib_http_api_check(root: Path) -> CheckResult:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "app.py", "--port", str(port)],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_http(port, "/health")
        health = _http_get(port, "/health")
        echo = _http_get(port, f"/echo?value={quote('hello')}")
        passed = health == "ok" and echo == "hello"
        return CheckResult(
            "http api endpoints",
            passed,
            "" if passed else f"health={health!r} echo={echo!r}",
        )
    except Exception as exc:
        stdout, stderr = process.communicate(timeout=1) if process.poll() is not None else ("", "")
        return CheckResult(
            "http api endpoints",
            False,
            f"{exc}; stdout={stdout[-500:]!r} stderr={stderr[-500:]!r}",
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def static_frontend_check(root: Path) -> CheckResult:
    required_files = ["static/index.html", "static/app.js", "static/styles.css"]
    missing = [relative for relative in required_files if not (root / relative).exists()]
    if missing:
        return CheckResult("static frontend", False, "missing " + ", ".join(missing))

    index = (root / "static/index.html").read_text()
    script = (root / "static/app.js").read_text()
    styles = (root / "static/styles.css").read_text()
    readme = (root / "README.md").read_text() if (root / "README.md").exists() else ""

    missing_snippets: list[str] = []
    for snippet in ("app.js", "styles.css"):
        if snippet not in index:
            missing_snippets.append(f"index.html lacks {snippet!r}")
    lower_index = index.lower()
    if "<form" not in lower_index:
        missing_snippets.append("index.html lacks a todo form")
    if "<input" not in lower_index:
        missing_snippets.append("index.html lacks a todo title input")
    if "<ul" not in lower_index and "<ol" not in lower_index:
        missing_snippets.append("index.html lacks a todo list container")
    for snippet in ("/todos", "POST", "DELETE"):
        if snippet not in script:
            missing_snippets.append(f"app.js lacks {snippet!r}")
    if "error" not in index.lower() and "error" not in script.lower():
        missing_snippets.append("frontend lacks error display/handling")
    if not styles.strip():
        missing_snippets.append("styles.css is empty")
    if "static" not in readme.lower() or "frontend" not in readme.lower():
        missing_snippets.append("README.md lacks static frontend instructions")
    frontend_build_files = [
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "vite.config.js",
        "vite.config.ts",
    ]
    for relative_path in frontend_build_files:
        if (root / relative_path).exists():
            missing_snippets.append(f"unexpected frontend build artifact {relative_path}")

    message = "; ".join(missing_snippets)
    if missing_snippets:
        message += (
            "; expected vanilla static frontend contract: static/index.html, "
            "static/app.js, static/styles.css, API calls for GET/POST/DELETE /todos, "
            "error display, and README usage instructions"
        )
    return CheckResult("static frontend", not missing_snippets, message)


def compose_deployment_artifacts_check(root: Path) -> CheckResult:
    required = {
        "compose.yaml": ["services:", "todo-api", "build:", "ports:"],
        ".env.example": ["IMAGE=", "PORT="],
        "Makefile": ["compose-check:", "deploy-local:", "undeploy-local:"],
        "scripts/smoke-test.sh": ["/health"],
    }
    missing: list[str] = []
    for relative_path, snippets in required.items():
        path = root / relative_path
        if not path.exists():
            missing.append(f"missing {relative_path}")
            continue
        text = path.read_text()
        for snippet in snippets:
            if snippet not in text:
                missing.append(f"{relative_path} lacks {snippet!r}")
    documentation = _documentation_text(root)
    for snippet in ("make compose-check", "make deploy-local", "make undeploy-local"):
        if snippet not in documentation:
            missing.append(f"deployment documentation lacks {snippet!r}")
    lower_documentation = documentation.lower()
    if "compose" not in lower_documentation or (
        "teardown" not in lower_documentation and "tear it down" not in lower_documentation
    ):
        missing.append("deployment documentation lacks Compose and teardown instructions")
    message = "; ".join(missing)
    if missing:
        message += (
            "; expected Compose deployment contract: compose.yaml, .env.example, "
            "Makefile targets `compose-check`, `deploy-local`, and `undeploy-local`, "
            "scripts/smoke-test.sh, and build/verify/teardown documentation"
        )
    return CheckResult("compose deployment artifacts", not missing, message)


def deployment_artifacts_check(root: Path) -> CheckResult:
    required = {
        "Containerfile": ["FROM", "COPY src", "src.todo_api.server", "EXPOSE 8000"],
        "Makefile": ["image:", "deployment-check:", "Containerfile"],
    }
    missing: list[str] = []
    for relative_path, snippets in required.items():
        path = root / relative_path
        if not path.exists():
            missing.append(f"missing {relative_path}")
            continue
        text = path.read_text()
        for snippet in snippets:
            if snippet not in text:
                missing.append(f"{relative_path} lacks {snippet!r}")
    documentation = _documentation_text(root)
    for snippet in ("make image", "make deployment-check"):
        if snippet not in documentation:
            missing.append(f"deployment documentation lacks {snippet!r}")
    if "deployment" not in documentation.lower():
        missing.append("deployment documentation lacks a deployment section")
    message = "; ".join(missing)
    if missing:
        message += (
            "; expected exact deployment contract: Containerfile, Makefile targets "
            "`image` and `deployment-check`, and documentation references to both commands"
        )
    return CheckResult("deployment artifacts", not missing, message)


def _documentation_text(root: Path) -> str:
    paths = [root / "README.md"]
    docs_dir = root / "docs"
    if docs_dir.exists():
        paths.extend(sorted(docs_dir.rglob("*.md")))
    return "\n\n".join(path.read_text() for path in paths if path.exists())


def stateful_todo_api_check(root: Path) -> CheckResult:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "src.todo_api.server", "--port", str(port)],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_http(port, "/health")
        health_status, health = _http_json(port, "GET", "/health")
        if health_status != 200 or health != {"status": "ok"}:
            return CheckResult("stateful todo api", False, f"bad health: {health_status} {health}")

        invalid_status, invalid = _http_json(port, "POST", "/todos", {"title": ""})
        create_status, created = _http_json(port, "POST", "/todos", {"title": "write eval"})
        created_item = cast(dict[str, object], created) if isinstance(created, dict) else {}
        todo_id = created_item.get("id")
        if not (
            create_status == 201
            and isinstance(todo_id, int)
            and created_item.get("title") == "write eval"
        ):
            return CheckResult(
                "stateful todo api",
                False,
                "POST /todos must return a top-level JSON object with integer "
                f"id and title fields; status={create_status} body={created!r}",
            )

        list_status, listed = _http_json(port, "GET", "/todos")
        delete_status, deleted = _http_json(port, "DELETE", f"/todos/{todo_id}")
        final_status, final = _http_json(port, "GET", "/todos")
        missing_status, _ = _http_json(port, "GET", "/missing")

        passed = (
            400 <= invalid_status < 500
            and list_status == 200
            and _todo_collection(listed) == [created_item]
            and delete_status == 200
            and deleted == {"deleted": todo_id}
            and final_status == 200
            and _todo_collection(final) == []
            and missing_status == 404
        )
        details = (
            f"empty-title={invalid_status}:{invalid!r} create={create_status}:{created!r} "
            f"list={list_status}:{listed!r} delete={delete_status}:{deleted!r} "
            f"final={final_status}:{final!r} missing={missing_status}"
        )
        return CheckResult("stateful todo api", passed, "" if passed else details)
    except Exception as exc:
        stdout, stderr = process.communicate(timeout=1) if process.poll() is not None else ("", "")
        return CheckResult(
            "stateful todo api",
            False,
            f"{exc}; stdout={stdout[-500:]!r} stderr={stderr[-500:]!r}",
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def _todo_collection(payload: object) -> list[object] | None:
    if isinstance(payload, dict):
        payload_dict = cast(dict[str, object], payload)
        todos = payload_dict.get("todos")
        if isinstance(todos, list):
            return cast(list[object], todos)
    return None



def finding_exists(root: Path, finding_id: str) -> bool:
    return any(finding.id == finding_id for finding in FileFindingTracker(root).list_findings())


def _wait_for_http(port: int, path: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            _http_get(port, path)
            return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"server did not respond on port {port}")


def _http_get(port: int, path: str) -> str:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode()
        if response.status != 200:
            raise AssertionError(f"GET {path} returned {response.status}: {body!r}")
        return body
    finally:
        connection.close()


def _http_json(
    port: int,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, object]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read().decode()
        return response.status, json.loads(response_body)
    finally:
        connection.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _design_plan(root: Path) -> Path:
    return root / ".devlab/plans/design-plan.md"


def _project_plan(root: Path) -> Path:
    return root / ".devlab/plans/project-plan.md"

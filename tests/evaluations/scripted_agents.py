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
from tests.evaluations.harness import CheckResult
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


def write_calculator(root: Path, *, include_subtract: bool) -> None:
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


def write_http_app(root: Path) -> None:
    root.joinpath("app.py").write_text(
        "from __future__ import annotations\n\n"
        "import argparse\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "from urllib.parse import parse_qs, urlparse\n\n\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        parsed = urlparse(self.path)\n"
        "        if parsed.path == '/health':\n"
        "            self._text(200, 'ok')\n"
        "            return\n"
        "        if parsed.path == '/echo':\n"
        "            value = parse_qs(parsed.query).get('value', [''])[0]\n"
        "            self._text(200, value)\n"
        "            return\n"
        "        self._text(404, 'not found')\n\n"
        "    def log_message(self, format, *args):\n"
        "        return\n\n"
        "    def _text(self, status, body):\n"
        "        data = body.encode()\n"
        "        self.send_response(status)\n"
        "        self.send_header('Content-Type', 'text/plain')\n"
        "        self.send_header('Content-Length', str(len(data)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(data)\n\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--port', type=int, required=True)\n"
        "    args = parser.parse_args()\n"
        "    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)\n"
        "    server.serve_forever()\n\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )


def write_stateful_todo_api(root: Path) -> None:
    source_dir = root / "src/todo_api"
    tests_dir = root / "tests"
    source_dir.mkdir(parents=True)
    tests_dir.mkdir()
    (source_dir / "__init__.py").write_text("")
    (source_dir / "server.py").write_text(
        "from __future__ import annotations\n\n"
        "import argparse\n"
        "import json\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "from urllib.parse import urlparse\n\n\n"
        "class TodoStore:\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "        self.next_id = 1\n\n"
        "    def create(self, title):\n"
        "        item = {'id': self.next_id, 'title': title, 'completed': False}\n"
        "        self.next_id += 1\n"
        "        self.items.append(item)\n"
        "        return item\n\n"
        "    def delete(self, item_id):\n"
        "        before = len(self.items)\n"
        "        self.items = [item for item in self.items if item['id'] != item_id]\n"
        "        return len(self.items) != before\n\n\n"
        "store = TodoStore()\n\n\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        path = urlparse(self.path).path\n"
        "        if path == '/health':\n"
        "            self._json(200, {'status': 'ok'})\n"
        "            return\n"
        "        if path == '/todos':\n"
        "            self._json(200, {'todos': store.items})\n"
        "            return\n"
        "        self._json(404, {'error': 'not found'})\n\n"
        "    def do_POST(self):\n"
        "        if urlparse(self.path).path != '/todos':\n"
        "            self._json(404, {'error': 'not found'})\n"
        "            return\n"
        "        try:\n"
        "            length = int(self.headers.get('Content-Length', '0'))\n"
        "            payload = json.loads(self.rfile.read(length).decode())\n"
        "        except (TypeError, ValueError, json.JSONDecodeError):\n"
        "            self._json(400, {'error': 'invalid json'})\n"
        "            return\n"
        "        title = payload.get('title')\n"
        "        if not isinstance(title, str) or not title.strip():\n"
        "            self._json(400, {'error': 'title is required'})\n"
        "            return\n"
        "        self._json(201, store.create(title.strip()))\n\n"
        "    def do_DELETE(self):\n"
        "        path = urlparse(self.path).path\n"
        "        prefix = '/todos/'\n"
        "        if not path.startswith(prefix):\n"
        "            self._json(404, {'error': 'not found'})\n"
        "            return\n"
        "        try:\n"
        "            item_id = int(path.removeprefix(prefix))\n"
        "        except ValueError:\n"
        "            self._json(400, {'error': 'invalid id'})\n"
        "            return\n"
        "        if not store.delete(item_id):\n"
        "            self._json(404, {'error': 'not found'})\n"
        "            return\n"
        "        self._json(200, {'deleted': item_id})\n\n"
        "    def log_message(self, format, *args):\n"
        "        return\n\n"
        "    def _json(self, status, payload):\n"
        "        data = json.dumps(payload).encode()\n"
        "        self.send_response(status)\n"
        "        self.send_header('Content-Type', 'application/json')\n"
        "        self.send_header('Content-Length', str(len(data)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(data)\n\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--port', type=int, required=True)\n"
        "    args = parser.parse_args()\n"
        "    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)\n"
        "    server.serve_forever()\n\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    (tests_dir / "smoke_todo_api.py").write_text(
        "# Smoke behavior is verified by the DevLab evaluation harness.\n"
        "# Run the service with: python -m src.todo_api.server --port 8000\n"
    )
    (root / "Makefile").write_text(
        ".PHONY: run test\n"
        "PORT ?= 8000\n\n"
        "run:\n"
        "\tpython -m src.todo_api.server --port $(PORT)\n\n"
        "test:\n"
        "\tpython tests/smoke_todo_api.py\n"
    )
    (root / "README.md").write_text(
        "# Todo API\n\n"
        "Run with `make run PORT=8000`. Validate with `make test`.\n\n"
        "Endpoints: `GET /health`, `GET /todos`, `POST /todos`, "
        "and `DELETE /todos/{id}`. Data is in-memory only.\n"
    )
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n.venv/\n")


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

        invalid_status, _ = _http_json(port, "POST", "/todos", {"title": ""})
        create_status, created = _http_json(port, "POST", "/todos", {"title": "write eval"})
        list_status, listed = _http_json(port, "GET", "/todos")
        created_item = cast(dict[str, object], created) if isinstance(created, dict) else {}
        todo_id = created_item.get("id")
        delete_status, deleted = _http_json(port, "DELETE", f"/todos/{todo_id}")
        final_status, final = _http_json(port, "GET", "/todos")
        missing_status, _ = _http_json(port, "GET", "/missing")

        passed = (
            invalid_status == 400
            and create_status == 201
            and created_item.get("title") == "write eval"
            and created_item.get("completed") is False
            and list_status == 200
            and listed == {"todos": [created]}
            and delete_status == 200
            and deleted == {"deleted": todo_id}
            and final_status == 200
            and final == {"todos": []}
            and missing_status == 404
        )
        details = (
            f"invalid={invalid_status} create={create_status}:{created!r} "
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

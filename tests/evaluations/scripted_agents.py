from __future__ import annotations

import http.client
import socket
import subprocess
import sys
import time
from pathlib import Path
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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _design_plan(root: Path) -> Path:
    return root / ".devlab/plans/design-plan.md"


def _project_plan(root: Path) -> Path:
    return root / ".devlab/plans/project-plan.md"

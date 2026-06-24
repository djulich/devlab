from __future__ import annotations

import dataclasses
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast
from urllib.parse import quote


@dataclasses.dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str = ""


BlackBoxCheck = Callable[[Path], CheckResult]


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


def command_fails_check(name: str, args: Sequence[str]) -> BlackBoxCheck:
    def check(root: Path) -> CheckResult:
        result = subprocess.run(
            [sys.executable, *args],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        passed = result.returncode != 0
        return CheckResult(
            name=name,
            passed=passed,
            message="" if passed else f"expected nonzero exit; stdout={result.stdout!r}",
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


def optional_docker_compose_config_check(
    name: str = "docker compose config",
    *,
    enable_env: str = "DEVLAB_EVAL_DEPLOYMENT_TOOLS",
    timeout: int = 10,
) -> BlackBoxCheck:
    def check(root: Path) -> CheckResult:
        if os.environ.get(enable_env) != "1":
            return CheckResult(
                name,
                True,
                f"skipped: set {enable_env}=1 to run docker compose config",
            )
        if shutil.which("docker") is None:
            return CheckResult(name, True, "skipped: 'docker' is not on PATH; unverified")
        if not (root / "compose.yaml").exists():
            return CheckResult(name, False, "missing compose.yaml")
        result = subprocess.run(
            ["docker", "compose", "config"],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        passed = result.returncode == 0
        return CheckResult(
            name,
            passed,
            ""
            if passed
            else f"docker compose config exited {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    return check


def optional_make_target_check(
    name: str,
    target: str,
    *,
    enable_env: str = "DEVLAB_EVAL_DEPLOYMENT_TOOLS",
    timeout: int = 10,
) -> BlackBoxCheck:
    """Run a target-owned Make target only when explicitly enabled.

    Missing host tools are reported as skipped/unverified successful checks so the
    normal suite stays structural and never installs prerequisites.
    """

    def check(root: Path) -> CheckResult:
        if os.environ.get(enable_env) != "1":
            return CheckResult(name, True, f"skipped: set {enable_env}=1 to run make {target}")
        if shutil.which("make") is None:
            return CheckResult(name, True, "skipped: 'make' is not on PATH; unverified")
        if not (root / "Makefile").exists():
            return CheckResult(name, False, "missing Makefile")
        result = subprocess.run(
            ["make", target],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        passed = result.returncode == 0
        return CheckResult(
            name,
            passed,
            ""
            if passed
            else f"make {target} exited {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    return check


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


def react_vite_frontend_check(root: Path) -> CheckResult:
    required_files = ["package.json", "index.html"]
    missing = [relative for relative in required_files if not (root / relative).exists()]
    if missing:
        return CheckResult("react vite frontend", False, "missing " + ", ".join(missing))

    main_path = _first_existing(
        root,
        ("src/main.jsx", "src/main.tsx", "src/main.js", "src/main.ts"),
    )
    app_path = _first_existing(
        root,
        ("src/App.jsx", "src/App.tsx", "src/App.js", "src/App.ts"),
    )
    css_path = _first_existing(root, ("src/App.css", "src/index.css", "src/style.css"))

    missing_snippets: list[str] = []
    if main_path is None:
        missing_snippets.append("missing src/main React entrypoint")
    if app_path is None:
        missing_snippets.append("missing src/App component")
    if css_path is None:
        missing_snippets.append("missing src CSS file")

    package_path = root / "package.json"
    try:
        package = json.loads(package_path.read_text())
    except json.JSONDecodeError as exc:
        return CheckResult("react vite frontend", False, f"package.json is invalid JSON: {exc}")
    if not isinstance(package, dict):
        return CheckResult("react vite frontend", False, "package.json must be a JSON object")

    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        missing_snippets.append("package.json lacks scripts")
    else:
        for script_name in ("dev", "build"):
            value = scripts.get(script_name)
            if not isinstance(value, str) or "vite" not in value:
                missing_snippets.append(f"package.json scripts.{script_name} must run vite")

    dependencies: dict[str, object] = {}
    for key in ("dependencies", "devDependencies"):
        value = package.get(key)
        if isinstance(value, dict):
            dependencies.update(value)
    for package_name in ("@vitejs/plugin-react", "vite", "react", "react-dom"):
        if package_name not in dependencies:
            missing_snippets.append(f"package.json lacks dependency {package_name!r}")

    index = (root / "index.html").read_text()
    if "/src/main" not in index and "src/main" not in index:
        missing_snippets.append("index.html lacks script reference to src/main")
    if "id=\"root\"" not in index and "id='root'" not in index:
        missing_snippets.append("index.html lacks root mount element")

    source_text = _frontend_source_text(root, (main_path, app_path, css_path))
    if "createRoot" not in source_text:
        missing_snippets.append("React entrypoint lacks createRoot")
    for snippet in ("/todos", "POST", "DELETE"):
        if snippet not in source_text:
            missing_snippets.append(f"React source lacks {snippet!r}")
    if "error" not in source_text.lower():
        missing_snippets.append("React source lacks error display/handling")
    if "form" not in source_text.lower() or "input" not in source_text.lower():
        missing_snippets.append("React source lacks todo form/input")
    documentation = _documentation_text(root)
    if "npm run dev" not in documentation or "npm run build" not in documentation:
        missing_snippets.append("documentation lacks npm run dev/build instructions")

    message = "; ".join(missing_snippets)
    if missing_snippets:
        message += (
            "; expected React/Vite frontend contract: package.json with Vite scripts "
            "and React/Vite dependencies, index.html root mount, src/main entrypoint, "
            "src/App component, CSS, direct GET/POST/DELETE /todos calls, error "
            "handling, and README usage instructions"
        )
    return CheckResult("react vite frontend", not missing_snippets, message)


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


def _first_existing(root: Path, relative_paths: Sequence[str]) -> Path | None:
    for relative_path in relative_paths:
        path = root / relative_path
        if path.exists():
            return path
    return None


def _frontend_source_text(root: Path, paths: Sequence[Path | None]) -> str:
    source = [path.read_text() for path in paths if path is not None and path.exists()]
    src_dir = root / "src"
    if src_dir.exists():
        source.extend(
            path.read_text()
            for path in sorted(src_dir.rglob("*"))
            if path.is_file() and path.suffix in {".js", ".jsx", ".ts", ".tsx", ".css"}
        )
    return "\n".join(source)


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
            200 <= create_status < 300
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

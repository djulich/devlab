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

TODO_API_ENDPOINTS = (
    "GET /health",
    "POST /todos",
    "GET /todos",
    "DELETE /todos/{id}",
)


def toolchain_command_check(
    name: str,
    command: Sequence[str],
    *,
    expected_stdout: str | None = None,
    timeout: int = 60,
) -> BlackBoxCheck:
    """Run a target-owned toolchain command as a required black-box check."""

    def check(root: Path) -> CheckResult:
        result = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        output_matches = expected_stdout is None or result.stdout.strip() == expected_stdout
        passed = result.returncode == 0 and output_matches
        return CheckResult(
            name,
            passed,
            ""
            if passed
            else f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    return check


def built_executable_output_check(
    name: str,
    build_directory: str,
    executable_name: str,
    args: Sequence[str],
    *,
    expected_stdout: str,
    timeout: int = 60,
) -> BlackBoxCheck:
    """Run one unambiguously named executable beneath a generated build tree."""

    def check(root: Path) -> CheckResult:
        build_root = root / build_directory
        candidates = sorted(
            path
            for path in build_root.rglob(executable_name)
            if path.is_file() and os.access(path, os.X_OK)
        )
        relative_candidates = [str(path.relative_to(root)) for path in candidates]
        if len(candidates) != 1:
            return CheckResult(
                name,
                False,
                f"expected exactly one executable named {executable_name!r} beneath "
                f"{build_directory}; found {relative_candidates!r}",
            )
        command = [str(candidates[0]), *args]
        try:
            result = subprocess.run(
                command,
                cwd=root,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except OSError as error:
            return CheckResult(name, False, f"could not run {relative_candidates[0]}: {error}")
        passed = result.returncode == 0 and result.stdout.strip() == expected_stdout
        return CheckResult(
            name,
            passed,
            ""
            if passed
            else f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    return check


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


def endpoint_documentation_check(
    endpoints: Sequence[str],
    *,
    relative_path: str = "README.md",
) -> BlackBoxCheck:
    """Require explicit method/path documentation for every defined endpoint."""

    def check(root: Path) -> CheckResult:
        path = root / relative_path
        if not path.exists():
            return CheckResult("endpoint documentation", False, f"missing {relative_path}")
        text = path.read_text()
        missing = [endpoint for endpoint in endpoints if endpoint not in text]
        return CheckResult(
            "endpoint documentation",
            not missing,
            ""
            if not missing
            else f"{relative_path} lacks defined endpoints: {', '.join(missing)}",
        )

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
    lower_script = script.lower()
    for snippet in ("/todos", "post", "delete"):
        if snippet not in lower_script:
            missing_snippets.append(f"app.js lacks case-insensitive {snippet!r}")
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
    css_path = next(
        (path for path in sorted((root / "src").rglob("*.css")) if path.is_file()),
        None,
    )

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
    if 'id="root"' not in index and "id='root'" not in index:
        missing_snippets.append("index.html lacks root mount element")

    source_text = _frontend_source_text(root, (main_path, app_path, css_path))
    if "createRoot" not in source_text:
        missing_snippets.append("React entrypoint lacks createRoot")
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
            "src/App component, CSS, error handling, and README usage instructions; "
            "endpoint behavior is verified by the browser integration check"
        )
    return CheckResult("react vite frontend", not missing_snippets, message)


def react_vite_container_build_check(
    root: Path,
    *,
    runtime: str = "podman",
    image: str = "node:22-alpine",
    timeout: int = 240,
) -> CheckResult:
    if shutil.which(runtime) is None:
        return CheckResult(
            "react vite container build",
            False,
            f"{runtime!r} is not on PATH; install/configure {runtime} to run this live check",
        )
    if not (root / "package.json").exists():
        return CheckResult("react vite container build", False, "missing package.json")

    script = (
        "set -eu; "
        "mkdir -p /tmp/work; "
        "cp -R /workspace/. /tmp/work; "
        "cd /tmp/work; "
        "if [ -f package-lock.json ]; then npm ci; else npm install; fi; "
        "npm run build"
    )
    command = [
        runtime,
        "run",
        "--rm",
        "--pull=missing",
        "--security-opt",
        "label=disable",
        "-v",
        f"{root.resolve()}:/workspace:ro",
        image,
        "sh",
        "-lc",
        script,
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    passed = result.returncode == 0
    return CheckResult(
        "react vite container build",
        passed,
        ""
        if passed
        else (
            f"{runtime} build exited {result.returncode}; target was mounted read-only "
            "and copied to container-local /tmp/work before npm install/build; "
            f"stdout={result.stdout[-1000:]!r} stderr={result.stderr[-1000:]!r}"
        ),
    )


def react_vite_browser_integration_check(
    root: Path,
    *,
    runtime: str = "podman",
    image: str = "mcr.microsoft.com/playwright:v1.53.1-jammy",
    timeout: int = 360,
) -> CheckResult:
    if shutil.which(runtime) is None:
        return CheckResult(
            "react vite browser integration",
            False,
            f"{runtime!r} is not on PATH; install/configure {runtime} to run this live check",
        )
    if not (root / "package.json").exists():
        return CheckResult("react vite browser integration", False, "missing package.json")

    script = _react_vite_browser_integration_script()
    command = [
        runtime,
        "run",
        "--rm",
        "--pull=missing",
        "--security-opt",
        "label=disable",
        "-v",
        f"{root.resolve()}:/workspace:ro",
        image,
        "bash",
        "-lc",
        script,
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    passed = result.returncode == 0
    return CheckResult(
        "react vite browser integration",
        passed,
        ""
        if passed
        else (
            f"{runtime} browser integration exited {result.returncode}; target was mounted "
            "read-only at /workspace and copied to container-local /tmp/work before npm "
            "install, API startup, Vite startup, and browser flow; "
            f"stdout={result.stdout[-2000:]!r} stderr={result.stderr[-2000:]!r}"
        ),
    )


def _react_vite_browser_integration_script() -> str:
    return r"""
set -eu
mkdir -p /tmp/work
cp -R /workspace/. /tmp/work
cd /tmp/work
dump_diagnostics() {
  status=$?
  echo "devlab browser integration failed during container command; exit=$status"
  for file in /tmp/devlab-api.out /tmp/devlab-api.err /tmp/devlab-vite.out /tmp/devlab-vite.err; do
    if [ -f "$file" ]; then
      echo "--- $file tail ---"
      tail -n 80 "$file" || true
    fi
  done
}
trap dump_diagnostics ERR
if [ -f package-lock.json ]; then npm ci; else npm install; fi
npm run build
# The Playwright image provides matching browser binaries and system libraries,
# but deliberately does not include the Playwright Node package.
npm install --prefix /tmp/devlab-browser-tools --no-save playwright@1.53.1
PYTHON_BIN="$(command -v python3 || command -v python)"
API_PORT=8765
VITE_PORT=5173
"$PYTHON_BIN" -m src.todo_api.server --port "$API_PORT" \
  > /tmp/devlab-api.out 2> /tmp/devlab-api.err &
API_PID=$!
VITE_PID=
cleanup() {
  if [ -n "${VITE_PID:-}" ]; then kill "$VITE_PID" 2>/dev/null || true; fi
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT
node <<'NODE'
const http = require('http');
const waitFor = (url, label) => new Promise((resolve, reject) => {
  const deadline = Date.now() + 10000;
  const poll = () => {
    http.get(url, (res) => {
      res.resume();
      if (res.statusCode >= 200 && res.statusCode < 500) {
        resolve();
      } else if (Date.now() > deadline) {
        reject(new Error(`${label} returned ${res.statusCode}`));
      } else {
        setTimeout(poll, 100);
      }
    }).on('error', (error) => {
      if (Date.now() > deadline) reject(new Error(`${label} did not start: ${error.message}`));
      else setTimeout(poll, 100);
    });
  };
  poll();
});
waitFor('http://127.0.0.1:8765/health', 'API').catch((error) => {
  console.error(error.message);
  process.exit(1);
});
NODE
API_BASE_URL="http://127.0.0.1:$API_PORT" \
  VITE_API_BASE_URL="http://127.0.0.1:$API_PORT" \
  npm run dev -- --host 127.0.0.1 --port "$VITE_PORT" \
  > /tmp/devlab-vite.out 2> /tmp/devlab-vite.err &
VITE_PID=$!
node <<'NODE'
const http = require('http');
const waitFor = (url, label) => new Promise((resolve, reject) => {
  const deadline = Date.now() + 15000;
  const poll = () => {
    http.get(url, (res) => {
      res.resume();
      if (res.statusCode >= 200 && res.statusCode < 500) {
        resolve();
      } else if (Date.now() > deadline) {
        reject(new Error(`${label} returned ${res.statusCode}`));
      } else {
        setTimeout(poll, 100);
      }
    }).on('error', (error) => {
      if (Date.now() > deadline) reject(new Error(`${label} did not start: ${error.message}`));
      else setTimeout(poll, 100);
    });
  };
  poll();
});
waitFor('http://127.0.0.1:5173/', 'Vite').catch((error) => {
  console.error(error.message);
  process.exit(1);
});
NODE
NODE_PATH=/tmp/devlab-browser-tools/node_modules node <<'NODE'
const { chromium } = require('playwright');

const diagnostics = {
  console: [],
  pageErrors: [],
  step: 'launch',
};

async function visibleText(page) {
  return (await page.locator('body').innerText({ timeout: 3000 })).trim();
}

async function todoInput(page) {
  const named = page.getByRole('textbox', { name: /todo|title/i }).first();
  if (await named.count()) return named;
  return page.locator('input, textarea').first();
}

async function submitButton(page) {
  const named = page.getByRole('button', { name: /add|submit|create/i }).first();
  if (await named.count()) return named;
  return page.locator('button, input[type=submit]').first();
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error') {
      diagnostics.console.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => diagnostics.pageErrors.push(error.message));
  try {
    diagnostics.step = 'open app';
    await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' });
    await page.locator('body').waitFor({ state: 'visible', timeout: 5000 });

    diagnostics.step = 'find form controls';
    const input = await todoInput(page);
    const add = await submitButton(page);
    await input.waitFor({ state: 'visible', timeout: 5000 });
    await add.waitFor({ state: 'visible', timeout: 5000 });

    diagnostics.step = 'empty submit validation';
    const beforeEmptySubmit = await visibleText(page);
    await add.click();
    await page.waitForTimeout(500);
    const afterEmptySubmit = await visibleText(page);
    if (
      afterEmptySubmit === beforeEmptySubmit ||
      !/error|required|invalid|empty|blank|title|enter|provide/i.test(afterEmptySubmit)
    ) {
      throw new Error(
        `empty submit did not show a visible validation error; body=${afterEmptySubmit}`
      );
    }

    diagnostics.step = 'add todo';
    await input.fill('write browser eval');
    await add.click();
    await page.getByText('write browser eval', { exact: false }).waitFor({
      state: 'visible',
      timeout: 5000,
    });

    diagnostics.step = 'delete todo';
    const item = page.getByText('write browser eval', { exact: false }).first();
    const deleteButton = page.getByRole('button', { name: /delete|remove/i }).first();
    if (!(await deleteButton.count())) {
      throw new Error('no visible delete/remove button found for todo item');
    }
    await deleteButton.click();
    await item.waitFor({ state: 'hidden', timeout: 5000 });

    diagnostics.step = 'runtime errors';
    if (diagnostics.pageErrors.length) {
      throw new Error(`browser page errors: ${diagnostics.pageErrors.join(' | ')}`);
    }
    const severeConsole = diagnostics.console.filter((line) => !/favicon/i.test(line));
    if (severeConsole.length) {
      throw new Error(`browser console errors: ${severeConsole.join(' | ')}`);
    }
  } catch (error) {
    console.error(JSON.stringify({ ...diagnostics, error: error.message }, null, 2));
    throw error;
  } finally {
    await browser.close();
  }
}

main().catch(() => process.exit(1));
NODE
"""


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

        invalid_statuses = {
            "invalid-json": _http_request_status(port, "POST", "/todos", b"{"),
            "missing-title": _http_request_status(port, "POST", "/todos", b"{}"),
            "empty-title": _http_request_status(port, "POST", "/todos", b'{"title": ""}'),
            "blank-title": _http_request_status(port, "POST", "/todos", b'{"title": "   "}'),
        }
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
            all(400 <= status < 500 for status in invalid_statuses.values())
            and list_status == 200
            and _todo_collection(listed) == [created_item]
            and delete_status == 200
            and deleted == {"deleted": todo_id}
            and final_status == 200
            and _todo_collection(final) == []
            and missing_status == 404
        )
        details = (
            f"invalid-create={invalid_statuses!r} create={create_status}:{created!r} "
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


def _http_request_status(port: int, method: str, path: str, body: bytes) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request(
            method,
            path,
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

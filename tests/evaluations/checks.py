from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


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

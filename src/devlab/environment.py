from __future__ import annotations

import dataclasses
import json
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from devlab._files import atomic_write_text

ENVIRONMENT_LOG_DIR = ".devlab/logs/environment"


@dataclasses.dataclass(frozen=True)
class EnvironmentTimeouts:
    pre_session: int = 300
    setup: int = 600
    post_session: int = 300


@dataclasses.dataclass(frozen=True)
class EnvironmentConfig:
    managed_roles: tuple[str, ...] = ()
    pre_session: tuple[str, ...] = ()
    setup: tuple[str, ...] = ()
    post_session: tuple[str, ...] = ()
    timeouts: EnvironmentTimeouts = EnvironmentTimeouts()


@dataclasses.dataclass(frozen=True)
class EnvironmentCommandError(RuntimeError):
    phase: str
    command: str
    return_code: int | None
    log_path: Path

    def __str__(self) -> str:
        code = "timed out" if self.return_code is None else f"exit code {self.return_code}"
        return (
            f"environment {self.phase} command failed ({code}): {self.command!r}; "
            f"see {self.log_path}"
        )


@dataclasses.dataclass(frozen=True)
class ValidationCommandResult:
    command: str
    outcome: str
    return_code: int | None
    log_path: str
    duration_seconds: float
    output_summary: str


@dataclasses.dataclass(frozen=True)
class ValidationRun:
    source: str
    outcome: str
    commands: tuple[ValidationCommandResult, ...]
    role: str
    session_id: str
    context_kind: str
    context_id: str
    repository_revision: str
    recovery_of: str


def run_validation_commands(
    root: Path,
    *,
    role_name: str,
    task_id: str | None = None,
    milestone_id: str | None = None,
    session_id: str,
    commands: tuple[str, ...],
    source: str = "none",
    timeout: int = 600,
    recovery_of: str = "",
) -> ValidationRun:
    """Run target-owned validation and persist compact observed outcomes."""
    if (task_id is None) == (milestone_id is None):
        raise ValueError("validation requires exactly one task_id or milestone_id")
    context_kind = "task" if task_id is not None else "milestone"
    context_id = task_id or milestone_id or ""
    revision = _repository_revision(root)
    results: list[ValidationCommandResult] = []
    overall = "not_configured" if not commands else "passed"
    for index, command in enumerate(commands, start=1):
        log_path = root / ENVIRONMENT_LOG_DIR / f"{session_id}_{role_name}_validation_{index}.log"
        stored_log_path = log_path.relative_to(root).as_posix()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            result = subprocess.run(
                command,
                cwd=root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            log_path.write_text(
                f"command: {command}\noutcome: timeout\n\n"
                + _decode_output(exc.stdout)
                + "\n"
                + _decode_output(exc.stderr)
            )
            output = _decode_output(exc.stdout) + "\n" + _decode_output(exc.stderr)
            results.append(
                ValidationCommandResult(
                    command,
                    "timeout",
                    None,
                    stored_log_path,
                    round(time.monotonic() - started, 3),
                    _output_summary(output),
                )
            )
            overall = "timeout"
            break
        except OSError as exc:
            log_path.write_text(f"command: {command}\noutcome: infrastructure_error\n{exc}\n")
            results.append(
                ValidationCommandResult(
                    command,
                    "infrastructure_error",
                    None,
                    stored_log_path,
                    round(time.monotonic() - started, 3),
                    _output_summary(str(exc)),
                )
            )
            overall = "infrastructure_error"
            break
        outcome = (
            "passed"
            if result.returncode == 0
            else ("missing_tool" if result.returncode == 127 else "failed")
        )
        log_path.write_text(
            f"command: {command}\noutcome: {outcome}\nexit_code: {result.returncode}\n\n"
            f"## stdout\n{result.stdout}\n## stderr\n{result.stderr}"
        )
        results.append(
            ValidationCommandResult(
                command,
                outcome,
                result.returncode,
                stored_log_path,
                round(time.monotonic() - started, 3),
                _output_summary(result.stdout + "\n" + result.stderr),
            )
        )
        if outcome != "passed":
            overall = outcome
            break
    run = ValidationRun(
        source,
        overall,
        tuple(results),
        role_name,
        session_id,
        context_kind,
        context_id,
        revision,
        recovery_of,
    )
    if task_id is not None:
        record_path = root / ".devlab/verification/tasks" / task_id / f"{session_id}.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(record_path, json.dumps(dataclasses.asdict(run), indent=2) + "\n")
    return run


def _repository_revision(root: Path) -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _output_summary(output: str, limit: int = 1000) -> str:
    normalized = "\n".join(line.rstrip() for line in output.strip().splitlines())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


class EnvironmentManager:
    def __init__(self, root: Path, config: EnvironmentConfig | None = None) -> None:
        self.root = root
        self.config = config or EnvironmentConfig()

    def manages_role(self, role_name: str) -> bool:
        return role_name in self.config.managed_roles

    def pre_session(self, role_name: str) -> None:
        self._run_phase(
            role_name, "pre_session", self.config.pre_session, self.config.timeouts.pre_session
        )

    def setup(self, role_name: str) -> None:
        self._run_phase(role_name, "setup", self.config.setup, self.config.timeouts.setup)

    def post_session(self, role_name: str) -> None:
        self._run_phase(
            role_name, "post_session", self.config.post_session, self.config.timeouts.post_session
        )

    def _run_phase(
        self,
        role_name: str,
        phase: str,
        commands: tuple[str, ...],
        timeout: int,
    ) -> None:
        for index, command in enumerate(commands, start=1):
            log_path = self._log_path(role_name, phase, index)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            header = (
                f"# Environment {phase}\n"
                f"role: {role_name}\n"
                f"command: {command}\n"
                f"cwd: {self.root}\n\n"
            )
            try:
                result = subprocess.run(
                    command,
                    cwd=self.root,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = _decode_output(exc.stdout)
                stderr = _decode_output(exc.stderr)
                log_path.write_text(
                    header
                    + f"timed out after {timeout}s\n\n"
                    + "## stdout\n"
                    + stdout
                    + "\n## stderr\n"
                    + stderr
                )
                raise EnvironmentCommandError(phase, command, None, log_path) from exc

            log_path.write_text(
                header
                + f"exit_code: {result.returncode}\n\n"
                + "## stdout\n"
                + result.stdout
                + "\n## stderr\n"
                + result.stderr
            )
            if result.returncode != 0:
                raise EnvironmentCommandError(phase, command, result.returncode, log_path)

    def _log_path(self, role_name: str, phase: str, index: int) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        return self.root / ENVIRONMENT_LOG_DIR / f"{timestamp}_{role_name}_{phase}_{index}.log"


def _string_tuple(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"environment config field {key!r} must be a list of strings")
    return tuple(value)


def _int_value(data: object, key: str, default: int) -> int:
    if not isinstance(data, Mapping):
        return default
    values = cast("Mapping[str, object]", data)
    value = values.get(key)
    if value is None:
        return default
    if not isinstance(value, int):
        raise ValueError(f"environment timeout {key!r} must be an integer")
    return value


def _decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value

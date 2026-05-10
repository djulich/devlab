from __future__ import annotations

import dataclasses
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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

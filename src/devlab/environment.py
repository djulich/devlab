from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from devlab._files import atomic_write_text

ENVIRONMENT_LOG_DIR = ".devlab/logs/environment"

TEST_SERVICE_RECORDS = ".devlab/test-services"
TEST_SERVICE_PRIVATE = ".devlab/local/test-services"
SERVICE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


class TestServiceError(ValueError):
    """An infrastructure failure; never a product validation failure."""

    __test__ = False


@dataclasses.dataclass(frozen=True)
class TestService:
    __test__ = False
    id: str
    summary: str
    host_checks: tuple[str, ...]
    ensure: str
    check: str
    destroy: str
    exports: tuple[str, ...]
    ensure_timeout_seconds: int = 180
    check_timeout_seconds: int = 30
    destroy_timeout_seconds: int = 60

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.definition(), sort_keys=True).encode()).hexdigest()

    def definition(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def parse_test_service(service_id: str, value: object) -> TestService:
    if not SERVICE_ID_RE.fullmatch(service_id) or not isinstance(value, dict):
        raise TestServiceError("invalid test service declaration")
    data = dict(value)
    if data.pop("id", service_id) != service_id:
        raise TestServiceError("test service definition ID mismatch")
    allowed = {field.name for field in dataclasses.fields(TestService)} - {"id"}
    if set(data) - allowed:
        raise TestServiceError(f"unknown fields for test service {service_id}")
    for key in ("ensure", "check", "destroy"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise TestServiceError(f"test service {service_id} requires {key}")
    for key in ("host_checks", "exports"):
        items = data.get(key, [])
        if (
            not isinstance(items, (list, tuple))
            or any(not isinstance(item, str) or not item.strip() for item in items)
            or len(set(items)) != len(items)
        ):
            raise TestServiceError(f"invalid {key} for test service {service_id}")
        data[key] = tuple(items)
    for key in ("ensure_timeout_seconds", "check_timeout_seconds", "destroy_timeout_seconds"):
        if key in data and (type(data[key]) is not int or data[key] <= 0):
            raise TestServiceError(f"invalid {key} for test service {service_id}")
    data.setdefault("summary", service_id)
    if not isinstance(data["summary"], str):
        raise TestServiceError("test service summary must be text")
    for name in data["exports"]:
        if (
            not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name)
            or name
            in {
                "PATH",
                "HOME",
                "SHELL",
                "ENV",
                "BASH_ENV",
                "IFS",
                "CDPATH",
                "TMPDIR",
                "NODE_OPTIONS",
                "RUBYOPT",
                "PERL5OPT",
                "ZDOTDIR",
            }
            or name.startswith(("DEVLAB_", "LD_", "DYLD_", "PYTHON", "BASH", "GIT_"))
        ):
            raise TestServiceError(f"reserved or invalid test service export: {name}")
    return TestService(id=service_id, **data)


@dataclasses.dataclass(frozen=True)
class TestServiceReference:
    __test__ = False
    service: TestService
    required_for: tuple[str, ...]


def _safe_service_path(root: Path, path: Path) -> None:
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise TestServiceError("test service paths must not contain symlinks")


def prepare_test_service_private(root: Path) -> Path:
    """Validate the ignored private area before creating any secret artifacts."""
    root = root.resolve()
    path = root / TEST_SERVICE_PRIVATE
    _safe_service_path(root, path)
    tracked = subprocess.run(
        ["git", "ls-files", "--", ".devlab/local"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", f"{TEST_SERVICE_PRIVATE}/probe"],
        cwd=root,
        check=False,
    )
    if tracked.stdout or ignored.returncode != 0:
        raise TestServiceError("run 'devlab test-service init' to prepare ignored private storage")
    for directory in (root / ".devlab/local", path):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not directory.is_dir() or directory.stat().st_mode & 0o077:
            raise TestServiceError("test service private directories require mode 0700")
    return path


@contextmanager
def test_service_lock(root: Path) -> Iterator[None]:
    """Hold workspace service ownership through the complete dependent operation."""
    try:
        import fcntl
    except ImportError as exc:
        raise TestServiceError("managed test services require POSIX file locking") from exc

    private = prepare_test_service_private(root)
    path = private / "lock"
    _safe_service_path(root.resolve(), path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TestServiceError("test services are in use by another DevLab operation") from exc
        yield
    finally:
        os.close(fd)


class FileTestServiceTracker:
    """Own service records and the tightly coupled target-command protocol.

    Call mutations through Workspace.test_services() while holding the workspace
    service lock. Stored definitions never authorize their own execution.
    """

    def __init__(
        self, root: Path, on_change: Callable[[dict[str, Any]], None] | None = None
    ) -> None:
        self.root = root.resolve()
        self.on_change = on_change

    def read(self, service_id: str) -> dict[str, Any] | None:
        if not SERVICE_ID_RE.fullmatch(service_id):
            raise TestServiceError("invalid test service ID")
        path = self.root / TEST_SERVICE_RECORDS / f"{service_id}.json"
        _safe_service_path(self.root, path)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or data.get("schema") != 1:
                raise ValueError
            service = parse_test_service(service_id, data["definition"])
            if data.get("digest") != service.digest or data.get("service") != service_id:
                raise ValueError
            if not re.fullmatch(r"[0-9a-f]{32}", data["instance"]):
                raise ValueError
            if data.get("state") not in {
                "preparing",
                "ready",
                "failed",
                "destroying",
                "cleanup_failed",
                "destroyed",
            } or not isinstance(data.get("workspace"), str):
                raise ValueError
        except (ValueError, KeyError, TypeError) as exc:
            raise TestServiceError(f"invalid test service record: {service_id}") from exc
        return data

    def list_records(self) -> list[dict[str, Any]]:
        directory = self.root / TEST_SERVICE_RECORDS
        _safe_service_path(self.root, directory)
        return [
            record
            for path in sorted(directory.glob("*.json"))
            if (record := self.read(path.stem)) is not None
        ]

    def _write(self, record: dict[str, Any], state: str, outcome: str = "") -> None:
        record.update(state=state, outcome=outcome, updated_at=datetime.now(UTC).isoformat())
        path = self.root / TEST_SERVICE_RECORDS / f"{record['service']}.json"
        _safe_service_path(self.root, path)
        atomic_write_text(path, json.dumps(record, sort_keys=True, indent=2) + "\n")
        if self.on_change is not None:
            self.on_change(record)

    def _private(self, record: dict[str, Any]) -> Path:
        path = prepare_test_service_private(self.root) / record["instance"]
        _safe_service_path(self.root, path)
        path.mkdir(mode=0o700, exist_ok=True)
        if path.stat().st_mode & 0o077:
            raise TestServiceError("test service private directory requires mode 0700")
        return path

    def _exports(self, service: TestService, record: dict[str, Any]) -> dict[str, str]:
        path = self._private(record) / "result.json"
        _safe_service_path(self.root, path)
        try:
            mode = path.stat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o077 or path.stat().st_size > 65536:
                raise ValueError
            data = json.loads(path.read_text())
            if set(data) != {"schema", "instance", "environment"} or data["schema"] != 1:
                raise ValueError
            exports = data["environment"]
            if data["instance"] != record["instance"] or not isinstance(exports, dict):
                raise ValueError
            if set(exports) != set(service.exports) or any(
                not isinstance(value, str) or "\0" in value for value in exports.values()
            ):
                raise ValueError
            return exports
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise TestServiceError(f"invalid or missing private exports for {service.id}") from exc

    def _command(
        self,
        service: TestService,
        record: dict[str, Any],
        phase: str,
        command: str,
        timeout: int,
        exports: Mapping[str, str] | None = None,
    ) -> bool:
        private = self._private(record)
        log = private / f"{phase}-{uuid.uuid4().hex}.log"
        environment = {
            **os.environ,
            **(exports or {}),
            "DEVLAB_TEST_SERVICE_ID": service.id,
            "DEVLAB_TEST_SERVICE_INSTANCE": record["instance"],
            "DEVLAB_TEST_SERVICE_STATE_DIR": str(private),
            "DEVLAB_TEST_SERVICE_RESULT": str(private / "result.json"),
        }
        started = time.monotonic()
        fd = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as output:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=self.root,
                env=environment,
                stdout=output,
                stderr=output,
                start_new_session=True,
                umask=0o077,
            )
            try:
                return process.wait(timeout=timeout) == 0
            except subprocess.TimeoutExpired as exc:
                raise TestServiceError(f"test service {service.id} {phase} timed out") from exc
            finally:
                # Also reap descendants left behind by an exited shell. Container
                # side effects remain owned by the durable instance identity.
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=1)
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=1)
                record["duration_seconds"] = round(
                    record.get("duration_seconds", 0) + time.monotonic() - started, 3
                )

    def ensure(self, service: TestService) -> dict[str, str]:
        record = self.read(service.id)
        if record is not None:
            if record["workspace"] != str(self.root):
                raise TestServiceError(f"test service {service.id} belongs to another workspace")
            if record["state"] != "destroyed" and record["digest"] != service.digest:
                raise TestServiceError(
                    f"test service {service.id} changed; clean up original first"
                )
            if record["state"] in {"destroying", "cleanup_failed"}:
                raise TestServiceError(f"retry 'devlab test-service cleanup {service.id}' first")
        if record is None or record["state"] == "destroyed":
            record = {
                "schema": 1,
                "workspace": str(self.root),
                "service": service.id,
                "instance": uuid.uuid4().hex,
                "definition": service.definition(),
                "digest": service.digest,
            }
            self._write(record, "preparing")
        try:
            for command in service.host_checks:
                if not self._command(
                    service, record, "host_check", command, service.check_timeout_seconds
                ):
                    raise TestServiceError(f"test service {service.id} host prerequisite failed")
            if record["state"] == "ready":
                try:
                    exports = self._exports(service, record)
                except TestServiceError:
                    exports = None
                if exports is not None and self._command(
                    service,
                    record,
                    "check",
                    service.check,
                    service.check_timeout_seconds,
                    exports,
                ):
                    self._write(record, "ready", "reused")
                    return exports
            self._write(record, "preparing")
            result = self._private(record) / "result.json"
            _safe_service_path(self.root, result)
            result.unlink(missing_ok=True)
            if not self._command(
                service, record, "ensure", service.ensure, service.ensure_timeout_seconds
            ):
                raise TestServiceError(f"test service {service.id} ensure failed")
            exports = self._exports(service, record)
            if not self._command(
                service, record, "check", service.check, service.check_timeout_seconds, exports
            ):
                raise TestServiceError(f"test service {service.id} readiness failed")
            self._write(record, "ready")
            return exports
        except (OSError, TestServiceError, KeyboardInterrupt) as exc:
            self._write(
                record,
                "failed",
                str(exc) if isinstance(exc, TestServiceError) else type(exc).__name__,
            )
            raise

    def cleanup(self, service: TestService) -> None:
        record = self.read(service.id)
        if record is None or record["state"] == "destroyed":
            return
        if record["workspace"] != str(self.root) or record["digest"] != service.digest:
            raise TestServiceError(
                "cleanup requires the original workspace and service definition"
            )
        self._write(record, "destroying")
        try:
            if not self._command(
                service, record, "destroy", service.destroy, service.destroy_timeout_seconds
            ):
                raise TestServiceError(f"test service {service.id} cleanup failed")
            (self._private(record) / "result.json").unlink(missing_ok=True)
            self._write(record, "destroyed")
        except (OSError, TestServiceError, KeyboardInterrupt) as exc:
            self._write(
                record,
                "cleanup_failed",
                str(exc) if isinstance(exc, TestServiceError) else type(exc).__name__,
            )
            raise


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
    infrastructure_error: str = ""


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
    environ: Mapping[str, str] | None = None,
    command_environments: tuple[Mapping[str, str], ...] | None = None,
    infrastructure_error: str = "",
) -> ValidationRun:
    """Run target-owned validation and persist compact observed outcomes."""
    if (task_id is None) == (milestone_id is None):
        raise ValueError("validation requires exactly one task_id or milestone_id")
    if command_environments is not None and len(command_environments) != len(commands):
        raise ValueError("validation command environments must match commands")
    context_kind = "task" if task_id is not None else "milestone"
    context_id = task_id or milestone_id or ""
    revision = _repository_revision(root)
    results: list[ValidationCommandResult] = []
    overall = "not_configured" if not commands else "passed"
    if infrastructure_error:
        overall = "infrastructure_error"
    for index, command in enumerate(() if infrastructure_error else commands, start=1):
        log_path = root / ENVIRONMENT_LOG_DIR / f"{session_id}_{role_name}_validation_{index}.log"
        stored_log_path = log_path.relative_to(root).as_posix()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            result = subprocess.run(
                command,
                cwd=root,
                env={
                    **os.environ,
                    **(
                        command_environments[index - 1]
                        if command_environments is not None
                        else environ or {}
                    ),
                },
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
        infrastructure_error,
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
        self.environ: dict[str, str] = {}

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
                    env={**os.environ, **self.environ},
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

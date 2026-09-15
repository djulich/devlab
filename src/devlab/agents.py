from __future__ import annotations

import dataclasses
import os
import selectors
import shlex
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Literal, Protocol, cast

AgentFailureKind = Literal[
    "none", "nonzero_exit", "timeout", "missing_executable", "provider_error"
]
AgentTimeoutKind = Literal["inactivity", "max_duration"]

_MONITOR_INTERVAL_SECONDS = 0.1
_TERMINATION_GRACE_SECONDS = 1.0
_FINAL_DRAIN_SECONDS = 0.5


class ProviderError(Exception):
    """Raised by agent providers for anticipated operational failures."""


@dataclasses.dataclass(frozen=True)
class AgentResult:
    return_code: int
    failure_kind: AgentFailureKind = "none"
    message: str = ""
    role_name: str = ""
    command: tuple[str, ...] = ()
    timeout_seconds: int | None = None
    inactivity_timeout_seconds: int | None = None
    max_session_duration_seconds: int | None = None
    timeout_kind: AgentTimeoutKind | None = None
    inactive_seconds_at_stop: float | None = None
    stdout_log: Path | None = None
    stderr_log: Path | None = None
    duration_seconds: float | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure_kind == "none" and self.return_code == 0


@dataclasses.dataclass(frozen=True)
class AgentInvocation:
    root: Path
    role_name: str
    system_prompt: str
    session_prompt: str
    invocation_id: str
    stdout_log: Path
    stderr_log: Path
    environment: Mapping[str, str] = dataclasses.field(default_factory=dict)


AgentCall = AgentInvocation


class AgentProvider(Protocol):
    """Invokes an agent for one DevLab role session."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult: ...


@dataclasses.dataclass(frozen=True)
class CliAgentProvider:
    """Template-based CLI agent provider.

    ``argv`` identifies the agent executable and command prefix. ``args`` are
    appended after the command prefix and may contain ``{system_prompt}``,
    ``{session_prompt}``, ``{role_name}``, and provider configuration
    placeholders. The provider does not add prompt arguments by default; callers
    must put prompt placeholders in ``args`` or provide ``stdin_template``. If
    ``stdin_template`` is set, rendered text is sent to stdin.

    This supports Claude- and Pi-style invocations, both of which can use
    ``--system-prompt`` plus a positional session prompt. It also supports
    Codex-style stdin invocation through ``stdin_template``. This keeps the
    orchestrator independent from the concrete CLI shape.
    """

    argv: tuple[str, ...]
    args: tuple[str, ...] = ()
    stdin_template: str | None = None
    template_values: Mapping[str, str] = dataclasses.field(default_factory=dict)
    timeout_seconds: int | None = None
    inactivity_timeout_seconds: int | None = None
    max_session_duration_seconds: int | None = None

    @classmethod
    def from_command(
        cls,
        command: str,
        *,
        args: Sequence[str] = (),
        stdin_template: str | None = None,
        template_values: Mapping[str, str] | None = None,
        timeout_seconds: int | None = None,
        inactivity_timeout_seconds: int | None = None,
        max_session_duration_seconds: int | None = None,
    ) -> CliAgentProvider:
        maximum = max_session_duration_seconds
        if maximum is None:
            maximum = timeout_seconds
        return cls(
            argv=tuple(shlex.split(command)),
            args=tuple(args),
            stdin_template=stdin_template,
            template_values=dict(template_values or {}),
            timeout_seconds=maximum,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
            max_session_duration_seconds=maximum,
        )

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        values = {
            **self.template_values,
            "role_name": invocation.role_name,
            "system_prompt": invocation.system_prompt,
            "session_prompt": invocation.session_prompt,
        }
        command = [*self.argv, *_render_args(self.args, values, redact_prompts=True)]
        cmd = [*self.argv, *_render_args(self.args, values)]
        stdin: str | None = None
        if self.stdin_template is not None:
            stdin = self.stdin_template.format_map(values)
        if self.max_session_duration_seconds is not None:
            deadline = datetime.now(UTC) + timedelta(seconds=self.max_session_duration_seconds)
            limit_context = (
                "\n\n## DevLab session limit\n\n"
                f"Maximum provider duration: {self.max_session_duration_seconds} seconds. "
                f"Advisory wall-clock deadline: {deadline.isoformat()}. "
                "DevLab enforces this with a monotonic timer. Complete validation and "
                "submit the handoff before the limit; you cannot extend it."
            )
            values["session_prompt"] += limit_context
            cmd = [*self.argv, *_render_args(self.args, values)]
            if self.stdin_template is not None:
                stdin = self.stdin_template.format_map(values)

        invocation.stdout_log.parent.mkdir(parents=True, exist_ok=True)
        invocation.stderr_log.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            with (
                invocation.stdout_log.open("w") as stdout_handle,
                invocation.stderr_log.open("w") as stderr_handle,
            ):
                result = _run_process(
                    cmd,
                    cwd=str(invocation.root),
                    env={**os.environ, **invocation.environment},
                    input=stdin,
                    text=stdin is not None,
                    check=False,
                    timeout=self.timeout_seconds,
                    inactivity_timeout_seconds=self.inactivity_timeout_seconds,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                )
        except FileNotFoundError as exc:
            duration = time.monotonic() - started
            _append_diagnostic(invocation.stderr_log, f"agent command not found: {exc.filename!r}")
            return AgentResult(
                return_code=127,
                failure_kind="missing_executable",
                message=f"agent command not found: {exc.filename!r}",
                role_name=invocation.role_name,
                command=tuple(command),
                timeout_seconds=self.timeout_seconds,
                inactivity_timeout_seconds=self.inactivity_timeout_seconds,
                max_session_duration_seconds=self.max_session_duration_seconds,
                stdout_log=invocation.stdout_log,
                stderr_log=invocation.stderr_log,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired as exc:
            duration = getattr(exc, "elapsed_seconds", time.monotonic() - started)
            timeout_kind = cast("AgentTimeoutKind", getattr(exc, "timeout_kind", "max_duration"))
            inactive_seconds = getattr(exc, "inactive_seconds", None)
            if timeout_kind == "inactivity":
                message = (
                    "Session stopped: provider output inactive for "
                    f"{self.inactivity_timeout_seconds} seconds."
                )
            else:
                message = (
                    "Session stopped: maximum duration of "
                    f"{self.max_session_duration_seconds} seconds reached."
                )
            if inactive_seconds is not None:
                message += f" Last provider output: {inactive_seconds:.1f} seconds ago."
            message += f" Elapsed session time: {duration:.1f} seconds."
            _append_diagnostic(
                invocation.stderr_log,
                message,
            )
            return AgentResult(
                return_code=124,
                failure_kind="timeout",
                message=message,
                role_name=invocation.role_name,
                command=tuple(command),
                timeout_seconds=self.timeout_seconds,
                inactivity_timeout_seconds=self.inactivity_timeout_seconds,
                max_session_duration_seconds=self.max_session_duration_seconds,
                timeout_kind=timeout_kind,
                inactive_seconds_at_stop=inactive_seconds,
                stdout_log=invocation.stdout_log,
                stderr_log=invocation.stderr_log,
                duration_seconds=duration,
            )
        except OSError as exc:
            duration = time.monotonic() - started
            _append_diagnostic(invocation.stderr_log, f"agent provider error: {exc}")
            return AgentResult(
                return_code=1,
                failure_kind="provider_error",
                message=f"agent provider error: {exc}",
                role_name=invocation.role_name,
                command=tuple(command),
                timeout_seconds=self.timeout_seconds,
                inactivity_timeout_seconds=self.inactivity_timeout_seconds,
                max_session_duration_seconds=self.max_session_duration_seconds,
                stdout_log=invocation.stdout_log,
                stderr_log=invocation.stderr_log,
                duration_seconds=duration,
            )

        duration = time.monotonic() - started
        failure_kind: AgentFailureKind = "none" if result.returncode == 0 else "nonzero_exit"
        message = "" if result.returncode == 0 else f"agent exited with code {result.returncode}"
        return AgentResult(
            return_code=result.returncode,
            failure_kind=failure_kind,
            message=message,
            role_name=invocation.role_name,
            command=tuple(command),
            timeout_seconds=self.timeout_seconds,
            inactivity_timeout_seconds=self.inactivity_timeout_seconds,
            max_session_duration_seconds=self.max_session_duration_seconds,
            stdout_log=invocation.stdout_log,
            stderr_log=invocation.stderr_log,
            duration_seconds=duration,
        )


@dataclasses.dataclass(frozen=True)
class _ProcessResult:
    returncode: int


class _MonitoredTimeout(subprocess.TimeoutExpired):
    def __init__(
        self,
        cmd: Sequence[str],
        timeout: float,
        *,
        timeout_kind: AgentTimeoutKind,
        inactive_seconds: float,
        elapsed_seconds: float,
    ) -> None:
        super().__init__(cmd, timeout)
        self.timeout_kind = timeout_kind
        self.inactive_seconds = inactive_seconds
        self.elapsed_seconds = elapsed_seconds


def _run_process(
    cmd: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    input: str | None,
    text: bool,
    check: bool,
    timeout: int | None,
    inactivity_timeout_seconds: int | None,
    stdout: IO[str],
    stderr: IO[str],
) -> _ProcessResult:
    """Run a provider while draining both byte streams and enforcing deadlines."""
    del text, check
    started = time.monotonic()
    process = subprocess.Popen(
        list(cmd),
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )
    last_output = started
    selector = selectors.DefaultSelector()
    streams: dict[int, tuple[IO[bytes], IO[str]]] = {}
    stdin_bytes = input.encode() if input is not None else b""
    stdin_offset = 0
    try:
        assert process.stdout is not None
        assert process.stderr is not None
        for source, target in ((process.stdout, stdout), (process.stderr, stderr)):
            os.set_blocking(source.fileno(), False)
            selector.register(source, selectors.EVENT_READ)
            streams[source.fileno()] = (source, target)
        if process.stdin is not None:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)

        while True:
            return_code = process.poll()
            now = time.monotonic()
            if return_code is not None:
                _drain_after_exit(selector, streams, stdout, stderr)
                return _ProcessResult(return_code)
            timeout_kind = _expired_timeout_kind(
                now,
                started=started,
                last_output=last_output,
                inactivity_timeout_seconds=inactivity_timeout_seconds,
                max_session_duration_seconds=timeout,
            )
            if timeout_kind is not None:
                inactive_seconds = now - last_output
                _terminate_owned_process(process, selector, streams, stdout, stderr)
                configured = (
                    inactivity_timeout_seconds if timeout_kind == "inactivity" else timeout
                )
                assert configured is not None
                raise _MonitoredTimeout(
                    cmd,
                    configured,
                    timeout_kind=timeout_kind,
                    inactive_seconds=inactive_seconds,
                    elapsed_seconds=now - started,
                )

            wait = _next_wait(
                now,
                started=started,
                last_output=last_output,
                inactivity_timeout_seconds=inactivity_timeout_seconds,
                max_session_duration_seconds=timeout,
            )
            for key, _events in selector.select(wait):
                stream = cast("IO[bytes]", key.fileobj)
                if process.stdin is not None and stream is process.stdin:
                    try:
                        written = os.write(process.stdin.fileno(), stdin_bytes[stdin_offset:])
                    except BrokenPipeError:
                        written = 0
                        stdin_offset = len(stdin_bytes)
                    else:
                        stdin_offset += written
                    if stdin_offset >= len(stdin_bytes):
                        selector.unregister(process.stdin)
                        process.stdin.close()
                    continue
                source, target = streams[stream.fileno()]
                try:
                    chunk = os.read(source.fileno(), 65536)
                except BlockingIOError:
                    continue
                if chunk:
                    _write_output(target, chunk)
                    last_output = time.monotonic()
                else:
                    fd = source.fileno()
                    selector.unregister(source)
                    source.close()
                    streams.pop(fd, None)
    except BaseException:
        if process.poll() is None:
            _terminate_owned_process(process, selector, streams, stdout, stderr)
        raise
    finally:
        selector.close()


def _expired_timeout_kind(
    now: float,
    *,
    started: float,
    last_output: float,
    inactivity_timeout_seconds: int | None,
    max_session_duration_seconds: int | None,
) -> AgentTimeoutKind | None:
    deadlines: list[tuple[float, AgentTimeoutKind]] = []
    if inactivity_timeout_seconds is not None:
        deadlines.append((last_output + inactivity_timeout_seconds, "inactivity"))
    if max_session_duration_seconds is not None:
        deadlines.append((started + max_session_duration_seconds, "max_duration"))
    expired = [item for item in deadlines if now >= item[0]]
    if not expired:
        return None
    # The earlier deadline wins; an exact tie favors the absolute legacy limit.
    return min(expired, key=lambda item: (item[0], item[1] != "max_duration"))[1]


def _next_wait(
    now: float,
    *,
    started: float,
    last_output: float,
    inactivity_timeout_seconds: int | None,
    max_session_duration_seconds: int | None,
) -> float:
    deadlines = []
    if inactivity_timeout_seconds is not None:
        deadlines.append(last_output + inactivity_timeout_seconds)
    if max_session_duration_seconds is not None:
        deadlines.append(started + max_session_duration_seconds)
    if not deadlines:
        return _MONITOR_INTERVAL_SECONDS
    return max(0.0, min(_MONITOR_INTERVAL_SECONDS, min(deadlines) - now))


def _write_output(target: IO[str], chunk: bytes) -> None:
    target.flush()
    offset = 0
    while offset < len(chunk):
        offset += os.write(target.fileno(), chunk[offset:])


def _drain_after_exit(
    selector: selectors.BaseSelector,
    streams: dict[int, tuple[IO[bytes], IO[str]]],
    stdout: IO[str],
    stderr: IO[str],
) -> None:
    for key in list(selector.get_map().values()):
        source = cast("IO[bytes]", key.fileobj)
        if source.fileno() not in streams:
            selector.unregister(source)
            source.close()
    deadline = time.monotonic() + _FINAL_DRAIN_SECONDS
    _drain_until(selector, streams, deadline)
    for source, _target in list(streams.values()):
        with suppress(KeyError):
            selector.unregister(source)
        source.close()
    stdout.flush()
    stderr.flush()


def _terminate_owned_process(
    process: subprocess.Popen[bytes],
    selector: selectors.BaseSelector,
    streams: dict[int, tuple[IO[bytes], IO[str]]],
    stdout: IO[str],
    stderr: IO[str],
) -> None:
    for key in list(selector.get_map().values()):
        source = cast("IO[bytes]", key.fileobj)
        if source.fileno() not in streams:
            selector.unregister(source)
            source.close()
    _signal_owned_process(process, signal.SIGTERM)
    deadline = time.monotonic() + _TERMINATION_GRACE_SECONDS
    while time.monotonic() < deadline:
        step_deadline = min(deadline, time.monotonic() + 0.1)
        if streams:
            try:
                _drain_until(selector, streams, step_deadline)
            except OSError:
                _close_streams(selector, streams)
        else:
            time.sleep(max(0.0, step_deadline - time.monotonic()))
    if os.name == "posix" or process.poll() is None:
        _signal_owned_process(process, signal.SIGKILL)
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    with suppress(OSError):
        _drain_after_exit(selector, streams, stdout, stderr)


def _signal_owned_process(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        pass


def _drain_until(
    selector: selectors.BaseSelector,
    streams: dict[int, tuple[IO[bytes], IO[str]]],
    deadline: float,
) -> None:
    while streams and time.monotonic() < deadline:
        events = selector.select(max(0.0, deadline - time.monotonic()))
        if not events:
            return
        for key, _event in events:
            source = cast("IO[bytes]", key.fileobj)
            if source.fileno() not in streams:
                continue
            source, target = streams[source.fileno()]
            try:
                chunk = os.read(source.fileno(), 65536)
            except BlockingIOError:
                continue
            if chunk:
                _write_output(target, chunk)
            else:
                fd = source.fileno()
                selector.unregister(source)
                source.close()
                streams.pop(fd, None)


def _close_streams(
    selector: selectors.BaseSelector,
    streams: dict[int, tuple[IO[bytes], IO[str]]],
) -> None:
    for source, _target in list(streams.values()):
        with suppress(KeyError):
            selector.unregister(source)
        source.close()
    streams.clear()


def claude_cli_provider(command: str = "claude -p") -> CliAgentProvider:
    return CliAgentProvider.from_command(
        command,
        args=["--system-prompt", "{system_prompt}", "{session_prompt}"],
    )


def pi_cli_provider(command: str = "pi -p", *, args: Sequence[str] = ()) -> CliAgentProvider:
    return CliAgentProvider.from_command(
        command,
        args=[*args, "--system-prompt", "{system_prompt}", "{session_prompt}"],
    )


def codex_cli_provider(command: str = "codex exec -") -> CliAgentProvider:
    return CliAgentProvider.from_command(
        command,
        args=(),
        stdin_template="{system_prompt}\n\n---\n\n{session_prompt}",
    )


@dataclasses.dataclass
class MockProvider:
    """Test agent provider that records calls and can write valid handoffs."""

    return_code: int = 0
    write_handoff: bool = True
    handoff_text: str | Callable[[AgentCall], str] | None = None
    on_invoke: Callable[[AgentCall], None] | None = None
    calls: list[AgentCall] = dataclasses.field(default_factory=list)

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        call = invocation
        self.calls.append(call)
        if self.on_invoke is not None:
            self.on_invoke(call)
        if self.write_handoff:
            handoff_path = (
                invocation.root / ".devlab/session-artifacts" / invocation.role_name / "handoff.md"
            )
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text(self._handoff_for(call))
            self._publish_test_result(invocation, handoff_path)
        failure_kind: AgentFailureKind = "none" if self.return_code == 0 else "nonzero_exit"
        return AgentResult(
            return_code=self.return_code,
            failure_kind=failure_kind,
            message="" if self.return_code == 0 else f"agent exited with code {self.return_code}",
            role_name=invocation.role_name,
            stdout_log=invocation.stdout_log,
            stderr_log=invocation.stderr_log,
        )

    @staticmethod
    def _publish_test_result(invocation: AgentInvocation, handoff_path: Path) -> None:
        """Make the mock emulate a successful in-session submission when valid."""
        from devlab.handoffs import (
            SESSION_ENVELOPE_ENV,
            candidate_from_handoff,
            load_session_envelope,
            parse_handoff,
            publish_session_result,
        )

        envelope_value = invocation.environment.get(SESSION_ENVELOPE_ENV, "")
        if not envelope_value:
            return
        envelope_path = Path(envelope_value)
        try:
            envelope = load_session_envelope(envelope_path)
            handoff = parse_handoff(handoff_path, invocation.role_name)
        except ValueError:
            return
        publish_session_result(
            envelope_path,
            envelope,
            candidate_from_handoff(handoff),
        )

    def _handoff_for(self, call: AgentCall) -> str:
        if callable(self.handoff_text):
            handoff_factory = cast("Callable[[AgentCall], str]", self.handoff_text)
            return handoff_factory(call)
        if self.handoff_text is not None:
            return self.handoff_text
        planning_state = (
            "## Planning State\nplanning_complete = false\n" if call.role_name == "planner" else ""
        )
        return (
            f"# Handoff: {call.role_name}\n"
            "## Done\n"
            "- Mock session completed.\n"
            "## Changed Artifacts\n"
            "- None\n"
            "## Open Issues\n"
            "- None\n"
            "## Addressed Findings\n"
            "- None\n"
            "## Next Session Hint\n"
            "Continue.\n"
            f"{planning_state}"
        )


def provider_for_role(
    role_name: str,
    providers: Mapping[str, AgentProvider],
    role_providers: Mapping[str, str] | None = None,
) -> AgentProvider:
    provider_name = (role_providers or {}).get(role_name, "default")
    try:
        return providers[provider_name]
    except KeyError as exc:
        raise KeyError(f"unknown agent provider {provider_name!r} for role {role_name!r}") from exc


def _render_args(
    args: Sequence[str], values: Mapping[str, str], *, redact_prompts: bool = False
) -> list[str]:
    render_values = dict(values)
    if redact_prompts:
        render_values["system_prompt"] = "{system_prompt}"
        render_values["session_prompt"] = "{session_prompt}"
    return [arg.format_map(render_values) for arg in args]


def _append_diagnostic(path: Path, message: str) -> None:
    # The structured result still reports capture-path failures when the
    # diagnostic file itself is unavailable.
    with suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(f"DevLab: {message}\n")

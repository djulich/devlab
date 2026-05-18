from __future__ import annotations

import dataclasses
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal, Protocol, cast

AgentFailureKind = Literal[
    "none", "nonzero_exit", "timeout", "missing_executable", "provider_error"
]


@dataclasses.dataclass(frozen=True)
class AgentResult:
    return_code: int
    failure_kind: AgentFailureKind = "none"
    message: str = ""
    role_name: str = ""
    command: tuple[str, ...] = ()
    timeout_seconds: int | None = None
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


AgentCall = AgentInvocation


class AgentProvider(Protocol):
    """Invokes an agent for one DevLab role session."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult: ...


@dataclasses.dataclass(frozen=True)
class CliAgentProvider:
    """Template-based CLI agent provider.

    ``argv`` identifies the agent executable and fixed arguments. ``prompt_args``
    are appended after optional extra args and may contain ``{system_prompt}``,
    ``{session_prompt}``, and ``{role_name}`` placeholders. If ``stdin_template``
    is set, rendered text is sent to stdin instead of being added as an arg.

    This supports Claude- and Pi-style invocations, both of which can use
    ``--system-prompt`` plus a positional session prompt. It also supports
    Codex-style stdin invocation through ``stdin_template``. This keeps the
    orchestrator independent from the concrete CLI shape.
    """

    argv: tuple[str, ...]
    prompt_args: tuple[str, ...] = ("--system-prompt", "{system_prompt}", "{session_prompt}")
    extra_args: tuple[str, ...] = ()
    stdin_template: str | None = None
    template_values: Mapping[str, str] = dataclasses.field(default_factory=dict)
    timeout_seconds: int | None = None

    @classmethod
    def from_command(
        cls,
        command: str,
        *,
        extra_args: Sequence[str] = (),
        prompt_args: Sequence[str] = ("--system-prompt", "{system_prompt}", "{session_prompt}"),
        stdin_template: str | None = None,
        template_values: Mapping[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> CliAgentProvider:
        return cls(
            argv=tuple(shlex.split(command)),
            prompt_args=tuple(prompt_args),
            extra_args=tuple(extra_args),
            stdin_template=stdin_template,
            template_values=dict(template_values or {}),
            timeout_seconds=timeout_seconds,
        )

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        values = {
            **self.template_values,
            "role_name": invocation.role_name,
            "system_prompt": invocation.system_prompt,
            "session_prompt": invocation.session_prompt,
        }
        command = [*self.argv, *_render_args(self.extra_args, values)]
        cmd = [*command]
        stdin: str | None = None
        if self.stdin_template is None:
            cmd.extend(_render_args(self.prompt_args, values))
        else:
            cmd.extend(_render_args(self.prompt_args, values))
            stdin = self.stdin_template.format_map(values)

        invocation.stdout_log.parent.mkdir(parents=True, exist_ok=True)
        invocation.stderr_log.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            with invocation.stdout_log.open("w") as stdout_handle, invocation.stderr_log.open(
                "w"
            ) as stderr_handle:
                result = subprocess.run(
                    cmd,
                    cwd=str(invocation.root),
                    input=stdin,
                    text=stdin is not None,
                    check=False,
                    timeout=self.timeout_seconds,
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
                stdout_log=invocation.stdout_log,
                stderr_log=invocation.stderr_log,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - started
            _append_diagnostic(
                invocation.stderr_log,
                f"agent command timed out after {self.timeout_seconds} second(s)",
            )
            return AgentResult(
                return_code=124,
                failure_kind="timeout",
                message=f"agent command timed out after {self.timeout_seconds} second(s)",
                role_name=invocation.role_name,
                command=tuple(command),
                timeout_seconds=self.timeout_seconds,
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
            stdout_log=invocation.stdout_log,
            stderr_log=invocation.stderr_log,
            duration_seconds=duration,
        )


def claude_cli_provider(
    command: str = "claude -p", *, dangerous_skip_permissions: bool = False
) -> CliAgentProvider:
    extra_args = ("--dangerously-skip-permissions",) if dangerous_skip_permissions else ()
    return CliAgentProvider.from_command(command, extra_args=extra_args)


def pi_cli_provider(command: str = "pi -p", *, extra_args: Sequence[str] = ()) -> CliAgentProvider:
    return CliAgentProvider.from_command(command, extra_args=extra_args)


def codex_cli_provider(command: str = "codex exec -") -> CliAgentProvider:
    return CliAgentProvider.from_command(
        command,
        prompt_args=(),
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
        failure_kind: AgentFailureKind = "none" if self.return_code == 0 else "nonzero_exit"
        return AgentResult(
            return_code=self.return_code,
            failure_kind=failure_kind,
            message="" if self.return_code == 0 else f"agent exited with code {self.return_code}",
            role_name=invocation.role_name,
            stdout_log=invocation.stdout_log,
            stderr_log=invocation.stderr_log,
        )

    def _handoff_for(self, call: AgentCall) -> str:
        if callable(self.handoff_text):
            handoff_factory = cast("Callable[[AgentCall], str]", self.handoff_text)
            return handoff_factory(call)
        if self.handoff_text is not None:
            return self.handoff_text
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


def _render_args(args: Sequence[str], values: Mapping[str, str]) -> list[str]:
    return [arg.format_map(values) for arg in args]


def _append_diagnostic(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(f"DevLab: {message}\n")

from __future__ import annotations

import dataclasses
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol


@dataclasses.dataclass(frozen=True)
class AgentResult:
    return_code: int


class AgentProvider(Protocol):
    """Invokes an agent for one harness role session."""

    def invoke(
        self,
        *,
        root: Path,
        role_name: str,
        system_prompt: str,
        session_prompt: str,
    ) -> AgentResult: ...


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

    @classmethod
    def from_command(
        cls,
        command: str,
        *,
        extra_args: Sequence[str] = (),
        prompt_args: Sequence[str] = ("--system-prompt", "{system_prompt}", "{session_prompt}"),
        stdin_template: str | None = None,
    ) -> CliAgentProvider:
        return cls(
            argv=tuple(shlex.split(command)),
            prompt_args=tuple(prompt_args),
            extra_args=tuple(extra_args),
            stdin_template=stdin_template,
        )

    def invoke(
        self,
        *,
        root: Path,
        role_name: str,
        system_prompt: str,
        session_prompt: str,
    ) -> AgentResult:
        values = {
            "role_name": role_name,
            "system_prompt": system_prompt,
            "session_prompt": session_prompt,
        }
        cmd = [*self.argv, *self.extra_args]
        stdin: str | None = None
        if self.stdin_template is None:
            cmd.extend(_render_args(self.prompt_args, values))
        else:
            cmd.extend(_render_args(self.prompt_args, values))
            stdin = self.stdin_template.format_map(values)

        result = subprocess.run(
            cmd,
            cwd=str(root),
            input=stdin,
            text=stdin is not None,
            check=False,
        )
        return AgentResult(return_code=result.returncode)


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

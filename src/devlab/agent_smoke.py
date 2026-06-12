from __future__ import annotations

import dataclasses
import shlex
from datetime import UTC, datetime
from pathlib import Path

from devlab.agent_config import (
    AGENTS_CONFIG,
    ROLE_NAMES,
    ResolvedAgentConfig,
    load_agent_configuration,
)
from devlab.agents import AgentInvocation, AgentResult

SMOKE_MARKER = "DEVLAB_SMOKE_OK"


@dataclasses.dataclass(frozen=True)
class AgentSmokeRoleResult:
    role_name: str
    config: ResolvedAgentConfig
    result: AgentResult
    marker_found: bool

    @property
    def passed(self) -> bool:
        return self.result.succeeded and self.marker_found


@dataclasses.dataclass(frozen=True)
class AgentSmokeResult:
    root: Path
    config_path: Path
    role_results: tuple[AgentSmokeRoleResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.role_results)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.role_results if result.passed)

    @property
    def failed_count(self) -> int:
        return len(self.role_results) - self.passed_count


def run_agent_smoke_test(
    root: Path,
    *,
    config_path: Path | None = None,
    role_names: tuple[str, ...] | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> AgentSmokeResult:
    """Invoke configured agent providers with a tiny prompt to verify wiring."""
    selected_roles = role_names or ROLE_NAMES
    _validate_roles(selected_roles)
    effective_config_path = config_path or root / AGENTS_CONFIG
    configuration = load_agent_configuration(
        root,
        config_path=config_path,
        provider=provider,
        model=model,
        effort=effort,
        discover_provider_versions=True,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results: list[AgentSmokeRoleResult] = []
    for role_name in selected_roles:
        resolved = configuration.resolved[role_name]
        provider_instance = configuration.providers[configuration.role_providers[role_name]]
        stdout_log = (
            root / ".devlab/logs/agents" / f"{timestamp}_smoke_{role_name}.stdout.log"
        )
        stderr_log = (
            root / ".devlab/logs/agents" / f"{timestamp}_smoke_{role_name}.stderr.log"
        )
        invocation = AgentInvocation(
            root=root,
            role_name=role_name,
            base_prompt=(
                "DevLab agent configuration smoke test. "
                f"Reply with exactly: {SMOKE_MARKER}"
            ),
            session_prompt=(
                "This is a DevLab provider wiring check. "
                "Do not inspect files, edit files, run commands, or create artifacts. "
                f"Role: {role_name}. Provider: {resolved.provider}. "
                f"Model: {resolved.model}. Effort: {resolved.effort}."
            ),
            invocation_id=f"smoke-{timestamp}-{role_name}",
            stdout_log=stdout_log,
            stderr_log=stderr_log,
        )
        result = provider_instance.invoke(invocation)
        results.append(
            AgentSmokeRoleResult(
                role_name=role_name,
                config=resolved,
                result=result,
                marker_found=_log_contains(stdout_log, SMOKE_MARKER),
            )
        )
    return AgentSmokeResult(
        root=root,
        config_path=effective_config_path,
        role_results=tuple(results),
    )


def format_agent_smoke_report(result: AgentSmokeResult) -> str:
    lines = [
        "Agent smoke test",
        f"Workspace: {result.root}",
        f"Config: {result.config_path}",
        "Roles: " + ", ".join(role.role_name for role in result.role_results),
        "",
    ]
    for role_result in result.role_results:
        config = role_result.config
        agent_result = role_result.result
        lines.extend(
            [
                f"[{role_result.role_name}]",
                f"Provider: {config.provider}",
                f"Model: {config.model}",
                f"Effort: {config.effort}",
                f"Timeout: {_format_timeout(config.timeout_seconds)}",
                f"Stdin: {_format_bool(config.uses_stdin)}",
                "Command: " + shlex.join(config.command),
                f"Result: {'OK' if role_result.passed else 'FAILED'}",
            ]
        )
        if not role_result.passed:
            lines.append(f"Failure: {_format_failure(role_result)}")
            lines.append(f"Exit code: {agent_result.return_code}")
        if agent_result.duration_seconds is not None:
            lines.append(f"Duration: {agent_result.duration_seconds:.1f}s")
        lines.extend(
            [
                f"Stdout: {_format_path(agent_result.stdout_log)}",
                f"Stderr: {_format_path(agent_result.stderr_log)}",
                "",
            ]
        )
    lines.append(f"Summary: {result.passed_count} passed, {result.failed_count} failed")
    return "\n".join(lines)


def _validate_roles(role_names: tuple[str, ...]) -> None:
    unknown = [role_name for role_name in role_names if role_name not in ROLE_NAMES]
    if unknown:
        valid = ", ".join(ROLE_NAMES)
        raise ValueError(f"unknown role(s): {', '.join(unknown)}; expected one of: {valid}")


def _log_contains(path: Path, text: str) -> bool:
    try:
        return text in path.read_text(errors="replace")
    except FileNotFoundError:
        return False


def _format_timeout(timeout_seconds: int | None) -> str:
    if timeout_seconds is None:
        return "none"
    return f"{timeout_seconds}s"


def _format_bool(value: bool) -> str:
    return "yes" if value else "no"


def _format_failure(result: AgentSmokeRoleResult) -> str:
    if not result.result.succeeded:
        return result.result.failure_kind
    return f"missing marker {SMOKE_MARKER!r}"


def _format_path(path: Path | None) -> str:
    if path is None:
        return "none"
    return str(path)

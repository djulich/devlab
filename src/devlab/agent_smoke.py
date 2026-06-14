from __future__ import annotations

import dataclasses
import shlex
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from devlab.agent_config import (
    AGENTS_CONFIG,
    ROLE_NAMES,
    ResolvedAgentConfig,
    ResolvedProviderConfig,
    load_agent_configuration,
)
from devlab.agents import AgentInvocation, AgentResult

SMOKE_MARKER = "DEVLAB_SMOKE_OK"


@dataclasses.dataclass(frozen=True)
class AgentSmokeCheckResult:
    check_name: str
    config: ResolvedAgentConfig | ResolvedProviderConfig
    result: AgentResult
    marker_found: bool
    scope: Literal["provider", "role"]

    @property
    def passed(self) -> bool:
        return self.result.succeeded and self.marker_found


@dataclasses.dataclass(frozen=True)
class AgentSmokeProgressEvent:
    event: Literal["start", "finish"]
    check_name: str
    config: ResolvedAgentConfig | ResolvedProviderConfig
    result: AgentSmokeCheckResult | None = None


@dataclasses.dataclass(frozen=True)
class AgentSmokeResult:
    root: Path
    config_path: Path
    check_results: tuple[AgentSmokeCheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.check_results)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.check_results if result.passed)

    @property
    def failed_count(self) -> int:
        return len(self.check_results) - self.passed_count

    @property
    def role_results(self) -> tuple[AgentSmokeCheckResult, ...]:
        return tuple(result for result in self.check_results if result.scope == "role")

    @property
    def provider_results(self) -> tuple[AgentSmokeCheckResult, ...]:
        return tuple(result for result in self.check_results if result.scope == "provider")


def run_agent_smoke_test(
    root: Path,
    *,
    config_path: Path | None = None,
    role_names: tuple[str, ...] | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    on_progress: Callable[[AgentSmokeProgressEvent], None] | None = None,
) -> AgentSmokeResult:
    """Invoke configured agent providers with a tiny prompt to verify wiring."""
    if role_names is not None:
        _validate_roles(role_names)
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
    results: list[AgentSmokeCheckResult] = []
    if role_names is None:
        checks = [
            (
                provider_name,
                "provider",
                resolved,
                configuration.configured_providers[provider_name],
            )
            for provider_name, resolved in configuration.configured_provider_configs.items()
        ]
    else:
        checks = [
            (
                role_name,
                "role",
                configuration.resolved[role_name],
                configuration.providers[configuration.role_providers[role_name]],
            )
            for role_name in role_names
        ]
    for check_name, scope, resolved, provider_instance in checks:
        stdout_log = (
            root / ".devlab/logs/agents" / f"{timestamp}_smoke_{check_name}.stdout.log"
        )
        stderr_log = (
            root / ".devlab/logs/agents" / f"{timestamp}_smoke_{check_name}.stderr.log"
        )
        invocation = AgentInvocation(
            root=root,
            role_name=check_name,
            system_prompt=(
                "DevLab agent configuration smoke test. "
                f"Reply with exactly: {SMOKE_MARKER}"
            ),
            session_prompt=(
                "This is a DevLab provider wiring check. "
                "Do not inspect files, edit files, run commands, or create artifacts. "
                f"Check: {check_name}. Provider: {resolved.provider}. "
                f"Model: {resolved.model}. Effort: {resolved.effort}."
            ),
            invocation_id=f"smoke-{timestamp}-{check_name}",
            stdout_log=stdout_log,
            stderr_log=stderr_log,
        )
        _emit_progress(
            on_progress,
            AgentSmokeProgressEvent("start", check_name, resolved),
        )
        agent_result = provider_instance.invoke(invocation)
        check_result = AgentSmokeCheckResult(
            check_name=check_name,
            config=resolved,
            result=agent_result,
            marker_found=_log_contains(stdout_log, SMOKE_MARKER),
            scope=scope,
        )
        results.append(check_result)
        _emit_progress(
            on_progress,
            AgentSmokeProgressEvent("finish", check_name, resolved, check_result),
        )
    return AgentSmokeResult(
        root=root,
        config_path=effective_config_path,
        check_results=tuple(results),
    )


def format_agent_smoke_report(result: AgentSmokeResult) -> str:
    label = "Roles" if result.role_results else "Providers"
    lines = [
        "Agent smoke test",
        f"Workspace: {result.root}",
        f"Config: {result.config_path}",
        f"{label}: " + ", ".join(check.check_name for check in result.check_results),
        "",
    ]
    for check_result in result.check_results:
        config = check_result.config
        agent_result = check_result.result
        lines.extend(
            [
                f"[{check_result.check_name}]",
                f"Provider: {config.provider}",
                f"Model: {config.model}",
                f"Effort: {config.effort}",
                f"Timeout: {_format_timeout(config.timeout_seconds)}",
                f"Stdin: {_format_bool(config.uses_stdin)}",
                "Command: " + shlex.join(config.command),
                f"Result: {'OK' if check_result.passed else 'FAILED'}",
            ]
        )
        if not check_result.passed:
            lines.append(f"Failure: {_format_failure(check_result)}")
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


def _emit_progress(
    on_progress: Callable[[AgentSmokeProgressEvent], None] | None,
    event: AgentSmokeProgressEvent,
) -> None:
    if on_progress is not None:
        on_progress(event)


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


def _format_failure(result: AgentSmokeCheckResult) -> str:
    if not result.result.succeeded:
        return result.result.failure_kind
    return f"missing marker {SMOKE_MARKER!r}"


def _format_path(path: Path | None) -> str:
    if path is None:
        return "none"
    return str(path)

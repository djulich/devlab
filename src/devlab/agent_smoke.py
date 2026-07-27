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
    AgentConfiguration,
    ResolvedAgentConfig,
    ResolvedProviderConfig,
    load_agent_configuration,
)
from devlab.agents import AgentInvocation, AgentProvider, AgentResult
from devlab.executable_config import ExecutableConfigSnapshot

SMOKE_MARKER = "DEVLAB_SMOKE_OK"


@dataclasses.dataclass(frozen=True)
class AgentSmokeCheckResult:
    check_name: str
    config: ResolvedAgentConfig | ResolvedProviderConfig
    result: AgentResult
    marker_found: bool
    role_names: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.result.succeeded and self.marker_found


@dataclasses.dataclass(frozen=True)
class AgentSmokeSkippedProvider:
    provider: str
    reason: str


@dataclasses.dataclass(frozen=True)
class AgentSmokeTarget:
    check_name: str
    config: ResolvedAgentConfig | ResolvedProviderConfig
    provider: AgentProvider
    role_names: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class AgentSmokeProgressEvent:
    event: Literal["start", "finish"]
    check_name: str
    config: ResolvedAgentConfig | ResolvedProviderConfig
    role_names: tuple[str, ...] = ()
    result: AgentSmokeCheckResult | None = None


@dataclasses.dataclass(frozen=True)
class AgentSmokeResult:
    root: Path
    config_path: Path
    check_results: tuple[AgentSmokeCheckResult, ...]
    skipped_providers: tuple[AgentSmokeSkippedProvider, ...] = ()
    executable_config_digest: str = ""
    executable_config_authorization: str = ""

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
    def skipped_count(self) -> int:
        return len(self.skipped_providers)


def run_agent_smoke_test(
    root: Path,
    *,
    config_path: Path | None = None,
    role_names: tuple[str, ...] | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    all_providers: bool = False,
    use_provider_defaults: bool = False,
    on_progress: Callable[[AgentSmokeProgressEvent], None] | None = None,
    executable_config: ExecutableConfigSnapshot | None = None,
) -> AgentSmokeResult:
    """Invoke configured agent providers with a tiny prompt to verify wiring."""
    if all_providers and role_names is not None:
        raise ValueError("all_providers cannot be combined with role_names")
    if all_providers and provider is not None:
        raise ValueError("all_providers cannot be combined with provider")
    if provider is not None and role_names is not None:
        raise ValueError("provider cannot be combined with role_names")
    if use_provider_defaults and role_names is not None:
        raise ValueError("use_provider_defaults cannot be combined with role_names")
    if use_provider_defaults and provider is None and not all_providers:
        raise ValueError("use_provider_defaults requires provider or all_providers")
    if role_names is not None:
        _validate_roles(role_names)
    effective_config_path = config_path or root / AGENTS_CONFIG
    configuration = (
        executable_config.resolve_agents(discover_provider_versions=True)
        if executable_config is not None
        else load_agent_configuration(
            root,
            config_path=config_path,
            model=model,
            effort=effort,
            discover_provider_versions=True,
        )
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results: list[AgentSmokeCheckResult] = []
    targets, skipped = _select_smoke_targets(
        configuration,
        role_names=role_names,
        provider_name=provider,
        all_providers=all_providers,
        use_provider_defaults=use_provider_defaults,
    )
    for target in targets:
        stdout_log = (
            root / ".devlab/logs/agents" / f"{timestamp}_smoke_{target.check_name}.stdout.log"
        )
        stderr_log = (
            root / ".devlab/logs/agents" / f"{timestamp}_smoke_{target.check_name}.stderr.log"
        )
        invocation = AgentInvocation(
            root=root,
            role_name=target.check_name,
            system_prompt=(
                "DevLab agent configuration smoke test. "
                f"Reply with exactly: {SMOKE_MARKER}"
            ),
            session_prompt=(
                "This is a DevLab provider wiring check. "
                "Do not inspect files, edit files, run commands, or create artifacts. "
                f"Check: {target.check_name}. Provider: {target.config.provider}. "
                f"Assigned roles: {_format_roles(target.role_names)}. "
                f"Model: {target.config.model}. Effort: {target.config.effort}."
            ),
            invocation_id=f"smoke-{timestamp}-{target.check_name}",
            stdout_log=stdout_log,
            stderr_log=stderr_log,
        )
        _emit_progress(
            on_progress,
            AgentSmokeProgressEvent(
                "start",
                target.check_name,
                target.config,
                target.role_names,
            ),
        )
        agent_result = target.provider.invoke(invocation)
        check_result = AgentSmokeCheckResult(
            check_name=target.check_name,
            config=target.config,
            result=agent_result,
            marker_found=_log_contains(stdout_log, SMOKE_MARKER),
            role_names=target.role_names,
        )
        results.append(check_result)
        _emit_progress(
            on_progress,
            AgentSmokeProgressEvent(
                "finish",
                target.check_name,
                target.config,
                target.role_names,
                check_result,
            ),
        )
    return AgentSmokeResult(
        root=root,
        config_path=effective_config_path,
        check_results=tuple(results),
        skipped_providers=tuple(skipped),
        executable_config_digest=(
            executable_config.digest if executable_config is not None else ""
        ),
        executable_config_authorization=(
            executable_config.authorization.source.value
            if executable_config is not None
            and executable_config.authorization is not None
            else ""
        ),
    )


def format_agent_smoke_report(result: AgentSmokeResult) -> str:
    lines = [
        "Agent smoke test",
        f"Workspace: {result.root}",
        f"Config: {result.config_path}",
        *(
            [
                f"Executable config: {result.executable_config_digest}",
                f"Authorization: {result.executable_config_authorization}",
            ]
            if result.executable_config_digest
            else []
        ),
        "Checks: " + _format_check_names(result.check_results),
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
                f"Assigned roles: {_format_roles(check_result.role_names)}",
                f"Stdin: {_format_bool(config.uses_stdin)}",
                "Command: " + shlex.join(agent_result.command),
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
    for skipped in result.skipped_providers:
        lines.extend(
            [
                f"[{skipped.provider}]",
                "Result: SKIPPED",
                f"Reason: {skipped.reason}",
                "",
            ]
        )
    lines.append(f"Summary: {result.passed_count} passed, {result.failed_count} failed")
    if result.skipped_count:
        lines[-1] += f", {result.skipped_count} skipped"
    return "\n".join(lines)


def _select_smoke_targets(
    configuration: AgentConfiguration,
    *,
    role_names: tuple[str, ...] | None,
    provider_name: str | None,
    all_providers: bool,
    use_provider_defaults: bool,
) -> tuple[list[AgentSmokeTarget], list[AgentSmokeSkippedProvider]]:
    role_targets = _role_provider_targets(configuration)
    if role_names is not None:
        selected_roles = set(role_names)
        return (
            [
                target
                for target in role_targets
                if selected_roles.intersection(target.role_names)
            ],
            [],
        )
    if use_provider_defaults:
        if provider_name is not None:
            if provider_name not in configuration.provider_names:
                raise ValueError(f"unknown provider: {provider_name}")
            target = _provider_default_target(configuration, provider_name)
            if target is None:
                raise ValueError(_missing_provider_defaults_message(provider_name))
            return [target], []
        targets: list[AgentSmokeTarget] = []
        skipped: list[AgentSmokeSkippedProvider] = []
        for configured_provider in configuration.provider_names:
            target = _provider_default_target(configuration, configured_provider)
            if target is None:
                skipped.append(_missing_provider_defaults(configured_provider))
            else:
                targets.append(target)
        return targets, skipped
    if provider_name is not None:
        if provider_name not in configuration.provider_names:
            raise ValueError(f"unknown provider: {provider_name}")
        targets = [target for target in role_targets if target.config.provider == provider_name]
        if targets:
            return targets, []
        target = _provider_default_target(configuration, provider_name)
        if target is not None:
            return [target], []
        raise ValueError(_missing_provider_defaults_message(provider_name))
    if not all_providers:
        return role_targets, []

    assigned_providers = {target.config.provider for target in role_targets}
    targets = list(role_targets)
    skipped: list[AgentSmokeSkippedProvider] = []
    for configured_provider in configuration.provider_names:
        if configured_provider in assigned_providers:
            continue
        target = _provider_default_target(configuration, configured_provider)
        if target is None:
            skipped.append(_missing_provider_defaults(configured_provider))
        else:
            targets.append(target)
    return targets, skipped


def _role_provider_targets(configuration: AgentConfiguration) -> list[AgentSmokeTarget]:
    groups: dict[
        tuple[str, str, str, bool, tuple[str, ...]],
        tuple[ResolvedAgentConfig, AgentProvider, list[str], list[ResolvedAgentConfig]],
    ] = {}
    for role_name in ROLE_NAMES:
        resolved = configuration.resolved[role_name]
        provider_instance = configuration.providers[configuration.role_providers[role_name]]
        key = (
            resolved.provider,
            resolved.model,
            resolved.effort,
            resolved.uses_stdin,
            resolved.provider_identity_command,
        )
        existing = groups.get(key)
        if existing is None:
            groups[key] = (resolved, provider_instance, [role_name], [resolved])
        else:
            existing[2].append(role_name)
            existing[3].append(resolved)

    provider_name_counts: dict[str, int] = {}
    targets: list[AgentSmokeTarget] = []
    for resolved, provider_instance, assigned_roles, configs in groups.values():
        config, provider_for_timeout = _config_with_min_timeout(
            configs,
            configuration,
            fallback_provider=provider_instance,
        )
        check_name = _unique_check_name(resolved.provider, provider_name_counts)
        targets.append(
            AgentSmokeTarget(
                check_name=check_name,
                config=config,
                provider=provider_for_timeout,
                role_names=tuple(assigned_roles),
            )
        )
    return targets


def _provider_default_target(
    configuration: AgentConfiguration,
    provider_name: str,
) -> AgentSmokeTarget | None:
    config = configuration.provider_configs_with_defaults.get(provider_name)
    provider = configuration.providers_with_defaults.get(provider_name)
    if config is None or provider is None:
        return None
    return AgentSmokeTarget(check_name=provider_name, config=config, provider=provider)


def _config_with_min_timeout(
    configs: list[ResolvedAgentConfig],
    configuration: AgentConfiguration,
    *,
    fallback_provider: AgentProvider,
) -> tuple[ResolvedAgentConfig, AgentProvider]:
    def timeout_sort_key(config: ResolvedAgentConfig) -> tuple[int, int]:
        if config.timeout_seconds is None:
            return (1, 0)
        return (0, config.timeout_seconds)

    selected = min(configs, key=timeout_sort_key)
    if selected.timeout_seconds is None:
        return selected, fallback_provider
    provider = configuration.providers[configuration.role_providers[selected.role_name]]
    return selected, provider


def _unique_check_name(provider_name: str, counts: dict[str, int]) -> str:
    count = counts.get(provider_name, 0) + 1
    counts[provider_name] = count
    if count == 1:
        return provider_name
    return f"{provider_name}_{count}"


def _missing_provider_defaults(provider_name: str) -> AgentSmokeSkippedProvider:
    return AgentSmokeSkippedProvider(
        provider=provider_name,
        reason=_missing_provider_defaults_message(provider_name),
    )


def _missing_provider_defaults_message(provider_name: str) -> str:
    return f"no assigned roles and no [providers.{provider_name}.defaults]"


def _format_roles(role_names: tuple[str, ...]) -> str:
    if not role_names:
        return "none"
    return ", ".join(role_names)


def _format_check_names(results: tuple[AgentSmokeCheckResult, ...]) -> str:
    if not results:
        return "none"
    return ", ".join(result.check_name for result in results)


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

from __future__ import annotations

import dataclasses
import shlex
import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from devlab.agents import AgentProvider, CliAgentProvider

AGENTS_CONFIG = ".devlab/config/agents.toml"
ROLE_NAMES = ("architect", "planner", "developer", "reviewer", "integrator")


@dataclasses.dataclass(frozen=True)
class ResolvedAgentConfig:
    role_name: str
    provider: str
    model: str
    effort: str
    provider_version: str
    timeout_seconds: int | None
    command: tuple[str, ...]
    uses_stdin: bool


@dataclasses.dataclass(frozen=True)
class AgentConfiguration:
    providers: dict[str, AgentProvider]
    role_providers: dict[str, str]
    resolved: dict[str, ResolvedAgentConfig]


def load_agent_configuration(
    root: Path,
    *,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    dangerous_skip_permissions: bool = False,
    discover_provider_versions: bool = False,
) -> AgentConfiguration:
    data = _load_config(root)
    if data is None:
        data = _fallback_config()

    defaults = _table(data.get("defaults", {}), "defaults")
    roles = _table(data.get("roles", {}), "roles")
    providers_config = _table(data.get("providers", {}), "providers")

    agent_providers: dict[str, AgentProvider] = {}
    role_providers: dict[str, str] = {}
    resolved_configs: dict[str, ResolvedAgentConfig] = {}

    for role_name in ROLE_NAMES:
        role_table = _table(roles.get(role_name, {}), f"roles.{role_name}")
        values = {**defaults, **role_table}
        if provider is not None:
            values["provider"] = provider
        if model is not None:
            values["model"] = model
        if effort is not None:
            values["effort"] = effort

        provider_name = _string(values.get("provider", "default"), f"roles.{role_name}.provider")
        provider_table = _table(
            providers_config.get(provider_name), f"providers.{provider_name}"
        )
        timeout_seconds = _optional_int(
            values.get("timeout_seconds"), f"roles.{role_name}.timeout_seconds"
        )
        provider_key = f"{role_name}:{provider_name}"
        template_values = {
            "role_name": role_name,
            "provider": provider_name,
            "model": _string(values.get("model", ""), f"roles.{role_name}.model"),
            "effort": _string(values.get("effort", ""), f"roles.{role_name}.effort"),
        }
        extra_args = _string_list(
            provider_table.get("args", []), f"providers.{provider_name}.args"
        )
        if dangerous_skip_permissions:
            extra_args = [*extra_args, "--dangerously-skip-permissions"]
        prompt_args = _string_list(
            provider_table.get(
                "prompt_args", ["--system-prompt", "{system_prompt}", "{session_prompt}"]
            ),
            f"providers.{provider_name}.prompt_args",
        )
        stdin_template = _optional_string(
            provider_table.get("stdin_template"), f"providers.{provider_name}.stdin_template"
        )
        command = _string(provider_table.get("command"), f"providers.{provider_name}.command")
        provider_version = (
            _provider_version(provider_table, command, template_values)
            if discover_provider_versions else ""
        )
        cli_provider = CliAgentProvider.from_command(
            command,
            extra_args=extra_args,
            prompt_args=prompt_args,
            stdin_template=stdin_template,
            template_values=template_values,
            timeout_seconds=timeout_seconds,
        )
        agent_providers[provider_key] = cli_provider
        role_providers[role_name] = provider_key
        resolved_configs[role_name] = ResolvedAgentConfig(
            role_name=role_name,
            provider=provider_name,
            model=template_values["model"],
            effort=template_values["effort"],
            provider_version=provider_version,
            timeout_seconds=timeout_seconds,
            command=tuple(_render_command(command, extra_args, template_values)),
            uses_stdin=stdin_template is not None,
        )

    return AgentConfiguration(agent_providers, role_providers, resolved_configs)


def format_resolved_agent_config(config: ResolvedAgentConfig) -> str:
    lines = [
        f'role = "{config.role_name}"',
        f'provider = "{config.provider}"',
        f'model = "{config.model}"',
        f'effort = "{config.effort}"',
        f"uses_stdin = {_toml_bool(config.uses_stdin)}",
    ]
    if config.provider_version:
        lines.append(f'provider_version = {_toml_string(config.provider_version)}')
    if config.timeout_seconds is not None:
        lines.append(f"timeout_seconds = {config.timeout_seconds}")
    lines.append("command = [" + ", ".join(_toml_string(part) for part in config.command) + "]")
    return "\n".join(lines) + "\n"


def _load_config(root: Path) -> dict[str, Any] | None:
    path = root / AGENTS_CONFIG
    if not path.exists():
        return None
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return _table(data, AGENTS_CONFIG)


def _fallback_config() -> dict[str, Any]:
    return {
        "defaults": {"provider": "default"},
        "providers": {
            "default": {
                "command": "claude -p",
                "args": [],
                "prompt_args": ["--system-prompt", "{system_prompt}", "{session_prompt}"],
            }
        },
    }


def _render_command(command: str, args: list[str], values: Mapping[str, str]) -> list[str]:
    return [*shlex.split(command), *(arg.format_map(values) for arg in args)]


def _provider_version(
    provider_table: dict[str, Any], command: str, values: Mapping[str, str]
) -> str:
    configured = _optional_string(
        provider_table.get("version_command"), "providers.<provider>.version_command"
    )
    if configured == "":
        return ""
    if configured is None:
        command_parts = shlex.split(command)
        if not command_parts:
            return ""
        version_command = [command_parts[0], "--version"]
    else:
        version_command = [part.format_map(values) for part in shlex.split(configured)]
    try:
        result = subprocess.run(
            version_command,
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode != 0:
        return ""
    output = (result.stdout.strip() or result.stderr.strip()).splitlines()
    return output[0][:500] if output else ""


def _table(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a TOML table")
    return cast("dict[str, Any]", value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return cast("list[str]", value)


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

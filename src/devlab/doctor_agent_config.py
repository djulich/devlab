from __future__ import annotations

import shutil
import string
import tomllib
from pathlib import Path
from typing import Any, cast

from devlab.agent_config import (
    AGENTS_CONFIG,
    ROLE_NAMES,
    ResolvedAgentConfig,
    load_agent_configuration,
)
from devlab.doctor_common import DoctorProblem

_SUPPORTED_PLACEHOLDERS = {
    "role_name",
    "provider",
    "model",
    "effort",
    "system_prompt",
    "session_prompt",
}


def check_agents_config(root: Path) -> list[DoctorProblem]:
    path = root / AGENTS_CONFIG
    if not path.exists():
        return []
    display_path = AGENTS_CONFIG
    problems: list[DoctorProblem] = []
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        return [DoctorProblem(display_path, f"invalid TOML: {exc}")]
    if not isinstance(data, dict):
        return [DoctorProblem(display_path, "must be a TOML table")]
    config = data

    defaults = _optional_table(config, "defaults", display_path, problems)
    roles = _optional_table(config, "roles", display_path, problems)
    providers = _optional_table(config, "providers", display_path, problems)
    prompt_context = _optional_table(config, "prompt_context", display_path, problems)

    if defaults is not None:
        _check_role_values(defaults, "defaults", display_path, problems)
    if roles is not None:
        for role_name, role_value in roles.items():
            if role_name not in ROLE_NAMES:
                problems.append(
                    DoctorProblem(display_path, f"roles.{role_name} is not a known role")
                )
                continue
            role_table = _require_table(role_value, f"roles.{role_name}", display_path, problems)
            if role_table is not None:
                _check_role_values(role_table, f"roles.{role_name}", display_path, problems)

    if providers is not None:
        for provider_name, provider_value in providers.items():
            provider_table = _require_table(
                provider_value, f"providers.{provider_name}", display_path, problems
            )
            if provider_table is not None:
                _check_provider(provider_name, provider_table, display_path, problems)

    _check_provider_references(defaults, roles, providers, display_path, problems)
    if prompt_context is not None:
        _check_prompt_context(prompt_context, display_path, problems)

    if not problems:
        try:
            resolved = load_agent_configuration(root)
        except (ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
            problems.append(DoctorProblem(display_path, str(exc)))
        else:
            _check_provider_executables(resolved.resolved, display_path, problems)
    return problems


def _check_provider_executables(
    resolved_configs: dict[str, ResolvedAgentConfig],
    display_path: str,
    problems: list[DoctorProblem],
) -> None:
    roles_by_executable: dict[tuple[str, str], list[str]] = {}
    for role_name, config in resolved_configs.items():
        if not config.command:
            problems.append(
                DoctorProblem(
                    display_path,
                    f"provider {config.provider!r} command resolves to an empty command",
                )
            )
            continue
        executable = config.command[0]
        roles_by_executable.setdefault((config.provider, executable), []).append(role_name)

    for (provider_name, executable), role_names in roles_by_executable.items():
        if shutil.which(executable) is not None:
            continue
        roles = ", ".join(sorted(role_names))
        problems.append(
            DoctorProblem(
                display_path,
                f"provider {provider_name!r} executable {executable!r} was not found on PATH "
                f"(used by roles: {roles})",
            )
        )


def _check_prompt_context(
    prompt_context: dict[str, Any], display_path: str, problems: list[DoctorProblem]
) -> None:
    warning_tokens = _check_positive_int(
        prompt_context,
        "warning_tokens",
        "prompt_context.warning_tokens",
        display_path,
        problems,
    )
    critical_tokens = _check_positive_int(
        prompt_context,
        "critical_tokens",
        "prompt_context.critical_tokens",
        display_path,
        problems,
    )
    _check_threshold_order(
        warning_tokens,
        critical_tokens,
        "prompt_context",
        display_path,
        problems,
    )
    roles = _optional_table(prompt_context, "roles", display_path, problems)
    if roles is None:
        return
    for role_name, role_value in roles.items():
        if role_name not in ROLE_NAMES:
            problems.append(
                DoctorProblem(
                    display_path,
                    f"prompt_context.roles.{role_name} is not a known role",
                )
            )
            continue
        role_table = _require_table(
            role_value,
            f"prompt_context.roles.{role_name}",
            display_path,
            problems,
        )
        if role_table is None:
            continue
        role_warning = _check_positive_int(
            role_table,
            "warning_tokens",
            f"prompt_context.roles.{role_name}.warning_tokens",
            display_path,
            problems,
        )
        role_critical = _check_positive_int(
            role_table,
            "critical_tokens",
            f"prompt_context.roles.{role_name}.critical_tokens",
            display_path,
            problems,
        )
        _check_threshold_order(
            role_warning,
            role_critical,
            f"prompt_context.roles.{role_name}",
            display_path,
            problems,
        )


def _check_positive_int(
    values: dict[str, Any],
    key: str,
    name: str,
    display_path: str,
    problems: list[DoctorProblem],
) -> int | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        problems.append(DoctorProblem(display_path, f"{name} must be an integer"))
        return None
    if value <= 0:
        problems.append(DoctorProblem(display_path, f"{name} must be greater than zero"))
        return None
    return value


def _check_threshold_order(
    warning_tokens: int | None,
    critical_tokens: int | None,
    name: str,
    display_path: str,
    problems: list[DoctorProblem],
) -> None:
    if warning_tokens is None or critical_tokens is None:
        return
    if critical_tokens < warning_tokens:
        problems.append(
            DoctorProblem(
                display_path,
                f"{name}.critical_tokens must be greater than or equal to warning_tokens",
            )
        )


def _optional_table(
    config: dict[str, Any], key: str, display_path: str, problems: list[DoctorProblem]
) -> dict[str, Any] | None:
    value = config.get(key, {})
    return _require_table(value, key, display_path, problems)


def _require_table(
    value: object, name: str, display_path: str, problems: list[DoctorProblem]
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        problems.append(DoctorProblem(display_path, f"{name} must be a TOML table"))
        return None
    return cast("dict[str, Any]", value)


def _check_role_values(
    values: dict[str, Any], name: str, display_path: str, problems: list[DoctorProblem]
) -> None:
    for key in ("provider", "model", "effort"):
        value = values.get(key)
        if value is not None and not isinstance(value, str):
            problems.append(DoctorProblem(display_path, f"{name}.{key} must be a string"))
    timeout = values.get("timeout_seconds")
    if timeout is not None and not isinstance(timeout, int):
        problems.append(DoctorProblem(display_path, f"{name}.timeout_seconds must be an integer"))


def _check_provider(
    provider_name: str,
    provider: dict[str, Any],
    display_path: str,
    problems: list[DoctorProblem],
) -> None:
    command = provider.get("command")
    if not isinstance(command, str):
        problems.append(
            DoctorProblem(display_path, f"providers.{provider_name}.command must be a string")
        )
    else:
        _check_placeholders(command, f"providers.{provider_name}.command", display_path, problems)
    for key in ("args", "prompt_args"):
        value = provider.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            problems.append(
                DoctorProblem(
                    display_path,
                    f"providers.{provider_name}.{key} must be a list of strings",
                )
            )
            continue
        string_values = cast("list[str]", value)
        for index, item in enumerate(string_values):
            _check_placeholders(
                item, f"providers.{provider_name}.{key}[{index}]", display_path, problems
            )
    stdin_template = provider.get("stdin_template")
    if stdin_template is not None:
        if not isinstance(stdin_template, str):
            problems.append(
                DoctorProblem(
                    display_path,
                    f"providers.{provider_name}.stdin_template must be a string",
                )
            )
        else:
            _check_placeholders(
                stdin_template, f"providers.{provider_name}.stdin_template", display_path, problems
            )


def _check_provider_references(
    defaults: dict[str, Any] | None,
    roles: dict[str, Any] | None,
    providers: dict[str, Any] | None,
    display_path: str,
    problems: list[DoctorProblem],
) -> None:
    provider_tables = providers or {}
    default_provider = "default"
    if defaults is not None and isinstance(defaults.get("provider"), str):
        default_provider = cast("str", defaults["provider"])
    role_tables = roles or {}
    for role_name in ROLE_NAMES:
        role_value = role_tables.get(role_name, {})
        role_provider = default_provider
        if isinstance(role_value, dict) and isinstance(role_value.get("provider"), str):
            role_provider = cast("str", role_value["provider"])
        if role_provider not in provider_tables:
            problems.append(
                DoctorProblem(
                    display_path,
                    f"roles.{role_name}.provider references missing provider {role_provider!r}",
                )
            )


def _check_placeholders(
    value: str, name: str, display_path: str, problems: list[DoctorProblem]
) -> None:
    try:
        parsed = string.Formatter().parse(value)
        for _, field_name, _, _ in parsed:
            if field_name is None:
                continue
            root_name = field_name.split(".", 1)[0].split("[", 1)[0]
            if root_name not in _SUPPORTED_PLACEHOLDERS:
                problems.append(
                    DoctorProblem(
                        display_path,
                        f"{name} references unsupported placeholder {{{field_name}}}",
                    )
                )
    except ValueError as exc:
        problems.append(DoctorProblem(display_path, f"{name} has invalid template: {exc}"))

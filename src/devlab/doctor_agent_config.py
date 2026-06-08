from __future__ import annotations

import re
import shlex
import shutil
import string
import tomllib
from pathlib import Path
from typing import Any, cast

from devlab.agent_config import (
    AGENTS_CONFIG,
    ROLE_NAMES,
    ResolvedAgentConfig,
    find_agent_executable_problems,
    load_agent_configuration,
)
from devlab.doctor_common import DoctorProblem

_COMMAND_PLACEHOLDERS = {"role_name", "provider", "model", "effort"}
_PROMPT_PLACEHOLDERS = _COMMAND_PLACEHOLDERS | {"system_prompt", "session_prompt"}
_SHELL_OPERATORS = ("&&", "||", "|", ";", "<", ">", "$(", "`")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


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
    for executable_problem in find_agent_executable_problems(resolved_configs):
        problems.append(DoctorProblem(display_path, executable_problem.format_message()))


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
    if timeout is not None:
        if not isinstance(timeout, int):
            problems.append(
                DoctorProblem(display_path, f"{name}.timeout_seconds must be an integer")
            )
        elif timeout <= 0:
            problems.append(
                DoctorProblem(display_path, f"{name}.timeout_seconds must be greater than zero")
            )


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
        _check_command_string(
            command, f"providers.{provider_name}.command", display_path, problems
        )
        _check_placeholders(
            command,
            f"providers.{provider_name}.command",
            _COMMAND_PLACEHOLDERS,
            display_path,
            problems,
        )

    args = _check_string_list(provider, "args", provider_name, display_path, problems)
    if args is not None:
        for index, item in enumerate(args):
            _check_placeholders(
                item,
                f"providers.{provider_name}.args[{index}]",
                _COMMAND_PLACEHOLDERS,
                display_path,
                problems,
            )

    prompt_args = _check_string_list(
        provider, "prompt_args", provider_name, display_path, problems
    )
    if prompt_args is None:
        prompt_args = []
    for index, item in enumerate(prompt_args):
        _check_placeholders(
            item,
            f"providers.{provider_name}.prompt_args[{index}]",
            _PROMPT_PLACEHOLDERS,
            display_path,
            problems,
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
            stdin_template = None
        elif not stdin_template.strip():
            problems.append(
                DoctorProblem(
                    display_path,
                    f"providers.{provider_name}.stdin_template must not be empty",
                )
            )
        else:
            _check_placeholders(
                stdin_template,
                f"providers.{provider_name}.stdin_template",
                _PROMPT_PLACEHOLDERS,
                display_path,
                problems,
            )

    version_command = provider.get("version_command")
    if version_command is not None:
        if not isinstance(version_command, str):
            problems.append(
                DoctorProblem(
                    display_path,
                    f"providers.{provider_name}.version_command must be a string",
                )
            )
        elif version_command:
            _check_command_string(
                version_command,
                f"providers.{provider_name}.version_command",
                display_path,
                problems,
            )
            _check_placeholders(
                version_command,
                f"providers.{provider_name}.version_command",
                _COMMAND_PLACEHOLDERS,
                display_path,
                problems,
            )
            _check_version_command_executable(
                provider_name, version_command, display_path, problems
            )

    effective_prompt_args = provider.get(
        "prompt_args", ["--system-prompt", "{system_prompt}", "{session_prompt}"]
    )
    if isinstance(effective_prompt_args, list) and all(
        isinstance(item, str) for item in effective_prompt_args
    ):
        _check_prompt_delivery(
            provider_name,
            cast("list[str]", effective_prompt_args),
            stdin_template if isinstance(stdin_template, str) else None,
            display_path,
            problems,
        )


def _check_string_list(
    provider: dict[str, Any],
    key: str,
    provider_name: str,
    display_path: str,
    problems: list[DoctorProblem],
) -> list[str] | None:
    value = provider.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        problems.append(
            DoctorProblem(
                display_path,
                f"providers.{provider_name}.{key} must be a list of strings",
            )
        )
        return None
    return cast("list[str]", value)


def _check_command_string(
    value: str, name: str, display_path: str, problems: list[DoctorProblem]
) -> None:
    if not value.strip():
        problems.append(DoctorProblem(display_path, f"{name} must not be empty"))
        return
    try:
        parts = shlex.split(value)
    except ValueError as exc:
        problems.append(
            DoctorProblem(display_path, f"{name} has invalid shell-style quoting: {exc}")
        )
        return
    if not parts:
        problems.append(DoctorProblem(display_path, f"{name} must not be empty"))
        return
    if any(_is_shell_operator(part) for part in parts):
        problems.append(
            DoctorProblem(
                display_path,
                f"{name} appears to use shell syntax; DevLab runs commands directly, "
                "not through a shell; use a wrapper script for shell setup",
            )
        )
    if parts[0] == "source" or _ENV_ASSIGNMENT.match(parts[0]):
        problems.append(
            DoctorProblem(
                display_path,
                f"{name} appears to require shell evaluation; DevLab runs commands directly, "
                "not through a shell; use a wrapper script or direct executable",
            )
        )


def _is_shell_operator(part: str) -> bool:
    return part in _SHELL_OPERATORS or part.startswith("$(") or "`" in part


def _check_prompt_delivery(
    provider_name: str,
    prompt_args: list[str],
    stdin_template: str | None,
    display_path: str,
    problems: list[DoctorProblem],
) -> None:
    delivered = set()
    for value in [*prompt_args, stdin_template or ""]:
        delivered.update(_placeholder_roots(value))
    missing = [
        placeholder
        for placeholder in ("system_prompt", "session_prompt")
        if placeholder not in delivered
    ]
    if missing:
        names = ", ".join(f"{{{name}}}" for name in missing)
        problems.append(
            DoctorProblem(
                display_path,
                f"providers.{provider_name} does not deliver required prompt "
                f"placeholder(s): {names}",
            )
        )


def _check_version_command_executable(
    provider_name: str,
    version_command: str,
    display_path: str,
    problems: list[DoctorProblem],
) -> None:
    try:
        parts = shlex.split(version_command)
    except ValueError:
        return
    if not parts or "{" in parts[0]:
        return
    executable = parts[0]
    if shutil.which(executable) is None:
        problems.append(
            DoctorProblem(
                display_path,
                f"providers.{provider_name}.version_command executable {executable!r} "
                "was not found on PATH",
            )
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


def _placeholder_roots(value: str) -> set[str]:
    roots: set[str] = set()
    try:
        for _, field_name, _, _ in string.Formatter().parse(value):
            if field_name is None:
                continue
            roots.add(field_name.split(".", 1)[0].split("[", 1)[0].split("!", 1)[0])
    except ValueError:
        return set()
    return roots


def _check_placeholders(
    value: str,
    name: str,
    supported_placeholders: set[str],
    display_path: str,
    problems: list[DoctorProblem],
) -> None:
    try:
        parsed = string.Formatter().parse(value)
        for _, field_name, _, _ in parsed:
            if field_name is None:
                continue
            root_name = field_name.split(".", 1)[0].split("[", 1)[0]
            if root_name not in supported_placeholders:
                problems.append(
                    DoctorProblem(
                        display_path,
                        f"{name} references unsupported placeholder {{{field_name}}}",
                    )
                )
    except ValueError as exc:
        problems.append(DoctorProblem(display_path, f"{name} has invalid template: {exc}"))

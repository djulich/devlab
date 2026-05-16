from __future__ import annotations

import dataclasses
import string
import tomllib
from pathlib import Path
from typing import Any, cast

from devlab.agent_config import AGENTS_CONFIG, ROLE_NAMES, load_agent_configuration
from devlab.findings import FileFindingTracker
from devlab.milestones import MILESTONE_ID_RE, MILESTONES_DIR, FileMilestoneTracker
from devlab.prompt_context import RolePromptContext, build_prompt_context_report
from devlab.task_tracker import FileTaskTracker
from devlab.workspace import Workspace, WorkspaceSnapshot

_SUPPORTED_PLACEHOLDERS = {
    "role_name",
    "provider",
    "model",
    "effort",
    "system_prompt",
    "session_prompt",
}


@dataclasses.dataclass(frozen=True)
class DoctorProblem:
    path: str
    message: str


def check_workspace(root: Path) -> list[DoctorProblem]:
    problems: list[DoctorProblem] = []
    agent_problems = _check_agents_config(root)
    problems.extend(agent_problems)
    if not agent_problems:
        problems.extend(_check_prompt_context_sizes(Workspace(root).snapshot()))
    problems.extend(_check_milestones(root))
    return problems


def format_doctor_report(problems: list[DoctorProblem]) -> str:
    if not problems:
        return "DevLab doctor: OK"
    lines = [f"DevLab doctor: {len(problems)} problem(s)"]
    lines.extend(f"- {problem.path}: {problem.message}" for problem in problems)
    return "\n".join(lines)


def _check_agents_config(root: Path) -> list[DoctorProblem]:
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
            load_agent_configuration(root)
        except (ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
            problems.append(DoctorProblem(display_path, str(exc)))
    return problems


def _check_prompt_context_sizes(snapshot: WorkspaceSnapshot) -> list[DoctorProblem]:
    try:
        report = build_prompt_context_report(snapshot)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
        return [DoctorProblem(".devlab", f"could not build prompt context report: {exc}")]
    problems: list[DoctorProblem] = []
    for role in report.roles:
        if role.status != "ok":
            problems.append(_prompt_context_problem(role))
    return problems


def _prompt_context_problem(role: RolePromptContext) -> DoctorProblem:
    total = _format_count(role.total.estimated_tokens)
    if role.status == "critical":
        threshold = _format_count(role.thresholds.critical_tokens)
        return DoctorProblem(
            ".devlab",
            f"{role.role_name} prompt context is critical: ~{total} tokens exceeds "
            f"critical threshold {threshold}",
        )
    threshold = _format_count(role.thresholds.warning_tokens)
    return DoctorProblem(
        ".devlab",
        f"{role.role_name} prompt context warning: ~{total} tokens exceeds "
        f"warning threshold {threshold}",
    )


def _check_milestones(root: Path) -> list[DoctorProblem]:
    problems: list[DoctorProblem] = []
    tasks = FileTaskTracker(root).list_tasks()
    task_by_id = {task.id: task for task in tasks}
    milestone_dir = root / MILESTONES_DIR
    milestone_files = sorted(milestone_dir.glob("M*.toml")) if milestone_dir.exists() else []
    milestone_by_id = {}
    seen_ids: dict[str, str] = {}

    for path in milestone_files:
        display_path = _display_path(path, root)
        if not MILESTONE_ID_RE.fullmatch(path.stem):
            problems.append(
                DoctorProblem(display_path, f"filename {path.name!r} is not a valid milestone ID")
            )
        try:
            milestone = FileMilestoneTracker(root).get(path.stem)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            problems.append(DoctorProblem(display_path, str(exc)))
            continue
        if milestone.id != path.stem:
            problems.append(
                DoctorProblem(
                    display_path,
                    f"id {milestone.id!r} does not match filename {path.stem!r}",
                )
            )
        if milestone.id in seen_ids:
            problems.append(
                DoctorProblem(
                    display_path,
                    f"duplicate milestone id {milestone.id!r}; first seen in "
                    f"{seen_ids[milestone.id]}",
                )
            )
        seen_ids[milestone.id] = display_path
        milestone_by_id[milestone.id] = milestone

    for task in tasks:
        if task.milestone is None:
            continue
        milestone = milestone_by_id.get(task.milestone)
        task_path = _display_path(task.path, root)
        if milestone is None:
            problems.append(
                DoctorProblem(task_path, f"references missing milestone {task.milestone!r}")
            )
        elif task.id not in milestone.task_ids:
            problems.append(
                DoctorProblem(
                    _display_path(milestone.path, root),
                    f"does not list task {task.id!r} referenced by {task_path}",
                )
            )

    finding_ids = {finding.id: finding for finding in FileFindingTracker(root).list_findings()}
    for milestone in milestone_by_id.values():
        display_path = _display_path(milestone.path, root)
        for task_id in milestone.task_ids:
            task = task_by_id.get(task_id)
            if task is None:
                problems.append(
                    DoctorProblem(display_path, f"task_ids references unknown task {task_id!r}")
                )
            elif task.milestone != milestone.id:
                problems.append(
                    DoctorProblem(
                        display_path,
                        f"task_ids references {task_id!r} but task milestone is "
                        f"{task.milestone!r}",
                    )
                )
        if milestone.integrated and not milestone.integration_handoff:
            problems.append(
                DoctorProblem(display_path, "integrated milestone is missing integration_handoff")
            )
        if milestone.architecture_approved and not milestone.integrated:
            problems.append(
                DoctorProblem(display_path, "architecture-approved milestone is not integrated")
            )
        if milestone.architecture_approved and not milestone.architecture_review_handoff:
            problems.append(
                DoctorProblem(
                    display_path,
                    "architecture-approved milestone is missing architecture_review_handoff",
                )
            )
        for finding_id in milestone.findings:
            finding = finding_ids.get(finding_id)
            if finding is None:
                problems.append(
                    DoctorProblem(
                        display_path,
                        f"findings references unknown finding {finding_id!r}",
                    )
                )
            elif finding.milestone != milestone.id:
                problems.append(
                    DoctorProblem(
                        display_path,
                        f"findings references {finding_id!r} but finding milestone is "
                        f"{finding.milestone!r}",
                    )
                )
    return problems


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


def _format_count(value: int) -> str:
    return f"{value:,}"


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


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

from __future__ import annotations

import dataclasses
import re
import tomllib
from pathlib import Path
from typing import Any, Literal, cast

from devlab.environment import EnvironmentConfig, EnvironmentTimeouts, _int_value, _string_tuple
from devlab.prerequisites import Prerequisite, PrerequisiteOperation
from devlab.task_tracker import Task

PROFILES_DIR = ".devlab/config/profiles"
DEFAULT_PROFILE = "default"
PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclasses.dataclass(frozen=True)
class ToolingConfig:
    summary: str = ""
    default_validation: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Profile:
    id: str
    title: str
    tooling: ToolingConfig = dataclasses.field(default_factory=ToolingConfig)
    environment: EnvironmentConfig = dataclasses.field(default_factory=EnvironmentConfig)
    prerequisites: tuple[Prerequisite, ...] = ()
    path: Path | None = None


@dataclasses.dataclass(frozen=True)
class EffectiveValidation:
    """Resolved validation contract for one task and profile."""

    source: Literal["task", "profile", "none"]
    commands: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class MilestoneValidationCommand:
    """One deduplicated milestone command with all task/profile provenance."""

    command: str
    task_ids: tuple[str, ...]
    sources: tuple[Literal["task", "profile"], ...]


@dataclasses.dataclass(frozen=True)
class EffectiveMilestoneValidation:
    commands: tuple[MilestoneValidationCommand, ...]


def effective_validation(task: Task, profile: Profile) -> EffectiveValidation:
    """Resolve task validation without executing commands or mutating state."""
    if task.validation is not None:
        return EffectiveValidation(
            source="task" if task.validation else "none",
            commands=task.validation,
        )
    if profile.tooling.default_validation:
        return EffectiveValidation(source="profile", commands=profile.tooling.default_validation)
    return EffectiveValidation(source="none", commands=())


def effective_milestone_validation(
    tasks: list[Task], profiles: dict[str, Profile], *, root: Path
) -> EffectiveMilestoneValidation:
    """Aggregate task contracts in stable order without changing precedence."""
    ordered: list[str] = []
    task_ids: dict[str, list[str]] = {}
    sources: dict[str, list[Literal["task", "profile"]]] = {}
    for task in tasks:
        profile = profile_from_snapshot(profiles, task.profile, root=root)
        validation = effective_validation(task, profile)
        if validation.source == "none":
            continue
        source = validation.source
        for command in validation.commands:
            if command not in task_ids:
                ordered.append(command)
                task_ids[command] = []
                sources[command] = []
            if task.id not in task_ids[command]:
                task_ids[command].append(task.id)
            if source not in sources[command]:
                sources[command].append(source)
    return EffectiveMilestoneValidation(
        tuple(
            MilestoneValidationCommand(command, tuple(task_ids[command]), tuple(sources[command]))
            for command in ordered
        )
    )


class ProfileNotFoundError(FileNotFoundError):
    def __init__(self, profile_id: str, path: Path) -> None:
        super().__init__(f"profile {profile_id!r} not found at {path}")
        self.profile_id = profile_id
        self.path = path


def effective_profile_id(profile_id: str | None) -> str:
    return profile_id or DEFAULT_PROFILE


def profile_path(root: Path, profile_id: str) -> Path:
    if not PROFILE_ID_RE.fullmatch(profile_id):
        raise ValueError(f"invalid profile id {profile_id!r}")
    return root / PROFILES_DIR / f"{profile_id}.toml"


def load_profile(root: Path, profile_id: str | None) -> Profile:
    resolved_id = effective_profile_id(profile_id)
    path = profile_path(root, resolved_id)
    if path.exists():
        return _read_profile(path, resolved_id)
    raise ProfileNotFoundError(resolved_id, path)


def load_profiles(root: Path) -> dict[str, Profile]:
    """Load every configured profile into one immutable-by-convention snapshot."""
    profiles_dir = root / PROFILES_DIR
    if not profiles_dir.exists():
        return {}
    return {
        path.stem: _read_profile(path, path.stem) for path in sorted(profiles_dir.glob("*.toml"))
    }


def profile_from_snapshot(
    profiles: dict[str, Profile], profile_id: str | None, *, root: Path
) -> Profile:
    resolved_id = effective_profile_id(profile_id)
    try:
        return profiles[resolved_id]
    except KeyError as exc:
        raise ProfileNotFoundError(resolved_id, profile_path(root, resolved_id)) from exc


def _read_profile(path: Path, expected_id: str) -> Profile:
    data = tomllib.loads(path.read_text())
    profile_id = str(data.get("id") or expected_id)
    if profile_id != expected_id:
        raise ValueError(
            f"profile id mismatch for {path}: expected {expected_id!r}, found {profile_id!r}"
        )
    title = str(data.get("title") or profile_id)
    tooling_data = _table(data, "tooling")
    environment_data = _table(data, "environment")
    timeouts_data = _table(data, "timeouts")
    prerequisites = _prerequisites(data.get("prerequisites", []), profile_id, path)
    return Profile(
        id=profile_id,
        title=title,
        tooling=ToolingConfig(
            summary=str(tooling_data.get("summary") or ""),
            default_validation=_string_tuple(tooling_data, "default_validation"),
        ),
        environment=EnvironmentConfig(
            managed_roles=_string_tuple(environment_data, "managed_roles"),
            pre_session=_string_tuple(environment_data, "pre_session"),
            setup=_string_tuple(environment_data, "setup"),
            post_session=_string_tuple(environment_data, "post_session"),
            timeouts=EnvironmentTimeouts(
                pre_session=_int_value(timeouts_data, "pre_session", 300),
                setup=_int_value(timeouts_data, "setup", 600),
                post_session=_int_value(timeouts_data, "post_session", 300),
            ),
        ),
        prerequisites=prerequisites,
        path=path,
    )


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"profile field {key!r} must be a table")
    return value


def _prerequisites(value: object, profile_id: str, path: Path) -> tuple[Prerequisite, ...]:
    if not isinstance(value, list):
        raise ValueError(f"profile prerequisites must be an array of tables: {path}")
    results: list[Prerequisite] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError(f"profile prerequisite must be a table: {path}")
        raw = cast("dict[str, Any]", raw)
        prerequisite_id = str(raw.get("id") or "")
        if not PROFILE_ID_RE.fullmatch(prerequisite_id) or prerequisite_id in seen:
            raise ValueError(f"invalid or duplicate prerequisite id {prerequisite_id!r}: {path}")
        seen.add(prerequisite_id)
        required = raw.get("required_for", [])
        if not isinstance(required, list) or not required:
            raise ValueError(f"prerequisite {prerequisite_id!r} requires required_for")
        try:
            required_for = tuple(PrerequisiteOperation(str(item)) for item in required)
        except ValueError as exc:
            raise ValueError(
                f"prerequisite {prerequisite_id!r} has invalid required_for: {path}"
            ) from exc
        if len(set(required_for)) != len(required_for):
            raise ValueError(f"prerequisite {prerequisite_id!r} repeats required_for values")
        check = str(raw.get("check") or "")
        environment = str(raw.get("environment") or "")
        attestation_value = raw.get("attestation", "")
        if not isinstance(attestation_value, str):
            raise ValueError(f"prerequisite {prerequisite_id!r} attestation must be a string")
        attestation = attestation_value
        if sum(bool(item) for item in (check, environment, attestation)) != 1:
            raise ValueError(
                f"prerequisite {prerequisite_id!r} must define exactly one of "
                f"check, environment, or attestation: {path}"
            )
        timeout = raw.get("timeout", 30)
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"prerequisite {prerequisite_id!r} timeout must be positive")
        if environment and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", environment):
            raise ValueError(f"prerequisite {prerequisite_id!r} has invalid environment variable")
        guide = str(raw.get("guide") or "")
        if guide:
            guide_path, separator, guide_heading = guide.partition("#")
            if (
                not guide_path
                or (separator and not guide_heading)
                or Path(guide_path).is_absolute()
                or ".." in Path(guide_path).parts
            ):
                raise ValueError(
                    f"prerequisite {prerequisite_id!r} guide must name a workspace-relative "
                    "file and optional Markdown heading"
                )
        results.append(
            Prerequisite(
                profile_id=profile_id,
                id=prerequisite_id,
                required_for=required_for,
                summary=str(raw.get("summary") or prerequisite_id),
                check=check,
                environment=environment,
                attestation=attestation,
                guide=guide,
                sensitive=bool(raw.get("sensitive", False)),
                timeout=timeout,
            )
        )
    return tuple(results)

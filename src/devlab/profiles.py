from __future__ import annotations

import dataclasses
import re
import tomllib
from pathlib import Path
from typing import Any

from devlab.environment import EnvironmentConfig, EnvironmentTimeouts, _int_value, _string_tuple

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
    path: Path | None = None


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
    if resolved_id == DEFAULT_PROFILE:
        return _legacy_default_profile(root)
    raise ProfileNotFoundError(resolved_id, path)


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
        path=path,
    )


def _legacy_default_profile(root: Path) -> Profile:
    """Compatibility profile backed by existing global environment config.

    This keeps repositories using only `.devlab/config/environment.toml` working while
    new repositories can put lifecycle and validation defaults in
    `.devlab/config/profiles/default.toml`.
    """
    return Profile(
        id=DEFAULT_PROFILE,
        title="Default",
        tooling=ToolingConfig(),
        environment=EnvironmentConfig.load(root),
        path=None,
    )


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"profile field {key!r} must be a table")
    return value

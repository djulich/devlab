from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shlex
import sys
from datetime import UTC, date, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from devlab._files import atomic_write_text
from devlab.agent_config import (
    AGENTS_CONFIG,
    AgentConfiguration,
    load_agent_configuration_data,
    resolve_agent_configuration,
)
from devlab.profiles import Profile, load_profiles

EXECUTABLE_CONFIG_SCHEMA = 2
TRUST_RECORD_SCHEMA = 1
DEVLAB_STATE_HOME_ENV = "DEVLAB_STATE_HOME"


class ExecutableConfigAuthorizationSource(StrEnum):
    STORED_TRUST = "stored_trust"
    EXPECTED_DIGEST = "expected_digest"
    ACCEPTED_CURRENT = "accepted_current"


@dataclasses.dataclass(frozen=True)
class ExecutableConfigAuthorization:
    source: ExecutableConfigAuthorizationSource
    digest: str


@dataclasses.dataclass(frozen=True)
class ExecutableConfigSnapshot:
    root: Path
    config_path: Path
    agent_data: dict[str, Any]
    profiles: dict[str, Profile]
    profile_texts: dict[str, str]
    provider_override: str | None
    model_override: str | None
    effort_override: str | None
    canonical_json: str
    digest: str
    authorization: ExecutableConfigAuthorization | None = None

    def resolve_agents(self, *, discover_provider_versions: bool = False) -> AgentConfiguration:
        return resolve_agent_configuration(
            self.agent_data,
            provider=self.provider_override,
            model=self.model_override,
            effort=self.effort_override,
            discover_provider_versions=discover_provider_versions,
        )


class ExecutableConfigTrustError(ValueError):
    pass


def build_executable_config_snapshot(
    root: Path,
    *,
    config_path: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> ExecutableConfigSnapshot:
    """Load and canonically fingerprint everything DevLab may execute."""
    resolved_root = root.resolve()
    resolved_config_path = (
        config_path.resolve()
        if config_path is not None
        else (resolved_root / AGENTS_CONFIG).resolve()
    )
    agent_data = load_agent_configuration_data(
        resolved_root,
        config_path=resolved_config_path if config_path is not None else None,
    )
    resolve_agent_configuration(
        agent_data,
        provider=provider,
        model=model,
        effort=effort,
        discover_provider_versions=False,
    )
    profiles = load_profiles(resolved_root)
    profile_texts = {
        profile_id: profile.path.read_text()
        for profile_id, profile in profiles.items()
        if profile.path is not None
    }
    payload = {
        "schema": EXECUTABLE_CONFIG_SCHEMA,
        "agents": {
            "defaults": agent_data.get("defaults", {}),
            "roles": agent_data.get("roles", {}),
            "providers": agent_data.get("providers", {}),
            "overrides": {
                "provider": provider,
                "model": model,
                "effort": effort,
            },
        },
        "profiles": {
            profile_id: {
                "default_validation": list(profile.tooling.default_validation),
                "managed_roles": list(profile.environment.managed_roles),
                "pre_session": list(profile.environment.pre_session),
                "setup": list(profile.environment.setup),
                "post_session": list(profile.environment.post_session),
                "timeouts": {
                    "pre_session": profile.environment.timeouts.pre_session,
                    "setup": profile.environment.timeouts.setup,
                    "post_session": profile.environment.timeouts.post_session,
                },
            }
            for profile_id, profile in sorted(profiles.items())
        },
    }
    canonical_json = json.dumps(
        _json_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    checksum = hashlib.sha256(canonical_json.encode()).hexdigest()
    return ExecutableConfigSnapshot(
        root=resolved_root,
        config_path=resolved_config_path,
        agent_data=agent_data,
        profiles=profiles,
        profile_texts=profile_texts,
        provider_override=provider,
        model_override=model,
        effort_override=effort,
        canonical_json=canonical_json,
        digest=f"exec-v{EXECUTABLE_CONFIG_SCHEMA}:{checksum}",
    )


def authorize_executable_config(
    snapshot: ExecutableConfigSnapshot,
    *,
    expected_digest: str | None = None,
    accept_current: bool = False,
) -> ExecutableConfigAuthorization:
    if expected_digest is not None and accept_current:
        raise ExecutableConfigTrustError(
            "expected digest and acceptance of current configuration are mutually exclusive"
        )
    if expected_digest is not None:
        if expected_digest != snapshot.digest:
            raise ExecutableConfigTrustError(
                "executable configuration digest mismatch: "
                f"expected {expected_digest}, current {snapshot.digest}"
            )
        return ExecutableConfigAuthorization(
            ExecutableConfigAuthorizationSource.EXPECTED_DIGEST,
            snapshot.digest,
        )
    if accept_current:
        return ExecutableConfigAuthorization(
            ExecutableConfigAuthorizationSource.ACCEPTED_CURRENT,
            snapshot.digest,
        )
    if executable_config_is_trusted(snapshot):
        return ExecutableConfigAuthorization(
            ExecutableConfigAuthorizationSource.STORED_TRUST,
            snapshot.digest,
        )
    raise ExecutableConfigTrustError(
        "executable configuration is not trusted for this workspace "
        f"(current fingerprint: {snapshot.digest}); review and authorize it with "
        "'devlab trust executable-config'"
    )


def trust_executable_config(snapshot: ExecutableConfigSnapshot) -> Path:
    record_path = executable_config_trust_record_path(snapshot)
    record = {
        "version": TRUST_RECORD_SCHEMA,
        "workspace": str(snapshot.root),
        "config_path": str(snapshot.config_path),
        "digest": snapshot.digest,
        "trusted_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_text(record_path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record_path


def revoke_executable_config_trust(snapshot: ExecutableConfigSnapshot) -> bool:
    path = executable_config_trust_record_path(snapshot)
    if not path.exists():
        return False
    path.unlink()
    return True


def executable_config_is_trusted(snapshot: ExecutableConfigSnapshot) -> bool:
    path = executable_config_trust_record_path(snapshot)
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, OSError, ValueError):
        return False
    return (
        isinstance(data, dict)
        and data.get("version") == TRUST_RECORD_SCHEMA
        and data.get("workspace") == str(snapshot.root)
        and data.get("config_path") == str(snapshot.config_path)
        and data.get("digest") == snapshot.digest
    )


def executable_config_trust_record_path(snapshot: ExecutableConfigSnapshot) -> Path:
    identity = json.dumps(
        {
            "workspace": str(snapshot.root),
            "config_path": str(snapshot.config_path),
            "digest": snapshot.digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    record_id = hashlib.sha256(identity.encode()).hexdigest()
    return devlab_state_home() / "trusted-executable-configs" / f"{record_id}.json"


def devlab_state_home() -> Path:
    override = os.environ.get(DEVLAB_STATE_HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base).expanduser() / "DevLab" if base else Path.home() / "AppData/Local/DevLab"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/DevLab"
    xdg_state = os.environ.get("XDG_STATE_HOME")
    return (
        Path(xdg_state).expanduser() / "devlab"
        if xdg_state
        else Path.home() / ".local/state/devlab"
    )


def format_executable_config(snapshot: ExecutableConfigSnapshot) -> str:
    configuration = snapshot.resolve_agents()
    lines = [
        "Executable configuration",
        f"Workspace: {snapshot.root}",
        f"Agent config: {snapshot.config_path}",
        f"Fingerprint: {snapshot.digest}",
        "Trust status: "
        + ("trusted" if executable_config_is_trusted(snapshot) else "not trusted"),
        "",
        "Agent providers:",
    ]
    seen_commands: set[tuple[str, ...]] = set()
    assigned_provider_names: set[str] = set()
    for role_name in sorted(configuration.resolved):
        config = configuration.resolved[role_name]
        assigned_provider_names.add(config.provider)
        if config.command in seen_commands:
            continue
        seen_commands.add(config.command)
        roles = sorted(
            role
            for role, candidate in configuration.resolved.items()
            if candidate.command == config.command
        )
        lines.extend(
            [
                f"- {config.provider}: {shlex.join(config.command)}",
                "  roles: " + ", ".join(roles),
            ]
        )
    providers_data = snapshot.agent_data.get("providers", {})
    if isinstance(providers_data, dict):
        for provider_name, provider_data in sorted(providers_data.items()):
            if not isinstance(provider_name, str) or not isinstance(provider_data, dict):
                continue
            provider_table = cast("dict[str, Any]", provider_data)
            command = provider_table.get("command")
            args = provider_table.get("args", [])
            if (
                provider_name not in assigned_provider_names
                and isinstance(command, str)
                and isinstance(args, list)
                and all(isinstance(item, str) for item in args)
            ):
                lines.extend(
                    [
                        f"- {provider_name}: {shlex.join([*shlex.split(command), *args])}",
                        "  roles: none",
                    ]
                )
            version_command = provider_table.get("version_command")
            if isinstance(version_command, str) and version_command:
                lines.append(f"  version discovery for {provider_name}: {version_command}")
    lifecycle_lines = []
    validation_lines = []
    for profile_id, profile in sorted(snapshot.profiles.items()):
        for command in profile.tooling.default_validation:
            validation_lines.append(f"- {profile_id}: {command}")
        for phase in ("pre_session", "setup", "post_session"):
            commands = getattr(profile.environment, phase)
            for command in commands:
                lifecycle_lines.append(f"- {profile_id}.{phase}: {command}")
    lines.extend(["", "Profile default validation commands:"])
    lines.extend(validation_lines or ["- None"])
    lines.extend(["", "Profile lifecycle commands:"])
    lines.extend(lifecycle_lines or ["- None"])
    lines.extend(
        [
            "",
            "Provider permission, sandbox, authentication, and network policy are operator-owned.",
            "Trust covers configured process entry points, not the transitive behavior "
            "of commands they invoke.",
        ]
    )
    return "\n".join(lines)


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"executable configuration contains unsupported value {value!r}")

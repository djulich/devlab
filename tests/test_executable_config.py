from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devlab.executable_config import (
    ExecutableConfigAuthorizationSource,
    ExecutableConfigTrustError,
    authorize_executable_config,
    build_executable_config_snapshot,
    executable_config_is_trusted,
    revoke_executable_config_trust,
    trust_executable_config,
)
from devlab.init import init_workspace


def test_snapshot_digest_is_canonical_and_tracks_executable_values(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    initial = build_executable_config_snapshot(tmp_path)
    agents_path = tmp_path / ".devlab/config/agents.toml"
    agents_path.write_text("# formatting-only comment\n" + agents_path.read_text())

    reformatted = build_executable_config_snapshot(tmp_path)

    assert reformatted.digest == initial.digest

    profile_path = tmp_path / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text().replace('setup = []', 'setup = ["uv sync"]')
    )

    changed = build_executable_config_snapshot(tmp_path)

    assert changed.digest != initial.digest


def test_snapshot_digest_includes_invocation_overrides(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    default = build_executable_config_snapshot(tmp_path)
    overridden = build_executable_config_snapshot(
        tmp_path, provider="default", model="different", effort="high"
    )

    assert overridden.digest != default.digest


def test_snapshot_keeps_provider_and_profile_configuration_frozen(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    snapshot = build_executable_config_snapshot(tmp_path)
    agents_path = tmp_path / ".devlab/config/agents.toml"
    agents_path.write_text(agents_path.read_text().replace('command = "claude"', 'command = "pi"'))
    profile_path = tmp_path / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text().replace('setup = []', 'setup = ["changed setup"]')
    )

    configuration = snapshot.resolve_agents()

    assert configuration.resolved["developer"].command[0] == "claude"
    assert snapshot.profiles["default"].environment.setup == ()


def test_snapshot_does_not_execute_configured_version_discovery_before_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_workspace(tmp_path)
    agents_path = tmp_path / ".devlab/config/agents.toml"
    agents_path.write_text(
        agents_path.read_text().replace(
            'command = "claude"',
            'command = "claude"\nversion_command = "configured-version --version"',
            1,
        )
    )
    calls: list[object] = []

    def fake_run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(["configured-version"], 0, "v1\n", "")

    monkeypatch.setattr("devlab.agent_config.subprocess.run", fake_run)

    snapshot = build_executable_config_snapshot(tmp_path)

    assert calls == []

    snapshot.resolve_agents(discover_provider_versions=True)

    assert calls


def test_operator_local_trust_is_workspace_and_digest_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_home = tmp_path / "operator-state"
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(state_home))
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    init_workspace(first_root)
    init_workspace(second_root)
    first = build_executable_config_snapshot(first_root)
    second = build_executable_config_snapshot(second_root)

    record = trust_executable_config(first)

    assert record.is_relative_to(state_home)
    assert executable_config_is_trusted(first)
    assert not executable_config_is_trusted(second)
    assert authorize_executable_config(first).source == (
        ExecutableConfigAuthorizationSource.STORED_TRUST
    )

    profile_path = first_root / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text().replace('setup = []', 'setup = ["make setup"]')
    )
    changed = build_executable_config_snapshot(first_root)

    assert not executable_config_is_trusted(changed)
    with pytest.raises(ExecutableConfigTrustError, match="not trusted"):
        authorize_executable_config(changed)


def test_expected_digest_and_explicit_acceptance_are_ephemeral(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    snapshot = build_executable_config_snapshot(tmp_path)

    expected = authorize_executable_config(snapshot, expected_digest=snapshot.digest)
    accepted = authorize_executable_config(snapshot, accept_current=True)

    assert expected.source == ExecutableConfigAuthorizationSource.EXPECTED_DIGEST
    assert accepted.source == ExecutableConfigAuthorizationSource.ACCEPTED_CURRENT
    assert not executable_config_is_trusted(snapshot)
    with pytest.raises(ExecutableConfigTrustError, match="digest mismatch"):
        authorize_executable_config(snapshot, expected_digest="exec-v1:wrong")


def test_revoke_removes_workspace_trust_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "state"))
    init_workspace(tmp_path / "target")
    snapshot = build_executable_config_snapshot(tmp_path / "target")
    trust_executable_config(snapshot)

    assert revoke_executable_config_trust(snapshot)
    assert not executable_config_is_trusted(snapshot)
    assert not revoke_executable_config_trust(snapshot)

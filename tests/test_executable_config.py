from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from devlab.executable_config import (
    ExecutableConfigAuthorizationSource,
    ExecutableConfigTrustError,
    authorize_executable_config,
    build_executable_config_snapshot,
    executable_config_is_trusted,
    format_executable_config,
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
    profile_path.write_text(profile_path.read_text().replace("setup = []", 'setup = ["uv sync"]'))

    changed = build_executable_config_snapshot(tmp_path)

    assert changed.digest != initial.digest


def test_snapshot_digest_includes_invocation_overrides(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    default = build_executable_config_snapshot(tmp_path)
    overridden = build_executable_config_snapshot(
        tmp_path, provider="default", model="different", effort="high"
    )

    assert overridden.digest != default.digest


def test_snapshot_digest_includes_session_limits(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    initial = build_executable_config_snapshot(tmp_path)
    agents_path = tmp_path / ".devlab/config/agents.toml"
    agents_path.write_text(
        agents_path.read_text().replace(
            "# inactivity_timeout_seconds = 600",
            "inactivity_timeout_seconds = 600",
        )
    )

    changed = build_executable_config_snapshot(tmp_path)

    assert changed.digest != initial.digest


def test_snapshot_digest_includes_profile_default_validation(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    initial = build_executable_config_snapshot(tmp_path)
    profile_path = tmp_path / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text().replace(
            "default_validation = []",
            'default_validation = ["make check"]',
        )
    )

    changed = build_executable_config_snapshot(tmp_path)

    assert changed.digest != initial.digest


def test_snapshot_digest_tracks_prerequisite_semantics_but_not_help_text(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    profile_path = tmp_path / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text()
        + "\n[[prerequisites]]\n"
        + 'id = "docker"\n'
        + 'required_for = ["validation"]\n'
        + 'check = "docker info"\n'
        + 'summary = "Docker is available."\n'
        + 'guide = ".devlab/config/prerequisites/docker.md"\n'
    )
    initial = build_executable_config_snapshot(tmp_path)
    profile_path.write_text(
        profile_path.read_text()
        .replace("Docker is available.", "Docker Engine is reachable.")
        .replace("docker.md", "docker-engine.md")
    )

    help_changed = build_executable_config_snapshot(tmp_path)
    profile_path.write_text(profile_path.read_text().replace("docker info", "podman info"))
    command_changed = build_executable_config_snapshot(tmp_path)

    profile_path.write_text(
        profile_path.read_text()
        + 'prepare = "make prepare-docker"\n'
        + 'prepare_kind = "workspace_local"\n'
        + 'prepare_outputs = [".local/docker"]\n'
    )
    preparation_changed = build_executable_config_snapshot(tmp_path)

    assert help_changed.digest == initial.digest
    assert command_changed.digest != initial.digest
    assert preparation_changed.digest != command_changed.digest


def test_format_executable_config_separates_profile_validation_and_lifecycle(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    profile_path = tmp_path / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text()
        .replace("default_validation = []", 'default_validation = ["make check"]')
        .replace("setup = []", 'setup = ["make setup"]')
    )

    text = format_executable_config(build_executable_config_snapshot(tmp_path))

    assert "Profile default validation commands:\n- default: make check" in text
    assert "Profile lifecycle commands:\n- default.setup: make setup" in text


def test_snapshot_keeps_provider_and_profile_configuration_frozen(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    snapshot = build_executable_config_snapshot(tmp_path)
    agents_path = tmp_path / ".devlab/config/agents.toml"
    agents_path.write_text(agents_path.read_text().replace('command = "claude"', 'command = "pi"'))
    profile_path = tmp_path / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text().replace("setup = []", 'setup = ["changed setup"]')
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
        profile_path.read_text().replace("setup = []", 'setup = ["make setup"]')
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


def test_trust_review_shows_changes_and_keeps_display_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "target"
    init_workspace(root)
    initial = build_executable_config_snapshot(root)
    assert "No previous approval found" in format_executable_config(initial)
    record = trust_executable_config(initial)
    saved = record.read_text()
    assert "No executable configuration changes." in format_executable_config(initial)

    profile_path = root / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text().replace("setup = []", 'setup = ["make setup"]')
    )
    changed = build_executable_config_snapshot(root, model="new-model")
    output = format_executable_config(changed)
    assert "Changes since last trust:" not in output
    assert "- default.setup: make setup  [NEW]" in output
    assert "--- last trusted" not in output
    assert record.read_text() == saved
    assert not executable_config_is_trusted(changed)

    trust_executable_config(changed)
    reverted = format_executable_config(initial)
    assert "Profile lifecycle commands:\n- None\nREMOVED:\n- default.setup: make setup" in reverted
    assert executable_config_is_trusted(initial)


@pytest.mark.parametrize("legacy", [True, False])
def test_trust_review_handles_missing_or_corrupt_saved_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "state"))
    init_workspace(tmp_path / "target")
    snapshot = build_executable_config_snapshot(tmp_path / "target")
    path = trust_executable_config(snapshot)
    record = json.loads(path.read_text())
    if legacy:
        del record["canonical_json"]
    else:
        record["canonical_json"] = "{}"
    path.write_text(json.dumps(record))

    assert "Comparison unavailable:" in format_executable_config(snapshot)
    assert executable_config_is_trusted(snapshot)


def test_trust_review_ignores_other_scopes_and_malformed_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "target"
    init_workspace(root)
    snapshot = build_executable_config_snapshot(root)
    original_path = trust_executable_config(snapshot)
    init_workspace(tmp_path / "other")
    trust_executable_config(build_executable_config_snapshot(tmp_path / "other"))
    alternate_config = root / "alternate.toml"
    alternate_config.write_text((root / ".devlab/config/agents.toml").read_text())
    trust_executable_config(
        build_executable_config_snapshot(root, config_path=alternate_config, model="other-model")
    )
    (original_path.parent / "broken.json").write_text("invalid json")
    (original_path.parent / "invalid.json").write_text("[1, 2]")

    assert "No executable configuration changes." in format_executable_config(snapshot)


def test_trust_review_marks_resolved_provider_commands_and_role_assignments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "state"))
    init_workspace(tmp_path / "target")
    root = tmp_path / "target"
    agents_path = root / ".devlab/config/agents.toml"
    agents_path.write_text(
        '[defaults]\nprovider = "codex"\nmodel = "model-one"\neffort = "medium"\n'
        '[providers.codex]\ncommand = "codex"\n'
        'args = ["--model", "{model}", "--effort", "{effort}", "exec", "-"]\n'
        'stdin_template = "{system_prompt}\\n{session_prompt}"\n'
        '[roles.developer]\neffort = "high"\n'
        '[roles.integrator]\neffort = "low"\n'
    )
    trust_executable_config(build_executable_config_snapshot(root))
    agents_path.write_text(agents_path.read_text().replace('effort = "low"', 'effort = "high"'))
    output = format_executable_config(build_executable_config_snapshot(root))

    assert "- codex: codex --model model-one --effort high exec -  [NEW]\n" in output
    provider_section = output.split("Agent providers:\n", 1)[1].split("\nREMOVED:", 1)[0]
    provider_lines = provider_section.splitlines()
    assert "  roles: developer, integrator" in provider_lines
    assert not any("roles:" in line and "[NEW]" in line for line in provider_lines)
    assert (
        "REMOVED:\n- codex: codex --model model-one --effort high exec -\n  roles: developer"
        in output
    )
    assert "- codex: codex --model model-one --effort low exec -\n  roles: integrator" in output
    assert not any("roles: architect" in line and "[NEW]" in line for line in provider_lines)


def test_trust_review_compares_validation_entries_without_marking_reordering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "target"
    init_workspace(root)
    profile_path = root / ".devlab/config/profiles/default.toml"
    profile_path.write_text(
        profile_path.read_text().replace(
            "default_validation = []", 'default_validation = ["ruff check", "ty check"]'
        )
    )
    trust_executable_config(build_executable_config_snapshot(root))
    profile_path.write_text(
        profile_path.read_text().replace('["ruff check", "ty check"]', '["ty check", "pytest"]')
    )
    output = format_executable_config(build_executable_config_snapshot(root))
    assert (
        "Profile default validation commands:\n- default: ty check\n"
        "- default: pytest  [NEW]\nREMOVED:\n- default: ruff check\n"
    ) in output
    trust_executable_config(build_executable_config_snapshot(root))
    profile_path.write_text(
        profile_path.read_text().replace('["ty check", "pytest"]', '["pytest", "ty check"]')
    )
    reordered = format_executable_config(build_executable_config_snapshot(root))
    assert "[NEW]" not in reordered
    assert "REMOVED:" not in reordered
    assert "Fingerprint changed, but displayed entries are unchanged." in reordered


def test_trust_review_reports_fingerprint_changes_outside_displayed_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "state"))
    init_workspace(tmp_path / "target")
    root = tmp_path / "target"
    trust_executable_config(build_executable_config_snapshot(root))
    agents_path = root / ".devlab/config/agents.toml"
    agents_path.write_text(
        agents_path.read_text().replace(
            "max_session_duration_seconds = 3600", "max_session_duration_seconds = 2400"
        )
    )
    output = format_executable_config(build_executable_config_snapshot(root))
    assert "Fingerprint changed, but displayed entries are unchanged." in output
    assert "[NEW]" not in output
    assert "REMOVED:" not in output


def test_trust_review_aligns_new_markers_within_each_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "state"))
    init_workspace(tmp_path / "target")
    root = tmp_path / "target"
    profile_path = root / ".devlab/config/profiles/default.toml"
    original = profile_path.read_text().replace(
        "default_validation = []", 'default_validation = ["a-long-unchanged-command"]'
    )
    profile_path.write_text(original)
    trust_executable_config(build_executable_config_snapshot(root))
    profile_path.write_text(
        original.replace(
            '["a-long-unchanged-command"]',
            '["short", "a-long-unchanged-command", "medium-command"]',
        ).replace("setup = []", 'setup = ["setup"]')
    )
    output = format_executable_config(build_executable_config_snapshot(root))
    marker_column = len("- default: medium-command") + 2
    assert "- default: short".ljust(marker_column) + "[NEW]" in output
    assert "- default: medium-command".ljust(marker_column) + "[NEW]" in output
    assert "- default: a-long-unchanged-command\n" in output
    assert "- default.setup: setup  [NEW]\n" in output

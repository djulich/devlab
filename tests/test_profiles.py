from __future__ import annotations

from pathlib import Path

import pytest

from devlab.profiles import ProfileNotFoundError, effective_profile_id, load_profile


def test_omitted_profile_resolves_to_default() -> None:
    assert effective_profile_id(None) == "default"
    assert effective_profile_id("api") == "api"


def test_loads_profile_tooling_and_environment(tmp_path: Path) -> None:
    profiles = tmp_path / ".devlab/config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "api.toml").write_text(
        'version = 1\n'
        'id = "api"\n'
        'title = "API"\n'
        '\n[tooling]\n'
        'summary = "Python API"\n'
        'default_validation = ["uv run pytest tests/api"]\n'
        '\n[environment]\n'
        'managed_roles = ["developer"]\n'
        'pre_session = ["echo pre"]\n'
        'setup = ["uv sync"]\n'
        'post_session = ["echo post"]\n'
        '\n[timeouts]\n'
        'setup = 42\n'
    )

    profile = load_profile(tmp_path, "api")

    assert profile.id == "api"
    assert profile.title == "API"
    assert profile.tooling.summary == "Python API"
    assert profile.tooling.default_validation == ("uv run pytest tests/api",)
    assert profile.environment.managed_roles == ("developer",)
    assert profile.environment.setup == ("uv sync",)
    assert profile.environment.timeouts.setup == 42


def test_missing_sections_default_to_empty_noop(tmp_path: Path) -> None:
    profiles = tmp_path / ".devlab/config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "docs.toml").write_text('version = 1\nid = "docs"\n')

    profile = load_profile(tmp_path, "docs")

    assert profile.tooling.default_validation == ()
    assert profile.environment.managed_roles == ()
    assert profile.environment.setup == ()


def test_default_profile_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ProfileNotFoundError, match="default"):
        load_profile(tmp_path, None)


def test_named_missing_profile_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProfileNotFoundError, match="api"):
        load_profile(tmp_path, "api")


def test_rejects_invalid_profile_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid profile id"):
        load_profile(tmp_path, "../api")


def test_rejects_profile_id_mismatch(tmp_path: Path) -> None:
    profiles = tmp_path / ".devlab/config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "api.toml").write_text('version = 1\nid = "other"\n')

    with pytest.raises(ValueError, match="id mismatch"):
        load_profile(tmp_path, "api")

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devlab.git import VersionControlError
from devlab.init import format_init_result, init_workspace


def test_init_workspace_creates_devlab_layout(tmp_path: Path) -> None:
    result = init_workspace(tmp_path)

    expected_files = [
        ".devlab/manifest.toml",
        ".devlab/config/README.md",
        ".devlab/config/tooling.md",
        ".devlab/config/agents.toml",
        ".devlab/config/profiles/default.toml",
        ".devlab/specs/system/README.md",
        ".devlab/specs/deployment/README.md",
        ".devlab/plans/design-plan.md",
        ".devlab/plans/project-plan.md",
        ".devlab/tasks/.gitkeep",
        ".devlab/milestones/.gitkeep",
        ".devlab/findings/.gitkeep",
        ".devlab/history/.gitkeep",
        ".devlab/logs/environment/.gitkeep",
        ".devlab/logs/deployment/.gitkeep",
        ".devlab/logs/agents/.gitkeep",
        ".devlab/session-artifacts/.gitkeep",
    ]
    for relative in expected_files:
        assert (tmp_path / relative).exists(), relative

    assert 'layout_version = 1' in (tmp_path / ".devlab/manifest.toml").read_text()
    assert 'id = "default"' in (tmp_path / ".devlab/config/profiles/default.toml").read_text()
    assert '[providers.default]' in (tmp_path / ".devlab/config/agents.toml").read_text()
    assert result.created
    assert not result.overwritten


def test_init_workspace_is_non_destructive_by_default(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    tooling = tmp_path / ".devlab/config/tooling.md"
    tooling.write_text("custom tooling\n")

    result = init_workspace(tmp_path)

    assert tooling.read_text() == "custom tooling\n"
    assert tooling in result.skipped
    assert not result.overwritten


def test_init_workspace_force_overwrites_starter_files(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    tooling = tmp_path / ".devlab/config/tooling.md"
    tooling.write_text("custom tooling\n")

    result = init_workspace(tmp_path, force=True)

    assert tooling.read_text().startswith("# Tooling Policy")
    assert tooling in result.overwritten


def test_format_init_result_uses_relative_paths(tmp_path: Path) -> None:
    result = init_workspace(tmp_path)

    text = format_init_result(result, tmp_path)

    assert "created: .devlab/manifest.toml" in text
    assert str(tmp_path) not in text


def test_init_workspace_can_initialize_git_and_commit_baseline(tmp_path: Path) -> None:
    init_workspace(
        tmp_path,
        automatic_git=True,
        git_user_name="DevLab Test",
        git_user_email="devlab-test@example.invalid",
    )

    assert (tmp_path / ".git").exists()
    assert _git(tmp_path, "status", "--porcelain").stdout.strip() == ""
    assert _git(tmp_path, "log", "-1", "--pretty=%s").stdout.strip() == (
        "Initialize DevLab workspace"
    )
    assert _git(tmp_path, "config", "--get", "user.name").stdout.strip() == "DevLab Test"
    assert _git(tmp_path, "config", "--get", "user.email").stdout.strip() == (
        "devlab-test@example.invalid"
    )


def test_init_workspace_commits_existing_clean_git_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Existing User")
    _git(tmp_path, "config", "user.email", "existing@example.invalid")
    _git(tmp_path, "commit", "--allow-empty", "-m", "Existing baseline")

    init_workspace(tmp_path, automatic_git=True)

    assert _git(tmp_path, "status", "--porcelain").stdout.strip() == ""
    assert _git(tmp_path, "log", "-1", "--pretty=%s").stdout.strip() == (
        "Initialize DevLab workspace"
    )
    assert _git(tmp_path, "config", "--get", "user.name").stdout.strip() == (
        "Existing User"
    )


def test_init_workspace_rejects_dirty_existing_git_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Existing User")
    _git(tmp_path, "config", "user.email", "existing@example.invalid")
    _git(tmp_path, "commit", "--allow-empty", "-m", "Existing baseline")
    (tmp_path / "dirty.txt").write_text("dirty\n")

    with pytest.raises(VersionControlError, match="working tree is dirty"):
        init_workspace(tmp_path, automatic_git=True)

    assert not (tmp_path / ".devlab").exists()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        text=True,
        capture_output=True,
        check=True,
    )

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devlab.version_control import VersionControlError, assert_clean_worktree, commit_all, tag


def test_commit_all_commits_non_ignored_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "tracked.txt").write_text("tracked\n")
    (tmp_path / "ignored.txt").write_text("ignored\n")

    committed = commit_all(tmp_path, "Commit tracked file")

    assert committed is True
    assert _git(tmp_path, "log", "-1", "--pretty=%s").stdout.strip() == "Commit tracked file"
    assert "tracked.txt" in _git(tmp_path, "ls-files").stdout
    assert "ignored.txt" not in _git(tmp_path, "ls-files").stdout


def test_assert_clean_worktree_ignores_ignored_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    commit_all(tmp_path, "Add gitignore")
    (tmp_path / "ignored.txt").write_text("ignored\n")

    assert_clean_worktree(tmp_path)


def test_assert_clean_worktree_rejects_unignored_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "untracked.txt").write_text("untracked\n")

    with pytest.raises(VersionControlError, match="working tree is dirty"):
        assert_clean_worktree(tmp_path)


def test_tag_creates_annotated_tag(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("content\n")
    commit_all(tmp_path, "Initial commit")

    tag(tmp_path, "devlab/milestone/M1", "Milestone M1 integrated")

    assert _git(tmp_path, "tag", "--list", "devlab/milestone/M1").stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "devlab-test@example.invalid")
    _git(root, "config", "user.name", "DevLab Test")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        text=True,
        capture_output=True,
        check=True,
    )

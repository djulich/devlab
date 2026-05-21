from __future__ import annotations

import subprocess
from pathlib import Path


class VersionControlError(RuntimeError):
    """Raised when DevLab cannot perform required Git operations."""


def ensure_git_repository(root: Path) -> None:
    _run_git(root, "rev-parse", "--show-toplevel")


def assert_clean_worktree(root: Path) -> None:
    status = _run_git(root, "status", "--porcelain").stdout.strip()
    if status:
        raise VersionControlError(
            "working tree is dirty; commit, stash, or ignore changes before running DevLab"
        )


def commit_all(root: Path, message: str) -> bool:
    _run_git(root, "add", "-A")
    if not _run_git(root, "status", "--porcelain").stdout.strip():
        return False
    _run_git(root, "commit", "-m", message)
    return True


def tag(root: Path, name: str, message: str) -> None:
    _run_git(root, "tag", "-a", name, "-m", message)


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise VersionControlError(
            f"git command failed: git -C {root.as_posix()} {' '.join(args)}"
            + (f": {detail}" if detail else "")
        )
    return result

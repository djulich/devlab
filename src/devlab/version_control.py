from __future__ import annotations

import subprocess
from pathlib import Path


class VersionControlError(RuntimeError):
    """Raised when DevLab cannot perform required Git operations."""


DEFAULT_GIT_USER_NAME = "DevLab"
DEFAULT_GIT_USER_EMAIL = "devlab@example.invalid"


def has_git_repository(root: Path) -> bool:
    return (root / ".git").exists()


def init_repository(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _run_git(root, "init")


def ensure_git_repository(root: Path) -> None:
    _run_git(root, "rev-parse", "--show-toplevel")


def ensure_git_identity(
    root: Path,
    *,
    user_name: str | None = None,
    user_email: str | None = None,
) -> None:
    current_name = git_config(root, "user.name")
    current_email = git_config(root, "user.email")
    resolved_name = user_name or current_name or DEFAULT_GIT_USER_NAME
    resolved_email = user_email or current_email or DEFAULT_GIT_USER_EMAIL
    if user_name is not None or not current_name:
        _run_git(root, "config", "user.name", resolved_name)
    if user_email is not None or not current_email:
        _run_git(root, "config", "user.email", resolved_email)


def git_config(root: Path, key: str) -> str:
    result = subprocess.run(
        ["git", "-C", root.as_posix(), "config", "--get", key],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


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

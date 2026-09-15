from __future__ import annotations

import subprocess
from pathlib import Path

from devlab.git import VersionControlError, run_git

DEFAULT_GIT_USER_NAME = "DevLab"
DEFAULT_GIT_USER_EMAIL = "devlab@example.invalid"


def has_git_repository(root: Path) -> bool:
    return (root / ".git").exists()


def init_repository(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    run_git(root, "init")


def ensure_git_repository(root: Path) -> None:
    run_git(root, "rev-parse", "--show-toplevel")


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
        run_git(root, "config", "user.name", resolved_name)
    if user_email is not None or not current_email:
        run_git(root, "config", "user.email", resolved_email)


def git_config(root: Path, key: str) -> str:
    result = subprocess.run(
        ["git", "-C", root.as_posix(), "config", "--get", key],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def assert_clean_worktree(root: Path) -> None:
    status = run_git(root, "status", "--porcelain").stdout.strip()
    if status:
        raise VersionControlError(
            "working tree is dirty; commit, stash, or ignore changes before running DevLab"
        )


def commit_all(root: Path, message: str) -> bool:
    run_git(root, "add", "-A")
    if not run_git(root, "status", "--porcelain").stdout.strip():
        return False
    run_git(root, "commit", "-m", message)
    return True


def tag(root: Path, name: str, message: str) -> None:
    run_git(root, "tag", "-f", "-a", name, "-m", message)


def commit_clarification_answer(root: Path, clarification_id: str, path: Path) -> None:
    """Commit one operator answer without including unrelated staged or unstaged work."""
    relative = path.relative_to(root).as_posix()
    run_git(root, "add", "--", relative)
    run_git(
        root,
        "commit",
        "--only",
        "-m",
        f"Answer DevLab clarification {clarification_id}",
        "--",
        relative,
    )


def commit_test_service_state(root: Path, service_id: str) -> None:
    """Commit only service ownership/provenance, preserving unrelated work in progress."""
    paths = (f".devlab/test-services/{service_id}.json", ".devlab/workflow-events.jsonl")
    run_git(root, "add", "--", *paths)
    run_git(root, "commit", "--only", "-m", f"Record test service {service_id}", "--", *paths)


def commit_prerequisite_preparation(root: Path) -> None:
    """Commit preparation provenance without including target workspace changes."""
    path = ".devlab/workflow-events.jsonl"
    run_git(root, "add", "--", path)
    run_git(root, "commit", "--only", "-m", "Record prerequisite preparation", "--", path)

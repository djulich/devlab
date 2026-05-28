from __future__ import annotations

import subprocess
from pathlib import Path


class VersionControlError(RuntimeError):
    """Raised when DevLab cannot perform required Git operations."""


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
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


def git_ls_files(root: Path, *args: str) -> list[str]:
    output = run_git(root, *args).stdout
    return sorted(path for path in output.split("\0") if path)

from __future__ import annotations

import dataclasses
from pathlib import Path

from devlab.git import run_git

FAILED_SESSION_CLEAN_PATHS = (
    ".devlab/logs/agents",
    ".devlab/session-artifacts",
)


@dataclasses.dataclass(frozen=True)
class CleanupResult:
    removed: tuple[str, ...]


def clean_failed_session_artifacts(root: Path) -> CleanupResult:
    """Remove untracked DevLab session diagnostics while preserving tracked files."""
    removed = _preview_untracked(root, FAILED_SESSION_CLEAN_PATHS)
    run_git(root, "clean", "-fd", "--", *FAILED_SESSION_CLEAN_PATHS)
    return CleanupResult(tuple(removed))


def format_cleanup_result(result: CleanupResult) -> str:
    if not result.removed:
        return "No failed-session artifacts to clean."
    lines = [f"Removed {len(result.removed)} failed-session artifact(s):"]
    lines.extend(f"- {path}" for path in result.removed)
    lines.append("Target source changes, if any, were left untouched.")
    return "\n".join(lines)


def _preview_untracked(root: Path, paths: tuple[str, ...]) -> list[str]:
    output = run_git(root, "clean", "-fdn", "--", *paths).stdout
    removed: list[str] = []
    for line in output.splitlines():
        if line.startswith("Would remove "):
            removed.append(line.removeprefix("Would remove "))
    return removed

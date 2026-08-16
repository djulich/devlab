"""Git-based artifact hygiene collection for workflow diagnostics."""

from __future__ import annotations

import dataclasses
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from devlab.git import git_ls_files


@dataclasses.dataclass(frozen=True)
class ArtifactContributor:
    path: str
    file_count: int
    total_bytes: int


@dataclasses.dataclass(frozen=True)
class ArtifactHygiene:
    file_count: int
    total_bytes: int
    product_file_count: int
    product_total_bytes: int
    ignored_file_count: int
    ignored_total_bytes: int
    devlab_file_count: int
    devlab_total_bytes: int
    flagged_paths: list[str]
    product_top_contributors: list[ArtifactContributor] = dataclasses.field(
        default_factory=list,
    )
    ignored_top_contributors: list[ArtifactContributor] = dataclasses.field(
        default_factory=list,
    )
    devlab_top_contributors: list[ArtifactContributor] = dataclasses.field(
        default_factory=list,
    )
    conventional_ignored_file_count: int = 0
    conventional_ignored_total_bytes: int = 0
    other_ignored_file_count: int = 0
    other_ignored_total_bytes: int = 0
    conventional_ignored_top_contributors: list[ArtifactContributor] = dataclasses.field(
        default_factory=list,
    )
    other_ignored_top_contributors: list[ArtifactContributor] = dataclasses.field(
        default_factory=list,
    )


LARGE_IGNORED_BYTES_WARNING = 100_000_000
LARGE_IGNORED_FILES_WARNING = 5_000

_CONVENTIONAL_IGNORED_DIRS = {
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


def collect_artifact_hygiene(root: Path) -> ArtifactHygiene:
    product_files = [
        path
        for path in git_ls_files(
            root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
        )
        if not path.startswith(".devlab/")
    ]
    ignored_files = [
        path
        for path in git_ls_files(
            root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        )
        if not path.startswith(".devlab/")
    ]
    devlab_files = [
        path.relative_to(root).as_posix() for path in root.rglob(".devlab/**/*") if path.is_file()
    ]
    conventional_ignored_files = [
        path for path in ignored_files if _is_conventional_ignored_artifact(path)
    ]
    other_ignored_files = [
        path for path in ignored_files if not _is_conventional_ignored_artifact(path)
    ]
    product_total_bytes = _total_bytes(root, product_files)
    ignored_total_bytes = _total_bytes(root, ignored_files)
    devlab_total_bytes = _total_bytes(root, devlab_files)
    return ArtifactHygiene(
        file_count=len(product_files),
        total_bytes=product_total_bytes,
        product_file_count=len(product_files),
        product_total_bytes=product_total_bytes,
        ignored_file_count=len(ignored_files),
        ignored_total_bytes=ignored_total_bytes,
        devlab_file_count=len(devlab_files),
        devlab_total_bytes=devlab_total_bytes,
        flagged_paths=[],
        product_top_contributors=_top_artifact_contributors(
            root,
            product_files,
            _top_level_contributor_key,
        ),
        ignored_top_contributors=_top_artifact_contributors(
            root,
            ignored_files,
            _ignored_artifact_contributor_key,
        ),
        devlab_top_contributors=_top_artifact_contributors(
            root,
            devlab_files,
            _devlab_contributor_key,
        ),
        conventional_ignored_file_count=len(conventional_ignored_files),
        conventional_ignored_total_bytes=_total_bytes(root, conventional_ignored_files),
        other_ignored_file_count=len(other_ignored_files),
        other_ignored_total_bytes=_total_bytes(root, other_ignored_files),
        conventional_ignored_top_contributors=_top_artifact_contributors(
            root,
            conventional_ignored_files,
            _ignored_artifact_contributor_key,
        ),
        other_ignored_top_contributors=_top_artifact_contributors(
            root,
            other_ignored_files,
            _ignored_artifact_contributor_key,
        ),
    )


def has_large_ignored_artifacts(artifact_hygiene: ArtifactHygiene) -> bool:
    return (
        artifact_hygiene.other_ignored_total_bytes > LARGE_IGNORED_BYTES_WARNING
        or artifact_hygiene.other_ignored_file_count > LARGE_IGNORED_FILES_WARNING
    )


def _is_conventional_ignored_artifact(relative_path: str) -> bool:
    return any(part in _CONVENTIONAL_IGNORED_DIRS for part in Path(relative_path).parts)


def _top_artifact_contributors(
    root: Path,
    relative_paths: Sequence[str],
    contributor_key: Callable[[Path, str], str],
    *,
    limit: int = 5,
) -> list[ArtifactContributor]:
    grouped: dict[str, list[int]] = {}
    for relative_path in relative_paths:
        path = root / relative_path
        if not path.is_file():
            continue
        key = contributor_key(root, relative_path)
        entry = grouped.setdefault(key, [0, 0])
        entry[0] += 1
        entry[1] += path.stat().st_size
    return [
        ArtifactContributor(path=key, file_count=count, total_bytes=total_bytes)
        for key, (count, total_bytes) in sorted(
            grouped.items(), key=lambda item: (-item[1][1], item[0])
        )[:limit]
    ]


def _top_level_contributor_key(_root: Path, relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) <= 1:
        return relative_path
    return f"{parts[0]}/"


def _devlab_contributor_key(_root: Path, relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}/"
    return relative_path


def _ignored_artifact_contributor_key(root: Path, relative_path: str) -> str:
    parts = Path(relative_path).parts
    for index in range(1, len(parts) + 1):
        candidate = Path(*parts[:index]).as_posix()
        if _is_git_ignored(root, candidate):
            path = root / candidate
            return candidate + "/" if path.is_dir() else candidate
    if len(parts) <= 1:
        return relative_path
    return f"{parts[0]}/"


def _is_git_ignored(root: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", root.as_posix(), "check-ignore", "-q", "--", relative_path],
        check=False,
    )
    return result.returncode == 0


def _total_bytes(root: Path, relative_paths: Sequence[str]) -> int:
    total = 0
    for relative_path in relative_paths:
        path = root / relative_path
        if path.is_file():
            total += path.stat().st_size
    return total

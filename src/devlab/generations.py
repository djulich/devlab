from __future__ import annotations

import dataclasses
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from devlab._files import atomic_write_text
from devlab._toml import format_toml_value

GENERATIONS_DIR = ".devlab/generations"
GENERATION_MANIFEST = "generation.toml"

# The active generation bundle is scoped to the current planning generation.
# Fresh-generation planning archives, clears, and recreates these workflow
# artifacts together while leaving cross-generation inputs such as specs and
# configuration in place.
ACTIVE_GENERATION_BUNDLE_PATHS = (
    ".devlab/tasks",
    ".devlab/milestones",
    ".devlab/findings",
    ".devlab/history",
    ".devlab/session-artifacts",
    ".devlab/logs/agents",
    ".devlab/plans",
    ".devlab/workflow.toml",
)

ACTIVE_GENERATION_SKELETON_DIRS = (
    ".devlab/tasks",
    ".devlab/milestones",
    ".devlab/findings",
    ".devlab/history",
    ".devlab/session-artifacts",
    ".devlab/logs/agents",
    ".devlab/plans",
)


@dataclasses.dataclass(frozen=True)
class GenerationManifest:
    version: int
    generation: int
    archived_at: str
    reason: str
    spec_baseline: str


def archived_generation_numbers(root: Path) -> tuple[int, ...]:
    generations = root / GENERATIONS_DIR
    if not generations.exists():
        return ()
    numbers: list[int] = []
    for path in generations.iterdir():
        if not path.is_dir() or not path.name.isdigit():
            continue
        numbers.append(int(path.name))
    return tuple(sorted(numbers))


def previous_generation(root: Path) -> int | None:
    numbers = archived_generation_numbers(root)
    return numbers[-1] if numbers else None


def active_generation(root: Path) -> int:
    previous = previous_generation(root)
    return 1 if previous is None else previous + 1


def generation_path(root: Path, generation: int) -> Path:
    if generation < 1:
        raise ValueError("generation must be a positive integer")
    return root / GENERATIONS_DIR / f"{generation:04d}"


def has_active_plan(root: Path) -> bool:
    devlab = root / ".devlab"
    checks = (
        devlab / "plans/design-plan.md",
        devlab / "plans/project-plan.md",
    )
    if any(path.exists() and path.stat().st_size > 0 for path in checks):
        return True
    for relative in (
        "tasks/*.md",
        "milestones/*.toml",
    ):
        if any(path.is_file() for path in devlab.glob(relative)):
            return True
    return any(path.is_file() and path.name != ".gitkeep" for path in devlab.glob("history/*"))


def archive_active_generation(
    root: Path,
    *,
    reason: str,
    spec_baseline: str = "",
    archived_at: datetime | None = None,
) -> GenerationManifest:
    generation = active_generation(root)
    archive_root = generation_path(root, generation)
    if archive_root.exists():
        raise FileExistsError(f"generation archive already exists: {archive_root}")
    archive_root.mkdir(parents=True)
    for relative in ACTIVE_GENERATION_BUNDLE_PATHS:
        source = root / relative
        if not source.exists():
            continue
        destination = archive_root / relative.removeprefix(".devlab/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    manifest = GenerationManifest(
        version=1,
        generation=generation,
        archived_at=(archived_at or datetime.now(UTC)).replace(microsecond=0).isoformat(),
        reason=reason,
        spec_baseline=spec_baseline,
    )
    atomic_write_text(archive_root / GENERATION_MANIFEST, format_generation_manifest(manifest))
    clear_active_generation(root)
    create_active_skeleton(root)
    return manifest


def clear_active_generation(root: Path) -> None:
    for relative in ACTIVE_GENERATION_BUNDLE_PATHS:
        path = root / relative
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def create_active_skeleton(root: Path) -> None:
    for relative in ACTIVE_GENERATION_SKELETON_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def format_generation_manifest(manifest: GenerationManifest) -> str:
    return (
        f"version = {format_toml_value(manifest.version)}\n"
        f"generation = {format_toml_value(manifest.generation)}\n"
        f"archived_at = {format_toml_value(manifest.archived_at)}\n"
        f"reason = {format_toml_value(manifest.reason)}\n"
        f"spec_baseline = {format_toml_value(manifest.spec_baseline)}\n"
    )


def parse_generation_manifest(data: object) -> GenerationManifest:
    if not isinstance(data, dict):
        raise ValueError("generation manifest must be a TOML table")
    config = cast(dict[str, Any], data)
    version = config.get("version")
    if version != 1:
        raise ValueError("generation manifest version must be 1")
    generation = config.get("generation")
    if not isinstance(generation, int) or generation < 1:
        raise ValueError("generation manifest generation must be a positive integer")
    archived_at = _string_field(config, "archived_at")
    reason = _string_field(config, "reason")
    spec_baseline = _string_field(config, "spec_baseline", default="")
    return GenerationManifest(
        version=version,
        generation=generation,
        archived_at=archived_at,
        reason=reason,
        spec_baseline=spec_baseline,
    )


def load_generation_manifest(path: Path) -> GenerationManifest:
    with path.open("rb") as handle:
        return parse_generation_manifest(tomllib.load(handle))


def _string_field(data: dict[str, Any], key: str, *, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"generation manifest {key} must be a string")
    return value

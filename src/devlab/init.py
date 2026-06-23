from __future__ import annotations

import dataclasses
from importlib import resources
from pathlib import Path

from devlab.version_control import (
    assert_clean_worktree,
    commit_all,
    ensure_git_identity,
    has_git_repository,
    init_repository,
)
from devlab.workflow_events import WORKFLOW_EVENTS, append_workflow_event
from devlab.workflow_state import WORKFLOW_STATE, initial_workflow_state_text

LAYOUT_VERSION = 1
_TEMPLATE_PACKAGE = "devlab.resources.init"

TEMPLATE_FILES = (
    "config/README.md",
    "config/tooling.md",
    "config/agents.toml",
    "config/profiles/default.toml",
    "specs/system/README.md",
    "specs/deployment/README.md",
)

EMPTY_FILES = (
    "plans/design-plan.md",
    "plans/project-plan.md",
)

GITKEEP_DIRS = (
    "tasks",
    "milestones",
    "findings",
    "history",
    "logs/environment",
    "logs/deployment",
    "logs/agents",
    "session-artifacts",
)


@dataclasses.dataclass(frozen=True)
class InitResult:
    created: tuple[Path, ...]
    skipped: tuple[Path, ...]
    overwritten: tuple[Path, ...]


def init_workspace(
    root: Path,
    *,
    force: bool = False,
    automatic_git: bool = False,
    git_user_name: str | None = None,
    git_user_email: str | None = None,
) -> InitResult:
    """Create a target-local `.devlab/` workflow tree."""
    root = root.resolve()
    created: list[Path] = []
    skipped: list[Path] = []
    overwritten: list[Path] = []

    if automatic_git:
        if has_git_repository(root):
            assert_clean_worktree(root)
        else:
            init_repository(root)
        ensure_git_identity(
            root,
            user_name=git_user_name,
            user_email=git_user_email,
        )

    devlab = root / ".devlab"
    _ensure_dir(devlab, created)

    manifest = devlab / "manifest.toml"
    _write_file(
        manifest,
        f"layout_version = {LAYOUT_VERSION}\ncreated_by = \"devlab\"\n",
        force=force,
        created=created,
        skipped=skipped,
        overwritten=overwritten,
    )
    _write_file(
        root / WORKFLOW_STATE,
        initial_workflow_state_text(),
        force=force,
        created=created,
        skipped=skipped,
        overwritten=overwritten,
    )

    template_root = resources.files(_TEMPLATE_PACKAGE)
    for relative in TEMPLATE_FILES:
        content = template_root.joinpath(relative).read_text()
        _write_file(
            devlab / relative,
            content,
            force=force,
            created=created,
            skipped=skipped,
            overwritten=overwritten,
        )

    for relative in EMPTY_FILES:
        _write_file(
            devlab / relative,
            "",
            force=force,
            created=created,
            skipped=skipped,
            overwritten=overwritten,
        )

    for relative in GITKEEP_DIRS:
        directory = devlab / relative
        _ensure_dir(directory, created)
        _write_file(
            directory / ".gitkeep",
            "",
            force=force,
            created=created,
            skipped=skipped,
            overwritten=overwritten,
        )

    if created or overwritten or not (root / WORKFLOW_EVENTS).exists():
        append_workflow_event(root, "init")

    if automatic_git:
        commit_all(root, "Initialize DevLab workspace")

    return InitResult(tuple(created), tuple(skipped), tuple(overwritten))


def format_init_result(result: InitResult, root: Path) -> str:
    lines: list[str] = []
    for label, paths in (
        ("created", result.created),
        ("overwritten", result.overwritten),
        ("skipped", result.skipped),
    ):
        for path in paths:
            lines.append(f"{label}: {_display_path(path, root)}")
    if not lines:
        return "DevLab workspace already initialized."
    return "\n".join(lines)


def format_init_next_steps() -> str:
    return """Next steps:
  1. Edit the system spec:
       .devlab/specs/system/README.md

  2. Optionally add deployment specs under:
       .devlab/specs/deployment/

  3. Configure an installed agent command:
       .devlab/config/agents.toml

  4. Commit your user-authored setup changes:
       git add .devlab/specs .devlab/config
       git commit -m "Configure DevLab project"

  5. Validate configuration:
       devlab doctor

  6. Generate plans:
       devlab plan

DevLab plan/run require a clean Git working tree. Commit spec and config edits before
starting agent sessions."""


def _ensure_dir(path: Path, created: list[Path]) -> None:
    if not path.exists():
        path.mkdir(parents=True)
        created.append(path)
    else:
        path.mkdir(parents=True, exist_ok=True)


def _write_file(
    path: Path,
    content: str,
    *,
    force: bool,
    created: list[Path],
    skipped: list[Path],
    overwritten: list[Path],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if force:
            path.write_text(content)
            overwritten.append(path)
        else:
            skipped.append(path)
        return
    path.write_text(content)
    created.append(path)


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)

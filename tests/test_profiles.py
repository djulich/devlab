from __future__ import annotations

from pathlib import Path

import pytest

from devlab.prerequisites import PrerequisiteOperation
from devlab.profiles import (
    ProfileNotFoundError,
    effective_milestone_validation,
    effective_profile_id,
    effective_validation,
    load_profile,
)
from devlab.task_tracker import FileTaskTracker


def test_effective_milestone_validation_deduplicates_with_provenance(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / ".devlab/config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "default.toml").write_text(
        'version = 1\nid = "default"\n[tooling]\n'
        'default_validation = ["make check", "ruff check"]\n'
    )
    tasks = tmp_path / ".devlab/tasks"
    tasks.mkdir(parents=True)
    (tasks / "T0001_first.md").write_text(
        '+++\nid = "T0001"\ntitle = "First"\nstatus = "closed"\n+++\n\n'
        "# T0001: First\n\n## Acceptance Criteria\n- [x] Done\n"
    )
    (tasks / "T0002_second.md").write_text(
        '+++\nid = "T0002"\ntitle = "Second"\nstatus = "closed"\n'
        'validation = ["make check", "pytest"]\n+++\n\n'
        "# T0002: Second\n\n## Acceptance Criteria\n- [x] Done\n"
    )
    profile = load_profile(tmp_path, "default")
    tracker = FileTaskTracker(tmp_path)

    result = effective_milestone_validation(
        [tracker.get("T0001"), tracker.get("T0002")],
        {"default": profile},
        root=tmp_path,
    )

    assert [item.command for item in result.commands] == [
        "make check",
        "ruff check",
        "pytest",
    ]
    assert result.commands[0].task_ids == ("T0001", "T0002")
    assert result.commands[0].sources == ("profile", "task")


def test_omitted_profile_resolves_to_default() -> None:
    assert effective_profile_id(None) == "default"
    assert effective_profile_id("api") == "api"


def test_loads_profile_tooling_and_environment(tmp_path: Path) -> None:
    profiles = tmp_path / ".devlab/config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "api.toml").write_text(
        "version = 1\n"
        'id = "api"\n'
        'title = "API"\n'
        "\n[tooling]\n"
        'summary = "Python API"\n'
        'default_validation = ["uv run pytest tests/api"]\n'
        "\n[environment]\n"
        'managed_roles = ["developer"]\n'
        'pre_session = ["echo pre"]\n'
        'setup = ["uv sync"]\n'
        'post_session = ["echo post"]\n'
        "\n[timeouts]\n"
        "setup = 42\n"
        "\n[[prerequisites]]\n"
        'id = "database"\n'
        'required_for = ["session", "validation"]\n'
        'environment = "TEST_DATABASE_URL"\n'
        'summary = "Disposable database"\n'
        'guide = ".devlab/config/prerequisites/database.md#setup"\n'
        "sensitive = true\n"
    )

    profile = load_profile(tmp_path, "api")

    assert profile.id == "api"
    assert profile.title == "API"
    assert profile.tooling.summary == "Python API"
    assert profile.tooling.default_validation == ("uv run pytest tests/api",)
    assert profile.environment.managed_roles == ("developer",)
    assert profile.environment.setup == ("uv sync",)
    assert profile.environment.timeouts.setup == 42
    prerequisite = profile.prerequisites[0]
    assert prerequisite.id == "database"
    assert prerequisite.required_for == (
        PrerequisiteOperation.SESSION,
        PrerequisiteOperation.VALIDATION,
    )
    assert prerequisite.sensitive
    assert prerequisite.guide == ".devlab/config/prerequisites/database.md#setup"


def test_missing_sections_default_to_empty_noop(tmp_path: Path) -> None:
    profiles = tmp_path / ".devlab/config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "docs.toml").write_text('version = 1\nid = "docs"\n')

    profile = load_profile(tmp_path, "docs")

    assert profile.tooling.default_validation == ()
    assert profile.environment.managed_roles == ()
    assert profile.environment.setup == ()


def test_default_profile_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ProfileNotFoundError, match="default"):
        load_profile(tmp_path, None)


def test_named_missing_profile_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProfileNotFoundError, match="api"):
        load_profile(tmp_path, "api")


def test_rejects_invalid_profile_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid profile id"):
        load_profile(tmp_path, "../api")


def test_rejects_profile_id_mismatch(tmp_path: Path) -> None:
    profiles = tmp_path / ".devlab/config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "api.toml").write_text('version = 1\nid = "other"\n')

    with pytest.raises(ValueError, match="id mismatch"):
        load_profile(tmp_path, "api")


@pytest.mark.parametrize(
    ("task_validation", "profile_validation", "source", "commands"),
    [
        (["task check"], ["profile check"], "task", ("task check",)),
        ([], ["profile check"], "none", ()),
        (None, ["profile check"], "profile", ("profile check",)),
        (None, [], "none", ()),
    ],
)
def test_effective_validation_resolution(
    tmp_path: Path,
    task_validation: list[str] | None,
    profile_validation: list[str],
    source: str,
    commands: tuple[str, ...],
) -> None:
    tasks = tmp_path / ".devlab/tasks"
    tasks.mkdir(parents=True)
    validation_line = (
        ""
        if task_validation is None
        else "validation = [" + ", ".join(f'"{command}"' for command in task_validation) + "]\n"
    )
    (tasks / "T0001_task.md").write_text(
        "+++\n"
        'id = "T0001"\n'
        'title = "Task"\n'
        'status = "open"\n'
        f"{validation_line}"
        "+++\n\n"
        "# T0001: Task\n\n## Acceptance Criteria\n- [ ] Done\n"
    )
    profiles = tmp_path / ".devlab/config/profiles"
    profiles.mkdir(parents=True)
    values = ", ".join(f'"{command}"' for command in profile_validation)
    (profiles / "default.toml").write_text(
        f'version = 1\nid = "default"\n[tooling]\ndefault_validation = [{values}]\n'
    )

    resolved = effective_validation(
        FileTaskTracker(tmp_path).get("T0001"), load_profile(tmp_path, None)
    )

    assert resolved.source == source
    assert resolved.commands == commands

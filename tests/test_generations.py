from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from devlab.generations import (
    ACTIVE_GENERATION_SKELETON_DIRS,
    active_generation,
    archive_active_generation,
    archived_generation_numbers,
    has_active_plan,
    load_generation_manifest,
    previous_generation,
)


def test_active_generation_is_derived_from_archive_directories(tmp_path: Path) -> None:
    assert active_generation(tmp_path) == 1
    assert previous_generation(tmp_path) is None

    (tmp_path / ".devlab/generations/0001").mkdir(parents=True)
    (tmp_path / ".devlab/generations/0003").mkdir()
    (tmp_path / ".devlab/generations/not-a-generation").mkdir()

    assert archived_generation_numbers(tmp_path) == (1, 3)
    assert previous_generation(tmp_path) == 3
    assert active_generation(tmp_path) == 4


def test_archive_active_generation_moves_workflow_bundle_and_keeps_specs(
    tmp_path: Path,
) -> None:
    _write(tmp_path / ".devlab/tasks/T0001_task.md", "task")
    _write(tmp_path / ".devlab/milestones/M1.toml", "milestone")
    _write(tmp_path / ".devlab/findings/F0001.md", "finding")
    _write(tmp_path / ".devlab/history/handoff.md", "history")
    _write(tmp_path / ".devlab/verification/milestones/M1.toml", "milestone evidence")
    _write(tmp_path / ".devlab/verification/tasks/T0001/session.json", "task evidence")
    _write(tmp_path / ".devlab/session-artifacts/planner/handoff.md", "artifact")
    _write(tmp_path / ".devlab/logs/agents/session.log", "log")
    _write(tmp_path / ".devlab/plans/project-plan.md", "plan")
    _write(tmp_path / ".devlab/workflow.toml", "version = 1\n")
    _write(tmp_path / ".devlab/specs/system/spec.md", "spec")
    _write(tmp_path / ".devlab/config/agents.toml", "config")
    _write(tmp_path / ".devlab/adr/0001-decision.md", "adr")

    manifest = archive_active_generation(
        tmp_path,
        reason="spec_reconciliation",
        spec_baseline="abc123",
        archived_at=datetime(2026, 6, 21, 12, 34, 56, tzinfo=UTC),
    )

    assert manifest.generation == 1
    archive = tmp_path / ".devlab/generations/0001"
    assert (archive / "tasks/T0001_task.md").read_text() == "task"
    assert (archive / "milestones/M1.toml").read_text() == "milestone"
    assert (archive / "findings/F0001.md").read_text() == "finding"
    assert (archive / "history/handoff.md").read_text() == "history"
    assert (archive / "session-artifacts/planner/handoff.md").read_text() == "artifact"
    assert (archive / "logs/agents/session.log").read_text() == "log"
    assert (archive / "plans/project-plan.md").read_text() == "plan"
    assert (archive / "verification/milestones/M1.toml").read_text() == "milestone evidence"
    assert (archive / "verification/tasks/T0001/session.json").read_text() == "task evidence"
    assert list((tmp_path / ".devlab/verification").iterdir()) == []
    assert (archive / "workflow.toml").read_text() == "version = 1\n"
    assert not (archive / "specs").exists()
    assert not (archive / "config").exists()
    assert not (archive / "adr").exists()
    assert (tmp_path / ".devlab/specs/system/spec.md").read_text() == "spec"
    assert (tmp_path / ".devlab/config/agents.toml").read_text() == "config"
    assert (tmp_path / ".devlab/adr/0001-decision.md").read_text() == "adr"
    assert not (tmp_path / ".devlab/tasks/T0001_task.md").exists()
    for relative in ACTIVE_GENERATION_SKELETON_DIRS:
        assert (tmp_path / relative).is_dir()
    assert load_generation_manifest(archive / "generation.toml").reason == ("spec_reconciliation")
    assert active_generation(tmp_path) == 2


def test_has_active_plan_ignores_archived_generations(tmp_path: Path) -> None:
    (tmp_path / ".devlab/generations/0001/tasks").mkdir(parents=True)

    assert has_active_plan(tmp_path) is False

    _write(tmp_path / ".devlab/tasks/T0001_task.md", "task")

    assert has_active_plan(tmp_path) is True


def test_has_active_plan_ignores_history_gitkeep(tmp_path: Path) -> None:
    _write(tmp_path / ".devlab/history/.gitkeep", "")

    assert has_active_plan(tmp_path) is False

    _write(tmp_path / ".devlab/history/architect-001.md", "handoff")

    assert has_active_plan(tmp_path) is True


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)

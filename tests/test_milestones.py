from __future__ import annotations

from pathlib import Path

import pytest

from devlab.milestones import (
    FileMilestoneTracker,
    MilestoneStatus,
    MilestoneVerification,
    MilestoneVerificationCommand,
)
from devlab.task_tracker import FileTaskTracker


def test_milestone_verification_round_trip(tmp_path: Path) -> None:
    tracker = FileMilestoneTracker(tmp_path)
    tracker.write_verification(
        MilestoneVerification(
            milestone_id="M1",
            state="verified",
            repository_revision="abc123",
            closed_task_ids=("T0001",),
            commands=(
                MilestoneVerificationCommand(
                    command="pytest",
                    task_ids=("T0001",),
                    sources=("task",),
                    outcome="passed",
                    exit_code=0,
                    duration_seconds=1.25,
                    output_summary="ok",
                    log_path="validation.log",
                ),
            ),
            untested_claims=("manual documentation review",),
        )
    )

    record = tracker.read_verification("M1")

    assert record is not None
    assert record.state == "verified"
    assert record.commands[0].command == "pytest"
    assert record.commands[0].exit_code == 0
    assert record.untested_claims == ("manual documentation review",)


def test_upsert_from_tasks_creates_missing_milestone_files(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0002", "Second", milestone="M1")
    _write_task(tmp_path, "T0001", "First", milestone="M1")
    tasks = FileTaskTracker(tmp_path).list_tasks()

    milestones = FileMilestoneTracker(tmp_path).upsert_from_tasks(
        tasks,
        project_plan_text="## M1: Foundation\n- T0001\n- T0002\n",
    )

    assert len(milestones) == 1
    milestone = milestones[0]
    assert milestone.id == "M1"
    assert milestone.title == "Foundation"
    assert milestone.status == MilestoneStatus.PLANNED
    assert milestone.integration_required is True
    assert milestone.integrated is False
    assert milestone.architecture_reviewed is False
    assert milestone.task_ids == ("T0001", "T0002")
    assert (tmp_path / ".devlab/milestones/M1.toml").exists()


def test_upsert_from_tasks_omits_generation_metadata_for_new_milestone(
    tmp_path: Path,
) -> None:
    _write_task(tmp_path, "T0001", "First", milestone="M1", generation=3)

    milestone = FileMilestoneTracker(tmp_path).upsert_from_tasks(
        FileTaskTracker(tmp_path).list_tasks()
    )[0]

    assert "planning_generation" not in milestone.metadata


def test_upsert_from_tasks_drops_legacy_generation_from_existing_milestone(
    tmp_path: Path,
) -> None:
    _write_task(tmp_path, "T0001", "Old", milestone="M1", generation=1)
    _write_task(tmp_path, "T0002", "New", milestone="M1", generation=2)
    milestones_dir = tmp_path / ".devlab/milestones"
    milestones_dir.mkdir(parents=True)
    (milestones_dir / "M1.toml").write_text(
        "version = 1\n"
        'id = "M1"\n'
        'title = "Existing"\n'
        'status = "planned"\n'
        "integration_required = true\n"
        "integrated = false\n"
        "architecture_reviewed = false\n"
        "planning_generation = 1\n"
        'task_ids = ["T0001"]\n'
        'integration_handoff = ""\n'
        'architecture_review_handoff = ""\n'
        "findings = []\n"
    )

    milestone = FileMilestoneTracker(tmp_path).upsert_from_tasks(
        FileTaskTracker(tmp_path).list_tasks()
    )[0]

    assert "planning_generation" not in milestone.path.read_text()
    assert milestone.task_ids == ("T0001", "T0002")


def test_upsert_from_tasks_resets_integrated_state_when_adding_task_ids(
    tmp_path: Path,
) -> None:
    milestones_dir = tmp_path / ".devlab/milestones"
    milestones_dir.mkdir(parents=True)
    (milestones_dir / "M1.toml").write_text(
        "version = 1\n"
        'id = "M1"\n'
        'title = "Existing"\n'
        'status = "integrated"\n'
        "integration_required = true\n"
        "integrated = true\n"
        "architecture_reviewed = false\n"
        'task_ids = ["T0001"]\n'
        'integration_handoff = "handoff.md"\n'
        'architecture_review_handoff = ""\n'
        "findings = []\n"
    )
    _write_task(tmp_path, "T0001", "First", milestone="M1")
    _write_task(tmp_path, "T0002", "Second", milestone="M1")

    milestone = FileMilestoneTracker(tmp_path).upsert_from_tasks(
        FileTaskTracker(tmp_path).list_tasks()
    )[0]

    assert milestone.status == MilestoneStatus.ACTIVE
    assert milestone.integrated is False
    assert milestone.integration_handoff == "handoff.md"
    assert milestone.task_ids == ("T0001", "T0002")


def test_upsert_from_tasks_resets_integration_when_new_task_added(
    tmp_path: Path,
) -> None:
    milestones_dir = tmp_path / ".devlab/milestones"
    milestones_dir.mkdir(parents=True)
    (milestones_dir / "M1.toml").write_text(
        "version = 1\n"
        'id = "M1"\n'
        'title = "Existing"\n'
        'status = "architecture_reviewed"\n'
        "integration_required = true\n"
        "integrated = true\n"
        "architecture_reviewed = true\n"
        'task_ids = ["T0001"]\n'
        'integration_handoff = "integrator.md"\n'
        'architecture_review_handoff = "architect.md"\n'
        "findings = []\n"
    )
    _write_task(tmp_path, "T0001", "First", milestone="M1")
    _write_task(tmp_path, "T0002", "Second", milestone="M1")

    milestone = FileMilestoneTracker(tmp_path).upsert_from_tasks(
        FileTaskTracker(tmp_path).list_tasks()
    )[0]

    assert milestone.status == MilestoneStatus.ACTIVE
    assert milestone.integrated is False
    assert milestone.architecture_reviewed is False
    assert milestone.task_ids == ("T0001", "T0002")


def test_mark_integrated_records_state_and_handoff(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1")

    FileMilestoneTracker(tmp_path).mark_integrated(
        "M1", tmp_path / ".devlab/history/20260101T000000_integrator_handoff.md"
    )

    milestone = FileMilestoneTracker(tmp_path).get("M1")
    assert milestone.status == MilestoneStatus.INTEGRATED
    assert milestone.integrated is True
    assert milestone.integration_handoff == "20260101T000000_integrator_handoff.md"


def test_mark_integration_failed_records_finding_once(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1")
    tracker = FileMilestoneTracker(tmp_path)

    tracker.mark_integration_failed("M1", "F0001")
    tracker.mark_integration_failed("M1", "F0001")

    milestone = tracker.get("M1")
    assert milestone.status == MilestoneStatus.INTEGRATION_FAILED
    assert milestone.integrated is False
    assert milestone.findings == ("F0001",)


def test_mark_architecture_reviewed_records_state_and_handoff(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1")

    FileMilestoneTracker(tmp_path).mark_architecture_reviewed(
        "M1", tmp_path / ".devlab/history/20260101T000000_architect_handoff.md"
    )

    milestone = FileMilestoneTracker(tmp_path).get("M1")
    assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED
    assert milestone.architecture_reviewed is True
    assert milestone.architecture_review_handoff == "20260101T000000_architect_handoff.md"


def test_invalid_milestone_status_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/milestones/M1.toml"
    path.parent.mkdir(parents=True)
    path.write_text('id = "M1"\nstatus = "bogus"\ntask_ids = []\nfindings = []\n')

    with pytest.raises(ValueError, match="invalid milestone status"):
        FileMilestoneTracker(tmp_path).get("M1")


def _write_task(
    root: Path,
    task_id: str,
    title: str,
    *,
    milestone: str,
    generation: int = 1,
) -> None:
    tasks_dir = root / ".devlab/tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.joinpath(f"{task_id}_{title.lower()}.md").write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{title}"\n'
        'status = "open"\n'
        f'milestone = "{milestone}"\n'
        f"planning_generation = {generation}\n"
        "depends_on = []\n"
        "+++\n\n"
        f"# {task_id}: {title}\n"
    )


def _write_milestone(root: Path, milestone_id: str) -> None:
    path = root / ".devlab/milestones" / f"{milestone_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version = 1\n"
        f'id = "{milestone_id}"\n'
        f'title = "{milestone_id}"\n'
        'status = "planned"\n'
        "integration_required = true\n"
        "integrated = false\n"
        "architecture_reviewed = false\n"
        "task_ids = []\n"
        'integration_handoff = ""\n'
        'architecture_review_handoff = ""\n'
        "findings = []\n"
    )

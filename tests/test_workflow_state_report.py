from __future__ import annotations

import json
from pathlib import Path

import pytest

from devlab.clarifications import FileClarificationTracker
from devlab.findings import FileFindingTracker
from devlab.generations import archive_active_generation
from devlab.init import init_workspace
from devlab.research import ResearchConfidence, ResearchEvidence, ResearchResult, ResearchSource
from devlab.task_tracker import FileTaskTracker
from devlab.workflow_events import append_workflow_event
from devlab.workflow_state import ResumeState, initial_workflow_state_text, set_resume_state
from devlab.workflow_state_report import (
    build_workflow_state_digest,
    build_workflow_state_report,
    format_workflow_state_digest,
    format_workflow_state_report,
)
from devlab.workspace import Workspace
from tests.helpers import write_task


def test_initialized_workspace_reports_awaiting_design(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    report = build_workflow_state_report(tmp_path)

    assert report.project_mode == "unknown"
    assert report.lifecycle_phase == "awaiting design"
    assert report.next_role == "architect"
    assert report.planning.complete is False
    assert report.planning.design_plan_present is False
    assert report.generations.active == 1
    assert report.generations.archived == []
    assert report.history.plan_revisions == 0


def test_workflow_state_report_json_has_stable_sections(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    payload = json.loads(build_workflow_state_report(tmp_path).to_json())

    assert set(payload) == {
        "current_work",
        "clarifications",
        "generations",
        "history",
        "lifecycle_events",
        "lifecycle_phase",
        "next_role",
        "planning",
        "project_mode",
        "research",
        "specs",
    }
    assert payload["planning"]["complete"] is False
    assert payload["specs"]["baseline_commit"] == ""
    assert payload["current_work"]["tasks_total"] == 0
    assert payload["clarifications"]["pending_blockers"] == []
    assert payload["clarifications"]["resume"] is None
    assert payload["research"] is None


def test_current_work_counts_tasks_milestones_and_findings(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / ".devlab/plans/design-plan.md").write_text("# Design\n")
    (tmp_path / ".devlab/plans/project-plan.md").write_text("# Plan\n")
    write_task(tmp_path, "T0001", "Closed task", "M1")
    write_task(tmp_path, "T0002", "Open task", "M1")
    FileTaskTracker(tmp_path).close("T0001")
    FileFindingTracker(tmp_path).create(
        title="Finding",
        source="integrator",
        milestone="M1",
        body="# Finding\n",
    )

    report = build_workflow_state_report(tmp_path)

    assert report.lifecycle_phase == "implementation"
    assert report.current_work.tasks_total == 2
    assert report.current_work.tasks_closed == 1
    assert report.current_work.tasks_active == 1
    assert report.current_work.findings_open == 1


def test_lifecycle_events_classify_adopted_project_and_counts(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    append_workflow_event(tmp_path, "plan_started", mode="adopt_existing", generation=1)
    append_workflow_event(tmp_path, "plan_started", mode="revise", generation=1)
    append_workflow_event(
        tmp_path,
        "generation_archived",
        mode="spec_reconciliation",
        generation=1,
        spec_baseline="abc123",
    )
    append_workflow_event(
        tmp_path,
        "generation_archived",
        mode="replace_plan",
        generation=2,
        spec_baseline="def456",
    )

    report = build_workflow_state_report(tmp_path)

    assert report.project_mode == "adopted existing project"
    assert report.history.adoption_planning_runs == 1
    assert report.history.plan_revisions == 1
    assert report.history.reconciliations == 1
    assert report.history.plan_replacements == 1


def test_old_workspace_infers_generation_counts_from_manifests(tmp_path: Path) -> None:
    (tmp_path / ".devlab/manifest.toml").parent.mkdir(parents=True)
    (tmp_path / ".devlab/manifest.toml").write_text("layout_version = 1\n")
    (tmp_path / ".devlab/workflow.toml").write_text(initial_workflow_state_text())
    (tmp_path / ".devlab/plans/design-plan.md").parent.mkdir(parents=True)
    (tmp_path / ".devlab/plans/design-plan.md").write_text("# Design\n")
    (tmp_path / ".devlab/plans/project-plan.md").write_text("# Plan\n")
    _write_required_dirs(tmp_path)
    archive_active_generation(tmp_path, reason="spec_reconciliation", spec_baseline="abc")
    archive_active_generation(tmp_path, reason="replace_plan", spec_baseline="def")

    report = build_workflow_state_report(tmp_path)

    assert report.specs.reconciliations == 1
    assert report.specs.plan_replacements == 1
    assert report.history.plan_revisions is None


def test_format_workflow_state_report_is_compact(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    output = format_workflow_state_report(build_workflow_state_report(tmp_path))

    assert "Workflow state:" in output
    assert "Project mode: unknown" in output
    assert "Lifecycle phase: awaiting design" in output
    assert "Pending clarification blockers: 0" in output
    assert "Resume pointer: none" in output
    assert "Current work:" in output


def test_format_workflow_state_digest_includes_digest_sections(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    digest = build_workflow_state_digest(build_workflow_state_report(tmp_path))

    output = format_workflow_state_digest(digest)

    assert output.startswith("# Workflow State")
    assert "- Lifecycle phase: awaiting design" in output
    assert "## Next Action" in output
    assert "Run `devlab plan` to continue design or planning." in output
    assert "## Current Work" in output
    assert "- Tasks: 0 total, 0 closed, 0 active" in output
    assert "## Specs" in output
    assert "## Validation" in output
    assert "Validation state: not reported." in output


def test_workflow_state_digest_json_is_compact_projection(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    payload = json.loads(
        build_workflow_state_digest(build_workflow_state_report(tmp_path)).to_json()
    )

    assert set(payload) == {
        "current_work",
        "clarifications",
        "next_action",
        "notes",
        "planning_history",
        "research",
        "specs",
        "summary",
        "validation",
    }
    assert payload["summary"]["lifecycle_phase"] == "awaiting design"
    assert payload["summary"]["active_generation"] == 1
    assert payload["next_action"] == "Run `devlab plan` to continue design or planning."
    assert payload["validation"]["state"] == "not_reported"
    assert payload["clarifications"]["pending_blockers"] == []
    assert payload["research"] is None


def test_workflow_state_report_includes_clarification_blockers(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    clarification = _create_pending_clarification(tmp_path)

    report = build_workflow_state_report(tmp_path)

    assert len(report.clarifications.pending_blockers) == 1
    blocker = report.clarifications.pending_blockers[0]
    assert blocker.id == clarification
    assert blocker.title == "Auth session timeout"
    assert blocker.scope == "planning"
    assert blocker.blocks == "planning"


def test_workflow_state_report_includes_resume_pointer(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    clarification = _create_pending_clarification(tmp_path)
    set_resume_state(
        tmp_path,
        ResumeState(
            blocked_by=clarification,
            command="plan",
            role="planner",
            task="",
            milestone="",
        ),
    )

    payload = json.loads(build_workflow_state_report(tmp_path).to_json())

    assert payload["clarifications"]["pending_blockers"][0]["id"] == clarification
    assert payload["clarifications"]["resume"] == {
        "blocked_by": clarification,
        "command": "plan",
        "role": "planner",
        "task": "",
        "milestone": "",
    }


def test_workflow_state_digest_prioritizes_clarification_next_action(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    clarification = _create_pending_clarification(tmp_path)

    digest = build_workflow_state_digest(build_workflow_state_report(tmp_path))

    assert digest.next_action == (
        f"Answer clarification {clarification} with "
        f"`devlab clarify answer {clarification} ...`, then run `devlab resume`."
    )


def test_workflow_state_digest_prioritizes_resume_pointer(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    clarification = _create_pending_clarification(tmp_path)
    set_resume_state(
        tmp_path,
        ResumeState(blocked_by=clarification, command="plan", role="planner"),
    )

    digest = build_workflow_state_digest(build_workflow_state_report(tmp_path))
    output = format_workflow_state_digest(digest)

    assert digest.next_action == (
        f"Answer clarification {clarification} if needed, then run `devlab resume`."
    )
    assert "## Clarifications" in output
    assert f"- {clarification}: Auth session timeout" in output
    assert f"- Resume pointer: {clarification} -> devlab plan planner" in output


def test_workflow_state_reports_requested_and_completed_research_route(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    research = _create_research(tmp_path)

    report = build_workflow_state_report(tmp_path)
    assert report.research is not None
    assert report.research.id == research.id
    assert report.research.status == "requested"
    assert report.research.next_step == "researcher_invocation"
    assert build_workflow_state_digest(report).next_action == (
        "Run `devlab plan` for the bounded researcher session."
    )

    Workspace(tmp_path).research().get(research.id).complete(
        ResearchResult(
            summary="The documented behavior is usable.",
            evidence=(ResearchEvidence("The primary source documents it.", ("S1",)),),
            sources=(ResearchSource("S1", "Primary docs", "docs/source.md", "primary"),),
            recommendation="Use the documented behavior.",
            confidence=ResearchConfidence.LOW,
            unresolved_questions=("Confirm the deployment version.",),
        ),
        researcher_session_id="researcher-1",
        researcher_provider="mock",
    )
    completed = build_workflow_state_report(tmp_path)
    assert completed.research is not None
    assert completed.research.status == "completed"
    assert completed.research.next_step == "resumed_role_execution"
    assert build_workflow_state_digest(completed).next_action == (
        "Run `devlab plan` for the resumed requesting-role session."
    )


def test_malformed_workflow_state_surfaces_error(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / ".devlab/workflow.toml").write_text('version = 1\n\n[planning]\ncomplete = "no"\n')

    with pytest.raises(ValueError, match=r"planning\.complete must be a boolean"):
        build_workflow_state_report(tmp_path)


def test_workflow_state_report_does_not_mutate_devlab_state(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    before = _devlab_files(tmp_path)

    build_workflow_state_report(tmp_path)

    assert _devlab_files(tmp_path) == before


def test_workflow_state_digest_does_not_create_state_file(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    before = _devlab_files(tmp_path)

    format_workflow_state_digest(
        build_workflow_state_digest(build_workflow_state_report(tmp_path))
    )

    assert _devlab_files(tmp_path) == before
    assert not (tmp_path / "STATE.md").exists()


def test_init_records_workflow_event(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    report = build_workflow_state_report(tmp_path)

    assert report.lifecycle_events == 1


def test_repeated_init_does_not_append_duplicate_init_event(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    init_workspace(tmp_path)

    report = build_workflow_state_report(tmp_path)

    assert report.lifecycle_events == 1


def _write_required_dirs(root: Path) -> None:
    for relative in (
        ".devlab/tasks",
        ".devlab/milestones",
        ".devlab/findings",
        ".devlab/history",
        ".devlab/session-artifacts",
        ".devlab/logs/agents",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)


def _create_pending_clarification(root: Path) -> str:
    clarification = FileClarificationTracker(root).create(
        title="Auth session timeout",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="choice",
        recommended_option="A",
        body=(
            "# Auth session timeout\n\n"
            "## Context\nC\n\n"
            "## Question\nQ\n\n"
            "## Options\n"
            "- A: 24-hour idle timeout.\n"
            "- B: No expiry for MVP.\n"
        ),
    )
    return clarification.id


def _create_research(root: Path):
    research = (
        Workspace(root)
        .research()
        .create(
            title="Dependency behavior",
            asking_role="planner",
            asking_session_id="planner-1",
            command="plan",
            scope="planning",
            question="What behavior is documented?",
            context="The plan depends on it.",
            desired_outcome="Choose a supported approach.",
            acceptance_criteria=("Use a primary source.",),
        )
    )
    set_resume_state(
        root,
        ResumeState(
            blocked_by=research.id,
            blocked_kind="research",
            command="plan",
            role="planner",
        ),
    )
    return research


def _devlab_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text()
        for path in sorted((root / ".devlab").rglob("*"))
        if path.is_file()
    }

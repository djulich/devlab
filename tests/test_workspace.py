from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

import pytest

from devlab.findings import FileFindingTracker
from devlab.milestones import FileMilestoneTracker
from devlab.research import (
    FileResearchTracker,
    ResearchConfidence,
    ResearchEvidence,
    ResearchResult,
    ResearchSource,
)
from devlab.task_tracker import FileTaskTracker
from devlab.workspace import Workspace


def test_workspace_snapshot_caches_task_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_task(tmp_path, "T0001")
    calls = 0
    original = FileTaskTracker.list_tasks

    def counting_list_tasks(self: FileTaskTracker):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(FileTaskTracker, "list_tasks", counting_list_tasks)
    snapshot = Workspace(tmp_path).snapshot

    assert [task.id for task in snapshot.list_tasks()] == ["T0001"]
    assert [task.id for task in snapshot.list_tasks()] == ["T0001"]
    assert not hasattr(snapshot, "task_tracker")
    assert calls == 1


def test_workspace_snapshot_is_disposable_after_file_changes(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001")
    workspace = Workspace(tmp_path)
    snapshot = workspace.snapshot

    assert [task.id for task in snapshot.list_tasks()] == ["T0001"]

    _write_task(tmp_path, "T0002")

    assert [task.id for task in snapshot.list_tasks()] == ["T0001"]
    assert [task.id for task in workspace.snapshot.list_tasks()] == ["T0001"]
    assert [task.id for task in Workspace(tmp_path).snapshot.list_tasks()] == ["T0001", "T0002"]


def test_workspace_task_handle_invalidates_cached_snapshot(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001")
    workspace = Workspace(tmp_path)
    assert workspace.snapshot.list_tasks()[0].status == "open"

    workspace.tasks().get("T0001").mark_in_review()
    assert workspace.snapshot.list_tasks()[0].status == "in_review"

    workspace.tasks().from_path(tmp_path / ".devlab/tasks/T0001_task.md").close()
    assert workspace.snapshot.list_tasks()[0].status == "closed"


def test_workspace_snapshot_caches_research_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    workspace.research().create(**_research_request())
    calls = 0
    original = FileResearchTracker.list_research

    def counting_list_research(self: FileResearchTracker):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(FileResearchTracker, "list_research", counting_list_research)
    snapshot = workspace.snapshot

    assert [research.id for research in snapshot.list_research()] == ["RS0001"]
    assert snapshot.get_research("RS0001").title == "Lock behavior"
    assert [research.id for research in snapshot.requested_research()] == ["RS0001"]
    assert calls == 1


def test_workspace_research_create_invalidates_cached_snapshot(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    snapshot = workspace.snapshot
    assert snapshot.list_research() == []

    research = workspace.research().create(**_research_request())

    assert snapshot.list_research() == []
    assert workspace.snapshot is not snapshot
    assert workspace.snapshot.get_research(research.id) == research


def test_workspace_research_completion_invalidates_cached_snapshot(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    research = workspace.research().create(**_research_request())
    snapshot = workspace.snapshot
    assert snapshot.requested_research() == [research]

    completed = (
        workspace.research()
        .get(research.id)
        .complete(
            _research_result(),
            researcher_session_id="researcher-session",
            researcher_provider="codex",
            researcher_model="gpt-5",
            completed_at="2026-08-12T10:20:00+00:00",
        )
    )

    assert snapshot.requested_research() == [research]
    assert workspace.snapshot is not snapshot
    assert workspace.snapshot.get_research(research.id) == completed
    assert workspace.snapshot.requested_research() == []
    assert workspace.research().get(research.id).read() == completed


def test_failed_workspace_research_mutation_preserves_snapshot(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    research = workspace.research().create(**_research_request())
    snapshot = workspace.snapshot
    before = research.path.read_bytes()

    with pytest.raises(ValueError, match="unknown source"):
        workspace.research().get(research.id).complete(
            ResearchResult(
                summary="Summary.",
                evidence=(ResearchEvidence("Claim.", ("S2",)),),
                sources=(ResearchSource("S1", "Source", "docs/source.md", "repository"),),
                recommendation="Recommendation.",
                confidence=ResearchConfidence.LOW,
                unresolved_questions=(),
            ),
            researcher_session_id="researcher-session",
            researcher_provider="codex",
        )

    assert workspace.snapshot is snapshot
    assert research.path.read_bytes() == before
    assert snapshot.get_research(research.id) == research


def test_workspace_milestone_handle_exposes_tasks_and_transitions(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M1")
    _write_milestone(tmp_path, "M1")
    handoff = tmp_path / ".devlab/history/handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("handoff")
    milestone = Workspace(tmp_path).milestones().get("M1")

    assert [task.id for task in milestone.tasks()] == ["T0001"]

    milestone.mark_ready_for_integration()
    assert milestone.read().status == "tasks_complete"

    milestone.mark_integrated(handoff)
    assert milestone.read().integrated
    assert milestone.read().integration_handoff == "handoff.md"

    milestone.mark_architecture_reviewed(handoff)
    assert milestone.read().architecture_reviewed
    assert milestone.read().architecture_review_handoff == "handoff.md"


def test_production_workflow_mutations_do_not_bypass_workspace_handles() -> None:
    root = Path(__file__).resolve().parents[1] / "src/devlab"
    allowed = {
        "workspace.py",
        "task_tracker.py",
        "findings.py",
        "milestones.py",
        "research.py",
    }
    pattern = re.compile(
        r"File(?:Task|Finding|Milestone|Research)Tracker\([^\n]*\)\."
        r"(?:create|create_from_handoff|complete|mark_|close|upsert_from_tasks)"
    )

    violations = []
    for path in root.rglob("*.py"):
        if path.name in allowed:
            continue
        text = path.read_text()
        if pattern.search(text):
            violations.append(str(path.relative_to(root)))

    assert violations == []


def test_workspace_domain_handles_do_not_expose_raw_trackers(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)

    assert not isinstance(workspace.tasks(), FileTaskTracker)
    assert not isinstance(workspace.findings(), FileFindingTracker)
    assert not isinstance(workspace.milestones(), FileMilestoneTracker)
    assert not isinstance(workspace.research(), FileResearchTracker)
    assert not hasattr(workspace, "task")
    assert not hasattr(workspace, "task_from_path")
    assert not hasattr(workspace, "finding")
    assert not hasattr(workspace, "milestone")


def test_workspace_finding_handles_create_and_transition_findings(tmp_path: Path) -> None:
    handoff = tmp_path / ".devlab/history/handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("## Open Issues\nNeeds correction.\n")
    workspace = Workspace(tmp_path)

    finding = workspace.findings().create_from_handoff(
        source="integrator",
        milestone="M1",
        handoff_path=handoff,
    )
    workspace.findings().get(finding.id).mark_planned()

    planned = workspace.milestones().get("M1").planned_findings()
    assert [finding.id for finding in planned] == ["F0001"]

    planned[0].mark_resolved()
    assert workspace.findings().get("F0001").read().status == "resolved"


def test_workspace_selectors_use_all_active_task_files(tmp_path: Path) -> None:
    _write_workflow_state(tmp_path, generation=2)
    _write_task(tmp_path, "T0001", generation=1)
    _write_task(tmp_path, "T0002", generation=2)

    snapshot = Workspace(tmp_path).snapshot

    assert [task.id for task in snapshot.active_tasks()] == ["T0001", "T0002"]
    selected_task = snapshot.select_next_development_task()
    assert selected_task is not None
    assert selected_task.id == "T0001"


def test_workspace_review_selector_uses_all_active_task_files(tmp_path: Path) -> None:
    _write_workflow_state(tmp_path, generation=2)
    _write_task(tmp_path, "T0001", status="in_review", generation=1)
    _write_task(tmp_path, "T0002", status="in_review", generation=2)

    task = Workspace(tmp_path).snapshot.select_next_review_task()

    assert task is not None
    assert task.id == "T0001"


def test_workspace_integration_selector_uses_all_active_milestones(
    tmp_path: Path,
) -> None:
    _write_workflow_state(tmp_path, generation=2)
    _write_task(tmp_path, "T0001", milestone="M1", status="closed", generation=1)
    _write_milestone(tmp_path, "M1", generation=1)
    _write_task(tmp_path, "T0002", milestone="M2", status="closed", generation=2)
    _write_milestone(tmp_path, "M2", task_ids=("T0002",), generation=2)

    assert Workspace(tmp_path).snapshot.select_integration_milestone() == "M1"


def test_workspace_milestone_completion_uses_all_active_tasks(
    tmp_path: Path,
) -> None:
    _write_workflow_state(tmp_path, generation=2)
    _write_task(tmp_path, "T0001", milestone="M1", status="open", generation=1)
    _write_task(tmp_path, "T0002", milestone="M1", status="closed", generation=2)

    assert Workspace(tmp_path).snapshot.milestone_complete("M1") is False


def _write_task(
    root: Path,
    task_id: str,
    milestone: str | None = None,
    *,
    status: str = "open",
    generation: int = 1,
) -> None:
    path = root / ".devlab/tasks" / f"{task_id}_task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{task_id}"\n'
        f'status = "{status}"\n'
        f"{f'milestone = {milestone!r}' if milestone is not None else ''}\n"
        f"planning_generation = {generation}\n"
        "depends_on = []\n"
        "+++\n\n"
        f"# {task_id}\n"
    )


def _write_milestone(
    root: Path,
    milestone_id: str,
    *,
    task_ids: tuple[str, ...] = ("T0001",),
    generation: int = 1,
) -> None:
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
        f"planning_generation = {generation}\n"
        f"task_ids = {list(task_ids)!r}\n"
        'integration_handoff = ""\n'
        'architecture_review_handoff = ""\n'
        "findings = []\n"
    )


def _write_workflow_state(root: Path, *, generation: int) -> None:
    path = root / ".devlab/workflow.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"version = 1\n\n[planning]\ncomplete = true\ngeneration = {generation}\n")


class _ResearchRequest(TypedDict):
    title: str
    asking_role: str
    asking_session_id: str
    command: str
    scope: str
    question: str
    context: str
    desired_outcome: str
    acceptance_criteria: list[str]
    created_at: str


def _research_request() -> _ResearchRequest:
    return {
        "title": "Lock behavior",
        "asking_role": "planner",
        "asking_session_id": "planner-session",
        "command": "plan",
        "scope": "planning",
        "question": "How do these locks behave?",
        "context": "The design needs a cross-process lock.",
        "desired_outcome": "Recommend a safe locking approach.",
        "acceptance_criteria": ["Use primary documentation."],
        "created_at": "2026-08-12T10:15:00+00:00",
    }


def _research_result() -> ResearchResult:
    return ResearchResult(
        summary="The lock is session scoped.",
        evidence=(ResearchEvidence("The lock ends with the session.", ("S1",)),),
        sources=(
            ResearchSource(
                id="S1",
                title="Lock documentation",
                location="docs/locks.md",
                source_type="repository",
            ),
        ),
        recommendation="Use a dedicated session.",
        confidence=ResearchConfidence.HIGH,
        unresolved_questions=(),
    )

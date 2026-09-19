"""Shared workspace infrastructure for DevLab modules.

Provides constants, tracker factories, file utilities, and state query
functions used by both the orchestrator (workflow control) and prompt
builders (text generation).
"""

from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path
from typing import Any

from devlab.clarifications import Clarification, FileClarificationTracker
from devlab.environment import FileTestServiceTracker, TestService
from devlab.findings import FileFindingTracker, Finding, FindingStatus
from devlab.generations import (
    GENERATION_MANIFEST,
    GENERATIONS_DIR,
    active_generation,
    load_generation_manifest,
)
from devlab.milestones import (
    FileMilestoneTracker,
    Milestone,
    MilestoneVerification,
)
from devlab.prerequisites import (
    FilePrerequisiteTracker,
    PrerequisiteOperation,
    PrerequisiteResult,
)
from devlab.research import FileResearchTracker, Research, ResearchResult, ResearchStatus
from devlab.task_tracker import (
    FileTaskTracker,
    Task,
    TaskStatus,
    blocked_tasks,
    eligible_tasks,
    milestone_complete,
    tasks_for_milestone,
)
from devlab.version_control import commit_test_service_state
from devlab.workflow_events import append_workflow_event
from devlab.workflow_state import WORKFLOW_STATE, WorkflowState, load_workflow_state

DESIGN_PLAN = ".devlab/plans/design-plan.md"
PROJECT_PLAN = ".devlab/plans/project-plan.md"
HISTORY_DIR = ".devlab/history"
FINDINGS_DIR = ".devlab/findings"
CLARIFICATIONS_DIR = ".devlab/clarifications"
ARTIFACTS_DIR = ".devlab/session-artifacts"
AGENT_LOG_DIR = ".devlab/logs/agents"
WORKSPACE_MANIFEST = ".devlab/manifest.toml"
WORKSPACE_LAYOUT_VERSION = 1


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def read_file(path: Path) -> str:
    try:
        return path.read_text()
    except (FileNotFoundError, OSError):
        return ""


class WorkspaceCompatibilityError(ValueError):
    """A durable workspace representation cannot be safely read or mutated."""


def validate_workspace_compatibility(root: Path) -> None:
    """Reject unsupported authoritative state before a workspace operation."""
    manifest_path = root / WORKSPACE_MANIFEST
    if manifest_path.exists():
        try:
            with manifest_path.open("rb") as handle:
                manifest = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise WorkspaceCompatibilityError(
                f"{WORKSPACE_MANIFEST} is invalid TOML; restore it from version control "
                "or migrate the workspace with a compatible DevLab release"
            ) from exc
        layout_version = manifest.get("layout_version")
        if layout_version != WORKSPACE_LAYOUT_VERSION:
            raise WorkspaceCompatibilityError(
                f"{WORKSPACE_MANIFEST} has unsupported layout_version "
                f"{layout_version!r}; supported version is {WORKSPACE_LAYOUT_VERSION}. "
                "Use a compatible DevLab release to migrate the workspace, or restore "
                "a supported manifest before retrying"
            )

    workflow_path = root / WORKFLOW_STATE
    if workflow_path.exists():
        try:
            load_workflow_state(root)
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            raise WorkspaceCompatibilityError(str(exc)) from exc

    milestone_tracker = FileMilestoneTracker(root)
    try:
        milestone_tracker.list_milestones()
        for path in sorted((root / GENERATIONS_DIR).glob(f"*/{GENERATION_MANIFEST}")):
            load_generation_manifest(path)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise WorkspaceCompatibilityError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Workspace access
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Workspace:
    """Target workspace access boundary for explicit workflow mutations.

    ``snapshot`` is lazily cached and invalidated only by mutations performed
    through this ``Workspace`` or its handles. If other code or another process
    may have changed workspace files, create a new ``Workspace`` instead of
    trying to refresh this one in place.
    """

    root: Path
    _snapshot: WorkspaceSnapshot | None = dataclasses.field(default=None, init=False, repr=False)
    _tasks: FileTaskTracker | None = dataclasses.field(default=None, init=False, repr=False)
    _findings: FileFindingTracker | None = dataclasses.field(default=None, init=False, repr=False)
    _milestones: FileMilestoneTracker | None = dataclasses.field(
        default=None, init=False, repr=False
    )
    _clarifications: FileClarificationTracker | None = dataclasses.field(
        default=None, init=False, repr=False
    )
    _research: FileResearchTracker | None = dataclasses.field(default=None, init=False, repr=False)
    _prerequisites: FilePrerequisiteTracker | None = dataclasses.field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        validate_workspace_compatibility(self.root)

    def _task_tracker(self) -> FileTaskTracker:
        if self._tasks is None:
            self._tasks = FileTaskTracker(self.root)
        return self._tasks

    def _finding_tracker(self) -> FileFindingTracker:
        if self._findings is None:
            self._findings = FileFindingTracker(self.root)
        return self._findings

    def _milestone_tracker(self) -> FileMilestoneTracker:
        if self._milestones is None:
            self._milestones = FileMilestoneTracker(self.root)
        return self._milestones

    def _clarification_tracker(self) -> FileClarificationTracker:
        if self._clarifications is None:
            self._clarifications = FileClarificationTracker(self.root)
        return self._clarifications

    def _research_tracker(self) -> FileResearchTracker:
        if self._research is None:
            self._research = FileResearchTracker(self.root)
        return self._research

    def _prerequisite_tracker(self) -> FilePrerequisiteTracker:
        if self._prerequisites is None:
            self._prerequisites = FilePrerequisiteTracker(self.root)
        return self._prerequisites

    @property
    def snapshot(self) -> WorkspaceSnapshot:
        if self._snapshot is None:
            self._snapshot = WorkspaceSnapshot(
                root=self.root,
                _task_tracker=self._task_tracker(),
                _finding_tracker=self._finding_tracker(),
                _milestone_tracker=self._milestone_tracker(),
                _clarification_tracker=self._clarification_tracker(),
                _research_tracker=self._research_tracker(),
            )
        return self._snapshot

    def sync(self) -> None:
        """Mutate milestone files so stored milestone state reflects task references."""
        self._milestone_tracker().upsert_from_tasks(
            self._task_tracker().list_tasks(),
            project_plan_text=read_file(self.root / PROJECT_PLAN),
        )
        self.did_mutate()

    def tasks(self) -> WorkspaceTasks:
        return WorkspaceTasks(self)

    def findings(self) -> WorkspaceFindings:
        return WorkspaceFindings(self)

    def milestones(self) -> WorkspaceMilestones:
        return WorkspaceMilestones(self)

    def clarifications(self) -> WorkspaceClarifications:
        return WorkspaceClarifications(self)

    def research(self) -> WorkspaceResearch:
        return WorkspaceResearch(self)

    def test_services(self) -> WorkspaceTestServices:
        return WorkspaceTestServices(self)

    def prerequisites(self) -> WorkspacePrerequisites:
        return WorkspacePrerequisites(self)

    def did_mutate(self) -> None:
        self._snapshot = None


@dataclasses.dataclass(frozen=True)
class WorkspaceTestServices:
    workspace: Workspace

    def _changed(self, record: dict[str, Any]) -> None:
        self.workspace.did_mutate()
        append_workflow_event(
            self.workspace.root,
            "test_service_state",
            service=record["service"],
            instance=record["instance"],
            state=record["state"],
            outcome=record["outcome"],
            cumulative_duration_seconds=record.get("duration_seconds", 0),
        )
        commit_test_service_state(self.workspace.root, record["service"])

    def ensure(self, service: TestService) -> dict[str, str]:
        return FileTestServiceTracker(self.workspace.root, self._changed).ensure(service)

    def cleanup(self, service: TestService) -> None:
        FileTestServiceTracker(self.workspace.root, self._changed).cleanup(service)


@dataclasses.dataclass(frozen=True)
class WorkspaceTasks:
    """Task domain handle bound to a target workspace."""

    workspace: Workspace

    def get(self, task_id: str) -> WorkspaceTask:
        return WorkspaceTask(self.workspace, task_id)

    def from_path(self, path: Path) -> WorkspaceTask:
        return self.get(path.stem.split("_")[0])


@dataclasses.dataclass(frozen=True)
class WorkspaceFindings:
    """Finding domain handle bound to a target workspace."""

    workspace: Workspace

    def get(self, finding_id: str) -> WorkspaceFinding:
        return WorkspaceFinding(self.workspace, finding_id)

    def create_from_handoff(
        self,
        *,
        source: str,
        milestone: str | None,
        handoff_path: Path,
    ) -> Finding:
        finding = self.workspace._finding_tracker().create_from_handoff(
            source=source,
            milestone=milestone,
            handoff_path=handoff_path,
        )
        self.workspace.did_mutate()
        return finding

    def create_from_handoff_issues(
        self,
        *,
        source: str,
        milestone: str | None,
        handoff_name: str,
        open_issues: tuple[str, ...],
    ) -> Finding:
        finding = self.workspace._finding_tracker().create_from_handoff_issues(
            source=source,
            milestone=milestone,
            handoff_name=handoff_name,
            open_issues=open_issues,
        )
        self.workspace.did_mutate()
        return finding

    def create(
        self,
        *,
        title: str,
        source: str,
        milestone: str | None,
        body: str,
        handoff: str | None = None,
    ) -> Finding:
        finding = self.workspace._finding_tracker().create(
            title=title, source=source, milestone=milestone, body=body, handoff=handoff
        )
        self.workspace.did_mutate()
        return finding


@dataclasses.dataclass(frozen=True)
class WorkspaceMilestones:
    """Milestone domain handle bound to a target workspace."""

    workspace: Workspace

    def get(self, milestone_id: str) -> WorkspaceMilestone:
        return WorkspaceMilestone(self.workspace, milestone_id)


@dataclasses.dataclass(frozen=True)
class WorkspaceClarifications:
    """Clarification domain handle bound to a target workspace."""

    workspace: Workspace

    def get(self, clarification_id: str) -> WorkspaceClarification:
        return WorkspaceClarification(self.workspace, clarification_id)

    def create(
        self,
        *,
        title: str,
        asking_role: str,
        session_id: str,
        scope: str,
        blocks: str,
        answer_shape: str,
        body: str,
        recommended_option: str = "",
        decision_refs: tuple[str, ...] = (),
    ) -> Clarification:
        clarification = self.workspace._clarification_tracker().create(
            title=title,
            asking_role=asking_role,
            session_id=session_id,
            scope=scope,
            blocks=blocks,
            answer_shape=answer_shape,
            body=body,
            recommended_option=recommended_option,
            decision_refs=decision_refs,
        )
        self.workspace.did_mutate()
        return clarification


@dataclasses.dataclass(frozen=True)
class WorkspacePrerequisites:
    """Prerequisite blocker mutations bound to a target workspace."""

    workspace: Workspace

    def record_blocker(
        self,
        *,
        command: str,
        role: str,
        task: str,
        milestone: str,
        operation: PrerequisiteOperation,
        results: tuple[PrerequisiteResult, ...],
    ) -> bool:
        changed = self.workspace._prerequisite_tracker().record_blocker(
            command=command,
            role=role,
            task=task,
            milestone=milestone,
            operation=operation,
            results=results,
        )
        if changed:
            self.workspace.did_mutate()
        return changed

    def clear_blocker(self) -> bool:
        cleared = self.workspace._prerequisite_tracker().clear_blocker()
        if cleared:
            self.workspace.did_mutate()
        return cleared


@dataclasses.dataclass(frozen=True)
class WorkspaceResearch:
    """Research domain handle bound to a target workspace."""

    workspace: Workspace

    def get(self, research_id: str) -> WorkspaceResearchRecord:
        return WorkspaceResearchRecord(self.workspace, research_id)

    def create(
        self,
        *,
        title: str,
        asking_role: str,
        asking_session_id: str,
        command: str,
        scope: str,
        question: str,
        context: str,
        desired_outcome: str,
        acceptance_criteria: tuple[str, ...] | list[str],
        task: str = "",
        milestone: str = "",
        created_at: str | None = None,
    ) -> Research:
        research = self.workspace._research_tracker().create(
            title=title,
            asking_role=asking_role,
            asking_session_id=asking_session_id,
            command=command,
            scope=scope,
            question=question,
            context=context,
            desired_outcome=desired_outcome,
            acceptance_criteria=acceptance_criteria,
            task=task,
            milestone=milestone,
            created_at=created_at,
        )
        self.workspace.did_mutate()
        return research


@dataclasses.dataclass(frozen=True)
class WorkspaceTask:
    """Mutable task handle bound to a target workspace."""

    workspace: Workspace
    id: str

    def read(self) -> Task:
        return self.workspace._task_tracker().get(self.id)

    @property
    def path(self) -> Path:
        return self.read().path

    def mark_in_review(self) -> None:
        self.workspace._task_tracker().mark_in_review(self.id)
        self.workspace.did_mutate()

    def mark_changes_requested(self) -> None:
        self.workspace._task_tracker().mark_changes_requested(self.id)
        self.workspace.did_mutate()

    def record_validation_failure(self, summary: str) -> None:
        self.workspace._task_tracker().record_validation_failure(self.id, summary)
        self.workspace.did_mutate()

    def close(self) -> None:
        self.workspace._task_tracker().close(self.id)
        self.workspace.did_mutate()

    def resolve_addressed_findings(self) -> None:
        task = self.read()
        findings = self.workspace.findings()
        for finding_id in task.addresses_findings:
            findings.get(finding_id).resolve_if_complete()


@dataclasses.dataclass(frozen=True)
class WorkspaceMilestone:
    """Mutable milestone handle bound to a target workspace."""

    workspace: Workspace
    id: str

    def read(self) -> Milestone:
        return self.workspace._milestone_tracker().get(self.id)

    def tasks(self) -> list[WorkspaceTask]:
        task_ids = [task.id for task in self.workspace.snapshot.tasks_for_milestone(self.id)]
        tasks = self.workspace.tasks()
        return [tasks.get(task_id) for task_id in task_ids]

    def planned_findings(self) -> list[WorkspaceFinding]:
        findings = self.workspace._finding_tracker().planned_findings_for_milestone(self.id)
        finding_handles = self.workspace.findings()
        return [finding_handles.get(finding.id) for finding in findings]

    def mark_ready_for_integration(self) -> None:
        self.workspace._milestone_tracker().mark_tasks_complete(self.id)
        self.workspace.did_mutate()

    def mark_integrated(self, handoff_path: Path) -> None:
        self.workspace._milestone_tracker().mark_integrated(self.id, handoff_path)
        self.workspace.did_mutate()

    def mark_integration_failed(self, finding_id: str) -> None:
        self.workspace._milestone_tracker().mark_integration_failed(self.id, finding_id)
        self.workspace.did_mutate()

    def mark_architecture_reviewed(self, handoff_path: Path) -> None:
        self.workspace._milestone_tracker().mark_architecture_reviewed(self.id, handoff_path)
        self.workspace.did_mutate()

    def write_verification(self, verification: MilestoneVerification) -> None:
        if verification.milestone_id != self.id:
            raise ValueError("milestone verification id does not match workspace handle")
        self.workspace._milestone_tracker().write_verification(verification)
        self.workspace.did_mutate()


@dataclasses.dataclass(frozen=True)
class WorkspaceFinding:
    """Mutable finding handle bound to a target workspace."""

    workspace: Workspace
    id: str

    def read(self) -> Finding:
        return self.workspace._finding_tracker().get(self.id)

    def mark_planned(self) -> None:
        self.workspace._finding_tracker().mark_planned(self.id)
        self.workspace.did_mutate()

    def mark_resolved(self) -> None:
        self.workspace._finding_tracker().mark_resolved(self.id)
        self.workspace.did_mutate()

    def resolve_if_complete(self) -> None:
        """Mark resolved if all addressing tasks are closed."""
        snapshot = self.workspace.snapshot
        finding = self.read()
        if finding.status != FindingStatus.PLANNED:
            return
        addressing_tasks = [
            task for task in snapshot.list_tasks() if self.id in task.addresses_findings
        ]
        if addressing_tasks and all(task.status.value == "closed" for task in addressing_tasks):
            self.mark_resolved()


@dataclasses.dataclass(frozen=True)
class WorkspaceClarification:
    """Mutable clarification handle bound to a target workspace."""

    workspace: Workspace
    id: str

    def read(self) -> Clarification:
        return self.workspace._clarification_tracker().get(self.id)

    def answer(self, answer: str, *, operator: str = "") -> Clarification:
        clarification = self.workspace._clarification_tracker().answer(
            self.id,
            answer,
            operator=operator,
        )
        self.workspace.did_mutate()
        return clarification

    def answer_choice(
        self,
        choice: str,
        *,
        note: str = "",
        operator: str = "",
    ) -> Clarification:
        clarification = self.workspace._clarification_tracker().answer_choice(
            self.id,
            choice,
            note=note,
            operator=operator,
        )
        self.workspace.did_mutate()
        return clarification

    def supersede(self, reason: str) -> Clarification:
        clarification = self.workspace._clarification_tracker().supersede(self.id, reason)
        self.workspace.did_mutate()
        return clarification


@dataclasses.dataclass(frozen=True)
class WorkspaceResearchRecord:
    """Mutable research record handle bound to a target workspace."""

    workspace: Workspace
    id: str

    def read(self) -> Research:
        return self.workspace._research_tracker().get(self.id)

    def complete(
        self,
        result: ResearchResult,
        *,
        researcher_session_id: str,
        researcher_provider: str,
        researcher_model: str = "",
        completed_at: str | None = None,
    ) -> Research:
        research = self.workspace._research_tracker().complete(
            self.id,
            result,
            researcher_session_id=researcher_session_id,
            researcher_provider=researcher_provider,
            researcher_model=researcher_model,
            completed_at=completed_at,
        )
        self.workspace.did_mutate()
        return research


@dataclasses.dataclass
class WorkspaceSnapshot:
    """Cached read-only snapshot of DevLab workspace files.

    A snapshot has no refresh operation. Mutations made through its owning
    ``Workspace`` invalidate the cached snapshot; accessing ``Workspace.snapshot``
    then creates a fresh one. If files may have changed outside that ``Workspace``
    instance, create a new ``Workspace``.
    """

    root: Path
    _task_tracker: FileTaskTracker = dataclasses.field(repr=False)
    _finding_tracker: FileFindingTracker = dataclasses.field(repr=False)
    _milestone_tracker: FileMilestoneTracker = dataclasses.field(repr=False)
    _clarification_tracker: FileClarificationTracker = dataclasses.field(repr=False)
    _research_tracker: FileResearchTracker = dataclasses.field(repr=False)
    _tasks: list[Task] | None = dataclasses.field(default=None, init=False, repr=False)
    _findings: list[Finding] | None = dataclasses.field(default=None, init=False, repr=False)
    _milestones: list[Milestone] | None = dataclasses.field(default=None, init=False, repr=False)
    _clarifications: list[Clarification] | None = dataclasses.field(
        default=None, init=False, repr=False
    )
    _research: list[Research] | None = dataclasses.field(default=None, init=False, repr=False)
    _test_services: list[dict[str, Any]] | None = dataclasses.field(
        default=None, init=False, repr=False
    )
    _workflow_state: WorkflowState | None = dataclasses.field(default=None, init=False, repr=False)

    def test_service_records(self) -> list[dict[str, Any]]:
        if self._test_services is None:
            self._test_services = FileTestServiceTracker(self.root).list_records()
        return [dict(record) for record in self._test_services]

    def list_tasks(self) -> list[Task]:
        if self._tasks is None:
            self._tasks = self._task_tracker.list_tasks()
        return list(self._tasks)

    def task_file_contents(self) -> dict[str, str]:
        return {task.id: read_file(task.path) for task in self.list_tasks()}

    def list_findings(self) -> list[Finding]:
        if self._findings is None:
            self._findings = self._finding_tracker.list_findings()
        return list(self._findings)

    def list_milestones(self) -> list[Milestone]:
        if self._milestones is None:
            self._milestones = self._milestone_tracker.list_milestones()
        return list(self._milestones)

    def milestone_verification(self, milestone_id: str) -> MilestoneVerification | None:
        return self._milestone_tracker.read_verification(milestone_id)

    def list_clarifications(self) -> list[Clarification]:
        if self._clarifications is None:
            self._clarifications = self._clarification_tracker.list_clarifications()
        return list(self._clarifications)

    def pending_clarifications(self) -> list[Clarification]:
        return [
            clarification
            for clarification in self.list_clarifications()
            if clarification.status.value == "pending"
        ]

    def blocking_clarifications(self) -> list[Clarification]:
        return [
            clarification
            for clarification in self.pending_clarifications()
            if clarification.blocks != "none"
        ]

    def list_research(self) -> list[Research]:
        if self._research is None:
            self._research = self._research_tracker.list_research()
        return list(self._research)

    def get_research(self, research_id: str) -> Research:
        for research in self.list_research():
            if research.id == research_id:
                return research
        raise KeyError(f"unknown research id: {research_id}")

    def requested_research(self) -> list[Research]:
        return [
            research
            for research in self.list_research()
            if research.status == ResearchStatus.REQUESTED
        ]

    def workflow_state(self) -> WorkflowState:
        if self._workflow_state is None:
            self._workflow_state = load_workflow_state(self.root)
        return self._workflow_state

    def current_planning_generation(self) -> int:
        return active_generation(self.root)

    def current_generation_tasks(self) -> list[Task]:
        return self.list_tasks()

    def current_generation_milestones(self) -> list[Milestone]:
        return self.list_milestones()

    def active_tasks(self) -> list[Task]:
        return [task for task in self.current_generation_tasks() if task.is_active]

    def select_next_development_task(self) -> Task | None:
        tasks = eligible_tasks(self.current_generation_tasks())
        return tasks[0] if tasks else None

    def select_next_review_task(self) -> Task | None:
        for task in self.current_generation_tasks():
            if task.status == TaskStatus.IN_REVIEW:
                return task
        return None

    def blocked_tasks(self) -> list[Task]:
        return blocked_tasks(self.current_generation_tasks())

    def tasks_for_milestone(self, milestone: str) -> list[Task]:
        return tasks_for_milestone(self.current_generation_tasks(), milestone)

    def milestone_complete(self, milestone: str) -> bool:
        return milestone_complete(self.current_generation_tasks(), milestone)

    def open_findings(self) -> list[Finding]:
        return [
            finding for finding in self.list_findings() if finding.status == FindingStatus.OPEN
        ]

    def select_task(self) -> Path | None:
        task = self.select_next_development_task()
        return task.path if task else None

    def select_review_task(self) -> Path | None:
        task = self.select_next_review_task()
        return task.path if task else None

    def select_integration_milestone(self) -> str | None:
        for milestone in self.current_generation_milestones():
            if (
                milestone.integration_required
                and not milestone.integrated
                and self.milestone_complete(milestone.id)
            ):
                return milestone.id
        return None

    def select_architecture_review_milestone(self) -> str | None:
        for milestone in self.current_generation_milestones():
            if milestone.integrated and not milestone.architecture_reviewed:
                return milestone.id
        return None

    def all_milestones_complete(self) -> bool:
        tasks = self.current_generation_tasks()
        if tasks:
            return all(task.status == TaskStatus.CLOSED for task in tasks)
        text = read_file(self.root / PROJECT_PLAN)
        checked = text.count("- [x]")
        unchecked = text.count("- [ ]")
        if checked == 0 and unchecked == 0:
            return False
        return unchecked == 0

    def explicit_complete_planning_with_no_durable_work(self) -> bool:
        if not (self.root / WORKFLOW_STATE).exists():
            return False
        if not self.workflow_state().planning.complete:
            return False
        if self.current_generation_tasks():
            return False
        text = read_file(self.root / PROJECT_PLAN)
        return "- [x]" not in text and "- [ ]" not in text

    def assess_state(self) -> str | None:
        design_plan = self.root / DESIGN_PLAN
        if not design_plan.exists() or design_plan.stat().st_size == 0:
            return "architect"

        if self.select_next_review_task() is not None:
            return "reviewer"

        if self.open_findings():
            return "planner"

        if self.select_architecture_review_milestone() is not None:
            return "architect"

        if self.select_integration_milestone() is not None:
            return "integrator"

        if self.select_next_development_task() is not None:
            return "developer"

        if self.blocked_tasks():
            return None

        if self.explicit_complete_planning_with_no_durable_work():
            return None

        if self.all_milestones_complete():
            if not self.workflow_state().planning.complete:
                return "planner"
            return None

        return "planner"

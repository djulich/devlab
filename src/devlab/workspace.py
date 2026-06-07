"""Shared workspace infrastructure for DevLab modules.

Provides constants, tracker factories, file utilities, and state query
functions used by both the orchestrator (workflow control) and prompt
builders (text generation).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from devlab.findings import FileFindingTracker, Finding, FindingStatus
from devlab.milestones import FileMilestoneTracker, Milestone
from devlab.task_tracker import DEVELOPABLE_STATUSES, FileTaskTracker, Task, TaskStatus

DESIGN_PLAN = ".devlab/plans/design-plan.md"
PROJECT_PLAN = ".devlab/plans/project-plan.md"
HISTORY_DIR = ".devlab/history"
FINDINGS_DIR = ".devlab/findings"
ARTIFACTS_DIR = ".devlab/session-artifacts"
AGENT_LOG_DIR = ".devlab/logs/agents"


@dataclasses.dataclass(frozen=True)
class RoleConfig:
    name: str
    prompt_resource: str
    reads_tooling: bool
    needs_environment: bool


ROLES: dict[str, RoleConfig] = {
    "architect": RoleConfig(
        "architect",
        "role-architect.md",
        reads_tooling=True,
        needs_environment=False,
    ),
    "planner": RoleConfig(
        "planner",
        "role-planner.md",
        reads_tooling=True,
        needs_environment=False,
    ),
    "developer": RoleConfig(
        "developer",
        "role-developer.md",
        reads_tooling=True,
        needs_environment=True,
    ),
    "reviewer": RoleConfig(
        "reviewer",
        "role-reviewer.md",
        reads_tooling=True,
        needs_environment=True,
    ),
    "integrator": RoleConfig(
        "integrator",
        "role-integrator.md",
        reads_tooling=True,
        needs_environment=True,
    ),
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def read_file(path: Path) -> str:
    try:
        return path.read_text()
    except (FileNotFoundError, OSError):
        return ""


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
    _snapshot: WorkspaceSnapshot | None = dataclasses.field(
        default=None, init=False, repr=False
    )
    _tasks: FileTaskTracker | None = dataclasses.field(
        default=None, init=False, repr=False
    )
    _findings: FileFindingTracker | None = dataclasses.field(
        default=None, init=False, repr=False
    )
    _milestones: FileMilestoneTracker | None = dataclasses.field(
        default=None, init=False, repr=False
    )

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

    @property
    def snapshot(self) -> WorkspaceSnapshot:
        if self._snapshot is None:
            self._snapshot = WorkspaceSnapshot(
                root=self.root,
                _task_tracker=self._task_tracker(),
                _finding_tracker=self._finding_tracker(),
                _milestone_tracker=self._milestone_tracker(),
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

    def did_mutate(self) -> None:
        self._snapshot = None


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


@dataclasses.dataclass(frozen=True)
class WorkspaceMilestones:
    """Milestone domain handle bound to a target workspace."""

    workspace: Workspace

    def get(self, milestone_id: str) -> WorkspaceMilestone:
        return WorkspaceMilestone(self.workspace, milestone_id)


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
    _tasks: list[Task] | None = dataclasses.field(default=None, init=False, repr=False)
    _findings: list[Finding] | None = dataclasses.field(default=None, init=False, repr=False)
    _milestones: list[Milestone] | None = dataclasses.field(default=None, init=False, repr=False)

    def list_tasks(self) -> list[Task]:
        if self._tasks is None:
            self._tasks = self._task_tracker.list_tasks()
        return list(self._tasks)

    def list_findings(self) -> list[Finding]:
        if self._findings is None:
            self._findings = self._finding_tracker.list_findings()
        return list(self._findings)

    def list_milestones(self) -> list[Milestone]:
        if self._milestones is None:
            self._milestones = self._milestone_tracker.list_milestones()
        return list(self._milestones)

    def active_tasks(self) -> list[Task]:
        return [task for task in self.list_tasks() if task.is_active]

    def select_next_development_task(self) -> Task | None:
        closed_ids = {task.id for task in self.list_tasks() if task.status == TaskStatus.CLOSED}
        for task in self.list_tasks():
            if task.status in DEVELOPABLE_STATUSES and set(task.depends_on).issubset(closed_ids):
                return task
        return None

    def select_next_review_task(self) -> Task | None:
        for task in self.list_tasks():
            if task.status == TaskStatus.IN_REVIEW:
                return task
        return None

    def blocked_tasks(self) -> list[Task]:
        closed_ids = {task.id for task in self.list_tasks() if task.status == TaskStatus.CLOSED}
        return [
            task
            for task in self.list_tasks()
            if task.status in DEVELOPABLE_STATUSES
            and not set(task.depends_on).issubset(closed_ids)
        ]

    def tasks_for_milestone(self, milestone: str) -> list[Task]:
        return [task for task in self.list_tasks() if task.milestone == milestone]

    def milestone_complete(self, milestone: str) -> bool:
        tasks = self.tasks_for_milestone(milestone)
        return bool(tasks) and all(task.status == TaskStatus.CLOSED for task in tasks)

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
        for milestone in self.list_milestones():
            if (
                milestone.integration_required
                and not milestone.integrated
                and self.milestone_complete(milestone.id)
            ):
                return milestone.id
        return None

    def select_architecture_review_milestone(self) -> str | None:
        for milestone in self.list_milestones():
            if milestone.integrated and not milestone.architecture_reviewed:
                return milestone.id
        return None

    def all_milestones_complete(self) -> bool:
        tasks = self.list_tasks()
        if tasks:
            return all(task.status == TaskStatus.CLOSED for task in tasks)
        text = read_file(self.root / PROJECT_PLAN)
        checked = text.count("- [x]")
        unchecked = text.count("- [ ]")
        if checked == 0 and unchecked == 0:
            return False
        return unchecked == 0

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

        if self.all_milestones_complete():
            return None

        return "planner"


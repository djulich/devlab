"""Shared workspace infrastructure for DevLab modules.

Provides constants, tracker factories, file utilities, and state query
functions used by both the orchestrator (workflow control) and prompt
builders (text generation).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from devlab.findings import FileFindingTracker, Finding, FindingStatus
from devlab.milestones import FileMilestoneTracker, Milestone, sync_milestones_from_tasks
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


@dataclasses.dataclass(frozen=True)
class Workspace:
    """Target workspace access boundary for explicit workflow mutations."""

    root: Path

    def snapshot(self) -> WorkspaceSnapshot:
        return WorkspaceSnapshot(
            root=self.root,
            task_tracker=FileTaskTracker(self.root),
            finding_tracker=FileFindingTracker(self.root),
            milestone_tracker=FileMilestoneTracker(self.root),
        )

    def sync(self) -> None:
        """Mutate milestone files so stored milestone state reflects task references."""
        sync_milestones_from_tasks(
            self.root,
            project_plan_text=read_file(self.root / PROJECT_PLAN),
        )
        self._did_mutate()

    def task(self, task_id: str) -> WorkspaceTask:
        return WorkspaceTask(self, task_id)

    def task_from_path(self, path: Path) -> WorkspaceTask:
        return self.task(path.stem.split("_")[0])

    def milestone(self, milestone_id: str) -> WorkspaceMilestone:
        return WorkspaceMilestone(self, milestone_id)

    def finding(self, finding_id: str) -> WorkspaceFinding:
        return WorkspaceFinding(self, finding_id)

    def findings(self) -> WorkspaceFindings:
        return WorkspaceFindings(self)

    def _did_mutate(self) -> None:
        """Hook for future snapshot invalidation when Workspace owns a cached snapshot."""


@dataclasses.dataclass(frozen=True)
class WorkspaceTask:
    """Mutable task handle bound to a target workspace."""

    workspace: Workspace
    id: str

    def read(self) -> Task:
        return FileTaskTracker(self.workspace.root).get(self.id)

    @property
    def path(self) -> Path:
        return self.read().path

    def mark_in_review(self) -> None:
        FileTaskTracker(self.workspace.root).mark_in_review(self.id)
        self.workspace._did_mutate()

    def mark_changes_requested(self) -> None:
        FileTaskTracker(self.workspace.root).mark_changes_requested(self.id)
        self.workspace._did_mutate()

    def close(self) -> None:
        FileTaskTracker(self.workspace.root).close(self.id)
        self.workspace._did_mutate()


@dataclasses.dataclass(frozen=True)
class WorkspaceMilestone:
    """Mutable milestone handle bound to a target workspace."""

    workspace: Workspace
    id: str

    def read(self) -> Milestone:
        return FileMilestoneTracker(self.workspace.root).get(self.id)

    def tasks(self) -> list[WorkspaceTask]:
        task_ids = [task.id for task in self.workspace.snapshot().tasks_for_milestone(self.id)]
        return [self.workspace.task(task_id) for task_id in task_ids]

    def planned_findings(self) -> list[WorkspaceFinding]:
        findings = FileFindingTracker(self.workspace.root).planned_findings_for_milestone(
            self.id
        )
        return [self.workspace.finding(finding.id) for finding in findings]

    def mark_ready_for_integration(self) -> None:
        FileMilestoneTracker(self.workspace.root).mark_tasks_complete(self.id)
        self.workspace._did_mutate()

    def mark_integrated(self, handoff_path: Path) -> None:
        FileMilestoneTracker(self.workspace.root).mark_integrated(self.id, handoff_path)
        self.workspace._did_mutate()

    def mark_integration_failed(self, finding_id: str) -> None:
        FileMilestoneTracker(self.workspace.root).mark_integration_failed(self.id, finding_id)
        self.workspace._did_mutate()

    def mark_architecture_approved(self, handoff_path: Path) -> None:
        FileMilestoneTracker(self.workspace.root).mark_architecture_approved(
            self.id, handoff_path
        )
        self.workspace._did_mutate()


@dataclasses.dataclass(frozen=True)
class WorkspaceFinding:
    """Mutable finding handle bound to a target workspace."""

    workspace: Workspace
    id: str

    def read(self) -> Finding:
        return FileFindingTracker(self.workspace.root).get(self.id)

    def mark_planned(self) -> None:
        FileFindingTracker(self.workspace.root).mark_planned(self.id)
        self.workspace._did_mutate()

    def mark_resolved(self) -> None:
        FileFindingTracker(self.workspace.root).mark_resolved(self.id)
        self.workspace._did_mutate()


@dataclasses.dataclass(frozen=True)
class WorkspaceFindings:
    """Finding collection handle for creating workspace findings."""

    workspace: Workspace

    def create_from_handoff(
        self,
        *,
        source: str,
        milestone: str | None,
        handoff_path: Path,
    ) -> Finding:
        finding = FileFindingTracker(self.workspace.root).create_from_handoff(
            source=source,
            milestone=milestone,
            handoff_path=handoff_path,
        )
        self.workspace._did_mutate()
        return finding


@dataclasses.dataclass
class WorkspaceSnapshot:
    """Cached read-only snapshot of DevLab workspace files.

    A snapshot is disposable. Do not reuse it after workspace files may have
    changed; create a fresh snapshot with ``Workspace.snapshot()`` instead.
    """

    root: Path
    task_tracker: FileTaskTracker
    finding_tracker: FileFindingTracker
    milestone_tracker: FileMilestoneTracker
    _tasks: list[Task] | None = dataclasses.field(default=None, init=False, repr=False)
    _findings: list[Finding] | None = dataclasses.field(default=None, init=False, repr=False)
    _milestones: list[Milestone] | None = dataclasses.field(default=None, init=False, repr=False)

    def list_tasks(self) -> list[Task]:
        if self._tasks is None:
            self._tasks = self.task_tracker.list_tasks()
        return list(self._tasks)

    def list_findings(self) -> list[Finding]:
        if self._findings is None:
            self._findings = self.finding_tracker.list_findings()
        return list(self._findings)

    def list_milestones(self) -> list[Milestone]:
        if self._milestones is None:
            self._milestones = self.milestone_tracker.list_milestones()
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
            if milestone.integrated and not milestone.architecture_approved:
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
            print("No task is eligible; remaining development tasks are blocked by dependencies.")
            return None

        if self.all_milestones_complete():
            return None

        return "planner"


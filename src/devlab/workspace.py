"""Shared workspace infrastructure for DevLab modules.

Provides constants, tracker factories, file utilities, and state query
functions used by both the orchestrator (workflow control) and prompt
builders (text generation).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from devlab.findings import FileFindingTracker
from devlab.milestones import FileMilestoneTracker, sync_milestones_from_tasks
from devlab.task_tracker import FileTaskTracker

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
# Tracker factories
# ---------------------------------------------------------------------------


def task_tracker(root: Path) -> FileTaskTracker:
    return FileTaskTracker(root)


def finding_tracker(root: Path) -> FileFindingTracker:
    return FileFindingTracker(root)


def milestone_tracker(root: Path) -> FileMilestoneTracker:
    return FileMilestoneTracker(root)


def sync_milestone_state(root: Path) -> None:
    """Mutate milestone files so stored milestone state reflects task references."""
    sync_milestones_from_tasks(root, project_plan_text=read_file(root / PROJECT_PLAN))


# ---------------------------------------------------------------------------
# State queries
# ---------------------------------------------------------------------------


def select_task(root: Path) -> Path | None:
    """Select the lowest-numbered task eligible for development."""
    task = task_tracker(root).select_next_development_task()
    return task.path if task else None


def select_review_task(root: Path) -> Path | None:
    task = task_tracker(root).select_next_review_task()
    return task.path if task else None


def select_integration_milestone(root: Path) -> str | None:
    tasks = task_tracker(root)
    for milestone in milestone_tracker(root).list_milestones():
        if (
            milestone.integration_required
            and not milestone.integrated
            and tasks.milestone_complete(milestone.id)
        ):
            return milestone.id
    return None


def select_architecture_review_milestone(root: Path) -> str | None:
    for milestone in milestone_tracker(root).list_milestones():
        if milestone.integrated and not milestone.architecture_approved:
            return milestone.id
    return None


def _all_milestones_complete(root: Path) -> bool:
    tracker = task_tracker(root)
    if tracker.has_tasks():
        return tracker.all_tasks_closed()
    text = read_file(root / PROJECT_PLAN)
    checked = text.count("- [x]")
    unchecked = text.count("- [ ]")
    if checked == 0 and unchecked == 0:
        return False
    return unchecked == 0


def assess_state(root: Path) -> str | None:
    design_plan = root / DESIGN_PLAN
    if not design_plan.exists() or design_plan.stat().st_size == 0:
        return "architect"

    tracker = task_tracker(root)

    if tracker.select_next_review_task() is not None:
        return "reviewer"

    if finding_tracker(root).open_findings():
        return "planner"

    if select_architecture_review_milestone(root) is not None:
        return "architect"

    if select_integration_milestone(root) is not None:
        return "integrator"

    if tracker.select_next_development_task() is not None:
        return "developer"

    if tracker.blocked_tasks():
        print("No task is eligible; remaining development tasks are blocked by dependencies.")
        return None

    if _all_milestones_complete(root):
        return None

    return "planner"

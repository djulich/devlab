"""Session context formatting for orchestrator log messages."""

from __future__ import annotations

from devlab.profiles import DEFAULT_PROFILE
from devlab.task_tracker import Task
from devlab.workspace import DESIGN_PLAN, WorkspaceSnapshot


def session_start_context(snapshot: WorkspaceSnapshot, role_name: str, task: Task | None) -> str:
    if role_name in {"developer", "reviewer"}:
        if task is None:
            return "task=none"
        return _format_task_context(task)
    if role_name == "planner":
        open_findings = len(snapshot.open_findings())
        active_tasks = len(snapshot.active_tasks())
        total_tasks = len(snapshot.list_tasks())
        return f"tasks={total_tasks} active_tasks={active_tasks} open_findings={open_findings}"
    if role_name == "integrator":
        milestone = snapshot.select_integration_milestone()
        if milestone is None:
            return "milestone=none"
        tasks = snapshot.tasks_for_milestone(milestone)
        closed = sum(1 for t in tasks if t.status.value == "closed")
        return f"milestone={milestone} closed_tasks={closed}/{len(tasks)}"
    if role_name == "architect":
        milestone = snapshot.select_architecture_review_milestone()
        if milestone is not None:
            return f"mode=architecture-review milestone={milestone}"
        if not (snapshot.root / DESIGN_PLAN).exists():
            return "mode=initial-design"
        return "mode=architecture"
    return ""


def session_finish_context(
    snapshot: WorkspaceSnapshot,
    role_name: str,
    *,
    task_id: str | None,
    milestone_id: str | None,
) -> str:
    parts: list[str] = []
    if role_name in {"developer", "reviewer"} and task_id is not None:
        task = _task_by_id(snapshot, task_id)
        parts.append(f"task={task_id}")
        if task is not None:
            parts.append(f"status={task.status.value}")
    elif role_name in {"integrator", "architect"} and milestone_id is not None:
        parts.append(f"milestone={milestone_id}")
    next_role = snapshot.assess_state()
    parts.append(f"next={next_role or 'complete'}")
    return " ".join(parts)


def _task_by_id(snapshot: WorkspaceSnapshot, task_id: str) -> Task | None:
    for task in snapshot.list_tasks():
        if task.id == task_id:
            return task
    return None


def _format_task_context(task: Task) -> str:
    parts = [
        f"task={task.id}",
        f"status={task.status.value}",
        f"profile={task.profile or DEFAULT_PROFILE}",
        f"domain={task.domain}",
    ]
    if task.milestone:
        parts.append(f"milestone={task.milestone}")
    return " ".join(parts)

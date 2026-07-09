from __future__ import annotations

import tomllib
from pathlib import Path

from devlab.clarification_ops import validate_clarification_answer
from devlab.clarifications import CLARIFICATIONS_DIR, FileClarificationTracker
from devlab.doctor_common import DoctorProblem, display_path
from devlab.findings import FindingStatus
from devlab.git import VersionControlError, run_git
from devlab.milestones import MILESTONE_ID_RE, MILESTONES_DIR, FileMilestoneTracker
from devlab.task_tracker import DEFAULT_TASK_DOMAIN
from devlab.workflow_state import WORKFLOW_STATE, load_workflow_state
from devlab.workspace import WorkspaceSnapshot

KNOWN_TASK_DOMAINS = {DEFAULT_TASK_DOMAIN, "deployment"}


def check_workflow_state(root: Path) -> list[DoctorProblem]:
    path = root / WORKFLOW_STATE
    if not (root / ".devlab").exists():
        return []
    if not path.exists() and not (root / ".devlab/manifest.toml").exists():
        return []
    if not path.exists():
        return [
            DoctorProblem(
                WORKFLOW_STATE,
                "missing workflow state; run devlab init or create version/planning.complete",
            )
        ]
    try:
        load_workflow_state(root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return [DoctorProblem(WORKFLOW_STATE, str(exc))]
    return []


def check_git_worktree(root: Path) -> list[DoctorProblem]:
    """Report dirty Git state when the target is already inside a Git repository."""
    try:
        run_git(root, "rev-parse", "--is-inside-work-tree")
        status = run_git(root, "status", "--porcelain").stdout.splitlines()
    except VersionControlError:
        return []
    if not status:
        return []
    preview = ", ".join(line.strip() for line in status[:5])
    if len(status) > 5:
        preview += f", ... and {len(status) - 5} more"
    return [
        DoctorProblem(
            ".",
            "working tree is dirty; commit, stash, or ignore changes before running "
            f"DevLab plan/implement ({preview})",
        )
    ]


def check_task_domains(snapshot: WorkspaceSnapshot) -> list[DoctorProblem]:
    problems: list[DoctorProblem] = []
    root = snapshot.root
    for task in snapshot.list_tasks():
        if task.domain not in KNOWN_TASK_DOMAINS:
            problems.append(
                DoctorProblem(
                    display_path(task.path, root),
                    f"unknown task domain {task.domain!r}; no built-in domain prompt "
                    "overlay will be used",
                )
            )
    return problems


def check_clarifications(root: Path) -> list[DoctorProblem]:
    clarifications_dir = root / CLARIFICATIONS_DIR
    if not clarifications_dir.exists():
        return []
    problems: list[DoctorProblem] = []
    tracker = FileClarificationTracker(root)
    for path in sorted(clarifications_dir.glob("CL*.md")):
        try:
            clarification = tracker.read_path(path)
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            problems.append(DoctorProblem(display_path(path, root), str(exc)))
            continue
        if clarification.status.value == "pending":
            if "## Context" not in clarification.body:
                problems.append(
                    DoctorProblem(
                        display_path(path, root),
                        "pending clarification is missing ## Context",
                    )
                )
            if "## Question" not in clarification.body:
                problems.append(
                    DoctorProblem(
                        display_path(path, root),
                        "pending clarification is missing ## Question",
                    )
                )
        else:
            validation = validate_clarification_answer(root, clarification.id)
            if not validation.valid:
                problems.append(DoctorProblem(display_path(path, root), validation.message))
    return problems


def check_milestones(root: Path, snapshot: WorkspaceSnapshot) -> list[DoctorProblem]:
    problems: list[DoctorProblem] = []
    tasks = snapshot.list_tasks()
    task_by_id = {task.id: task for task in tasks}
    milestone_dir = root / MILESTONES_DIR
    milestone_files = sorted(milestone_dir.glob("M*.toml")) if milestone_dir.exists() else []
    milestone_by_id = {}
    seen_ids: dict[str, str] = {}
    milestone_tracker = FileMilestoneTracker(root)

    for path in milestone_files:
        path_display = display_path(path, root)
        if not MILESTONE_ID_RE.fullmatch(path.stem):
            problems.append(
                DoctorProblem(path_display, f"filename {path.name!r} is not a valid milestone ID")
            )
        try:
            milestone = milestone_tracker.get(path.stem)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            problems.append(DoctorProblem(path_display, str(exc)))
            continue
        if milestone.id != path.stem:
            problems.append(
                DoctorProblem(
                    path_display,
                    f"id {milestone.id!r} does not match filename {path.stem!r}",
                )
            )
        if milestone.id in seen_ids:
            problems.append(
                DoctorProblem(
                    path_display,
                    f"duplicate milestone id {milestone.id!r}; first seen in "
                    f"{seen_ids[milestone.id]}",
                )
            )
        seen_ids[milestone.id] = path_display
        milestone_by_id[milestone.id] = milestone

    for task in tasks:
        if task.milestone is None:
            continue
        milestone = milestone_by_id.get(task.milestone)
        task_path = display_path(task.path, root)
        if milestone is None:
            problems.append(
                DoctorProblem(task_path, f"references missing milestone {task.milestone!r}")
            )
        elif task.id not in milestone.task_ids:
            problems.append(
                DoctorProblem(
                    display_path(milestone.path, root),
                    f"does not list task {task.id!r} referenced by {task_path}",
                )
            )

    findings = snapshot.list_findings()
    finding_ids = {finding.id: finding for finding in findings}
    addressing_tasks: dict[str, list[str]] = {finding.id: [] for finding in findings}
    for task in tasks:
        task_path = display_path(task.path, root)
        for finding_id in task.addresses_findings:
            finding = finding_ids.get(finding_id)
            if finding is None:
                problems.append(
                    DoctorProblem(
                        task_path,
                        f"addresses_findings references unknown finding {finding_id!r}",
                    )
                )
                continue
            addressing_tasks.setdefault(finding_id, []).append(task.id)

    for finding in findings:
        task_ids = addressing_tasks.get(finding.id, [])
        if finding.status == FindingStatus.OPEN and task_ids:
            problems.append(
                DoctorProblem(
                    display_path(finding.path, root),
                    "open finding has addressing tasks but is not planned",
                )
            )
        elif finding.status == FindingStatus.PLANNED:
            if not task_ids:
                problems.append(
                    DoctorProblem(
                        display_path(finding.path, root),
                        "planned finding has no addressing tasks",
                    )
                )
            else:
                related = [task_by_id[task_id] for task_id in task_ids if task_id in task_by_id]
                if related and all(task.status.value == "closed" for task in related):
                    problems.append(
                        DoctorProblem(
                            display_path(finding.path, root),
                            "planned finding has all addressing tasks closed",
                        )
                    )

    for milestone in milestone_by_id.values():
        path_display = display_path(milestone.path, root)
        for task_id in milestone.task_ids:
            task = task_by_id.get(task_id)
            if task is None:
                problems.append(
                    DoctorProblem(path_display, f"task_ids references unknown task {task_id!r}")
                )
            elif task.milestone != milestone.id:
                problems.append(
                    DoctorProblem(
                        path_display,
                        f"task_ids references {task_id!r} but task milestone is "
                        f"{task.milestone!r}",
                    )
                )
        if milestone.integrated and not milestone.integration_handoff:
            problems.append(
                DoctorProblem(path_display, "integrated milestone is missing integration_handoff")
            )
        if milestone.architecture_reviewed and not milestone.integrated:
            problems.append(
                DoctorProblem(path_display, "architecture-reviewed milestone is not integrated")
            )
        if milestone.architecture_reviewed and not milestone.architecture_review_handoff:
            problems.append(
                DoctorProblem(
                    path_display,
                    "architecture-reviewed milestone is missing architecture_review_handoff",
                )
            )
        for finding_id in milestone.findings:
            finding = finding_ids.get(finding_id)
            if finding is None:
                problems.append(
                    DoctorProblem(
                        path_display,
                        f"findings references unknown finding {finding_id!r}",
                    )
                )
            elif finding.milestone != milestone.id:
                problems.append(
                    DoctorProblem(
                        path_display,
                        f"findings references {finding_id!r} but finding milestone is "
                        f"{finding.milestone!r}",
                    )
                )
    return problems

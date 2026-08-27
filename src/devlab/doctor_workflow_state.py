from __future__ import annotations

import tomllib
from pathlib import Path

from devlab.clarification_ops import validate_clarification_answer
from devlab.clarifications import CLARIFICATIONS_DIR, FileClarificationTracker
from devlab.doctor_common import DoctorProblem, display_path
from devlab.findings import FindingStatus
from devlab.git import VersionControlError, run_git
from devlab.milestones import (
    MILESTONE_ID_RE,
    MILESTONE_VERIFICATION_DIR,
    MILESTONES_DIR,
    FileMilestoneTracker,
)
from devlab.profiles import profile_path
from devlab.research import (
    RESEARCH_DIR,
    FileResearchTracker,
    ResearchStatus,
    parse_research_result_candidate,
)
from devlab.task_tracker import DEFAULT_TASK_DOMAIN
from devlab.workflow_state import WORKFLOW_STATE, load_workflow_state
from devlab.workspace import ARTIFACTS_DIR, WorkspaceSnapshot

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


def check_research_resume_state(root: Path) -> list[DoctorProblem]:
    """Report inconsistent requested-research and resume-pointer pairs read-only."""
    research_dir = root / RESEARCH_DIR
    artifact_problems = _check_researcher_artifacts(root)
    if not research_dir.exists():
        return artifact_problems
    try:
        research = FileResearchTracker(root).list_research()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return [DoctorProblem(RESEARCH_DIR, str(exc)), *artifact_problems]
    try:
        resume = load_workflow_state(root).resume
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return []
    requested = [item for item in research if item.status == ResearchStatus.REQUESTED]
    problems: list[DoctorProblem] = list(artifact_problems)
    if resume is None or resume.blocked_kind != "research":
        for item in requested:
            problems.append(
                DoctorProblem(
                    display_path(item.path, root),
                    "requested research has no matching research resume pointer",
                )
            )
        return problems
    matches = [item for item in research if item.id == resume.blocked_by]
    if not matches:
        problems.append(
            DoctorProblem(
                WORKFLOW_STATE,
                f"research resume references missing {resume.blocked_by}",
            )
        )
        return problems
    item = matches[0]
    route_pairs = (
        ("command", resume.command, item.command),
        ("role", resume.role, item.asking_role),
        ("task", resume.task, item.task),
        ("milestone", resume.milestone, item.milestone),
    )
    for field, pointer_value, record_value in route_pairs:
        if pointer_value != record_value:
            problems.append(
                DoctorProblem(
                    WORKFLOW_STATE,
                    f"research resume {field} {pointer_value!r} does not match "
                    f"{item.id} value {record_value!r}",
                )
            )
    expected_scope = (
        f"task:{item.task}"
        if item.task
        else f"milestone:{item.milestone}"
        if item.milestone
        else "planning"
        if item.command == "plan"
        else "workspace"
    )
    if item.scope != expected_scope:
        problems.append(
            DoctorProblem(
                display_path(item.path, root),
                f"research scope {item.scope!r} does not match stored route "
                f"scope {expected_scope!r}",
            )
        )
    for other in requested:
        if other.id != item.id:
            problems.append(
                DoctorProblem(
                    display_path(other.path, root),
                    "requested research has no matching research resume pointer",
                )
            )
    return problems


def _check_researcher_artifacts(root: Path) -> list[DoctorProblem]:
    directory = root / ARTIFACTS_DIR / "researcher"
    if not directory.exists():
        return []
    problems: list[DoctorProblem] = []
    entries = sorted(path for path in directory.iterdir() if path.name != ".gitkeep")
    for path in entries:
        if path.name != "result.json" or not path.is_file():
            problems.append(
                DoctorProblem(
                    display_path(path, root),
                    "unexpected staged researcher artifact; only result.json is allowed",
                )
            )
    result_path = directory / "result.json"
    if not result_path.is_file():
        return problems
    try:
        resume = load_workflow_state(root).resume
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return problems
    if resume is None or resume.blocked_kind != "research":
        problems.append(
            DoctorProblem(
                display_path(result_path, root),
                "staged researcher result has no active research resume pointer",
            )
        )
        return problems
    try:
        parse_research_result_candidate(result_path, research_id=resume.blocked_by)
    except (OSError, ValueError) as exc:
        problems.append(DoctorProblem(display_path(result_path, root), str(exc)))
    return problems


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


def check_task_contracts(snapshot: WorkspaceSnapshot) -> list[DoctorProblem]:
    """Report deterministic task work-packet defects before agent execution."""
    problems: list[DoctorProblem] = []
    tasks = snapshot.list_tasks()
    task_ids = {task.id for task in tasks}
    dependencies = {task.id: task.depends_on for task in tasks}
    for task in tasks:
        task_path = display_path(task.path, snapshot.root)
        for issue in task.contract_errors:
            problems.append(DoctorProblem(task_path, issue))
        for dependency in task.depends_on:
            if dependency not in task_ids:
                problems.append(
                    DoctorProblem(task_path, f"depends_on references unknown task {dependency!r}")
                )
        if task.profile is not None and not profile_path(snapshot.root, task.profile).exists():
            problems.append(
                DoctorProblem(task_path, f"references missing profile {task.profile!r}")
            )
    for cycle in _dependency_cycles(dependencies):
        task = next(task for task in tasks if task.id == cycle[0])
        problems.append(
            DoctorProblem(
                display_path(task.path, snapshot.root),
                "dependency cycle: " + " -> ".join((*cycle, cycle[0])),
            )
        )
    return problems


def _dependency_cycles(dependencies: dict[str, tuple[str, ...]]) -> list[tuple[str, ...]]:
    cycles: set[tuple[str, ...]] = set()
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            cycle = visiting[visiting.index(task_id) :]
            rotations = [tuple(cycle[index:] + cycle[:index]) for index in range(len(cycle))]
            cycles.add(min(rotations))
            return
        if task_id in visited:
            return
        visiting.append(task_id)
        for dependency in dependencies.get(task_id, ()):
            if dependency in dependencies:
                visit(dependency)
        visiting.pop()
        visited.add(task_id)

    for task_id in dependencies:
        visit(task_id)
    return sorted(cycles)


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
    verification_dir = root / MILESTONE_VERIFICATION_DIR
    for path in sorted(verification_dir.glob("*.toml")):
        path_display = display_path(path, root)
        try:
            verification = milestone_tracker.read_verification(path.stem)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            problems.append(
                DoctorProblem(
                    path_display,
                    str(exc),
                    blocks=frozenset(),
                )
            )
            continue
        if verification is None:
            continue
        if verification.milestone_id != path.stem:
            problems.append(DoctorProblem(path_display, "milestone_id does not match filename"))
        if verification.milestone_id not in milestone_by_id:
            problems.append(DoctorProblem(path_display, "references unknown milestone"))
        for task_id in verification.closed_task_ids:
            if task_id not in task_by_id:
                problems.append(
                    DoctorProblem(path_display, f"references unknown task {task_id!r}")
                )
        for finding_id in verification.finding_ids:
            if finding_id not in finding_ids:
                problems.append(
                    DoctorProblem(path_display, f"references unknown finding {finding_id!r}")
                )
        for handoff in (
            verification.integration_handoff,
            verification.architecture_handoff,
        ):
            if handoff and not (root / ".devlab/history" / handoff).exists():
                problems.append(
                    DoctorProblem(path_display, f"references missing handoff {handoff!r}")
                )
        for command in verification.commands:
            log_path = Path(command.log_path)
            if (
                command.log_path
                and not (log_path if log_path.is_absolute() else root / log_path).exists()
            ):
                problems.append(
                    DoctorProblem(
                        path_display,
                        f"references missing validation log {command.log_path!r}",
                    )
                )
    return problems

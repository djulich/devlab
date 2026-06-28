from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable
from pathlib import Path

from devlab.findings import Finding, FindingStatus
from devlab.generations import (
    GENERATION_MANIFEST,
    active_generation,
    archived_generation_numbers,
    generation_path,
    load_generation_manifest,
)
from devlab.git import VersionControlError
from devlab.milestones import Milestone, MilestoneStatus
from devlab.spec_reconciliation import inspect_spec_reconciliation
from devlab.task_tracker import Task, TaskStatus
from devlab.workflow_events import (
    WorkflowEvent,
    count_events,
    first_planning_mode,
    load_workflow_events,
)
from devlab.workflow_history import derive_session_records
from devlab.workspace import DESIGN_PLAN, PROJECT_PLAN, Workspace


@dataclasses.dataclass(frozen=True)
class PlanningReport:
    complete: bool
    design_plan_present: bool
    project_plan_present: bool


@dataclasses.dataclass(frozen=True)
class SpecReport:
    baseline_commit: str
    specs_changed_since_baseline: bool | None
    dirty_spec_paths: list[str]
    reconciliations: int
    plan_replacements: int


@dataclasses.dataclass(frozen=True)
class GenerationReport:
    active: int
    archived: list[int]


@dataclasses.dataclass(frozen=True)
class PlanningHistoryReport:
    architect_sessions: int
    planner_sessions: int
    greenfield_planning_runs: int | None
    adoption_planning_runs: int | None
    plan_revisions: int | None
    reconciliations: int
    plan_replacements: int


@dataclasses.dataclass(frozen=True)
class CurrentWorkReport:
    tasks_total: int
    tasks_closed: int
    tasks_active: int
    milestones_total: int
    findings_open: int
    findings_planned: int
    findings_resolved: int


@dataclasses.dataclass(frozen=True)
class WorkflowStateReport:
    project_mode: str
    lifecycle_phase: str
    next_role: str | None
    planning: PlanningReport
    generations: GenerationReport
    specs: SpecReport
    history: PlanningHistoryReport
    current_work: CurrentWorkReport
    lifecycle_events: int

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


def build_workflow_state_report(root: Path) -> WorkflowStateReport:
    events = load_workflow_events(root)
    if not (root / ".devlab").exists() or not (root / ".devlab/manifest.toml").exists():
        return _uninitialized_report(root, events)

    workspace = Workspace(root)
    snapshot = workspace.snapshot
    next_role = snapshot.assess_state()
    workflow_state = snapshot.workflow_state()
    tasks = snapshot.list_tasks()
    milestones = snapshot.list_milestones()
    findings = snapshot.list_findings()
    current_work = _current_work_report(tasks, milestones, findings)
    planning = PlanningReport(
        complete=workflow_state.planning.complete,
        design_plan_present=_non_empty(root / DESIGN_PLAN),
        project_plan_present=_non_empty(root / PROJECT_PLAN),
    )
    specs = _spec_report(root, workflow_state.specs.last_planned_spec_commit, events)
    history = _planning_history_report(root, events, specs)
    return WorkflowStateReport(
        project_mode=_project_mode(events),
        lifecycle_phase=_lifecycle_phase(
            planning=planning,
            next_role=next_role,
            current_work=current_work,
            milestones=milestones,
            planning_complete=workflow_state.planning.complete,
        ),
        next_role=next_role,
        planning=planning,
        generations=GenerationReport(
            active=active_generation(root),
            archived=list(archived_generation_numbers(root)),
        ),
        specs=specs,
        history=history,
        current_work=current_work,
        lifecycle_events=len(events),
    )


def format_workflow_state_report(report: WorkflowStateReport) -> str:
    lines = ["Workflow state:"]
    lines.append(f"Project mode: {report.project_mode}")
    lines.append(f"Lifecycle phase: {report.lifecycle_phase}")
    lines.append(f"Next role: {report.next_role or 'none'}")
    lines.append(f"Planning: {_bool_text(report.planning.complete)}")
    lines.append(f"Design plan: {_present_text(report.planning.design_plan_present)}")
    lines.append(f"Project plan: {_present_text(report.planning.project_plan_present)}")
    lines.append(f"Active generation: {report.generations.active}")
    lines.append(f"Archived generations: {len(report.generations.archived)}")
    lines.append("")
    lines.append("Spec reconciliation:")
    lines.append(f"Baseline commit: {report.specs.baseline_commit or 'none'}")
    lines.append(
        "Specs changed since baseline: "
        + _unknown_bool_text(report.specs.specs_changed_since_baseline)
    )
    dirty = ", ".join(report.specs.dirty_spec_paths) or "none"
    lines.append(f"Dirty spec paths: {dirty}")
    lines.append(f"Reconciliations: {report.specs.reconciliations}")
    lines.append(f"Plan replacements: {report.specs.plan_replacements}")
    lines.append("")
    lines.append("Planning history:")
    lines.append(f"Architect sessions: {report.history.architect_sessions}")
    lines.append(f"Planner sessions: {report.history.planner_sessions}")
    lines.append(
        "Greenfield planning runs: "
        + _unknown_int_text(report.history.greenfield_planning_runs)
    )
    lines.append(
        "Adoption planning runs: "
        + _unknown_int_text(report.history.adoption_planning_runs)
    )
    lines.append(f"Plan revisions: {_unknown_int_text(report.history.plan_revisions)}")
    lines.append(f"Reconciliations: {report.history.reconciliations}")
    lines.append(f"Plan replacements: {report.history.plan_replacements}")
    lines.append("")
    lines.append("Current work:")
    lines.append(
        "Tasks: "
        f"{report.current_work.tasks_total} total, "
        f"{report.current_work.tasks_closed} closed, "
        f"{report.current_work.tasks_active} active"
    )
    lines.append(f"Milestones: {report.current_work.milestones_total} total")
    lines.append(
        "Findings: "
        f"{report.current_work.findings_open} open, "
        f"{report.current_work.findings_planned} planned, "
        f"{report.current_work.findings_resolved} resolved"
    )
    return "\n".join(lines)


def format_workflow_state_markdown(report: WorkflowStateReport) -> str:
    lines = ["# Workflow State", ""]
    lines.append(f"- Lifecycle phase: {report.lifecycle_phase}")
    lines.append(f"- Project mode: {report.project_mode}")
    lines.append(f"- Next role: {report.next_role or 'none'}")
    lines.append(f"- Active generation: {report.generations.active}")
    lines.append(f"- Archived generations: {len(report.generations.archived)}")
    lines.append("")
    lines.append("## Next Action")
    lines.append("")
    lines.append(_next_action(report))
    lines.append("")
    lines.append("## Current Work")
    lines.append("")
    lines.append(
        "- Tasks: "
        f"{report.current_work.tasks_total} total, "
        f"{report.current_work.tasks_closed} closed, "
        f"{report.current_work.tasks_active} active"
    )
    lines.append(
        "- Findings: "
        f"{report.current_work.findings_open} open, "
        f"{report.current_work.findings_planned} planned, "
        f"{report.current_work.findings_resolved} resolved"
    )
    lines.append(f"- Milestones: {report.current_work.milestones_total} total")
    lines.append("")
    lines.append("## Specs")
    lines.append("")
    lines.append(f"- Baseline commit: {report.specs.baseline_commit or 'none'}")
    lines.append(
        "- Changed since baseline: "
        + _unknown_bool_text(report.specs.specs_changed_since_baseline)
    )
    dirty = ", ".join(report.specs.dirty_spec_paths) or "none"
    lines.append(f"- Dirty spec paths: {dirty}")
    lines.append(f"- Reconciliations: {report.specs.reconciliations}")
    lines.append(f"- Plan replacements: {report.specs.plan_replacements}")
    lines.append("")
    lines.append("## Planning History")
    lines.append("")
    lines.append(f"- Architect sessions: {report.history.architect_sessions}")
    lines.append(f"- Planner sessions: {report.history.planner_sessions}")
    lines.append(
        "- Greenfield planning runs: "
        + _unknown_int_text(report.history.greenfield_planning_runs)
    )
    lines.append(
        "- Adoption planning runs: "
        + _unknown_int_text(report.history.adoption_planning_runs)
    )
    lines.append(f"- Plan revisions: {_unknown_int_text(report.history.plan_revisions)}")
    lines.append(f"- Reconciliations: {report.history.reconciliations}")
    lines.append(f"- Plan replacements: {report.history.plan_replacements}")
    lines.append("")
    lines.append("## Validation")
    lines.append("")
    lines.append("Validation state: not reported.")
    notes = _markdown_notes(report)
    if notes:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        lines.extend(f"- {note}" for note in notes)
    return "\n".join(lines)


def _next_action(report: WorkflowStateReport) -> str:
    if report.lifecycle_phase == "uninitialized":
        return "Run `devlab init` to initialize DevLab workflow state."
    if report.specs.dirty_spec_paths:
        return "Commit or revert dirty spec paths, then run `devlab plan` to reconcile specs."
    if report.specs.specs_changed_since_baseline is True:
        return "Run `devlab plan` to reconcile committed spec changes."
    if report.next_role in {"architect", "planner"}:
        return "Run `devlab plan` to continue design or planning."
    if report.next_role in {"developer", "reviewer", "integrator"}:
        return "Run `devlab implement` to continue the next eligible workflow session."
    if report.lifecycle_phase == "complete":
        return "No workflow action is currently required."
    if report.lifecycle_phase == "blocked or inconsistent":
        return "Run `devlab status --verbose` and `devlab doctor` to inspect the blockage."
    return "Inspect `devlab status --verbose` for the next workflow action."


def _markdown_notes(report: WorkflowStateReport) -> list[str]:
    notes: list[str] = []
    if report.project_mode == "unknown":
        notes.append(
            "Project mode is unknown because no initial planning mode event is available."
        )
    if (
        report.history.greenfield_planning_runs is None
        or report.history.adoption_planning_runs is None
        or report.history.plan_revisions is None
    ):
        notes.append(
            "Some planning history is unknown for older workspaces without lifecycle events."
        )
    if report.specs.specs_changed_since_baseline is None:
        notes.append("Spec reconciliation status could not be verified from Git state.")
    return notes


def _uninitialized_report(root: Path, events: list[WorkflowEvent]) -> WorkflowStateReport:
    specs = _spec_report(root, "", events)
    history = _planning_history_report(root, events, specs)
    return WorkflowStateReport(
        project_mode=_project_mode(events),
        lifecycle_phase="uninitialized",
        next_role=None,
        planning=PlanningReport(
            complete=False,
            design_plan_present=False,
            project_plan_present=False,
        ),
        generations=GenerationReport(active=active_generation(root), archived=[]),
        specs=specs,
        history=history,
        current_work=CurrentWorkReport(
            tasks_total=0,
            tasks_closed=0,
            tasks_active=0,
            milestones_total=0,
            findings_open=0,
            findings_planned=0,
            findings_resolved=0,
        ),
        lifecycle_events=len(events),
    )


def _spec_report(
    root: Path,
    baseline_commit: str | None,
    events: list[WorkflowEvent],
) -> SpecReport:
    changed: bool | None = None
    dirty_paths: list[str] = []
    if (root / ".git").exists() and (root / ".devlab").exists():
        try:
            status = inspect_spec_reconciliation(
                root,
                Workspace(root).snapshot.workflow_state(),
            )
            changed = status.changed
            dirty_paths = list(status.dirty_spec_paths)
            baseline_commit = status.baseline_spec_commit
        except (OSError, ValueError, VersionControlError):
            changed = None
            dirty_paths = []

    reconciliations = count_events(events, "generation_archived", mode="spec_reconciliation")
    replacements = count_events(events, "generation_archived", mode="replace_plan")
    if not events:
        inferred = _generation_reason_counts(root)
        reconciliations = inferred.get("spec_reconciliation", 0)
        replacements = inferred.get("replace_plan", 0)
    return SpecReport(
        baseline_commit=baseline_commit or "",
        specs_changed_since_baseline=changed,
        dirty_spec_paths=dirty_paths,
        reconciliations=reconciliations,
        plan_replacements=replacements,
    )


def _planning_history_report(
    root: Path,
    events: list[WorkflowEvent],
    specs: SpecReport,
) -> PlanningHistoryReport:
    sessions = derive_session_records(root)
    has_events = bool(events)
    return PlanningHistoryReport(
        architect_sessions=sum(1 for session in sessions if session.role == "architect"),
        planner_sessions=sum(1 for session in sessions if session.role == "planner"),
        greenfield_planning_runs=(
            count_events(events, "plan_started", mode="greenfield") if has_events else None
        ),
        adoption_planning_runs=(
            count_events(events, "plan_started", mode="adopt_existing")
            if has_events
            else None
        ),
        plan_revisions=(
            count_events(events, "plan_started", mode="revise") if has_events else None
        ),
        reconciliations=specs.reconciliations,
        plan_replacements=specs.plan_replacements,
    )


def _generation_reason_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for number in archived_generation_numbers(root):
        path = generation_path(root, number) / GENERATION_MANIFEST
        try:
            manifest = load_generation_manifest(path)
        except (OSError, ValueError):
            continue
        counts[manifest.reason] = counts.get(manifest.reason, 0) + 1
    return counts


def _project_mode(events: list[WorkflowEvent]) -> str:
    mode = first_planning_mode(events)
    if mode == "greenfield":
        return "greenfield"
    if mode == "adopt_existing":
        return "adopted existing project"
    return "unknown"


def _lifecycle_phase(
    *,
    planning: PlanningReport,
    next_role: str | None,
    current_work: CurrentWorkReport,
    milestones: Iterable[Milestone],
    planning_complete: bool,
) -> str:
    if not planning.design_plan_present and next_role == "architect":
        return "awaiting design"
    if (
        planning.design_plan_present
        and not planning.project_plan_present
        and next_role == "planner"
    ):
        return "awaiting planning"
    if next_role in {"integrator", "architect"} and _has_pending_integration(milestones):
        return "integration"
    if current_work.tasks_active > 0 or next_role in {"developer", "reviewer"}:
        return "implementation"
    if (
        next_role is None
        and planning_complete
        and current_work.tasks_active == 0
        and current_work.findings_open == 0
        and current_work.findings_planned == 0
    ):
        return "complete"
    if next_role is None:
        return "blocked or inconsistent"
    return "awaiting planning" if next_role == "planner" else "implementation"


def _has_pending_integration(milestones: Iterable[Milestone]) -> bool:
    return any(
        milestone.status
        in {
            MilestoneStatus.TASKS_COMPLETE,
            MilestoneStatus.INTEGRATION_FAILED,
            MilestoneStatus.INTEGRATED,
        }
        for milestone in milestones
    )


def _current_work_report(
    tasks: Iterable[Task],
    milestones: Iterable[Milestone],
    findings: Iterable[Finding],
) -> CurrentWorkReport:
    task_list = list(tasks)
    milestone_list = list(milestones)
    finding_list = list(findings)
    return CurrentWorkReport(
        tasks_total=len(task_list),
        tasks_closed=sum(1 for task in task_list if task.status == TaskStatus.CLOSED),
        tasks_active=sum(1 for task in task_list if task.status != TaskStatus.CLOSED),
        milestones_total=len(milestone_list),
        findings_open=sum(1 for finding in finding_list if finding.status == FindingStatus.OPEN),
        findings_planned=sum(
            1 for finding in finding_list if finding.status == FindingStatus.PLANNED
        ),
        findings_resolved=sum(
            1 for finding in finding_list if finding.status == FindingStatus.RESOLVED
        ),
    )


def _non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _bool_text(value: bool) -> str:
    return "complete" if value else "incomplete"


def _present_text(value: bool) -> str:
    return "present" if value else "absent"


def _unknown_bool_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _unknown_int_text(value: int | None) -> str:
    return "unknown" if value is None else str(value)

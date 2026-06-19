from __future__ import annotations

import dataclasses
import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

from devlab._toml import format_toml_value
from devlab.task_tracker import FileTaskTracker, Task

MILESTONES_DIR = ".devlab/milestones"
MILESTONE_ID_RE = re.compile(r"(?<![A-Z0-9])M\d{1,5}(?!\d)")
_PROJECT_PLAN_HEADING_RE = re.compile(r"^##\s+(M\d{1,5})(?::\s*(.+?))?\s*$", re.MULTILINE)


class MilestoneStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    TASKS_COMPLETE = "tasks_complete"
    INTEGRATION_FAILED = "integration_failed"
    INTEGRATED = "integrated"
    ARCHITECTURE_REVIEWED = "architecture_reviewed"
    COMPLETE = "complete"


@dataclasses.dataclass(frozen=True)
class Milestone:
    id: str
    title: str
    status: MilestoneStatus
    integration_required: bool
    integrated: bool
    architecture_reviewed: bool
    planning_generation: int
    task_ids: tuple[str, ...]
    integration_handoff: str
    architecture_review_handoff: str
    findings: tuple[str, ...]
    path: Path
    metadata: dict[str, Any]


class FileMilestoneTracker:
    """File-backed milestone state tracker.

    Task files remain the source of truth for task status. Milestone files track
    workflow state around a milestone, such as integration and architecture
    review state.
    """

    def __init__(self, root: Path, milestones_dir: str = MILESTONES_DIR) -> None:
        self.root = root
        self.milestones_path = root / milestones_dir

    def list_milestones(self) -> list[Milestone]:
        return sorted(
            (self._read_milestone(path) for path in self.milestones_path.glob("M*.toml")),
            key=lambda milestone: _natural_sort_key(milestone.id),
        )

    def get(self, milestone_id: str) -> Milestone:
        path = self.milestones_path / f"{milestone_id}.toml"
        if not path.exists():
            raise KeyError(f"unknown milestone id: {milestone_id}")
        return self._read_milestone(path)

    def upsert_from_tasks(
        self,
        tasks: list[Task],
        *,
        project_plan_text: str = "",
    ) -> list[Milestone]:
        """Ensure milestone files exist for milestones referenced by tasks.

        Existing milestone workflow state is preserved. Missing milestone files
        are created from task metadata and project-plan headings.
        """
        self.milestones_path.mkdir(parents=True, exist_ok=True)
        titles = _milestone_titles_from_project_plan(project_plan_text)
        task_ids_by_milestone: dict[str, list[str]] = {}
        generation_by_milestone: dict[str, int] = {}
        for task in tasks:
            if task.milestone is None:
                continue
            task_ids_by_milestone.setdefault(task.milestone, []).append(task.id)
            generation_by_milestone.setdefault(task.milestone, task.planning_generation)

        milestones: list[Milestone] = []
        for milestone_id in sorted(task_ids_by_milestone, key=_natural_sort_key):
            path = self.milestones_path / f"{milestone_id}.toml"
            if path.exists():
                milestone = self._read_milestone(path)
                merged_task_ids = tuple(
                    sorted(
                        {*milestone.task_ids, *task_ids_by_milestone[milestone_id]},
                        key=_natural_sort_key,
                    )
                )
                if merged_task_ids != milestone.task_ids:
                    metadata = dict(milestone.metadata)
                    metadata["task_ids"] = list(merged_task_ids)
                    if milestone.integrated:
                        metadata["status"] = MilestoneStatus.ACTIVE.value
                        metadata["integrated"] = False
                        metadata["architecture_reviewed"] = False
                    path.write_text(_format_milestone_file(metadata))
                    milestone = self._read_milestone(path)
            else:
                metadata = _default_milestone_metadata(
                    milestone_id,
                    titles.get(milestone_id, milestone_id),
                    task_ids_by_milestone[milestone_id],
                    generation_by_milestone[milestone_id],
                )
                path.write_text(_format_milestone_file(metadata))
                milestone = self._read_milestone(path)
            milestones.append(milestone)
        return milestones

    def mark_tasks_complete(self, milestone_id: str) -> None:
        milestone = self.get(milestone_id)
        if milestone.integrated:
            return
        metadata = dict(milestone.metadata)
        metadata["status"] = MilestoneStatus.TASKS_COMPLETE.value
        milestone.path.write_text(_format_milestone_file(metadata))

    def mark_integrated(self, milestone_id: str, handoff_path: Path) -> None:
        milestone = self.get(milestone_id)
        metadata = dict(milestone.metadata)
        metadata["status"] = MilestoneStatus.INTEGRATED.value
        metadata["integrated"] = True
        metadata["integration_handoff"] = handoff_path.name
        milestone.path.write_text(_format_milestone_file(metadata))

    def mark_integration_failed(self, milestone_id: str, finding_id: str) -> None:
        milestone = self.get(milestone_id)
        findings = [*milestone.findings]
        if finding_id not in findings:
            findings.append(finding_id)
        metadata = dict(milestone.metadata)
        metadata["status"] = MilestoneStatus.INTEGRATION_FAILED.value
        metadata["integrated"] = False
        metadata["findings"] = findings
        milestone.path.write_text(_format_milestone_file(metadata))

    def mark_architecture_reviewed(self, milestone_id: str, handoff_path: Path) -> None:
        milestone = self.get(milestone_id)
        metadata = dict(milestone.metadata)
        metadata["status"] = MilestoneStatus.ARCHITECTURE_REVIEWED.value
        metadata["architecture_reviewed"] = True
        metadata["architecture_review_handoff"] = handoff_path.name
        milestone.path.write_text(_format_milestone_file(metadata))

    def _read_milestone(self, path: Path) -> Milestone:
        metadata = tomllib.loads(path.read_text())
        milestone_id = str(metadata.get("id") or path.stem)
        title = str(metadata.get("title") or milestone_id)
        status = _parse_status(metadata.get("status"))
        task_ids = _string_tuple(metadata.get("task_ids", []), "task_ids")
        findings = _string_tuple(metadata.get("findings", []), "findings")
        normalized = dict(metadata)
        normalized["id"] = milestone_id
        normalized["title"] = title
        normalized["status"] = status.value
        normalized["integration_required"] = bool(metadata.get("integration_required", True))
        normalized["integrated"] = bool(metadata.get("integrated", False))
        normalized["architecture_reviewed"] = bool(metadata.get("architecture_reviewed", False))
        normalized["planning_generation"] = _parse_planning_generation(
            metadata.get("planning_generation")
        )
        normalized["task_ids"] = list(task_ids)
        normalized["integration_handoff"] = str(metadata.get("integration_handoff", ""))
        normalized["architecture_review_handoff"] = str(
            metadata.get("architecture_review_handoff", "")
        )
        normalized["findings"] = list(findings)
        return Milestone(
            id=milestone_id,
            title=title,
            status=status,
            integration_required=normalized["integration_required"],
            integrated=normalized["integrated"],
            architecture_reviewed=normalized["architecture_reviewed"],
            planning_generation=normalized["planning_generation"],
            task_ids=task_ids,
            integration_handoff=normalized["integration_handoff"],
            architecture_review_handoff=normalized["architecture_review_handoff"],
            findings=findings,
            path=path,
            metadata=normalized,
        )


def sync_milestones_from_tasks(
    root: Path,
    *,
    project_plan_text: str = "",
) -> list[Milestone]:
    return FileMilestoneTracker(root).upsert_from_tasks(
        FileTaskTracker(root).list_tasks(),
        project_plan_text=project_plan_text,
    )


def _default_milestone_metadata(
    milestone_id: str, title: str, task_ids: list[str], planning_generation: int
) -> dict[str, Any]:
    return {
        "version": 1,
        "id": milestone_id,
        "title": title,
        "status": MilestoneStatus.PLANNED.value,
        "integration_required": True,
        "integrated": False,
        "architecture_reviewed": False,
        "planning_generation": planning_generation,
        "task_ids": sorted(task_ids, key=_natural_sort_key),
        "integration_handoff": "",
        "architecture_review_handoff": "",
        "findings": [],
    }


def _format_milestone_file(metadata: dict[str, Any]) -> str:
    keys = (
        "version",
        "id",
        "title",
        "status",
        "integration_required",
        "integrated",
        "architecture_reviewed",
        "planning_generation",
        "task_ids",
        "integration_handoff",
        "architecture_review_handoff",
        "findings",
    )
    lines: list[str] = []
    for key in keys:
        if key in metadata:
            lines.append(f"{key} = {format_toml_value(metadata[key])}")
    for key in sorted(k for k in metadata if k not in keys):
        lines.append(f"{key} = {format_toml_value(metadata[key])}")
    return "\n".join(lines) + "\n"


def _parse_status(value: object) -> MilestoneStatus:
    if value is None:
        return MilestoneStatus.PLANNED
    try:
        return MilestoneStatus(str(value))
    except ValueError as exc:
        allowed = ", ".join(status.value for status in MilestoneStatus)
        raise ValueError(
            f"invalid milestone status {value!r}; expected one of: {allowed}"
        ) from exc


def _parse_planning_generation(value: object) -> int:
    if value is None:
        return 1
    if not isinstance(value, int) or value < 1:
        raise ValueError("milestone field 'planning_generation' must be a positive integer")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"milestone field {field_name!r} must be a list")
    return tuple(str(item) for item in value)


def _milestone_titles_from_project_plan(text: str) -> dict[str, str]:
    return {
        match.group(1): (match.group(2) or match.group(1)).strip()
        for match in _PROJECT_PLAN_HEADING_RE.finditer(text)
    }



def _natural_sort_key(value: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Za-z]+)(\d+)$", value)
    if not match:
        return (value, -1, value)
    return (match.group(1), int(match.group(2)), value)

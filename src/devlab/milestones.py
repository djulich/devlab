from __future__ import annotations

import dataclasses
import re
import tomllib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from devlab._files import atomic_write_text
from devlab._toml import format_toml_value
from devlab.task_tracker import Task

MILESTONES_DIR = ".devlab/milestones"
MILESTONE_VERIFICATION_DIR = ".devlab/verification/milestones"
MILESTONE_VERSION = 1
MILESTONE_VERIFICATION_SCHEMA_VERSION = 1
MILESTONE_ID_RE = re.compile(r"(?<![A-Z0-9])M\d{1,5}(?!\d)")
_PROJECT_PLAN_HEADING_RE = re.compile(r"^##\s+(M\d{1,5})(?::\s*(.+?))?\s*$", re.MULTILINE)
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
_UNSAFE_TOML_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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
    task_ids: tuple[str, ...]
    integration_handoff: str
    architecture_review_handoff: str
    findings: tuple[str, ...]
    path: Path
    metadata: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class MilestoneVerificationCommand:
    command: str
    task_ids: tuple[str, ...]
    sources: tuple[str, ...]
    outcome: str = "not_run"
    exit_code: int | None = None
    duration_seconds: float = 0.0
    output_summary: str = ""
    log_path: str = ""


@dataclasses.dataclass(frozen=True)
class MilestoneVerification:
    milestone_id: str
    state: str
    repository_revision: str
    closed_task_ids: tuple[str, ...]
    commands: tuple[MilestoneVerificationCommand, ...]
    integration_session: str = ""
    integration_handoff: str = ""
    finding_ids: tuple[str, ...] = ()
    finding_statuses: tuple[str, ...] = ()
    semantic_integration_concerns: tuple[str, ...] = ()
    untested_claims: tuple[str, ...] = ()
    architecture_session: str = ""
    architecture_handoff: str = ""
    design_drift: tuple[str, ...] = ()
    updated_at: str = ""
    schema_version: int = 1


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

    def read_verification(self, milestone_id: str) -> MilestoneVerification | None:
        path = self.root / MILESTONE_VERIFICATION_DIR / f"{milestone_id}.toml"
        if not path.exists():
            return None
        return _read_verification(path)

    def write_verification(self, verification: MilestoneVerification) -> None:
        path = self.root / MILESTONE_VERIFICATION_DIR / f"{verification.milestone_id}.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        value = dataclasses.replace(verification, updated_at=datetime.now(UTC).isoformat())
        atomic_write_text(path, _format_verification(value))

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
        for task in tasks:
            if task.milestone is None:
                continue
            task_ids_by_milestone.setdefault(task.milestone, []).append(task.id)

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
                    atomic_write_text(path, _format_milestone_file(metadata))
                    milestone = self._read_milestone(path)
            else:
                metadata = _default_milestone_metadata(
                    milestone_id,
                    titles.get(milestone_id, milestone_id),
                    task_ids_by_milestone[milestone_id],
                )
                atomic_write_text(path, _format_milestone_file(metadata))
                milestone = self._read_milestone(path)
            milestones.append(milestone)
        return milestones

    def mark_tasks_complete(self, milestone_id: str) -> None:
        milestone = self.get(milestone_id)
        if milestone.integrated:
            return
        metadata = dict(milestone.metadata)
        metadata["status"] = MilestoneStatus.TASKS_COMPLETE.value
        atomic_write_text(milestone.path, _format_milestone_file(metadata))

    def mark_integrated(self, milestone_id: str, handoff_path: Path) -> None:
        milestone = self.get(milestone_id)
        metadata = dict(milestone.metadata)
        metadata["status"] = MilestoneStatus.INTEGRATED.value
        metadata["integrated"] = True
        metadata["integration_handoff"] = handoff_path.name
        atomic_write_text(milestone.path, _format_milestone_file(metadata))

    def mark_integration_failed(self, milestone_id: str, finding_id: str) -> None:
        milestone = self.get(milestone_id)
        findings = [*milestone.findings]
        if finding_id not in findings:
            findings.append(finding_id)
        metadata = dict(milestone.metadata)
        metadata["status"] = MilestoneStatus.INTEGRATION_FAILED.value
        metadata["integrated"] = False
        metadata["findings"] = findings
        atomic_write_text(milestone.path, _format_milestone_file(metadata))

    def mark_architecture_reviewed(self, milestone_id: str, handoff_path: Path) -> None:
        milestone = self.get(milestone_id)
        metadata = dict(milestone.metadata)
        metadata["status"] = MilestoneStatus.ARCHITECTURE_REVIEWED.value
        metadata["architecture_reviewed"] = True
        metadata["architecture_review_handoff"] = handoff_path.name
        atomic_write_text(milestone.path, _format_milestone_file(metadata))

    def _read_milestone(self, path: Path) -> Milestone:
        metadata = tomllib.loads(path.read_text())
        version = metadata.get("version", MILESTONE_VERSION)
        if version != MILESTONE_VERSION:
            raise ValueError(
                f"{path} has unsupported milestone version {version!r}; supported version "
                f"is {MILESTONE_VERSION}. Use a compatible DevLab release to migrate the "
                "workspace, or restore a supported milestone before retrying"
            )
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
        normalized.pop("planning_generation", None)
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
            task_ids=task_ids,
            integration_handoff=normalized["integration_handoff"],
            architecture_review_handoff=normalized["architecture_review_handoff"],
            findings=findings,
            path=path,
            metadata=normalized,
        )


def _default_milestone_metadata(
    milestone_id: str, title: str, task_ids: list[str]
) -> dict[str, Any]:
    return {
        "version": MILESTONE_VERSION,
        "id": milestone_id,
        "title": title,
        "status": MilestoneStatus.PLANNED.value,
        "integration_required": True,
        "integrated": False,
        "architecture_reviewed": False,
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


def _format_verification(value: MilestoneVerification) -> str:
    scalar_fields: tuple[tuple[str, object], ...] = (
        ("schema_version", value.schema_version),
        ("milestone_id", value.milestone_id),
        ("state", value.state),
        ("repository_revision", value.repository_revision),
        ("updated_at", value.updated_at),
        ("closed_task_ids", value.closed_task_ids),
        ("integration_session", value.integration_session),
        ("integration_handoff", value.integration_handoff),
        ("finding_ids", value.finding_ids),
        ("finding_statuses", value.finding_statuses),
        ("semantic_integration_concerns", value.semantic_integration_concerns),
        ("untested_claims", value.untested_claims),
        ("architecture_session", value.architecture_session),
        ("architecture_handoff", value.architecture_handoff),
        ("design_drift", value.design_drift),
    )
    lines = [f"{key} = {format_toml_value(item)}" for key, item in scalar_fields]
    for command in value.commands:
        lines.extend(
            (
                "",
                "[[commands]]",
                f"command = {format_toml_value(command.command)}",
                f"task_ids = {format_toml_value(command.task_ids)}",
                f"sources = {format_toml_value(command.sources)}",
                f"outcome = {format_toml_value(command.outcome)}",
            )
        )
        if command.exit_code is not None:
            lines.append(f"exit_code = {command.exit_code}")
        lines.extend(
            (
                f"duration_seconds = {command.duration_seconds}",
                "output_summary = "
                f"{format_toml_value(_sanitize_output_summary(command.output_summary))}",
                f"log_path = {format_toml_value(command.log_path)}",
            )
        )
    return "\n".join(lines) + "\n"


def _sanitize_output_summary(value: str) -> str:
    """Remove terminal escapes and TOML-invalid controls from command evidence."""
    without_ansi = _ANSI_ESCAPE_RE.sub("", value)
    return _UNSAFE_TOML_CONTROL_RE.sub("", without_ansi)


def _read_verification(path: Path) -> MilestoneVerification:
    data = tomllib.loads(path.read_text())
    version = data.get("schema_version")
    if version != MILESTONE_VERIFICATION_SCHEMA_VERSION:
        raise ValueError(
            f"{path} has unsupported milestone verification schema_version {version!r}; "
            f"supported version is {MILESTONE_VERIFICATION_SCHEMA_VERSION}. Use a compatible "
            "DevLab release to migrate the workspace, or restore supported verification "
            "evidence before retrying"
        )
    milestone_id = str(data.get("milestone_id") or "")
    if not milestone_id:
        raise ValueError(f"milestone verification has no milestone_id: {path}")
    raw_commands = data.get("commands", [])
    if not isinstance(raw_commands, list):
        raise ValueError("milestone verification commands must be an array of tables")
    commands: list[MilestoneVerificationCommand] = []
    for raw in raw_commands:
        if not isinstance(raw, dict):
            raise ValueError("milestone verification command must be a table")
        exit_code = raw.get("exit_code")
        if exit_code is not None and not isinstance(exit_code, int):
            raise ValueError("milestone verification command exit_code must be an integer")
        commands.append(
            MilestoneVerificationCommand(
                command=str(raw.get("command") or ""),
                task_ids=_string_tuple(raw.get("task_ids", []), "commands.task_ids"),
                sources=_string_tuple(raw.get("sources", []), "commands.sources"),
                outcome=str(raw.get("outcome") or "not_run"),
                exit_code=exit_code,
                duration_seconds=float(raw.get("duration_seconds") or 0.0),
                output_summary=str(raw.get("output_summary") or ""),
                log_path=str(raw.get("log_path") or ""),
            )
        )
    return MilestoneVerification(
        schema_version=MILESTONE_VERIFICATION_SCHEMA_VERSION,
        milestone_id=milestone_id,
        state=str(data.get("state") or ""),
        repository_revision=str(data.get("repository_revision") or ""),
        updated_at=str(data.get("updated_at") or ""),
        closed_task_ids=_string_tuple(data.get("closed_task_ids", []), "closed_task_ids"),
        commands=tuple(commands),
        integration_session=str(data.get("integration_session") or ""),
        integration_handoff=str(data.get("integration_handoff") or ""),
        finding_ids=_string_tuple(data.get("finding_ids", []), "finding_ids"),
        finding_statuses=_string_tuple(data.get("finding_statuses", []), "finding_statuses"),
        semantic_integration_concerns=_string_tuple(
            data.get("semantic_integration_concerns", []),
            "semantic_integration_concerns",
        ),
        untested_claims=_string_tuple(data.get("untested_claims", []), "untested_claims"),
        architecture_session=str(data.get("architecture_session") or ""),
        architecture_handoff=str(data.get("architecture_handoff") or ""),
        design_drift=_string_tuple(data.get("design_drift", []), "design_drift"),
    )


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

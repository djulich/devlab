from __future__ import annotations

import dataclasses
import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

TASKS_DIR = ".devlab/tasks"
TASK_ID_RE = re.compile(r"(?<![A-Z0-9])T\d{3,5}(?!\d)")
_FRONT_MATTER_RE = re.compile(r"\A\+\+\+\n([\s\S]*?)\n\+\+\+\n?", re.MULTILINE)


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    CLOSED = "closed"


ACTIVE_STATUSES = {
    TaskStatus.OPEN,
    TaskStatus.IN_REVIEW,
    TaskStatus.CHANGES_REQUESTED,
}
DEVELOPABLE_STATUSES = {TaskStatus.OPEN, TaskStatus.CHANGES_REQUESTED}


@dataclasses.dataclass(frozen=True)
class Task:
    id: str
    title: str
    status: TaskStatus
    path: Path
    milestone: str | None
    profile: str | None
    depends_on: tuple[str, ...]
    addresses_findings: tuple[str, ...]
    # None means validation metadata is omitted; () means explicit validation = [].
    validation: tuple[str, ...] | None
    body: str
    metadata: dict[str, Any]

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


class FileTaskTracker:
    """File-backed task tracker using one Markdown file per task.

    Task state is stored in TOML front matter in files under ``.devlab/tasks``.
    The tracker is the abstraction boundary between orchestration logic and the
    current file-based backend.
    """

    def __init__(self, root: Path, tasks_dir: str = TASKS_DIR) -> None:
        self.root = root
        self.tasks_path = root / tasks_dir

    def list_tasks(self) -> list[Task]:
        return sorted(
            (self._read_task(path) for path in self.tasks_path.glob("T*.md")),
            key=lambda task: (_task_sort_key(task.id), task.path.name),
        )

    def get(self, task_id: str) -> Task:
        for task in self.list_tasks():
            if task.id == task_id:
                return task
        raise KeyError(f"unknown task id: {task_id}")

    def active_tasks(self) -> list[Task]:
        return [task for task in self.list_tasks() if task.is_active]

    def open_task_ids(self) -> set[str]:
        return {task.id for task in self.active_tasks()}

    def eligible_tasks(self) -> list[Task]:
        closed_ids = {task.id for task in self.list_tasks() if task.status == TaskStatus.CLOSED}
        return [
            task
            for task in self.list_tasks()
            if task.status in DEVELOPABLE_STATUSES and set(task.depends_on).issubset(closed_ids)
        ]

    def blocked_tasks(self) -> list[Task]:
        closed_ids = {task.id for task in self.list_tasks() if task.status == TaskStatus.CLOSED}
        return [
            task
            for task in self.list_tasks()
            if task.status in DEVELOPABLE_STATUSES
            and not set(task.depends_on).issubset(closed_ids)
        ]

    def review_tasks(self) -> list[Task]:
        return [task for task in self.list_tasks() if task.status == TaskStatus.IN_REVIEW]

    def select_next_development_task(self) -> Task | None:
        tasks = self.eligible_tasks()
        return tasks[0] if tasks else None

    def select_next_review_task(self) -> Task | None:
        tasks = self.review_tasks()
        return tasks[0] if tasks else None

    def has_active_tasks(self) -> bool:
        return bool(self.active_tasks())

    def has_tasks(self) -> bool:
        return bool(self.list_tasks())

    def all_tasks_closed(self) -> bool:
        tasks = self.list_tasks()
        return bool(tasks) and all(task.status == TaskStatus.CLOSED for task in tasks)

    def milestones(self) -> list[str]:
        return sorted(
            {task.milestone for task in self.list_tasks() if task.milestone is not None},
            key=_natural_sort_key,
        )

    def tasks_for_milestone(self, milestone: str) -> list[Task]:
        return [task for task in self.list_tasks() if task.milestone == milestone]

    def milestone_complete(self, milestone: str) -> bool:
        tasks = self.tasks_for_milestone(milestone)
        return bool(tasks) and all(task.status == TaskStatus.CLOSED for task in tasks)

    def completed_milestones(self) -> list[str]:
        return [milestone for milestone in self.milestones() if self.milestone_complete(milestone)]

    def mark_in_review(self, task_id: str) -> None:
        self.set_status(task_id, TaskStatus.IN_REVIEW)

    def mark_changes_requested(self, task_id: str) -> None:
        self.set_status(task_id, TaskStatus.CHANGES_REQUESTED)

    def close(self, task_id: str) -> None:
        self.set_status(task_id, TaskStatus.CLOSED)

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        task = self.get(task_id)
        metadata = dict(task.metadata)
        metadata["id"] = task.id
        metadata["title"] = task.title
        metadata["status"] = status.value
        if task.milestone is not None:
            metadata["milestone"] = task.milestone
        if task.profile is not None:
            metadata["profile"] = task.profile
        else:
            metadata.pop("profile", None)
        metadata["depends_on"] = list(task.depends_on)
        metadata["addresses_findings"] = list(task.addresses_findings)
        if task.validation is None:
            metadata.pop("validation", None)
        else:
            metadata["validation"] = list(task.validation)
        task.path.write_text(_format_task_file(metadata, task.body))

    def _read_task(self, path: Path) -> Task:
        text = path.read_text()
        metadata, body = _split_front_matter(text)
        task_id = str(metadata.get("id") or _task_id_from_path(path) or "")
        if not task_id:
            raise ValueError(f"task file has no task id: {path}")
        title = str(metadata.get("title") or _title_from_body(body, task_id) or task_id)
        status = _parse_status(metadata.get("status"))
        milestone = metadata.get("milestone")
        profile = metadata.get("profile")
        depends_on = _parse_depends_on(metadata.get("depends_on"), body)
        addresses_findings = _parse_string_list(
            metadata.get("addresses_findings", []), "addresses_findings"
        )
        validation = (
            _parse_validation(metadata.get("validation")) if "validation" in metadata else None
        )
        normalized_metadata = dict(metadata)
        normalized_metadata["id"] = task_id
        normalized_metadata["title"] = title
        normalized_metadata["status"] = status.value
        normalized_metadata["addresses_findings"] = list(addresses_findings)
        if validation is not None:
            normalized_metadata["validation"] = list(validation)
        return Task(
            id=task_id,
            title=title,
            status=status,
            path=path,
            milestone=str(milestone) if milestone is not None else None,
            profile=str(profile) if profile is not None else None,
            depends_on=tuple(depends_on),
            addresses_findings=tuple(addresses_findings),
            validation=tuple(validation) if validation is not None else None,
            body=body,
            metadata=normalized_metadata,
        )


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    metadata = tomllib.loads(match.group(1))
    return metadata, text[match.end() :]


def _format_task_file(metadata: dict[str, Any], body: str) -> str:
    lines = ["+++"]
    for key in (
        "id",
        "title",
        "status",
        "milestone",
        "profile",
        "depends_on",
        "addresses_findings",
        "validation",
    ):
        if key not in metadata:
            continue
        value = metadata[key]
        if value is None:
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    known_keys = {
        "id",
        "title",
        "status",
        "milestone",
        "profile",
        "depends_on",
        "addresses_findings",
        "validation",
    }
    for key in sorted(k for k in metadata if k not in known_keys):
        lines.append(f"{key} = {_toml_value(metadata[key])}")
    lines.append("+++")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, TaskStatus):
        return _toml_value(value.value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return _toml_value(str(value))


def _parse_status(value: Any) -> TaskStatus:
    if value is None:
        return TaskStatus.OPEN
    try:
        return TaskStatus(str(value))
    except ValueError as exc:
        allowed = ", ".join(status.value for status in TaskStatus)
        raise ValueError(f"invalid task status {value!r}; expected one of: {allowed}") from exc


def _parse_depends_on(value: Any, body: str) -> list[str]:
    if value is not None:
        if not isinstance(value, list):
            raise ValueError("task front matter field 'depends_on' must be a list")
        return [str(item) for item in value]
    match = re.search(r"^## Depends On[ \t]*$([\s\S]*?)(?=^##\s|\Z)", body, flags=re.MULTILINE)
    if not match:
        return []
    return TASK_ID_RE.findall(match.group(1))


def _parse_validation(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("task front matter field 'validation' must be a list")
    return [str(item) for item in value]


def _parse_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"task front matter field {field_name!r} must be a list")
    return [str(item) for item in value]


def _task_id_from_path(path: Path) -> str | None:
    match = TASK_ID_RE.search(path.name)
    return match.group(0) if match else None


def _title_from_body(body: str, task_id: str) -> str | None:
    match = re.search(rf"^#\s+{re.escape(task_id)}:\s*(.+)$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _task_sort_key(task_id: str) -> int:
    match = re.search(r"\d+", task_id)
    return int(match.group(0)) if match else 0


def _natural_sort_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]

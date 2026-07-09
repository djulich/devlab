from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path
from typing import Any, cast

from devlab._toml import format_toml_value

WORKFLOW_STATE = ".devlab/workflow.toml"
WORKFLOW_STATE_VERSION = 1


@dataclasses.dataclass(frozen=True)
class PlanningState:
    complete: bool


@dataclasses.dataclass(frozen=True)
class SpecsState:
    last_planned_spec_commit: str | None = None


@dataclasses.dataclass(frozen=True)
class ResumeState:
    blocked_by: str
    command: str
    role: str
    task: str = ""
    milestone: str = ""


@dataclasses.dataclass(frozen=True)
class WorkflowState:
    version: int
    planning: PlanningState
    specs: SpecsState = dataclasses.field(default_factory=SpecsState)
    resume: ResumeState | None = None


def default_workflow_state(*, planning_complete: bool = True) -> WorkflowState:
    return WorkflowState(
        version=WORKFLOW_STATE_VERSION,
        planning=PlanningState(complete=planning_complete),
    )


def initial_workflow_state_text() -> str:
    return "version = 1\n\n[planning]\ncomplete = false\n"


def load_workflow_state(root: Path) -> WorkflowState:
    path = root / WORKFLOW_STATE
    if not path.exists():
        return default_workflow_state(planning_complete=True)
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return parse_workflow_state(data)


def write_workflow_state(root: Path, state: WorkflowState) -> None:
    path = root / WORKFLOW_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_workflow_state(state))


def set_planning_complete(root: Path, complete: bool) -> WorkflowState:
    return update_workflow_state(root, planning_complete=complete)


def update_workflow_state(
    root: Path,
    *,
    planning_complete: bool | None = None,
    last_planned_spec_commit: str | None = None,
) -> WorkflowState:
    path = root / WORKFLOW_STATE
    current = load_workflow_state(root)
    complete = current.planning.complete if planning_complete is None else planning_complete
    updated = WorkflowState(
        version=current.version,
        planning=PlanningState(complete=complete),
        specs=SpecsState(
            last_planned_spec_commit=(
                current.specs.last_planned_spec_commit
                if last_planned_spec_commit is None
                else last_planned_spec_commit
            )
        ),
        resume=current.resume,
    )
    if path.exists():
        text = path.read_text()
        if planning_complete is not None:
            text = _replace_table_key(text, "planning", "complete", complete)
        if last_planned_spec_commit is not None:
            text = _replace_table_key(
                text,
                "specs",
                "last_planned_spec_commit",
                last_planned_spec_commit,
            )
        path.write_text(text)
    else:
        write_workflow_state(root, updated)
    return updated


def set_resume_state(root: Path, resume: ResumeState) -> WorkflowState:
    current = load_workflow_state(root)
    updated = WorkflowState(
        version=current.version,
        planning=current.planning,
        specs=current.specs,
        resume=resume,
    )
    path = root / WORKFLOW_STATE
    if path.exists():
        text = _remove_table(path.read_text(), "resume")
        suffix = "" if text.endswith("\n") or not text else "\n"
        text = text + suffix + _format_resume_table(resume)
        path.write_text(text)
    else:
        write_workflow_state(root, updated)
    return updated


def clear_resume_state(root: Path) -> WorkflowState:
    current = load_workflow_state(root)
    updated = WorkflowState(
        version=current.version,
        planning=current.planning,
        specs=current.specs,
        resume=None,
    )
    path = root / WORKFLOW_STATE
    if path.exists():
        path.write_text(_remove_table(path.read_text(), "resume"))
    else:
        write_workflow_state(root, updated)
    return updated


def format_workflow_state(state: WorkflowState) -> str:
    return (
        f"version = {format_toml_value(state.version)}\n\n"
        "[planning]\n"
        f"complete = {format_toml_value(state.planning.complete)}\n"
        + (
            "\n[specs]\n"
            f"last_planned_spec_commit = "
            f"{format_toml_value(state.specs.last_planned_spec_commit)}\n"
            if state.specs.last_planned_spec_commit is not None
            else ""
        )
        + (
            "\n" + _format_resume_table(state.resume)
            if state.resume is not None
            else ""
        )
    )


def _replace_planning_complete(text: str, complete: bool) -> str:
    return _replace_table_key(text, "planning", "complete", complete)


def _replace_table_key(text: str, table: str, key: str, value: object) -> str:
    replacement = f"{key} = {format_toml_value(value)}"
    lines = text.splitlines(keepends=True)
    in_table = False
    table_header_index: int | None = None
    insert_before_index: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_table and insert_before_index is None:
                insert_before_index = index
            in_table = stripped == f"[{table}]"
            if in_table:
                table_header_index = index
            continue
        if in_table and stripped.split("=", 1)[0].strip() == key:
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = replacement + newline
            return "".join(lines)
    if table_header_index is None:
        suffix = "" if text.endswith("\n") or not text else "\n"
        return text + suffix + f"\n[{table}]\n" + replacement + "\n"
    insert_at = insert_before_index if insert_before_index is not None else table_header_index + 1
    lines.insert(insert_at, replacement + "\n")
    return "".join(lines)


def _remove_table(text: str, table: str) -> str:
    lines = text.splitlines(keepends=True)
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == f"[{table}]":
            start = index
            continue
        if (
            start is not None
            and index > start
            and stripped.startswith("[")
            and stripped.endswith("]")
        ):
            end = index
            break
    if start is None:
        return text
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    while end < len(lines) and not lines[end].strip():
        end += 1
    return "".join(lines[:start] + lines[end:])


def _format_resume_table(resume: ResumeState) -> str:
    return (
        "[resume]\n"
        f"blocked_by = {format_toml_value(resume.blocked_by)}\n"
        f"command = {format_toml_value(resume.command)}\n"
        f"role = {format_toml_value(resume.role)}\n"
        f"task = {format_toml_value(resume.task)}\n"
        f"milestone = {format_toml_value(resume.milestone)}\n"
    )


def parse_workflow_state(data: object) -> WorkflowState:
    if not isinstance(data, dict):
        raise ValueError(f"{WORKFLOW_STATE} must be a TOML table")
    config = cast("dict[str, Any]", data)
    version = config.get("version")
    if version != WORKFLOW_STATE_VERSION:
        raise ValueError(f"{WORKFLOW_STATE}.version must be {WORKFLOW_STATE_VERSION}")
    planning = config.get("planning")
    if not isinstance(planning, dict):
        raise ValueError(f"{WORKFLOW_STATE}.planning must be a TOML table")
    complete = planning.get("complete")
    if not isinstance(complete, bool):
        raise ValueError(f"{WORKFLOW_STATE}.planning.complete must be a boolean")
    specs = config.get("specs", {})
    if specs is None:
        specs = {}
    if not isinstance(specs, dict):
        raise ValueError(f"{WORKFLOW_STATE}.specs must be a TOML table")
    last_planned_spec_commit = specs.get("last_planned_spec_commit")
    if last_planned_spec_commit is not None and not isinstance(
        last_planned_spec_commit, str
    ):
        raise ValueError(
            f"{WORKFLOW_STATE}.specs.last_planned_spec_commit must be a string"
        )
    resume = config.get("resume")
    parsed_resume = _parse_resume_state(resume) if resume is not None else None
    return WorkflowState(
        version=version,
        planning=PlanningState(complete=complete),
        specs=SpecsState(last_planned_spec_commit=last_planned_spec_commit),
        resume=parsed_resume,
    )


def _parse_resume_state(value: object) -> ResumeState:
    if not isinstance(value, dict):
        raise ValueError(f"{WORKFLOW_STATE}.resume must be a TOML table")
    resume = cast("dict[str, Any]", value)
    blocked_by = _resume_string(resume, "blocked_by")
    command = _resume_string(resume, "command")
    role = _resume_string(resume, "role")
    task = _resume_optional_string(resume, "task")
    milestone = _resume_optional_string(resume, "milestone")
    if command not in {"plan", "implement"}:
        raise ValueError(f"{WORKFLOW_STATE}.resume.command must be plan or implement")
    return ResumeState(
        blocked_by=blocked_by,
        command=command,
        role=role,
        task=task,
        milestone=milestone,
    )


def _resume_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{WORKFLOW_STATE}.resume.{key} must be a non-empty string")
    return value


def _resume_optional_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{WORKFLOW_STATE}.resume.{key} must be a string")
    return value

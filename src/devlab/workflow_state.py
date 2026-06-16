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
class WorkflowState:
    version: int
    planning: PlanningState


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
    path = root / WORKFLOW_STATE
    current = load_workflow_state(root)
    updated = WorkflowState(
        version=current.version,
        planning=PlanningState(complete=complete),
    )
    if path.exists():
        path.write_text(_replace_planning_complete(path.read_text(), complete))
    else:
        write_workflow_state(root, updated)
    return updated


def format_workflow_state(state: WorkflowState) -> str:
    return (
        f"version = {format_toml_value(state.version)}\n\n"
        "[planning]\n"
        f"complete = {format_toml_value(state.planning.complete)}\n"
    )


def _replace_planning_complete(text: str, complete: bool) -> str:
    replacement = f"complete = {format_toml_value(complete)}"
    lines = text.splitlines(keepends=True)
    in_planning = False
    planning_header_index: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_planning = stripped == "[planning]"
            if in_planning:
                planning_header_index = index
            continue
        if in_planning and stripped.split("=", 1)[0].strip() == "complete":
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = replacement + newline
            return "".join(lines)
    if planning_header_index is None:
        suffix = "" if text.endswith("\n") or not text else "\n"
        return text + suffix + "\n[planning]\n" + replacement + "\n"
    insert_at = planning_header_index + 1
    lines.insert(insert_at, replacement + "\n")
    return "".join(lines)


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
    return WorkflowState(
        version=version,
        planning=PlanningState(complete=complete),
    )

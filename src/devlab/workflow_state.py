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
    generation: int = 1


@dataclasses.dataclass(frozen=True)
class SpecsState:
    last_planned_spec_commit: str | None = None


@dataclasses.dataclass(frozen=True)
class WorkflowState:
    version: int
    planning: PlanningState
    specs: SpecsState = dataclasses.field(default_factory=SpecsState)


def default_workflow_state(*, planning_complete: bool = True) -> WorkflowState:
    return WorkflowState(
        version=WORKFLOW_STATE_VERSION,
        planning=PlanningState(complete=planning_complete, generation=1),
    )


def initial_workflow_state_text() -> str:
    return "version = 1\n\n[planning]\ncomplete = false\ngeneration = 1\n"


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
    planning_generation: int | None = None,
    last_planned_spec_commit: str | None = None,
) -> WorkflowState:
    path = root / WORKFLOW_STATE
    current = load_workflow_state(root)
    complete = current.planning.complete if planning_complete is None else planning_complete
    generation = (
        current.planning.generation
        if planning_generation is None
        else planning_generation
    )
    updated = WorkflowState(
        version=current.version,
        planning=PlanningState(complete=complete, generation=generation),
        specs=SpecsState(
            last_planned_spec_commit=(
                current.specs.last_planned_spec_commit
                if last_planned_spec_commit is None
                else last_planned_spec_commit
            )
        ),
    )
    if path.exists():
        text = path.read_text()
        if planning_complete is not None:
            text = _replace_table_key(text, "planning", "complete", complete)
        if planning_generation is not None:
            text = _replace_table_key(text, "planning", "generation", generation)
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


def format_workflow_state(state: WorkflowState) -> str:
    return (
        f"version = {format_toml_value(state.version)}\n\n"
        "[planning]\n"
        f"complete = {format_toml_value(state.planning.complete)}\n"
        f"generation = {format_toml_value(state.planning.generation)}\n"
        + (
            "\n[specs]\n"
            f"last_planned_spec_commit = "
            f"{format_toml_value(state.specs.last_planned_spec_commit)}\n"
            if state.specs.last_planned_spec_commit is not None
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
    generation = planning.get("generation", 1)
    if not isinstance(generation, int) or generation < 1:
        raise ValueError(f"{WORKFLOW_STATE}.planning.generation must be a positive integer")
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
    return WorkflowState(
        version=version,
        planning=PlanningState(complete=complete, generation=generation),
        specs=SpecsState(last_planned_spec_commit=last_planned_spec_commit),
    )

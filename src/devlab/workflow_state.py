from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path
from typing import Any, cast

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

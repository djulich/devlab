from __future__ import annotations

import dataclasses
from pathlib import Path

from devlab.git import run_git
from devlab.workflow_state import WorkflowState

SPEC_PATHS = (".devlab/specs/system", ".devlab/specs/deployment")


@dataclasses.dataclass(frozen=True)
class SpecReconciliationStatus:
    baseline_exists: bool
    changed: bool
    dirty_spec_paths: tuple[str, ...]
    latest_spec_commit: str
    baseline_spec_commit: str


def inspect_spec_reconciliation(
    root: Path,
    workflow_state: WorkflowState,
) -> SpecReconciliationStatus:
    baseline = workflow_state.specs.last_planned_spec_commit or ""
    latest = latest_spec_commit(root)
    return SpecReconciliationStatus(
        baseline_exists=workflow_state.specs.last_planned_spec_commit is not None,
        changed=workflow_state.specs.last_planned_spec_commit is not None
        and latest != baseline,
        dirty_spec_paths=dirty_spec_paths(root),
        latest_spec_commit=latest,
        baseline_spec_commit=baseline,
    )


def dirty_spec_paths(root: Path) -> tuple[str, ...]:
    output = run_git(root, "status", "--porcelain", "--", *SPEC_PATHS).stdout
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        paths.append(path)
    return tuple(sorted(paths))


def latest_spec_commit(root: Path) -> str:
    return run_git(root, "log", "--format=%H", "-1", "--", *SPEC_PATHS).stdout.strip()

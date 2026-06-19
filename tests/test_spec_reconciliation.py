from __future__ import annotations

from pathlib import Path

from devlab.git import run_git
from devlab.spec_reconciliation import inspect_spec_reconciliation
from devlab.version_control import init_repository
from devlab.workflow_state import PlanningState, SpecsState, WorkflowState


def _init_repo(root: Path) -> None:
    init_repository(root)
    run_git(root, "config", "user.name", "Test User")
    run_git(root, "config", "user.email", "test@example.invalid")


def _commit_all(root: Path, message: str) -> str:
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", message)
    return run_git(root, "rev-parse", "HEAD").stdout.strip()


def _write_spec(root: Path, text: str) -> Path:
    path = root / ".devlab/specs/system/spec.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _state(baseline: str | None) -> WorkflowState:
    return WorkflowState(
        version=1,
        planning=PlanningState(complete=True),
        specs=SpecsState(last_planned_spec_commit=baseline),
    )


def test_inspect_detects_latest_spec_commit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_spec(tmp_path, "# Spec\n")
    baseline = _commit_all(tmp_path, "Add spec")

    status = inspect_spec_reconciliation(tmp_path, _state(baseline))

    assert status.baseline_exists is True
    assert status.latest_spec_commit == baseline
    assert status.baseline_spec_commit == baseline
    assert status.changed is False
    assert status.dirty_spec_paths == ()


def test_inspect_detects_dirty_unstaged_spec_paths(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    path = _write_spec(tmp_path, "# Spec\n")
    baseline = _commit_all(tmp_path, "Add spec")
    path.write_text("# Changed\n")

    status = inspect_spec_reconciliation(tmp_path, _state(baseline))

    assert status.dirty_spec_paths == (".devlab/specs/system/spec.md",)


def test_inspect_detects_dirty_staged_spec_paths(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_spec(tmp_path, "# Spec\n")
    baseline = _commit_all(tmp_path, "Add spec")
    _write_spec(tmp_path, "# Changed\n")
    run_git(tmp_path, "add", ".devlab/specs/system/spec.md")

    status = inspect_spec_reconciliation(tmp_path, _state(baseline))

    assert status.dirty_spec_paths == (".devlab/specs/system/spec.md",)


def test_later_spec_commit_is_changed_even_when_content_restored(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    _write_spec(tmp_path, "# Spec\n")
    baseline = _commit_all(tmp_path, "Add spec")
    _write_spec(tmp_path, "# Changed\n")
    _commit_all(tmp_path, "Change spec")
    _write_spec(tmp_path, "# Spec\n")
    latest = _commit_all(tmp_path, "Restore spec")

    status = inspect_spec_reconciliation(tmp_path, _state(baseline))

    assert status.latest_spec_commit == latest
    assert status.changed is True


def test_missing_baseline_is_first_planning_status(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_spec(tmp_path, "# Spec\n")
    latest = _commit_all(tmp_path, "Add spec")

    status = inspect_spec_reconciliation(tmp_path, _state(None))

    assert status.baseline_exists is False
    assert status.latest_spec_commit == latest
    assert status.baseline_spec_commit == ""
    assert status.changed is False

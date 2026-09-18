from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from devlab.cli import main
from devlab.doctor import check_workspace
from devlab.executable_config import (
    ExecutableConfigTrustError,
    authorize_executable_config,
    build_executable_config_snapshot,
)
from devlab.generations import load_generation_manifest
from devlab.git import run_git
from devlab.handoffs import HandoffError, load_session_result
from devlab.history import format_history
from devlab.spec_reconciliation import inspect_spec_reconciliation
from devlab.status import format_status
from devlab.version_control import commit_all, ensure_git_identity, init_repository
from devlab.workflow_diagnostics import build_workflow_diagnostics
from devlab.workflow_history import derive_session_records
from devlab.workflow_state import load_workflow_state, update_workflow_state
from devlab.workflow_state_report import build_workflow_state_report
from devlab.workspace import Workspace, WorkspaceCompatibilityError

FIXTURE = Path(__file__).parent / "fixtures/workspaces/v1-baseline"


@pytest.fixture
def v1_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    shutil.copytree(FIXTURE, root)
    return root


def _contents(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def test_v1_baseline_readers_remain_compatible_and_non_mutating(v1_workspace: Path) -> None:
    init_repository(v1_workspace)
    ensure_git_identity(v1_workspace, user_name="Fixture", user_email="fixture@example.invalid")
    commit_all(v1_workspace, "Commit compatibility fixture")
    before = _contents(v1_workspace)

    assert check_workspace(v1_workspace) == []
    assert "Next role: developer" in format_status(v1_workspace, verbose=True)
    assert build_workflow_state_report(v1_workspace).next_role == "developer"
    diagnostics = build_workflow_diagnostics(v1_workspace)
    assert diagnostics.sessions[0].task_id == "T0001"
    assert diagnostics.sessions[0].task_id_source == "structured_result"
    assert "fixture/fixture-model" in format_history(v1_workspace)

    sessions = derive_session_records(v1_workspace)
    assert [(item.role, item.task_id) for item in sessions] == [("developer", "T0001")]
    result = load_session_result(
        v1_workspace / ".devlab/history/20260901T101000_003_developer_result.toml"
    )
    assert (result.envelope.role, result.envelope.task) == ("developer", "T0001")
    generation = load_generation_manifest(
        v1_workspace / ".devlab/generations/0001/generation.toml"
    )
    assert (generation.version, generation.generation) == (1, 1)

    snapshot = Workspace(v1_workspace).snapshot
    assert snapshot.get_research("RS0001").result is not None
    assert snapshot.list_clarifications()[0].answer_text == "A: Plain text."
    assert _contents(v1_workspace) == before


def test_v1_baseline_continues_task_finding_and_milestone_through_workspace_handles(
    v1_workspace: Path,
) -> None:
    workspace = Workspace(v1_workspace)
    original_snapshot = workspace.snapshot
    task = workspace.tasks().get("T0001")

    task.mark_in_review()
    assert workspace.snapshot is not original_snapshot
    task.close()
    task.resolve_addressed_findings()
    milestone = workspace.milestones().get("M1")
    milestone.mark_ready_for_integration()
    milestone.mark_integrated(Path("integration-handoff.md"))
    milestone.mark_architecture_reviewed(Path("architecture-handoff.md"))

    assert task.read().status.value == "closed"
    assert workspace.findings().get("F0001").read().status.value == "resolved"
    assert milestone.read().architecture_reviewed is True
    assert 'fixture_extension = "preserved"' in task.path.read_text()
    assert 'fixture_extension = "preserved"' in milestone.read().path.read_text()
    assert (
        'fixture_extension = "preserved"'
        in workspace.findings().get("F0001").read().path.read_text()
    )


def test_v1_baseline_planning_state_reconciles_against_committed_specs(
    v1_workspace: Path,
) -> None:
    init_repository(v1_workspace)
    ensure_git_identity(v1_workspace, user_name="Fixture", user_email="fixture@example.invalid")
    commit_all(v1_workspace, "Commit compatibility fixture")
    baseline = run_git(v1_workspace, "rev-parse", "HEAD").stdout.strip()
    update_workflow_state(v1_workspace, last_planned_spec_commit=baseline)
    commit_all(v1_workspace, "Record spec baseline")

    state = Workspace(v1_workspace).snapshot.workflow_state()
    status = inspect_spec_reconciliation(v1_workspace, state)

    assert status.baseline_exists is True
    assert status.changed is False
    assert status.dirty_spec_paths == ()


@pytest.mark.parametrize(
    ("relative", "old", "new", "expected"),
    [
        (
            ".devlab/manifest.toml",
            "layout_version = 1",
            "layout_version = 2",
            "unsupported layout_version 2; supported version is 1",
        ),
        (
            ".devlab/workflow.toml",
            "version = 1",
            "version = 2",
            "unsupported version 2; supported version is 1",
        ),
    ],
)
def test_unknown_authoritative_workspace_versions_block_before_mutation_with_guidance(
    v1_workspace: Path,
    relative: str,
    old: str,
    new: str,
    expected: str,
) -> None:
    path = v1_workspace / relative
    path.write_text(path.read_text().replace(old, new, 1))
    before = _contents(v1_workspace)

    with pytest.raises(WorkspaceCompatibilityError, match=expected):
        Workspace(v1_workspace).tasks().get("T0001").mark_in_review()

    assert _contents(v1_workspace) == before
    problems = check_workspace(v1_workspace)
    assert len(problems) == 1
    assert expected in problems[0].message
    assert "migrate" in problems[0].message
    assert "restore" in problems[0].message
    assert _contents(v1_workspace) == before


def test_cli_reports_incompatible_workspace_without_traceback(
    v1_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = v1_workspace / ".devlab/manifest.toml"
    manifest.write_text(manifest.read_text().replace("layout_version = 1", "layout_version = 2"))
    monkeypatch.setattr("sys.argv", ["devlab", "status", "--root", str(v1_workspace)])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "unsupported layout_version 2" in error
    assert "migrate" in error
    assert "Traceback" not in error


def test_unknown_milestone_version_blocks_handle_mutation_and_preserves_files(
    v1_workspace: Path,
) -> None:
    path = v1_workspace / ".devlab/milestones/M1.toml"
    path.write_text(path.read_text().replace("version = 1", "version = 2", 1))
    before = _contents(v1_workspace)
    with pytest.raises(
        WorkspaceCompatibilityError, match=r"unsupported milestone version 2.*migrate"
    ):
        Workspace(v1_workspace).tasks().get("T0001").mark_in_review()

    assert _contents(v1_workspace) == before


def test_malformed_authoritative_state_and_stale_resume_pointer_are_read_only(
    v1_workspace: Path,
) -> None:
    workflow = v1_workspace / ".devlab/workflow.toml"
    workflow.write_text(
        "version = 1\n\n[planning]\ncomplete = true\n\n[resume]\n"
        'blocked_by = "CL9999"\nblocked_kind = "clarification"\n'
        'command = "implement"\nrole = "developer"\ntask = "T0001"\nmilestone = "M1"\n'
    )
    before = _contents(v1_workspace)

    problems = check_workspace(v1_workspace)

    assert any(
        "clarification resume references missing CL9999" in problem.message for problem in problems
    )
    assert _contents(v1_workspace) == before

    workflow.write_text('version = 1\n\n[planning]\ncomplete = "yes"\n')
    malformed = _contents(v1_workspace)
    with pytest.raises(WorkspaceCompatibilityError, match="must be a boolean"):
        Workspace(v1_workspace)
    assert _contents(v1_workspace) == malformed


def test_closed_session_protocol_rejects_unknown_schema(v1_workspace: Path) -> None:
    path = v1_workspace / ".devlab/history/20260901T101000_003_developer_result.toml"
    path.write_text(path.read_text().replace("schema_version = 1", "schema_version = 2", 1))
    before = _contents(v1_workspace)

    with pytest.raises(
        HandoffError,
        match=r"developer_result\.toml has unsupported session result schema_version 2; "
        r"supported version is 1.*restore",
    ):
        load_session_result(path)

    assert _contents(v1_workspace) == before


def test_unknown_planning_generation_blocks_workspace_mutation(v1_workspace: Path) -> None:
    path = v1_workspace / ".devlab/generations/0001/generation.toml"
    path.write_text(path.read_text().replace("version = 1", "version = 2", 1))
    before = _contents(v1_workspace)

    with pytest.raises(
        WorkspaceCompatibilityError,
        match=r"generation\.toml: generation manifest has unsupported version 2; "
        r"supported version is 1.*migrate.*restore",
    ):
        Workspace(v1_workspace).tasks().get("T0001").mark_in_review()

    assert _contents(v1_workspace) == before


def test_changed_executable_configuration_invalidates_expected_fingerprint(
    v1_workspace: Path,
) -> None:
    original = build_executable_config_snapshot(v1_workspace)
    config = v1_workspace / ".devlab/config/agents.toml"
    config.write_text(config.read_text().replace('model = "fixture-model"', 'model = "changed"'))
    changed = build_executable_config_snapshot(v1_workspace)
    before = _contents(v1_workspace)

    with pytest.raises(ExecutableConfigTrustError, match="digest mismatch"):
        authorize_executable_config(changed, expected_digest=original.digest)

    assert changed.digest != original.digest
    assert _contents(v1_workspace) == before


def test_v1_workflow_updates_preserve_unknown_extension_fields(v1_workspace: Path) -> None:
    update_workflow_state(v1_workspace, planning_complete=False)

    text = (v1_workspace / ".devlab/workflow.toml").read_text()
    assert 'fixture_extension = "preserve-on-write"' in text
    assert "fixture_extension = true" in text
    assert load_workflow_state(v1_workspace).planning.complete is False

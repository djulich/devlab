from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import devlab.recovery as recovery
from devlab.git import VersionControlError
from devlab.handoffs import SessionEnvelope, write_session_envelope
from devlab.recovery import (
    INTERRUPTION_COMMIT_MESSAGE,
    IncompleteDiscardError,
    discard_interrupted_session,
    format_operator_guidance,
    inspect_recovery,
)


def _git(root: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        check=check,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(root: Path) -> str:
    _git(root, "init")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / ".gitignore").write_text("ignored.txt\n")
    (root / "app.py").write_text("original = True\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Initial")
    return _git(root, "rev-parse", "HEAD")


def _dirty_session(root: Path) -> str:
    head = _repository(root)
    (root / "app.py").write_text("interrupted = True\n")
    _git(root, "add", "app.py")
    (root / "new.py").write_text("new = True\n")
    (root / "ignored.txt").write_text("keep me\n")
    write_session_envelope(
        root / ".devlab/session-artifacts/developer/session.toml",
        SessionEnvelope(1, "s1_developer", "developer", task="T0001"),
    )
    return head


def test_discard_restores_boundary_and_records_compact_interruption(tmp_path: Path) -> None:
    head = _dirty_session(tmp_path)
    inspection = inspect_recovery(tmp_path)

    assert inspection.proposal is not None
    assert inspection.proposal.head == head
    assert inspection.proposal.session.session_id == "s1_developer"
    commit = discard_interrupted_session(tmp_path, inspection.proposal)

    assert commit == _git(tmp_path, "rev-parse", "HEAD")
    assert _git(tmp_path, "status", "--short") == ""
    assert (tmp_path / "app.py").read_text() == "original = True\n"
    assert not (tmp_path / "new.py").exists()
    assert (tmp_path / "ignored.txt").read_text() == "keep me\n"
    assert _git(tmp_path, "log", "-1", "--pretty=%s") == INTERRUPTION_COMMIT_MESSAGE
    events = (tmp_path / ".devlab/workflow-events.jsonl").read_text()
    assert '"type": "interrupted_session_discarded"' in events
    assert '"session_id": "s1_developer"' in events


def test_discard_proposal_is_invalidated_when_affected_git_scope_changes(tmp_path: Path) -> None:
    _dirty_session(tmp_path)
    proposal = inspect_recovery(tmp_path).proposal
    assert proposal is not None
    (tmp_path / "later.txt").write_text("operator change\n")

    with pytest.raises(VersionControlError, match="stale"):
        discard_interrupted_session(tmp_path, proposal)


def test_discard_stops_when_worktree_is_not_clean_after_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dirty_session(tmp_path)
    proposal = inspect_recovery(tmp_path).proposal
    assert proposal is not None
    original_status_entries = recovery._status_entries
    calls = 0

    def status_entries(root: Path) -> tuple[tuple[str, str], ...]:
        nonlocal calls
        calls += 1
        if calls >= 2:
            return (("??", "concurrent.txt"),)
        return original_status_entries(root)

    monkeypatch.setattr(recovery, "_status_entries", status_entries)

    with pytest.raises(IncompleteDiscardError) as exc:
        discard_interrupted_session(tmp_path, proposal)

    assert "concurrent.txt" in str(exc.value)
    assert "git status --short" in format_operator_guidance(exc.value.guidance)
    assert not (tmp_path / ".devlab/workflow-events.jsonl").exists()


def test_decline_guidance_offers_stash_and_manual_restore_to_current_head(
    tmp_path: Path,
) -> None:
    _dirty_session(tmp_path)
    inspection = inspect_recovery(tmp_path)
    assert inspection.guidance is not None

    text = format_operator_guidance(inspection.guidance)

    assert "Inspect:" not in text
    assert "git status --short" not in text
    assert "git diff --cached" not in text
    assert "git stash push --include-untracked" in text
    assert "git restore --source=HEAD --staged --worktree ." in text
    assert "git reset --hard" not in text
    assert "keeping the current HEAD commit" in text
    assert "while HEAD and the affected scope remain unchanged" in text
    assert "preserve the newer commits" in text
    assert "Prefer approving the devlab continue prompt" in text
    assert "commits an interruption record" in text
    assert "bypass those checks and that record" in text
    assert "git clean -fd deletes" in text
    assert "external effects" in text
    assert text.endswith("  devlab continue")


def test_discard_uses_latest_session_identity_across_role_artifacts(tmp_path: Path) -> None:
    _dirty_session(tmp_path)
    write_session_envelope(
        tmp_path / ".devlab/session-artifacts/reviewer/session.toml",
        SessionEnvelope(1, "s0_reviewer", "reviewer", task="T0000"),
    )

    proposal = inspect_recovery(tmp_path).proposal

    assert proposal is not None
    assert proposal.session.session_id == "s1_developer"


def test_recovery_refuses_merge_and_advises_continue_or_abort(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / ".git/MERGE_HEAD").write_text("0" * 40 + "\n")
    (tmp_path / "app.py").write_text("dirty = True\n")

    inspection = inspect_recovery(tmp_path)

    assert inspection.proposal is None
    assert inspection.reason == "Git merge is in progress"
    assert inspection.guidance is not None
    text = format_operator_guidance(inspection.guidance)
    assert "git merge --continue" in text
    assert "git merge --abort" in text


def test_recovery_refuses_untracked_nested_repository(tmp_path: Path) -> None:
    _repository(tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()
    _git(nested, "init")

    inspection = inspect_recovery(tmp_path)

    assert inspection.proposal is None
    assert "nested Git repositories" in inspection.reason
    assert inspection.guidance is not None
    assert "git -C nested/ status" in format_operator_guidance(inspection.guidance)


def _recovery_report(root: Path) -> str:
    inspection = inspect_recovery(root)
    assert inspection.guidance is not None
    return format_operator_guidance(inspection.guidance)


def _dirty_session_evidence(root: Path, **overrides: object) -> Path:
    import dataclasses
    import json

    from devlab.handoffs import SessionEnvelope, write_session_envelope
    from devlab.init import init_workspace
    from devlab.session_logging import SessionMetadata

    init_workspace(
        root, automatic_git=True, git_user_name="Test", git_user_email="test@example.invalid"
    )
    invocation_id = "20261004T004128_003_developer"
    directory = root / ".devlab/session-artifacts/developer"
    write_session_envelope(
        directory / "session.toml", SessionEnvelope(1, invocation_id, "developer", task="T0003")
    )
    (directory / "handoff-candidate.toml").write_text('outcome = "completed"\n')
    metadata = SessionMetadata(
        invocation_id,
        3,
        "developer",
        "codex",
        "test",
        124,
        "timeout",
        2400.0,
        "T0003",
        timeout_kind="max_duration",
        inactive_seconds_at_stop=6.6,
    )
    path = root / f".devlab/logs/agents/{invocation_id}.metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(metadata) | overrides))
    (root / "unfinished.py").write_text("partial = True\n")
    return path


def test_recovery_explains_timeout_and_preservation_without_mutating(tmp_path: Path) -> None:
    from devlab.git import run_git

    _dirty_session_evidence(tmp_path)
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(tmp_path).parts
    }
    head = run_git(tmp_path, "rev-parse", "HEAD").stdout
    status = run_git(tmp_path, "status", "--porcelain").stdout
    output = _recovery_report(tmp_path)

    assert "Related session: 20261004T004128_003_developer" in output
    assert "role=developer; task=T0003" in output
    assert "maximum duration" in output
    assert "2400.0s" in output
    assert "6.6s before stop" in output
    assert "Accepted handoff result absent" in output
    assert "unverified claims" in output
    assert "normal handoff/commit path" in output
    assert "git stash push --include-untracked" in output
    assert "Save this attempt aside and start over" in output
    assert "DevLab will not reuse the stashed work automatically" in output
    assert "later inspection or selective recovery" in output
    assert "Keep and finish" in output
    assert "clean-failed-session removes only untracked diagnostics" in output
    assert "devlab continue" in output
    assert "plan/implement" not in output
    assert "later operator edits" in output
    assert run_git(tmp_path, "rev-parse", "HEAD").stdout == head
    assert run_git(tmp_path, "status", "--porcelain").stdout == status
    assert before == {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(tmp_path).parts
    }


def test_recovery_distinguishes_provider_success_from_commit_failure(tmp_path: Path) -> None:
    _dirty_session_evidence(
        tmp_path,
        return_code=0,
        failure_kind="none",
        timeout_kind="",
        lifecycle_phase="commit",
        lifecycle_stop_reason="version_control: hook rejected commit",
        starting_head="abc123",
    )
    output = _recovery_report(tmp_path)
    assert "Provider completed successfully (exit code 0)" in output
    assert "hook rejected commit" in output
    assert "Reached commit phase" in output
    assert "Starting HEAD: abc123" in output


def test_recovery_retains_guidance_with_invalid_metadata_and_result(tmp_path: Path) -> None:
    path = _dirty_session_evidence(tmp_path)
    path.write_text('{"session_number": "invalid"}')
    (tmp_path / ".devlab/session-artifacts/developer/result.toml").write_text("invalid")
    output = _recovery_report(tmp_path)
    assert "Related session:" in output
    assert "metadata is missing, invalid, or mismatched" in output
    assert "Staged result is invalid" in output
    assert "git stash push --include-untracked" in output


def test_recovery_does_not_attribute_operator_edits_to_old_session(tmp_path: Path) -> None:
    from devlab.git import run_git

    _dirty_session_evidence(tmp_path)
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-m", "Preserve partial work")
    commit = run_git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    (tmp_path / "unfinished.py").write_text("operator = True\n")
    output = _recovery_report(tmp_path)
    assert "Latest recorded session (relationship to edits unknown)" in output
    assert f"Session metadata recorded in commit: {commit}" in output
    assert "not proof of task approval" in output
    assert "no session commit found" not in output


def test_recovery_explains_missing_completion_without_claiming_a_crash(tmp_path: Path) -> None:
    _dirty_session_evidence(
        tmp_path, return_code=-1, failure_kind="incomplete", lifecycle_phase="provider"
    )
    output = _recovery_report(tmp_path)
    assert "may still be running or interrupted" in output
    assert "Last recorded lifecycle phase: provider" in output


def test_recovery_does_not_call_setup_failure_a_provider_failure(tmp_path: Path) -> None:
    _dirty_session_evidence(
        tmp_path,
        return_code=1,
        failure_kind="provider_error",
        lifecycle_phase="environment_setup",
        lifecycle_stop_reason="environment_setup: setup command failed",
    )
    output = _recovery_report(tmp_path)
    assert "Provider invocation not reached" in output
    assert "Normal handoff/commit phase not reached" in output
    assert "environment_setup: setup command failed" in output
    assert "Provider failure stops" not in output


def test_summary_does_not_claim_uncommitted_session_when_metadata_was_committed(
    tmp_path: Path,
) -> None:
    from devlab.git import run_git

    _dirty_session_evidence(tmp_path)
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-m", "Preserve interrupted work")
    candidate = tmp_path / ".devlab/session-artifacts/developer/handoff-candidate.toml"
    candidate.write_text(candidate.read_text() + "# Later edit\n")
    report = _recovery_report(tmp_path)
    summary = report.split("What happened: ", 1)[1].split("\n\n", 1)[0]
    assert "Its metadata appears in Git history" in summary
    assert "do not establish why the current changes remain uncommitted" in summary
    assert "No commit" not in summary
    assert "before its normal session commit" not in summary

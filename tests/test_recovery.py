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


def test_decline_guidance_offers_inspection_stash_and_exact_manual_boundary(
    tmp_path: Path,
) -> None:
    head = _dirty_session(tmp_path)
    inspection = inspect_recovery(tmp_path)
    assert inspection.guidance is not None

    text = format_operator_guidance(inspection.guidance)

    assert "git status --short" in text
    assert "git diff --cached" in text
    assert "git stash push --include-untracked" in text
    assert f"git reset --hard {head}" in text
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

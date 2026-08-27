from __future__ import annotations

import subprocess
from pathlib import Path

from devlab.handoffs import (
    SessionEnvelope,
    parse_handoff_candidate,
    publish_session_result,
    write_session_envelope,
)
from devlab.recovery import apply_recovery, inspect_recovery


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _interrupted_session(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "commit", "--allow-empty", "-m", "Initial")
    artifacts = root / ".devlab/session-artifacts/developer"
    envelope_path = artifacts / "session.toml"
    envelope = SessionEnvelope(1, "s1_developer", "developer", task="T0001")
    write_session_envelope(envelope_path, envelope)
    candidate_path = artifacts / "handoff-candidate.toml"
    candidate_path.write_text(
        'schema_version = 1\noutcome = "failed"\n'
        'commit_message = "Record blocker"\n'
        'done = ["Recorded the blocker"]\nchanged_artifacts = []\n'
        'open_issues = ["External service unavailable"]\naddressed_findings = []\n'
        'next_session_hint = "Continue when available."\n'
    )
    candidate = parse_handoff_candidate(candidate_path, "developer")
    publish_session_result(envelope_path, envelope, candidate)
    history = root / ".devlab/history"
    history.mkdir(parents=True)
    (history / "20260101T000000_developer_handoff.md").write_text(
        (artifacts / "handoff.md").read_text()
    )
    (history / "20260101T000000_developer_result.toml").write_text(
        (artifacts / "result.toml").read_text()
    )
    events = root / ".devlab/workflow-events.jsonl"
    events.write_text("")


def test_recovery_commits_one_complete_interrupted_session(tmp_path: Path) -> None:
    _interrupted_session(tmp_path)

    inspection = inspect_recovery(tmp_path)

    assert inspection.proposal is not None
    assert inspection.proposal.session_id == "s1_developer"
    commit = apply_recovery(tmp_path, inspection.proposal)
    assert commit == _git(tmp_path, "rev-parse", "HEAD")
    assert _git(tmp_path, "status", "--short") == ""
    assert _git(tmp_path, "log", "-1", "--pretty=%s") == (
        "Operator intervention: preserve interrupted session evidence"
    )
    assert '"type": "recovery_applied"' in events_text(tmp_path)


def test_recovery_refuses_mixed_product_changes(tmp_path: Path) -> None:
    _interrupted_session(tmp_path)
    (tmp_path / "app.py").write_text("changed = True\n")

    inspection = inspect_recovery(tmp_path)

    assert inspection.proposal is None
    assert "mixes" in inspection.reason


def events_text(root: Path) -> str:
    return (root / ".devlab/workflow-events.jsonl").read_text()

from __future__ import annotations

import dataclasses
from pathlib import Path

from devlab.git import VersionControlError, run_git
from devlab.handoffs import HandoffError, load_session_result
from devlab.workflow_events import append_workflow_event
from devlab.workspace import AGENT_LOG_DIR, ARTIFACTS_DIR, HISTORY_DIR

RECOVERY_COMMIT_MESSAGE = "Operator intervention: preserve interrupted session evidence"
_SESSION_FILES = {
    "handoff-candidate.toml",
    "handoff.md",
    "result.toml",
    "session.toml",
    "submission-attempts.jsonl",
}


@dataclasses.dataclass(frozen=True)
class RecoveryProposal:
    """A fingerprinted, evidence-preserving interrupted-session recovery."""

    head: str
    session_id: str
    role: str
    task: str
    paths: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class RecoveryInspection:
    proposal: RecoveryProposal | None
    reason: str
    dirty_paths: tuple[str, ...] = ()


def inspect_recovery(root: Path) -> RecoveryInspection:
    """Recognize one complete accepted session left as DevLab-owned Git residue."""
    entries = _status_entries(root)
    if not entries:
        return RecoveryInspection(None, "clean")
    if any(index not in {" ", "?"} for index, _worktree, _path in entries):
        return RecoveryInspection(
            None,
            "staged changes prevent automatic recovery",
            tuple(path for _index, _worktree, path in entries),
        )
    dirty_paths = tuple(path for _index, _worktree, path in entries)
    result_paths = [
        path
        for path in dirty_paths
        if path.startswith(f"{ARTIFACTS_DIR}/") and path.endswith("/result.toml")
    ]
    if len(result_paths) != 1:
        return RecoveryInspection(
            None,
            "dirty state is not one interrupted accepted session",
            dirty_paths,
        )
    result_path = root / result_paths[0]
    try:
        result = load_session_result(result_path)
    except (OSError, ValueError, HandoffError) as exc:
        return RecoveryInspection(None, f"session result is not valid: {exc}", dirty_paths)
    envelope = result.envelope
    artifact_prefix = f"{ARTIFACTS_DIR}/{envelope.role}/"
    allowed = {
        path
        for path in dirty_paths
        if path.startswith(artifact_prefix) and Path(path).name in _SESSION_FILES
    }
    history_results = sorted(
        path
        for path in dirty_paths
        if path.startswith(f"{HISTORY_DIR}/") and path.endswith(f"_{envelope.role}_result.toml")
    )
    matching_history = [
        path for path in history_results if (root / path).read_text() == result_path.read_text()
    ]
    if len(matching_history) != 1:
        return RecoveryInspection(
            None,
            "accepted session does not have one matching archived result",
            dirty_paths,
        )
    history_stem = matching_history[0].removesuffix("_result.toml")
    allowed.update(path for path in dirty_paths if path.startswith(history_stem + "_"))
    log_prefix = f"{AGENT_LOG_DIR}/{envelope.session_id}."
    allowed.update(path for path in dirty_paths if path.startswith(log_prefix))
    for path in (
        ".devlab/workflow-events.jsonl",
        ".devlab/prerequisite-blocker.json",
    ):
        if path in dirty_paths:
            allowed.add(path)
    if set(dirty_paths) != allowed:
        return RecoveryInspection(
            None,
            "dirty state mixes interrupted-session evidence with unrelated changes",
            dirty_paths,
        )
    required = {
        f"{artifact_prefix}handoff.md",
        f"{artifact_prefix}result.toml",
        matching_history[0],
        history_stem + "_handoff.md",
    }
    if not required.issubset(allowed):
        return RecoveryInspection(None, "interrupted-session evidence is incomplete", dirty_paths)
    head = run_git(root, "rev-parse", "HEAD").stdout.strip()
    return RecoveryInspection(
        RecoveryProposal(
            head=head,
            session_id=envelope.session_id,
            role=envelope.role,
            task=envelope.task,
            paths=tuple(sorted(allowed)),
        ),
        "interrupted accepted session",
        dirty_paths,
    )


def apply_recovery(root: Path, proposal: RecoveryProposal) -> str:
    """Apply a still-current proposal and commit only its evidence paths."""
    current = inspect_recovery(root).proposal
    if current != proposal:
        raise VersionControlError("recovery proposal is stale; inspect the workspace again")
    append_workflow_event(
        root,
        "recovery_applied",
        session_id=proposal.session_id,
        role=proposal.role,
        task=proposal.task,
        recovery="preserve_interrupted_session_evidence",
    )
    commit_paths = tuple(sorted({*proposal.paths, ".devlab/workflow-events.jsonl"}))
    run_git(root, "add", "--", *commit_paths)
    run_git(root, "commit", "-m", RECOVERY_COMMIT_MESSAGE)
    return run_git(root, "rev-parse", "HEAD").stdout.strip()


def format_recovery_proposal(proposal: RecoveryProposal) -> str:
    lines = [
        "DevLab found an accepted session whose bookkeeping commit was interrupted.",
        "",
        f"Session: {proposal.session_id}",
        f"Role: {proposal.role}",
        f"Task: {proposal.task or 'none'}",
        "",
        "Recovery will preserve these DevLab-owned evidence paths:",
    ]
    lines.extend(f"- {path}" for path in proposal.paths)
    lines.extend(
        [
            "",
            f"Commit: {RECOVERY_COMMIT_MESSAGE}",
            "Product, task, plan, finding, and verification content will not be altered.",
        ]
    )
    return "\n".join(lines)


def _status_entries(root: Path) -> tuple[tuple[str, str, str], ...]:
    output = run_git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout
    entries: list[tuple[str, str, str]] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append((line[0], line[1], path))
    return tuple(entries)

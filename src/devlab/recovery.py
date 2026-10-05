from __future__ import annotations

import dataclasses
import shlex
from pathlib import Path

from devlab._console import wrap_prose as _wrap_prose
from devlab.git import VersionControlError, run_git
from devlab.handoffs import HandoffError, load_session_envelope
from devlab.history import SessionDiagnosticLine, session_diagnostic_lines
from devlab.workflow_events import append_workflow_event
from devlab.workspace import ARTIFACTS_DIR, Workspace

INTERRUPTION_COMMIT_MESSAGE = "Record discarded interrupted DevLab session"


@dataclasses.dataclass(frozen=True)
class OperatorAlternative:
    title: str
    effect: str
    commands: tuple[str, ...]
    destructive: bool = False
    prompt_instruction: str = ""


@dataclasses.dataclass(frozen=True)
class OperatorGuidance:
    summary: str
    explanation: str
    inspection_commands: tuple[str, ...]
    alternatives: tuple[OperatorAlternative, ...]
    warnings: tuple[str, ...]
    retry_command: str = "devlab continue"
    diagnosis: tuple[SessionDiagnosticLine, ...] = ()


@dataclasses.dataclass(frozen=True)
class InterruptedSession:
    session_id: str = ""
    role: str = ""
    task: str = ""


@dataclasses.dataclass(frozen=True)
class DiscardProposal:
    """A fingerprinted proposal to restore the current committed boundary."""

    head: str
    entries: tuple[tuple[str, str], ...]
    clean_paths: tuple[str, ...]
    session: InterruptedSession

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(path for _status, path in self.entries)


@dataclasses.dataclass(frozen=True)
class RecoveryInspection:
    proposal: DiscardProposal | None
    reason: str
    guidance: OperatorGuidance | None = None


class IncompleteDiscardError(VersionControlError):
    """Raised when Git still reports uncommitted state after reset and clean."""

    def __init__(self, entries: tuple[tuple[str, str], ...]) -> None:
        self.entries = entries
        paths = ", ".join(path for _status, path in entries)
        super().__init__(f"repository is still dirty after discard: {paths}")

    @property
    def guidance(self) -> OperatorGuidance:
        return OperatorGuidance(
            summary="Git could not fully restore a clean workflow boundary.",
            explanation=(
                "DevLab stopped after reset and clean because Git still reports uncommitted "
                "state. It did not record the interruption or start another session."
            ),
            inspection_commands=("git status --short", "git diff", "git diff --cached"),
            alternatives=(),
            warnings=(
                "Inspect and explicitly commit, stash, or discard the remaining paths: "
                + ", ".join(path for _status, path in self.entries),
            ),
        )


def inspect_recovery(root: Path) -> RecoveryInspection:
    """Offer discard only when Git has a plain, restorable uncommitted state."""
    entries = _status_entries(root)
    if not entries:
        return RecoveryInspection(None, "clean")
    head = run_git(root, "rev-parse", "HEAD").stdout.strip()
    operation = _git_operation(root)
    if operation is not None:
        return RecoveryInspection(
            None,
            f"Git {operation} is in progress",
            _git_operation_guidance(operation),
        )
    if any("U" in status or status in {"AA", "DD"} for status, _path in entries):
        return RecoveryInspection(
            None,
            "the Git index contains unresolved conflicts",
            _conflict_guidance(),
        )
    if any(any(character.islower() for character in status) for status, _path in entries):
        return RecoveryInspection(
            None,
            "a submodule or nested worktree has uncommitted state",
            _submodule_guidance(),
        )
    nested = _nested_repository_paths(root, entries)
    if nested:
        return RecoveryInspection(
            None,
            "untracked nested Git repositories cannot be discarded safely",
            _nested_repository_guidance(nested),
        )
    clean_paths = _clean_preview(root)
    session = _interrupted_session(root, entries)
    proposal = DiscardProposal(head, entries, clean_paths, session)
    guidance = discard_guidance(proposal)
    diagnosis = list(
        session_diagnostic_lines(
            root, session_id=session.session_id, role=session.role, task=session.task
        )
    )
    counts = {"product/other": 0, "workflow/configuration": 0, "session diagnostics": 0}
    for _status, path in entries:
        category = (
            "session diagnostics"
            if path.startswith((".devlab/logs/", ".devlab/session-artifacts/"))
            else "workflow/configuration"
            if path.startswith(".devlab/")
            else "product/other"
        )
        counts[category] += 1
    diagnosis.append(
        SessionDiagnosticLine(
            "Changed paths: "
            + ", ".join(f"{count} {category}" for category, count in counts.items() if count)
            + ".",
            prose=True,
        )
    )
    if session.task:
        try:
            task = next(
                (
                    task
                    for task in Workspace(root).snapshot.list_tasks()
                    if task.id == session.task
                ),
                None,
            )
            if task is not None:
                diagnosis.append(
                    SessionDiagnosticLine(
                        f"Current task: {task.id}; status={task.status.value}; "
                        f"{task.path.relative_to(root)}"
                    )
                )
        except (OSError, ValueError):
            diagnosis.append(
                SessionDiagnosticLine(
                    "Current task state could not be read; inspect the task diagnostics.",
                    prose=True,
                )
            )
    return RecoveryInspection(
        proposal,
        "uncommitted repository state",
        dataclasses.replace(guidance, diagnosis=tuple(diagnosis)),
    )


def discard_interrupted_session(root: Path, proposal: DiscardProposal) -> str:
    """Restore a still-current Git boundary and record compact interruption provenance."""
    current = inspect_recovery(root).proposal
    if current != proposal:
        raise VersionControlError("discard proposal is stale; inspect the workspace again")
    run_git(root, "reset", "--hard", proposal.head)
    run_git(root, "clean", "-fd")
    remaining = _status_entries(root)
    if remaining:
        raise IncompleteDiscardError(remaining)
    append_workflow_event(
        root,
        "interrupted_session_discarded",
        session_id=proposal.session.session_id,
        role=proposal.session.role,
        task=proposal.session.task,
        restart_commit=proposal.head,
        discarded_paths=list(proposal.changed_paths),
    )
    run_git(root, "add", "--", ".devlab/workflow-events.jsonl")
    run_git(root, "commit", "-m", INTERRUPTION_COMMIT_MESSAGE)
    return run_git(root, "rev-parse", "HEAD").stdout.strip()


def discard_guidance(proposal: DiscardProposal) -> OperatorGuidance:
    identity = proposal.session.session_id or "unknown interrupted invocation"
    stash_message = f"Interrupted DevLab session {identity}"
    return OperatorGuidance(
        summary="Uncommitted repository state prevents workflow continuation.",
        explanation=(
            f"DevLab can restore the repository to committed boundary {proposal.head} "
            "if the discard is approved at the prompt below. "
            "Declining leaves every file unchanged."
        ),
        inspection_commands=(),
        alternatives=(
            OperatorAlternative(
                "Discard and restart through DevLab",
                "Approve the exact discard scope shown below. DevLab discards the changes, "
                "records the interruption, and continues automatically.",
                (),
                destructive=True,
                prompt_instruction="y to approve the discard and continue.",
            ),
            OperatorAlternative(
                "Discard manually",
                "Prefer approving the devlab continue prompt: DevLab rechecks the HEAD, "
                "affected Git scope, and session identity, verifies the worktree is clean, "
                "and commits an interruption record before continuing. These manual commands "
                "bypass those checks and that record. Run them from the repository root to "
                "discard staged and unstaged changes and delete non-ignored untracked files, "
                "keeping the current HEAD commit. This matches the proposed discard only "
                "while HEAD and the affected scope remain unchanged. If HEAD has advanced, "
                "these commands preserve the newer commits; DevLab would reject the old "
                "proposal as stale.",
                (
                    "git restore --source=HEAD --staged --worktree .",
                    "git clean -fd",
                    "devlab continue",
                ),
                destructive=True,
                prompt_instruction="N (or Enter), then run the commands below yourself.",
            ),
            OperatorAlternative(
                "Save this attempt aside and start over",
                "Stash tracked and non-ignored untracked changes, then retry from the last "
                "commit. DevLab will not reuse the stashed work automatically. Keep the stash "
                "for later inspection or selective recovery.",
                (
                    "git stash push --include-untracked -m " + shlex.quote(stash_message),
                    "devlab continue",
                ),
                prompt_instruction="N (or Enter), then run the commands below.",
            ),
            OperatorAlternative(
                "Keep and finish the work",
                "Review tracked and untracked changes and the session evidence. Finish and "
                "validate the work before selectively committing it; a commit alone does not "
                "establish handoff acceptance or reviewer approval.",
                (),
                prompt_instruction="N (or Enter), then review and finish the work yourself.",
            ),
        ),
        warnings=(
            "git clean -fd deletes non-ignored untracked files.",
            "Ignored files and external effects such as databases, deployments, APIs, and "
            "running processes are not restored.",
            "Restarting may repeat external effects from the interrupted session.",
            "Read untracked files separately; git diff does not show their contents. "
            "clean-failed-session removes only untracked diagnostics, not product changes.",
        ),
    )


def format_discard_proposal(proposal: DiscardProposal, *, width: int | None = None) -> str:
    lines = [
        "Discard proposal — technical details:",
        _wrap_prose(
            "DevLab found uncommitted state outside a completed workflow boundary.", width
        ),
        "",
        f"Restart boundary: {proposal.head}",
    ]
    if proposal.session.session_id:
        lines.extend(
            [
                f"Session: {proposal.session.session_id}",
                f"Role: {proposal.session.role or 'unknown'}",
                f"Task: {proposal.session.task or 'none'}",
            ]
        )
    lines.extend(["", "Discarded tracked/untracked paths:"])
    lines.extend(f"- {status} {path}" for status, path in proposal.entries)
    if proposal.clean_paths:
        lines.extend(["", "Git clean preview:"])
        lines.extend(f"- {path}" for path in proposal.clean_paths)
    return "\n".join(lines)


def format_operator_guidance(guidance: OperatorGuidance, *, width: int | None = None) -> str:
    lines = [_wrap_prose(guidance.summary, width), ""]
    if guidance.diagnosis:
        lines.extend(
            _wrap_prose(line.text, width) if line.prose else line.text
            for line in guidance.diagnosis
        )
        lines.append("")
    lines.append(_wrap_prose(guidance.explanation, width))
    if guidance.inspection_commands:
        lines.extend(["", "Inspect:"])
        lines.extend(f"  {command}" for command in guidance.inspection_commands)
    if guidance.alternatives:
        lines.extend(["", "Recovery options:"])
    for number, alternative in enumerate(guidance.alternatives, start=1):
        marker = " (destructive)" if alternative.destructive else ""
        lines.extend(
            [
                "",
                _wrap_prose(
                    f"{alternative.title}{marker}:",
                    width,
                    indent=f"  {number}. ",
                    continuation="     ",
                ),
            ]
        )
        if alternative.prompt_instruction:
            lines.append(
                _wrap_prose(
                    f"At the discard prompt: {alternative.prompt_instruction}",
                    width,
                    indent="     ",
                )
            )
        lines.append(_wrap_prose(alternative.effect, width, indent="     "))
        lines.extend(f"       {command}" for command in alternative.commands)
    if guidance.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(
            _wrap_prose(warning, width, indent="- ", continuation="  ")
            for warning in guidance.warnings
        )
    lines.extend(["", "After resolving the condition, run:", f"  {guidance.retry_command}"])
    return "\n".join(lines)


def _status_entries(root: Path) -> tuple[tuple[str, str], ...]:
    output = run_git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append((line[:2], path))
    return tuple(entries)


def _clean_preview(root: Path) -> tuple[str, ...]:
    output = run_git(root, "clean", "-fdn").stdout
    return tuple(
        line.removeprefix("Would remove ")
        for line in output.splitlines()
        if line.startswith("Would remove ")
    )


def _nested_repository_paths(root: Path, entries: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(
        path for status, path in entries if status == "??" and (root / path / ".git").exists()
    )


def _interrupted_session(root: Path, entries: tuple[tuple[str, str], ...]) -> InterruptedSession:
    dirty_roles = {
        Path(path).parts[2]
        for _status, path in entries
        if len(Path(path).parts) > 3 and Path(path).parts[:2] == (".devlab", "session-artifacts")
    }
    candidates = [root / ARTIFACTS_DIR / role / "session.toml" for role in sorted(dirty_roles)]
    sessions: list[InterruptedSession] = []
    for path in candidates:
        try:
            envelope = load_session_envelope(path)
        except (OSError, ValueError, HandoffError):
            continue
        sessions.append(InterruptedSession(envelope.session_id, envelope.role, envelope.task))
    return max(sessions, key=lambda item: item.session_id, default=InterruptedSession())


def _git_operation(root: Path) -> str | None:
    git_dir_value = run_git(root, "rev-parse", "--git-dir").stdout.strip()
    git_dir = Path(git_dir_value)
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    checks = (
        ("merge", git_dir / "MERGE_HEAD"),
        ("rebase", git_dir / "rebase-merge"),
        ("rebase", git_dir / "rebase-apply"),
        ("cherry-pick", git_dir / "CHERRY_PICK_HEAD"),
        ("revert", git_dir / "REVERT_HEAD"),
    )
    for operation, path in checks:
        if path.exists():
            return operation
    return None


def _git_operation_guidance(operation: str) -> OperatorGuidance:
    command = "cherry-pick" if operation == "cherry-pick" else operation
    return OperatorGuidance(
        summary=f"Git {operation} state prevents DevLab continuation.",
        explanation="DevLab will not resolve or discard an in-progress Git operation.",
        inspection_commands=("git status",),
        alternatives=(
            OperatorAlternative(
                f"Complete the {operation}",
                "Resolve Git's reported work and complete the operation.",
                (f"git {command} --continue", "devlab continue"),
            ),
            OperatorAlternative(
                f"Abort the {operation}",
                "Return to the state from before the Git operation.",
                (f"git {command} --abort", "devlab continue"),
                destructive=True,
            ),
        ),
        warnings=("Review Git's status before choosing continue or abort.",),
    )


def _conflict_guidance() -> OperatorGuidance:
    return OperatorGuidance(
        summary="Unresolved Git conflicts prevent DevLab continuation.",
        explanation="DevLab cannot decide which conflicting content is correct.",
        inspection_commands=("git status", "git diff --name-only --diff-filter=U"),
        alternatives=(),
        warnings=("Resolve or abort the operation that created the conflicts.",),
    )


def _submodule_guidance() -> OperatorGuidance:
    return OperatorGuidance(
        summary="Nested repository state prevents DevLab continuation.",
        explanation="Top-level discard cannot safely restore uncommitted submodule content.",
        inspection_commands=("git status", "git submodule status"),
        alternatives=(),
        warnings=("Commit, stash, or discard nested changes explicitly before continuing.",),
    )


def _nested_repository_guidance(paths: tuple[str, ...]) -> OperatorGuidance:
    return OperatorGuidance(
        summary="Untracked nested Git repositories prevent DevLab continuation.",
        explanation=(
            "A top-level git clean skips nested repositories and cannot prove their contents "
            "were restored."
        ),
        inspection_commands=(
            "git status --short",
            *(f"git -C {shlex.quote(path)} status" for path in paths),
        ),
        alternatives=(),
        warnings=("Move, commit, or remove each nested repository explicitly.",),
    )

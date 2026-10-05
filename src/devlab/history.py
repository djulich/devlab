"""Session history reporting from metadata files."""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

from devlab.git import VersionControlError, run_git
from devlab.handoffs import HandoffError, load_session_result
from devlab.session_logging import SessionMetadata
from devlab.workflow_events import load_workflow_events
from devlab.workspace import AGENT_LOG_DIR


def load_session_metadata(root: Path) -> list[SessionMetadata]:
    log_dir = root / AGENT_LOG_DIR
    entries: list[SessionMetadata] = []
    for path in log_dir.glob("*.metadata.json"):
        try:
            data = json.loads(path.read_text())
            entry = SessionMetadata(**data)
            string_fields = (
                "invocation_id",
                "role_name",
                "provider",
                "model",
                "task_id",
                "failure_kind",
                "timeout_kind",
                "provider_version",
                "starting_head",
                "lifecycle_phase",
                "lifecycle_stop_reason",
                "accepted_handoff",
            )
            if not all(isinstance(getattr(entry, name), str) for name in string_fields):
                continue
            if entry.invocation_id != path.name.removesuffix(".metadata.json"):
                continue
            if not isinstance(entry.session_number, int) or not isinstance(entry.return_code, int):
                continue
            numbers = (
                entry.duration_seconds,
                entry.inactive_seconds_at_stop,
                entry.max_session_duration_seconds,
                entry.inactivity_timeout_seconds,
            )
            if any(
                value is not None
                and (not isinstance(value, int | float) or not math.isfinite(value) or value < 0)
                for value in numbers
            ):
                continue
            entries.append(entry)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return sorted(entries, key=lambda m: m.invocation_id)


@dataclasses.dataclass(frozen=True)
class SessionDiagnosticLine:
    """A session diagnostic sentence or a literal evidence line."""

    text: str
    prose: bool = False


def describe_session(root: Path, *, session_id: str = "", role: str = "", task: str = "") -> str:
    return "\n".join(
        line.text
        for line in session_diagnostic_lines(root, session_id=session_id, role=role, task=task)
    )


def session_diagnostic_lines(
    root: Path, *, session_id: str = "", role: str = "", task: str = ""
) -> tuple[SessionDiagnosticLine, ...]:
    """Explain recorded session evidence without assigning ownership of current edits."""
    entries = load_session_metadata(root)
    entry = next((item for item in entries if item.invocation_id == session_id), None)
    related = bool(session_id)
    if not session_id:
        paths = sorted((root / AGENT_LOG_DIR).glob("*.metadata.json"))
        if paths:
            session_id = paths[-1].name.removesuffix(".metadata.json")
            entry = next((item for item in entries if item.invocation_id == session_id), None)
            if entry is not None:
                role, task = entry.role_name, entry.task_id
    if not session_id:
        return (
            SessionDiagnosticLine(
                "What happened: No usable session evidence was found, "
                "so the origin of these changes is unknown.",
                prose=True,
            ),
        )
    label = (
        "Related session" if related else "Latest recorded session (relationship to edits unknown)"
    )
    if entry is not None and related and (entry.role_name != role or entry.task_id != task):
        entry = None
    commit = ""
    if entry is not None:
        try:
            commit = run_git(
                root,
                "log",
                "-1",
                "--format=%H",
                "--",
                f"{AGENT_LOG_DIR}/{session_id}.metadata.json",
            ).stdout.strip()
        except VersionControlError:
            commit = ""
    lines = [
        SessionDiagnosticLine(
            "What happened: " + _session_summary(entry, related=related, committed=bool(commit)),
            prose=True,
        )
    ]
    lines.extend(
        [
            SessionDiagnosticLine(""),
            SessionDiagnosticLine(f"{label}: {session_id}; role={role}; task={task or 'none'}."),
        ]
    )
    lines.append(
        SessionDiagnosticLine("Current changes may also include later operator edits.", prose=True)
    )
    if related:
        lines.extend(_describe_staged_handoff(root, session_id, role, task))
    metadata_path = f"{AGENT_LOG_DIR}/{session_id}.metadata.json"
    lines.append(SessionDiagnosticLine(f"Evidence: {metadata_path}"))
    for suffix in ("stderr.log", "stdout.log"):
        path = f"{AGENT_LOG_DIR}/{session_id}.{suffix}"
        if (root / path).is_file():
            lines.append(SessionDiagnosticLine(f"Log: {path}"))
    if entry is None:
        lines.append(
            SessionDiagnosticLine(
                "Provider outcome unavailable: metadata is missing, invalid, or mismatched.",
                prose=True,
            )
        )
        return tuple(lines)
    if entry.lifecycle_phase in {"starting", "environment_setup"}:
        lines.append(
            SessionDiagnosticLine(
                "Provider invocation not reached in the recorded lifecycle.", prose=True
            )
        )
    elif entry.failure_kind == "incomplete":
        lines.append(
            SessionDiagnosticLine(
                "Provider completion not recorded; session may still be running or interrupted.",
                prose=True,
            )
        )
    elif entry.failure_kind == "timeout":
        kind = {"max_duration": "maximum duration", "inactivity": "inactivity"}.get(
            entry.timeout_kind, "unspecified timeout"
        )
        lines.append(
            SessionDiagnosticLine(
                f"Provider stopped: {kind}; exit code {entry.return_code}.", prose=True
            )
        )
        limit = (
            entry.max_session_duration_seconds
            if entry.timeout_kind == "max_duration"
            else entry.inactivity_timeout_seconds
            if entry.timeout_kind == "inactivity"
            else None
        )
        if limit is not None:
            lines.append(SessionDiagnosticLine(f"Configured {kind} limit: {limit}s.", prose=True))
    elif entry.return_code == 0 and entry.failure_kind == "none":
        lines.append(
            SessionDiagnosticLine(
                "Provider completed successfully (exit code 0); workflow completion is separate.",
                prose=True,
            )
        )
    else:
        lines.append(
            SessionDiagnosticLine(
                f"Provider outcome: {entry.failure_kind}; exit code {entry.return_code}.",
                prose=True,
            )
        )
    if entry.duration_seconds is not None:
        lines.append(
            SessionDiagnosticLine(f"Provider duration: {entry.duration_seconds:.1f}s.", prose=True)
        )
    if entry.inactive_seconds_at_stop is not None:
        lines.append(
            SessionDiagnosticLine(
                f"Last provider output: {entry.inactive_seconds_at_stop:.1f}s before stop.",
                prose=True,
            )
        )
    if entry.lifecycle_phase:
        lines.append(
            SessionDiagnosticLine(
                f"Last recorded lifecycle phase: {entry.lifecycle_phase}.", prose=True
            )
        )
    if entry.lifecycle_stop_reason:
        lines.append(SessionDiagnosticLine(f"Orchestrator stop: {entry.lifecycle_stop_reason}"))
    if entry.starting_head:
        lines.append(SessionDiagnosticLine(f"Starting HEAD: {entry.starting_head}"))
    if commit:
        lines.append(
            SessionDiagnosticLine(
                f"Session metadata recorded in commit: {commit} (not proof of task approval)."
            )
        )
    elif entry.lifecycle_phase == "commit":
        lines.append(
            SessionDiagnosticLine(
                "Reached commit phase; no commit containing this metadata was found.", prose=True
            )
        )
    elif entry.lifecycle_phase in {"starting", "environment_setup"}:
        lines.append(SessionDiagnosticLine("Normal handoff/commit phase not reached.", prose=True))
    elif entry.failure_kind in {"timeout", "nonzero_exit", "provider_error"}:
        lines.append(
            SessionDiagnosticLine(
                "Provider failure stops the normal handoff/commit path; no session commit found.",
                prose=True,
            )
        )
    else:
        lines.append(
            SessionDiagnosticLine(
                "No commit containing this session metadata found; completion is not established.",
                prose=True,
            )
        )
    if entry.accepted_handoff:
        lines.append(SessionDiagnosticLine(f"Recorded accepted handoff: {entry.accepted_handoff}"))
    return tuple(lines)


def _session_summary(entry: SessionMetadata | None, *, related: bool, committed: bool) -> str:
    """Summarize recorded causes, keeping unrelated and incomplete evidence explicit."""
    if entry is None:
        return (
            "Session evidence is missing, invalid, or inconsistent, so DevLab cannot reliably "
            "explain why these changes remain uncommitted."
        )
    if not related:
        return (
            "The latest session record cannot be linked to these changes. DevLab cannot tell "
            "whether they are unfinished session work or later edits."
        )
    subject = f"The {entry.role_name} session"
    if entry.task_id:
        subject += f" for {entry.task_id}"
    if entry.failure_kind == "incomplete" and not entry.lifecycle_stop_reason:
        return (
            f"{subject} has no recorded completion. It may still be running or may have been "
            "interrupted; the records do not establish which."
        )
    if entry.lifecycle_phase in {"starting", "environment_setup"}:
        summary = f"{subject} did not reach agent invocation in the recorded lifecycle."
        if entry.lifecycle_stop_reason:
            summary += " DevLab stopped during session preparation."
    elif entry.failure_kind == "timeout":
        if entry.timeout_kind == "max_duration":
            limit = entry.max_session_duration_seconds
            duration = (
                f"{limit / 60:g}-minute"
                if limit is not None and limit % 60 == 0
                else f"{limit:g}-second"
                if limit is not None
                else "maximum duration"
            )
            summary = f"{subject} reached its {duration} limit and was stopped."
            if entry.inactive_seconds_at_stop is not None:
                summary += (
                    f" It last produced output {entry.inactive_seconds_at_stop:.1f}"
                    " seconds earlier."
                )
        elif entry.timeout_kind == "inactivity":
            summary = f"{subject} was stopped because it exceeded its inactivity limit."
        else:
            summary = f"{subject} timed out; the timeout type was not recorded."
    elif entry.failure_kind == "incomplete":
        summary = f"{subject} was interrupted before its provider outcome was recorded."
    elif entry.failure_kind != "none" or entry.return_code != 0:
        summary = f"{subject}'s agent invocation failed."
    elif entry.lifecycle_stop_reason:
        phase = entry.lifecycle_stop_reason.split(":", 1)[0]
        cause = {
            "handoff_validation": "accepting its handoff",
            "environment_teardown": "tearing down its environment",
            "version_control": "recording its changes in Git",
            "task_validation": "validating its task",
            "milestone_validation": "validating its milestone",
        }.get(phase, "processing the session after agent execution")
        summary = f"{subject}'s agent finished successfully, but DevLab stopped while {cause}."
    else:
        summary = (
            f"{subject}'s agent finished successfully, but that alone does not establish "
            "workflow completion."
        )
    if committed:
        return summary + (
            " Its metadata appears in Git history; these records do not establish why the "
            "current changes remain uncommitted."
        )
    if entry.failure_kind in {
        "timeout",
        "nonzero_exit",
        "provider_error",
        "missing_executable",
    } and entry.role_name in {"architect", "planner", "developer", "reviewer", "integrator"}:
        summary += " Such failures stop DevLab before its normal session commit."
    return (
        summary
        + " No commit containing this session's metadata was found; review the remaining work."
    )


def _describe_staged_handoff(
    root: Path, session_id: str, role: str, task: str
) -> list[SessionDiagnosticLine]:
    lines: list[SessionDiagnosticLine] = []
    # Roles from envelopes must remain a single workspace directory name.
    if Path(role).name != role or role in {".", ".."}:
        return [SessionDiagnosticLine("Invalid role in session evidence.", prose=True)]
    directory = root / ".devlab/session-artifacts" / role
    candidate = directory / "handoff-candidate.toml"
    if candidate.is_file():
        lines.append(
            SessionDiagnosticLine(
                f"Handoff candidate: {candidate.relative_to(root)} (unverified claims)."
            )
        )
    result = directory / "result.toml"
    if result.is_file():
        try:
            accepted = load_session_result(result)
            matches = (
                accepted.envelope.session_id == session_id
                and accepted.envelope.role == role
                and accepted.envelope.task == task
            )
        except (OSError, ValueError, HandoffError):
            matches = False
        lines.append(
            SessionDiagnosticLine(
                "Accepted handoff result: " + str(result.relative_to(root))
                if matches
                else "Staged result is invalid or belongs to another session.",
                prose=not matches,
            )
        )
    else:
        lines.append(
            SessionDiagnosticLine(
                "Accepted handoff result absent from this session's staging directory.", prose=True
            )
        )
    return lines


def format_history(root: Path, *, json_output: bool = False) -> str:
    entries = load_session_metadata(root)
    research_events = [
        event
        for event in load_workflow_events(root)
        if event.type in {"research_requested", "research_completed", "research_resume_completed"}
    ]
    if not entries and not research_events:
        return "Session history: none"
    if json_output:
        return json.dumps(
            [dataclasses.asdict(entry) for entry in entries],
            indent=2,
        )
    lines = ["Session history:"]
    for entry in entries:
        lines.append(_format_entry(entry))
    if research_events:
        lines.append("Research lifecycle:")
        for event in research_events:
            research_id = event.data.get("research", "unknown")
            role = event.data.get("role", "")
            route = f" role={role}" if role else ""
            lines.append(f"  {event.at} {event.type} {research_id}{route}")
    return "\n".join(lines)


def _format_entry(entry: SessionMetadata) -> str:
    provider_model = f"{entry.provider}/{entry.model}" if entry.provider else ""
    if provider_model and entry.provider_version:
        provider_model = f"{provider_model} ({entry.provider_version})"
    if entry.failure_kind == "incomplete":
        outcome = "INCOMPLETE"
    elif entry.failure_kind != "none" or entry.return_code != 0:
        failure = entry.timeout_kind or entry.failure_kind
        outcome = f"FAILED ({failure})"
    elif entry.lifecycle_stop_reason:
        outcome = f"STOPPED ({entry.lifecycle_phase})"
    else:
        outcome = "ok"
    task = entry.task_id or ""
    duration = f"{entry.duration_seconds:.1f}s" if entry.duration_seconds is not None else ""
    parts = [
        f"  #{entry.session_number:<3d}",
        f"{entry.role_name:<12s}",
        f"{provider_model:<30s}" if provider_model else "",
        f"{outcome:<20s}",
        f"{task:<6s}" if task else "",
        duration,
    ]
    return " ".join(part for part in parts if part)

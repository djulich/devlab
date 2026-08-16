"""Session history reporting from metadata files."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from devlab.orchestrator import SessionMetadata
from devlab.workflow_events import load_workflow_events
from devlab.workspace import AGENT_LOG_DIR


def load_session_metadata(root: Path) -> list[SessionMetadata]:
    log_dir = root / AGENT_LOG_DIR
    entries: list[SessionMetadata] = []
    for path in log_dir.glob("*.metadata.json"):
        try:
            data = json.loads(path.read_text())
            entries.append(SessionMetadata(**data))
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
    return sorted(entries, key=lambda m: m.session_number)


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
            [dataclasses.asdict(entry) for entry in entries], indent=2,
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
    if entry.failure_kind == "none" and entry.return_code == 0:
        outcome = "ok"
    else:
        outcome = f"FAILED ({entry.failure_kind})"
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

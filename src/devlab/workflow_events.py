from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKFLOW_EVENTS = ".devlab/workflow-events.jsonl"
WORKFLOW_EVENT_VERSION = 1


@dataclasses.dataclass(frozen=True)
class WorkflowEvent:
    version: int
    type: str
    at: str
    data: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "type": self.type,
            "at": self.at,
            **self.data,
        }


def append_workflow_event(
    root: Path,
    event_type: str,
    *,
    at: datetime | None = None,
    **data: object,
) -> WorkflowEvent:
    event = WorkflowEvent(
        version=WORKFLOW_EVENT_VERSION,
        type=event_type,
        at=(at or datetime.now(UTC)).replace(microsecond=0).isoformat(),
        data=data,
    )
    path = root / WORKFLOW_EVENTS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.as_dict(), sort_keys=True) + "\n")
    return event


def load_workflow_events(root: Path) -> list[WorkflowEvent]:
    path = root / WORKFLOW_EVENTS
    if not path.exists():
        return []
    events: list[WorkflowEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
            event = parse_workflow_event(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        events.append(event)
    return events


def parse_workflow_event(raw: object) -> WorkflowEvent:
    if not isinstance(raw, dict):
        raise ValueError("workflow event must be a JSON object")
    data = dict(raw)
    version = data.pop("version", None)
    event_type = data.pop("type", None)
    at = data.pop("at", None)
    if version != WORKFLOW_EVENT_VERSION:
        raise ValueError("unsupported workflow event version")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("workflow event type must be a string")
    if not isinstance(at, str) or not at:
        raise ValueError("workflow event at must be a string")
    return WorkflowEvent(
        version=version,
        type=event_type,
        at=at,
        data={key: value for key, value in data.items() if _json_scalar_or_list(value)},
    )


def count_events(
    events: list[WorkflowEvent],
    event_type: str,
    *,
    mode: str | None = None,
) -> int:
    count = 0
    for event in events:
        if event.type != event_type:
            continue
        if mode is not None and event.data.get("mode") != mode:
            continue
        count += 1
    return count


def first_planning_mode(events: list[WorkflowEvent]) -> str | None:
    for event in events:
        if event.type != "plan_started":
            continue
        mode = event.data.get("mode")
        if mode in {"greenfield", "adopt_existing"}:
            return str(mode)
    return None


def _json_scalar_or_list(value: Any) -> bool:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(_json_scalar_or_list(item) for item in value)
    return False

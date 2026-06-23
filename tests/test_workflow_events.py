from __future__ import annotations

import json
from pathlib import Path

from devlab.workflow_events import (
    WORKFLOW_EVENTS,
    append_workflow_event,
    count_events,
    first_planning_mode,
    load_workflow_events,
)


def test_append_and_load_workflow_events(tmp_path: Path) -> None:
    append_workflow_event(tmp_path, "plan_started", mode="adopt_existing", generation=1)
    append_workflow_event(tmp_path, "plan_completed", mode="adopt_existing", generation=1)

    events = load_workflow_events(tmp_path)

    assert [event.type for event in events] == ["plan_started", "plan_completed"]
    assert events[0].data["mode"] == "adopt_existing"
    assert count_events(events, "plan_started", mode="adopt_existing") == 1
    assert first_planning_mode(events) == "adopt_existing"


def test_load_workflow_events_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / WORKFLOW_EVENTS
    path.parent.mkdir(parents=True)
    path.write_text(
        "{not-json}\n"
        + json.dumps({"version": 2, "type": "future", "at": "now"})
        + "\n"
        + json.dumps(
            {
                "version": 1,
                "type": "plan_started",
                "at": "2026-06-23T00:00:00+00:00",
                "mode": "greenfield",
            }
        )
        + "\n"
    )

    events = load_workflow_events(tmp_path)

    assert len(events) == 1
    assert events[0].type == "plan_started"
    assert events[0].data["mode"] == "greenfield"

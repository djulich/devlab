from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from devlab.clarifications import FileClarificationTracker
from devlab.init import init_workspace
from devlab.workflow_diagnostics import (
    build_workflow_diagnostics,
    format_workflow_diagnostics,
)
from devlab.workflow_events import append_workflow_event


def test_diagnostics_count_clarification_stops_by_role(tmp_path: Path) -> None:
    _init_workspace(tmp_path)
    _create_clarification(tmp_path, session_id="s1", role="planner", scope="planning")
    _create_clarification(tmp_path, session_id="s2", role="developer", scope="task:T0001")
    append_workflow_event(tmp_path, "clarification_requested", role="planner")
    append_workflow_event(tmp_path, "clarification_requested", role="developer")
    append_workflow_event(tmp_path, "clarification_requested", role="developer")

    diagnostics = build_workflow_diagnostics(tmp_path)

    assert diagnostics.clarifications.stops_total == 3
    assert diagnostics.clarifications.stops_by_role == {
        "developer": 2,
        "planner": 1,
    }
    assert diagnostics.clarifications.pending == 2
    assert "developer" in diagnostics.clarifications.repeated_roles
    assert "repeated clarification requests by role: developer" in (
        diagnostics.quality.warnings
    )


def test_diagnostics_report_clarification_answer_latency(tmp_path: Path) -> None:
    _init_workspace(tmp_path)
    tracker = FileClarificationTracker(tmp_path)
    clarification = tracker.create(
        title="Auth session timeout",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="text",
        body=_text_body(),
        created_at="2026-07-07T10:00:00Z",
    )
    tracker.answer(
        clarification.id,
        "Use 24h.",
        answered_at="2026-07-07T10:05:00Z",
    )

    diagnostics = build_workflow_diagnostics(tmp_path)

    assert diagnostics.clarifications.answered == 1
    assert diagnostics.clarifications.answered_latency_seconds_avg == 300


def test_diagnostics_warn_on_repeated_clarification_scope(tmp_path: Path) -> None:
    _init_workspace(tmp_path)
    _create_clarification(tmp_path, session_id="s1", role="planner", scope="planning")
    _create_clarification(tmp_path, session_id="s2", role="planner", scope="planning")

    diagnostics = build_workflow_diagnostics(tmp_path)

    assert diagnostics.clarifications.repeated_scopes == ["planning"]
    assert "repeated clarification requests for scope: planning" in (
        diagnostics.quality.warnings
    )


def test_diagnostics_text_reports_clarification_summary(tmp_path: Path) -> None:
    _init_workspace(tmp_path)
    _create_clarification(tmp_path, session_id="s1", role="planner", scope="planning")
    append_workflow_event(
        tmp_path,
        "clarification_requested",
        role="planner",
        at=datetime(2026, 7, 7, 10, 0, tzinfo=UTC),
    )

    output = format_workflow_diagnostics(tmp_path, verbose=True)

    assert "Clarifications: 1 stops, 1 pending, 0 answered" in output
    assert "Clarifications:\n- stops: 1" in output


def _create_clarification(
    root: Path,
    *,
    session_id: str,
    role: str,
    scope: str,
) -> str:
    clarification = FileClarificationTracker(root).create(
        title="Auth session timeout",
        asking_role=role,
        session_id=session_id,
        scope=scope,
        blocks="planning" if scope == "planning" else scope,
        answer_shape="text",
        body=_text_body(),
    )
    return clarification.id


def _init_workspace(root: Path) -> None:
    init_workspace(
        root,
        automatic_git=True,
        git_user_name="DevLab Test",
        git_user_email="devlab-test@example.invalid",
    )


def _text_body() -> str:
    return (
        "# Auth session timeout\n\n"
        "## Context\nC\n\n"
        "## Question\nQ\n\n"
        "## Expected Answer\nA\n"
    )

from __future__ import annotations

import json
from pathlib import Path

from devlab.history import format_history, load_session_metadata
from devlab.workspace import AGENT_LOG_DIR


def _write_metadata(
    root: Path,
    invocation_id: str,
    *,
    session_number: int = 1,
    role_name: str = "developer",
    provider: str = "default",
    model: str = "test-model",
    provider_version: str = "test-provider 1.0",
    return_code: int = 0,
    failure_kind: str = "none",
    duration_seconds: float | None = 42.5,
    task_id: str = "",
) -> Path:
    log_dir = root / AGENT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{invocation_id}.metadata.json"
    path.write_text(
        json.dumps(
            {
                "invocation_id": invocation_id,
                "session_number": session_number,
                "role_name": role_name,
                "provider": provider,
                "model": model,
                "provider_version": provider_version,
                "return_code": return_code,
                "failure_kind": failure_kind,
                "duration_seconds": duration_seconds,
                "task_id": task_id,
            },
            indent=2,
        )
    )
    return path


class TestLoadSessionMetadata:
    def test_no_metadata_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / AGENT_LOG_DIR).mkdir(parents=True)
        assert load_session_metadata(tmp_path) == []

    def test_loads_single_metadata_file(self, tmp_path: Path) -> None:
        _write_metadata(tmp_path, "20260529T120000_001_developer", task_id="T0001")

        entries = load_session_metadata(tmp_path)

        assert len(entries) == 1
        assert entries[0].role_name == "developer"
        assert entries[0].task_id == "T0001"
        assert entries[0].duration_seconds == 42.5
        assert entries[0].provider_version == "test-provider 1.0"

    def test_sorted_by_session_number(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path,
            "20260529T120002_003_reviewer",
            session_number=3,
            role_name="reviewer",
        )
        _write_metadata(
            tmp_path,
            "20260529T120000_001_architect",
            session_number=1,
            role_name="architect",
        )
        _write_metadata(
            tmp_path,
            "20260529T120001_002_planner",
            session_number=2,
            role_name="planner",
        )

        entries = load_session_metadata(tmp_path)

        assert [e.role_name for e in entries] == ["architect", "planner", "reviewer"]

    def test_loads_metadata_without_provider_version(self, tmp_path: Path) -> None:
        path = _write_metadata(tmp_path, "20260529T120000_001_developer")
        data = json.loads(path.read_text())
        del data["provider_version"]
        path.write_text(json.dumps(data))

        entries = load_session_metadata(tmp_path)

        assert len(entries) == 1
        assert entries[0].provider_version == ""

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        log_dir = tmp_path / AGENT_LOG_DIR
        log_dir.mkdir(parents=True)
        (log_dir / "bad.metadata.json").write_text("not json")
        _write_metadata(tmp_path, "20260529T120000_001_developer")

        entries = load_session_metadata(tmp_path)

        assert len(entries) == 1


class TestFormatHistory:
    def test_no_metadata(self, tmp_path: Path) -> None:
        (tmp_path / AGENT_LOG_DIR).mkdir(parents=True)
        assert format_history(tmp_path) == "Session history: none"

    def test_successful_session(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path,
            "20260529T120000_001_developer",
            task_id="T0001",
            duration_seconds=98.7,
        )

        output = format_history(tmp_path)

        assert "Session history:" in output
        assert "developer" in output
        assert "ok" in output
        assert "test-provider 1.0" in output
        assert "T0001" in output
        assert "98.7s" in output

    def test_failed_session(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path,
            "20260529T120000_001_developer",
            return_code=1,
            failure_kind="timeout",
        )

        output = format_history(tmp_path)

        assert "FAILED" in output
        assert "timeout" in output

    def test_timeout_subtype_is_reported_when_present(self, tmp_path: Path) -> None:
        path = _write_metadata(
            tmp_path,
            "20260529T120000_001_developer",
            return_code=124,
            failure_kind="timeout",
        )
        data = json.loads(path.read_text())
        data["timeout_kind"] = "inactivity"
        path.write_text(json.dumps(data))

        assert "FAILED (inactivity)" in format_history(tmp_path)

    def test_json_output(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path,
            "20260529T120000_001_developer",
            task_id="T0001",
        )

        output = format_history(tmp_path, json_output=True)
        data = json.loads(output)

        assert len(data) == 1
        assert data[0]["role_name"] == "developer"
        assert data[0]["task_id"] == "T0001"
        assert data[0]["provider_version"] == "test-provider 1.0"
        assert data[0]["duration_seconds"] == 42.5

    def test_no_duration(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path,
            "20260529T120000_001_developer",
            duration_seconds=None,
        )

        output = format_history(tmp_path)

        assert "developer" in output
        assert "ok" in output


def test_history_orders_across_runs_by_invocation_not_session_number(tmp_path: Path) -> None:
    _write_metadata(tmp_path, "20260529T120000_010_reviewer", session_number=10)
    _write_metadata(tmp_path, "20260530T120000_001_developer", session_number=1)
    assert [entry.session_number for entry in load_session_metadata(tmp_path)] == [10, 1]


def test_history_skips_wrongly_typed_metadata(tmp_path: Path) -> None:
    path = _write_metadata(tmp_path, "20260529T120000_001_developer")
    data = json.loads(path.read_text())
    data["duration_seconds"] = "forty"
    path.write_text(json.dumps(data))
    assert load_session_metadata(tmp_path) == []


def test_latest_malformed_record_does_not_fall_back_to_old_success(tmp_path: Path) -> None:
    from devlab.history import describe_session

    _write_metadata(tmp_path, "20260529T120000_010_reviewer", session_number=10)
    path = _write_metadata(tmp_path, "20260530T120000_001_developer", session_number=1)
    path.write_text("invalid")
    output = describe_session(tmp_path)
    assert "20260530T120000_001_developer" in output
    assert "20260529T120000_010_reviewer" not in output
    assert "Provider outcome unavailable" in output


def test_history_keeps_provider_failure_when_teardown_was_last_phase(tmp_path: Path) -> None:
    path = _write_metadata(
        tmp_path, "20260529T120000_001_developer", return_code=124, failure_kind="timeout"
    )
    data = json.loads(path.read_text())
    data.update(
        timeout_kind="max_duration",
        lifecycle_phase="environment_teardown",
        lifecycle_stop_reason="agent_invocation: timeout",
    )
    path.write_text(json.dumps(data))
    assert "FAILED (max_duration)" in format_history(tmp_path)


def test_recovery_summary_explains_duration_timeout_before_evidence(tmp_path: Path) -> None:
    from devlab.history import describe_session

    invocation = "20260529T120000_001_developer"
    path = _write_metadata(
        tmp_path, invocation, task_id="T0003", return_code=124, failure_kind="timeout"
    )
    data = json.loads(path.read_text())
    data.update(
        timeout_kind="max_duration",
        max_session_duration_seconds=2400,
        inactive_seconds_at_stop=6.6,
    )
    path.write_text(json.dumps(data))
    output = describe_session(tmp_path, session_id=invocation, role="developer", task="T0003")
    summary = output.split("\n\n", 1)[0]
    assert summary.startswith("What happened: The developer session for T0003")
    assert "40-minute limit" in summary
    assert "6.6 seconds earlier" in summary
    assert "before its normal session commit" in summary
    assert "review the remaining work" in summary
    assert output.index("What happened:") < output.index("Related session:")


def test_recovery_summary_uses_failure_reason_not_last_phase(tmp_path: Path) -> None:
    from devlab.history import describe_session

    invocation = "20260529T120000_001_developer"
    path = _write_metadata(tmp_path, invocation, task_id="T0003")
    data = json.loads(path.read_text())
    data.update(
        lifecycle_phase="environment_teardown",
        lifecycle_stop_reason="handoff_validation: invalid result",
    )
    path.write_text(json.dumps(data))
    summary = describe_session(
        tmp_path, session_id=invocation, role="developer", task="T0003"
    ).split("\n\n", 1)[0]
    assert "agent finished successfully, but DevLab stopped while accepting its handoff" in summary
    assert "tearing down" not in summary


def test_recovery_summary_does_not_invent_reason_for_unrelated_edits(tmp_path: Path) -> None:
    from devlab.history import describe_session

    _write_metadata(tmp_path, "20260529T120000_001_developer", failure_kind="timeout")
    summary = describe_session(tmp_path).split("\n\n", 1)[0]
    assert "cannot be linked to these changes" in summary
    assert "normal session commit" not in summary


def test_recovery_summary_does_not_call_unknown_completion_a_failure(tmp_path: Path) -> None:
    from devlab.history import describe_session

    invocation = "20260529T120000_001_developer"
    _write_metadata(tmp_path, invocation, failure_kind="incomplete", return_code=-1)
    summary = describe_session(tmp_path, session_id=invocation, role="developer").split("\n\n", 1)[
        0
    ]
    assert "may still be running or may have been interrupted" in summary
    assert "normal session commit" not in summary


def test_narrow_history_stacks_fields_without_changing_json(tmp_path: Path) -> None:
    _write_metadata(tmp_path, "20260529T120000_001_developer", task_id="T0001")
    narrow = format_history(tmp_path, width=50)
    assert "  #1 developer" in narrow.splitlines()
    assert "    T0001" in narrow.splitlines()
    assert "    42.5s" in narrow.splitlines()
    assert max(map(len, narrow.splitlines())) <= 50
    assert format_history(tmp_path, json_output=True, width=50) == format_history(
        tmp_path, json_output=True
    )
    assert format_history(tmp_path, width=120) == format_history(tmp_path)

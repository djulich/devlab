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
    return_code: int = 0,
    failure_kind: str = "none",
    duration_seconds: float | None = 42.5,
    task_id: str = "",
) -> Path:
    log_dir = root / AGENT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{invocation_id}.metadata.json"
    path.write_text(json.dumps({
        "invocation_id": invocation_id,
        "session_number": session_number,
        "role_name": role_name,
        "provider": provider,
        "model": model,
        "return_code": return_code,
        "failure_kind": failure_kind,
        "duration_seconds": duration_seconds,
        "task_id": task_id,
    }, indent=2))
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

    def test_sorted_by_session_number(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path, "20260529T120002_003_reviewer",
            session_number=3, role_name="reviewer",
        )
        _write_metadata(
            tmp_path, "20260529T120000_001_architect",
            session_number=1, role_name="architect",
        )
        _write_metadata(
            tmp_path, "20260529T120001_002_planner",
            session_number=2, role_name="planner",
        )

        entries = load_session_metadata(tmp_path)

        assert [e.role_name for e in entries] == ["architect", "planner", "reviewer"]

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
            tmp_path, "20260529T120000_001_developer",
            task_id="T0001", duration_seconds=98.7,
        )

        output = format_history(tmp_path)

        assert "Session history:" in output
        assert "developer" in output
        assert "ok" in output
        assert "T0001" in output
        assert "98.7s" in output

    def test_failed_session(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path, "20260529T120000_001_developer",
            return_code=1, failure_kind="timeout",
        )

        output = format_history(tmp_path)

        assert "FAILED" in output
        assert "timeout" in output

    def test_json_output(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path, "20260529T120000_001_developer",
            task_id="T0001",
        )

        output = format_history(tmp_path, json_output=True)
        data = json.loads(output)

        assert len(data) == 1
        assert data[0]["role_name"] == "developer"
        assert data[0]["task_id"] == "T0001"
        assert data[0]["duration_seconds"] == 42.5

    def test_no_duration(self, tmp_path: Path) -> None:
        _write_metadata(
            tmp_path, "20260529T120000_001_developer",
            duration_seconds=None,
        )

        output = format_history(tmp_path)

        assert "developer" in output
        assert "ok" in output

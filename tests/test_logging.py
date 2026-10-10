from __future__ import annotations

import io
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from devlab._logging import configure_logging, logger


def test_heartbeat_tracks_output_per_interval_without_resetting_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import devlab._logging as reporting

    now = 0.0
    monkeypatch.setattr(reporting, "time", SimpleNamespace(monotonic=lambda: now))
    stream = io.StringIO()
    configure_logging(logging.INFO, stream=stream)
    heartbeat = reporting.OutputHeartbeat("Validation T0001: command 1/2")
    now = 59
    heartbeat.observe_output()
    heartbeat.report_if_due()
    assert stream.getvalue() == ""
    now = 60
    heartbeat.report_if_due()
    assert "running for 60s; output received since last heartbeat" in stream.getvalue()
    now = 120
    heartbeat.report_if_due()
    assert "running for 120s; no output for 61s" in stream.getvalue()
    now = 121
    heartbeat.report_if_due()
    assert len(stream.getvalue().splitlines()) == 2


@pytest.mark.parametrize(
    "interval, level, expected",
    [(0, logging.INFO, False), (120, logging.INFO, True), (60, logging.WARNING, False)],
)
def test_heartbeat_configuration_and_quiet(
    monkeypatch: pytest.MonkeyPatch, interval: int, level: int, expected: bool
) -> None:
    import devlab._logging as reporting

    now = 0.0
    monkeypatch.setattr(reporting, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(reporting, "_heartbeat_interval_seconds", 60)
    stream = io.StringIO()
    configure_logging(level, stream=stream, heartbeat_interval_seconds=interval)
    heartbeat = reporting.OutputHeartbeat("Provider developer")
    now = 60
    heartbeat.report_if_due()
    assert stream.getvalue() == ""
    now = 120
    heartbeat.report_if_due()
    assert bool(stream.getvalue()) is expected
    logger.warning("completion still visible")
    assert "completion still visible" in stream.getvalue()


def test_configure_logging_info_emits_info_not_debug() -> None:
    stream = io.StringIO()

    configure_logging(logging.INFO, stream=stream)
    logger.info("hello")
    logger.debug("hidden")

    assert "hello" in stream.getvalue()
    assert "hidden" not in stream.getvalue()


def test_configure_logging_quiet_suppresses_info_but_emits_error() -> None:
    stream = io.StringIO()

    configure_logging(logging.WARNING, stream=stream)
    logger.info("hidden")
    logger.error("boom")

    assert "boom" in stream.getvalue()
    assert "hidden" not in stream.getvalue()


def test_configure_logging_debug_includes_level() -> None:
    stream = io.StringIO()

    configure_logging(logging.DEBUG, stream=stream)
    logger.debug("details")

    output = stream.getvalue()
    assert "DEBUG" in output
    assert "details" in output


def test_configure_logging_file_captures_debug_and_creates_parent(tmp_path: Path) -> None:
    stream = io.StringIO()
    log_file = tmp_path / "logs/devlab.log"

    configure_logging(logging.WARNING, log_file, stream=stream)
    logger.debug("file detail")
    logger.info("file info")

    assert stream.getvalue() == ""
    text = log_file.read_text()
    assert "DEBUG file detail" in text
    assert "INFO  file info" in text


def test_configure_logging_replaces_owned_handlers_without_duplicates() -> None:
    first = io.StringIO()
    second = io.StringIO()

    configure_logging(logging.INFO, stream=first)
    configure_logging(logging.INFO, stream=second)
    logger.info("once")

    assert first.getvalue() == ""
    assert "once" in second.getvalue()

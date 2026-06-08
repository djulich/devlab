from __future__ import annotations

import io
import logging
from pathlib import Path

from devlab._logging import configure_logging, logger


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

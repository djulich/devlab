from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TextIO

from devlab._console import console_width, wrap_prose

logger = logging.getLogger("devlab")

_DEVLAB_OWNED = "_devlab_owned"


def configure_logging(
    level: int,
    log_file: Path | None = None,
    *,
    stream: TextIO | None = None,
) -> None:
    """Configure DevLab CLI logging.

    Library callers may skip this function and configure ``logging.getLogger("devlab")``
    themselves. Repeated calls replace only handlers installed by this function.
    """
    for handler in list(logger.handlers):
        if getattr(handler, _DEVLAB_OWNED, False):
            logger.removeHandler(handler)
            handler.close()

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    console = logging.StreamHandler(stream or sys.stderr)
    console.setLevel(level)
    console.setFormatter(_ConsoleFormatter(level, console.stream))
    setattr(console, _DEVLAB_OWNED, True)
    logger.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s"))
        setattr(file_handler, _DEVLAB_OWNED, True)
        logger.addHandler(file_handler)


class _ConsoleFormatter(logging.Formatter):
    def __init__(self, level: int, stream: TextIO) -> None:
        super().__init__(datefmt="%H:%M")
        self.verbose = level <= logging.DEBUG
        self.stream = stream

    def format(self, record: logging.LogRecord) -> str:
        prefix = self.formatTime(record, self.datefmt) + " "
        if self.verbose:
            prefix += record.levelname + ": "
        message = record.getMessage()
        # Debug records and explicitly literal records are diagnostic evidence.
        # Existing multiline bodies (including tracebacks) retain their layout.
        first, separator, rest = message.partition("\n")
        if (
            not first
            or record.levelno <= logging.DEBUG
            or getattr(record, "console_literal", False)
        ):
            result = prefix + message
        else:
            result = (
                wrap_prose(
                    first,
                    console_width(self.stream),
                    indent=prefix,
                    continuation=" " * len(prefix),
                )
                + separator
                + rest
            )
        if record.exc_info:
            result += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            result += "\n" + self.formatStack(record.stack_info)
        return result

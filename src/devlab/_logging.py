from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TextIO

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
    console.setFormatter(_console_formatter(level))
    setattr(console, _DEVLAB_OWNED, True)
    logger.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(message)s")
        )
        setattr(file_handler, _DEVLAB_OWNED, True)
        logger.addHandler(file_handler)


def _console_formatter(level: int) -> logging.Formatter:
    if level <= logging.DEBUG:
        return logging.Formatter("%(levelname)s: %(message)s")
    return logging.Formatter("%(message)s")

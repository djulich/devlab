from __future__ import annotations

import argparse
import os
import re
import sys
import textwrap
from typing import NoReturn, TextIO


def console_width(stream: TextIO) -> int | None:
    """Resolve the destination terminal's width; redirected output is unwrapped."""
    if not stream.isatty():
        return None
    try:
        columns = int(os.environ.get("COLUMNS", "0"))
    except ValueError:
        columns = 0
    if columns <= 0:
        try:
            columns = os.get_terminal_size(stream.fileno()).columns
        except (OSError, ValueError):
            columns = 80
    return columns if columns > 0 else 80


def wrap_prose(
    text: str,
    width: int | None = None,
    *,
    indent: str = "",
    continuation: str | None = None,
) -> str:
    """Wrap explicitly selected prose, retaining paragraphs and hanging list indents.

    None leaves text unwrapped. Literal commands, evidence, and file contents
    must bypass this function, including when embedded in a larger report.
    """
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        if width is None:
            lines.append(indent + paragraph)
            continue
        match = re.match(r"^(\s*)(?:(?:[-*+] |\d+[.)] ))?", paragraph)
        assert match is not None
        prefix = match.group()
        following = continuation if continuation is not None else indent + " " * len(prefix)
        lines.append(
            textwrap.fill(
                paragraph[len(prefix) :],
                width=max(1, width),
                initial_indent=indent + prefix,
                subsequent_indent=following,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(lines)


def print_prose(text: str, *, file: TextIO | None = None, flush: bool = False) -> None:
    """Print a DevLab-authored prose message to its destination stream."""
    stream = sys.stdout if file is None else file
    print(wrap_prose(text, console_width(stream)), file=stream, flush=flush)


class ConsoleArgumentParser(argparse.ArgumentParser):
    """Use the output destination's width for argparse help and error prose."""

    def _get_formatter(self) -> argparse.HelpFormatter:
        return argparse.HelpFormatter(
            prog=self.prog, width=console_width(sys.stdout) or sys.maxsize
        )

    def error(self, message: str) -> NoReturn:
        formatter = argparse.HelpFormatter(
            prog=self.prog, width=console_width(sys.stderr) or sys.maxsize
        )
        formatter.add_usage(self.usage, self._actions, self._mutually_exclusive_groups)
        self._print_message(formatter.format_help(), sys.stderr)
        self.exit(
            2, wrap_prose(f"{self.prog}: error: {message}", console_width(sys.stderr)) + "\n"
        )

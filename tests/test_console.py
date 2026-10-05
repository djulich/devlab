from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path

import pytest

from devlab._console import ConsoleArgumentParser, console_width, wrap_prose
from devlab._logging import configure_logging, logger
from devlab.clarification_ops import format_clarification_list
from devlab.clarifications import FileClarificationTracker
from devlab.cli import main
from devlab.doctor import format_doctor_report
from devlab.doctor_common import DoctorProblem
from devlab.executable_config import build_executable_config_snapshot, format_executable_config
from devlab.init import format_init_next_steps, init_workspace
from devlab.prerequisites import (
    Prerequisite,
    PrerequisiteOperation,
    PrerequisiteResult,
    PrerequisiteStatus,
    format_prerequisite_result,
)
from devlab.workflow_state_report import build_workflow_state_report, format_workflow_state_report
from devlab.workspace import WorkspaceCompatibilityError


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 42


@pytest.mark.parametrize("columns", [50, 80, 120, None])
def test_width_uses_destination_terminal_or_fallback(
    monkeypatch: pytest.MonkeyPatch, columns: int | None
) -> None:
    monkeypatch.delenv("COLUMNS", raising=False)

    def terminal_size(fd: int) -> os.terminal_size:
        assert fd == 42
        if columns is None:
            raise OSError("No size available")
        return os.terminal_size((columns, 24))

    monkeypatch.setattr(os, "get_terminal_size", terminal_size)
    assert console_width(Terminal()) == (columns or 80)
    assert console_width(io.StringIO()) is None


@pytest.mark.parametrize("value, expected", [("55", 55), ("0", 80), ("-1", 80), ("bad", 80)])
def test_columns_override_only_applies_to_terminals(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int
) -> None:
    monkeypatch.setenv("COLUMNS", value)
    assert console_width(Terminal()) == expected
    assert console_width(io.StringIO()) is None


@pytest.mark.parametrize("width", [50, 80, 120])
def test_prose_retains_paragraphs_list_indents_and_long_tokens(width: int) -> None:
    text = "  12. " + "An explanatory sentence with several words. " * 8
    text += "\n\n- " + "Another warning for the operator. " * 8
    result = wrap_prose(text, width)
    first, second = result.split("\n\n")
    assert all(line.startswith("      ") for line in first.splitlines()[1:])
    assert all(line.startswith("  ") for line in second.splitlines()[1:])
    assert max(map(len, result.splitlines())) <= width
    token = "path-" * 40
    assert token in wrap_prose("Inspect " + token, width).splitlines()
    assert wrap_prose(text) == text


@pytest.mark.parametrize("width", [50, 80, 120])
def test_reports_wrap_prose_and_keep_init_commands_literal(tmp_path: Path, width: int) -> None:
    message = "The workspace needs operator attention before another session can run. " * 4
    doctor = format_doctor_report([DoctorProblem(".devlab", message)], width=width)
    assert max(map(len, doctor.splitlines())) <= width
    assert all(line.startswith("  ") for line in doctor.splitlines()[2:])
    assert message in format_doctor_report([DoctorProblem(".devlab", message)])
    status = format_workflow_state_report(build_workflow_state_report(tmp_path), width=width)
    assert max(map(len, status.splitlines())) <= width
    steps = format_init_next_steps(width=width)
    assert '       git commit -m "Configure DevLab project"' in steps.splitlines()
    assert max(map(len, steps.splitlines())) <= width


def test_prerequisite_commands_paths_and_guide_are_verbatim(tmp_path: Path) -> None:
    guide = "# Setup\n\n" + "Guide prose stays raw. " * 10 + "\n\n```sh\nprintf 'some text'\n```"
    (tmp_path / "guide with spaces.md").write_text(guide)
    command = "printf '" + "literal shell argument with spaces " * 8 + "'"
    item = Prerequisite(
        "api",
        "service",
        (PrerequisiteOperation.SESSION,),
        "Service description. " * 20,
        check=command,
        guide="guide with spaces.md",
    )
    result = PrerequisiteResult(item, PrerequisiteStatus.UNSATISFIED, "Needs setup. " * 20)
    report = format_prerequisite_result(tmp_path, result, width=50)
    assert "Check: " + command in report.splitlines()
    assert f"Guide: {tmp_path / 'guide with spaces.md'}" in report.splitlines()
    assert guide in report
    prose = report.split("Check:", 1)[0]
    assert max(map(len, prose.splitlines())) <= 50


def test_trust_keeps_configuration_evidence_literal(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    snapshot = build_executable_config_snapshot(tmp_path)
    original = format_executable_config(snapshot)
    narrow = format_executable_config(snapshot, width=50)
    for line in original.splitlines():
        if line.startswith(("Workspace:", "Agent config:", "Fingerprint:", "- ", "  ")):
            assert line in narrow.splitlines()
    assert max(map(len, narrow.split("\n\nProvider permission", 1)[1].splitlines())) <= 50


def test_clarification_list_uses_stacked_fields_on_narrow_terminal(tmp_path: Path) -> None:
    item = FileClarificationTracker(tmp_path).create(
        title="Choose how the system handles unavailable dependencies and delayed responses",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="text",
        body="## Question\nWhich behavior is intended?",
    )
    narrow = format_clarification_list([item], width=50)
    assert "  Status: pending" in narrow
    assert "  Blocks: planning" in narrow
    assert max(map(len, narrow.splitlines())) <= 50
    assert format_clarification_list([item]).startswith("ID      Status")


def test_cli_uses_stdout_width_but_json_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COLUMNS", "30")
    terminal = Terminal()
    monkeypatch.setattr("sys.stdout", terminal)
    monkeypatch.setattr("sys.argv", ["devlab", "status", "--root", str(tmp_path)])
    main()
    assert max(map(len, terminal.getvalue().splitlines())) <= 30
    monkeypatch.setattr("sys.argv", ["devlab", "status", "--json", "--root", str(tmp_path)])
    terminal.seek(0)
    terminal.truncate()
    main()
    interactive = terminal.getvalue()
    assert isinstance(json.loads(interactive), dict)
    pipe = io.StringIO()
    monkeypatch.setattr("sys.stdout", pipe)
    main()
    assert pipe.getvalue() == interactive


def test_cli_errors_use_stderr_width_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    from devlab import cli

    message = "There is an explanatory problem with the configuration. " * 8

    def fail() -> None:
        raise WorkspaceCompatibilityError(message)

    monkeypatch.setattr(cli, "_main", fail)
    monkeypatch.setenv("COLUMNS", "50")
    stream = Terminal()
    monkeypatch.setattr("sys.stdout", io.StringIO())
    monkeypatch.setattr("sys.stderr", stream)
    with pytest.raises(SystemExit):
        cli.main()
    assert max(map(len, stream.getvalue().splitlines())) <= 50
    pipe = io.StringIO()
    monkeypatch.setattr("sys.stderr", pipe)
    with pytest.raises(SystemExit):
        cli.main()
    assert message in pipe.getvalue()


@pytest.mark.parametrize("verbose", [False, True])
def test_console_log_wraps_with_prefix_but_file_and_evidence_stay_raw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, verbose: bool
) -> None:
    monkeypatch.setenv("COLUMNS", "50")
    stream = Terminal()
    log_file = tmp_path / "devlab.log"
    configure_logging(logging.DEBUG if verbose else logging.INFO, log_file, stream=stream)
    message = "An explanatory progress message. " * 8
    logger.info(message)
    lines = stream.getvalue().splitlines()
    assert max(map(len, lines)) <= 50
    assert all(line.startswith(" " * (12 if verbose else 6)) for line in lines[1:])
    assert message in log_file.read_text()
    literal = "printf '" + "a command argument " * 10 + "'"
    logger.info(literal, extra={"console_literal": True})
    assert literal in stream.getvalue()
    logger.error("Command failed:\n%s", literal)
    assert literal in stream.getvalue().splitlines()


def test_doctor_keeps_long_paths_with_spaces_intact() -> None:
    path = "a directory with spaces/" * 5 + "config.toml"
    report = format_doctor_report([DoctorProblem(path, "An explanatory warning. " * 8)], width=50)
    assert f"- {path}:" in report.splitlines()
    assert all(len(line) <= 50 for line in report.splitlines() if path not in line)


def test_cli_raw_clarification_file_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item = FileClarificationTracker(tmp_path).create(
        title="Choose behavior",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="text",
        body="## Question\n" + "Raw question text. " * 20 + "\n\n```sh\necho 'a b c'\n```",
    )
    stream = Terminal()
    monkeypatch.setenv("COLUMNS", "30")
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr(
        "sys.argv", ["devlab", "clarify", "--root", str(tmp_path), "show", item.id]
    )
    main()
    assert stream.getvalue() == item.path.read_text()


def test_help_and_parser_errors_use_their_own_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    description = "An explanation of how to invoke this command. " * 8
    parser = ConsoleArgumentParser(prog="devlab", description=description)
    parser.add_subparsers().add_parser("example", description=description)
    monkeypatch.setenv("COLUMNS", "50")
    terminal = Terminal()
    pipe = io.StringIO()
    monkeypatch.setattr("sys.stdout", terminal)
    monkeypatch.setattr("sys.stderr", pipe)
    parser.print_help()
    assert max(map(len, terminal.getvalue().splitlines())) <= 50
    with pytest.raises(SystemExit):
        parser.parse_args(["example", "--help"])
    assert max(map(len, terminal.getvalue().splitlines())) <= 50
    with pytest.raises(SystemExit):
        parser.error(description)
    assert description in pipe.getvalue()
    monkeypatch.setattr("sys.stdout", pipe)
    monkeypatch.setattr("sys.stderr", terminal)
    terminal.seek(0)
    terminal.truncate()
    with pytest.raises(SystemExit):
        parser.error(description)
    assert max(map(len, terminal.getvalue().splitlines())) <= 50
    assert description.strip() in parser.format_help()

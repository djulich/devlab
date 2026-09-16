from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from devlab.agents import (
    AgentInvocation,
    AgentResult,
    CliAgentProvider,
    MockProvider,
    _expired_timeout_kind,
    claude_cli_provider,
    codex_cli_provider,
    pi_cli_provider,
    provider_for_role,
)


def _invocation(
    root: Path,
    role_name: str = "developer",
    system_prompt: str = "system",
    session_prompt: str = "session",
) -> AgentInvocation:
    return AgentInvocation(
        root=root,
        role_name=role_name,
        system_prompt=system_prompt,
        session_prompt=session_prompt,
        invocation_id="test-invocation",
        stdout_log=root / ".devlab/logs/agents/test.stdout.log",
        stderr_log=root / ".devlab/logs/agents/test.stderr.log",
    )


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.calls.append(invocation.role_name)
        return AgentResult(return_code=0)


def test_provider_for_role_uses_default_provider() -> None:
    default = RecordingProvider()

    provider = provider_for_role("developer", {"default": default})

    assert provider is default


def test_provider_for_role_uses_role_specific_provider() -> None:
    default = RecordingProvider()
    reviewer = RecordingProvider()

    provider = provider_for_role(
        "reviewer",
        {"default": default, "reviewer-provider": reviewer},
        {"reviewer": "reviewer-provider"},
    )

    assert provider is reviewer


def test_provider_for_role_rejects_unknown_provider() -> None:
    with pytest.raises(KeyError, match="unknown agent provider"):
        provider_for_role("reviewer", {"default": RecordingProvider()}, {"reviewer": "missing"})


def test_mock_provider_records_calls_and_writes_valid_handoff(tmp_path: Path) -> None:
    provider = MockProvider()

    result = provider.invoke(_invocation(tmp_path, "developer", "system", "session"))

    assert result.return_code == 0
    assert provider.calls[0].role_name == "developer"
    assert provider.calls[0].system_prompt == "system"
    handoff = tmp_path / ".devlab/session-artifacts" / "developer" / "handoff.md"
    assert "## Open Issues" in handoff.read_text()


def test_mock_provider_supports_callable_handoff_text(tmp_path: Path) -> None:
    provider = MockProvider(handoff_text=lambda call: f"handoff for {call.role_name}")

    provider.invoke(_invocation(tmp_path, "reviewer", "", ""))

    handoff = tmp_path / ".devlab/session-artifacts" / "reviewer" / "handoff.md"
    assert handoff.read_text() == "handoff for reviewer"


def test_cli_agent_provider_renders_prompt_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))

        class Result:
            returncode = 7

        return Result()

    monkeypatch.setattr("devlab.agents._run_process", fake_run)
    provider = CliAgentProvider.from_command(
        "pi -p",
        args=[
            "--no-context-files",
            "--system-prompt",
            "{system_prompt}",
            "{session_prompt}",
        ],
    )

    result = provider.invoke(_invocation(tmp_path, "developer", "system", "session"))

    assert result.return_code == 7
    assert result.failure_kind == "nonzero_exit"
    assert result.command == (
        "pi",
        "-p",
        "--no-context-files",
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
    )
    args, kwargs = calls[0]
    assert args[0] == [
        "pi",
        "-p",
        "--no-context-files",
        "--system-prompt",
        "system",
        "session",
    ]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["stdout"].name.endswith("stdout.log")
    assert kwargs["stderr"].name.endswith("stderr.log")


def test_pi_cli_provider_uses_pi_print_command(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = pi_cli_provider(args=["--no-context-files"])

    assert provider.argv == ("pi", "-p")
    assert provider.args == (
        "--no-context-files",
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
    )


def test_claude_cli_provider_uses_prompt_args() -> None:
    provider = claude_cli_provider()

    assert provider.argv == ("claude", "-p")
    assert provider.args == (
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
    )


def test_cli_agent_provider_supports_stdin_prompt_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents._run_process", fake_run)
    provider = CliAgentProvider.from_command(
        "agent run",
        args=["--role", "{role_name}"],
        stdin_template="{system_prompt}\n---\n{session_prompt}",
    )

    provider.invoke(_invocation(tmp_path, "reviewer", "system", "session"))

    args, kwargs = calls[0]
    assert args[0] == ["agent", "run", "--role", "reviewer"]
    assert kwargs["input"] == "system\n---\nsession"
    assert kwargs["text"] is True


def test_codex_cli_provider_uses_exec_stdin_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents._run_process", fake_run)
    provider = codex_cli_provider()

    provider.invoke(_invocation(tmp_path, "reviewer", "system", "session"))

    args, kwargs = calls[0]
    assert args[0] == ["codex", "exec", "-"]
    assert kwargs["input"] == "system\n\n---\n\nsession"
    assert kwargs["text"] is True


def test_cli_agent_provider_returns_timeout_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> object:
        raise subprocess.TimeoutExpired(cmd=["agent"], timeout=5)

    monkeypatch.setattr("devlab.agents._run_process", fake_run)
    provider = CliAgentProvider.from_command("agent", max_session_duration_seconds=5)

    result = provider.invoke(_invocation(tmp_path))

    assert result.return_code == 124
    assert result.failure_kind == "timeout"
    assert "maximum duration" in (tmp_path / ".devlab/logs/agents/test.stderr.log").read_text()


def test_maximum_duration_adds_trusted_deadline_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> object:
        commands.append(command)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents._run_process", fake_run)
    provider = CliAgentProvider.from_command(
        "agent",
        args=("{session_prompt}",),
        max_session_duration_seconds=30,
    )

    provider.invoke(_invocation(tmp_path))

    assert "Maximum provider duration: 30 seconds" in commands[0][-1]
    assert "Advisory wall-clock deadline:" in commands[0][-1]


def test_direct_provider_uses_maximum_duration_consistently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        calls.append((command, kwargs))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents._run_process", fake_run)
    provider = CliAgentProvider(
        argv=("agent",),
        args=("{session_prompt}",),
        max_session_duration_seconds=30,
    )

    result = provider.invoke(_invocation(tmp_path))

    command, kwargs = calls[0]
    assert kwargs["timeout"] == 30
    assert "Maximum provider duration: 30 seconds" in command[-1]
    assert result.max_session_duration_seconds == 30


def test_direct_provider_enforces_max_session_duration(tmp_path: Path) -> None:
    provider = CliAgentProvider(
        argv=(sys.executable,),
        args=("-c", "import time; time.sleep(5)"),
        max_session_duration_seconds=1,
    )

    result = provider.invoke(_invocation(tmp_path))

    assert result.failure_kind == "timeout"
    assert result.timeout_kind == "max_duration"
    assert result.max_session_duration_seconds == 1
    assert "maximum duration of 1 seconds reached" in result.message


def test_cli_agent_provider_returns_missing_executable_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> object:
        raise FileNotFoundError("missing", "missing", "agent")

    monkeypatch.setattr("devlab.agents._run_process", fake_run)
    provider = CliAgentProvider.from_command("agent")

    result = provider.invoke(_invocation(tmp_path))

    assert result.return_code == 127
    assert result.failure_kind == "missing_executable"
    assert "not found" in result.message
    assert "not found" in (tmp_path / ".devlab/logs/agents/test.stderr.log").read_text()


def test_cli_agent_provider_stops_silent_process_for_inactivity(tmp_path: Path) -> None:
    provider = CliAgentProvider.from_command(
        sys.executable,
        args=("-c", "import time; time.sleep(5)"),
        inactivity_timeout_seconds=1,
        max_session_duration_seconds=4,
    )

    result = provider.invoke(_invocation(tmp_path))

    assert result.return_code == 124
    assert result.failure_kind == "timeout"
    assert result.timeout_kind == "inactivity"
    assert result.inactivity_timeout_seconds == 1
    assert result.max_session_duration_seconds == 4
    assert result.inactive_seconds_at_stop is not None
    assert result.inactive_seconds_at_stop >= 1


def test_partial_binary_output_resets_inactivity_until_maximum(tmp_path: Path) -> None:
    script = (
        "import os,time\n"
        "for _ in range(5):\n"
        " os.write(2, b'\\xff'); time.sleep(.35)\n"
        "time.sleep(5)\n"
    )
    provider = CliAgentProvider.from_command(
        sys.executable,
        args=("-c", script),
        inactivity_timeout_seconds=1,
        max_session_duration_seconds=2,
    )

    result = provider.invoke(_invocation(tmp_path))

    assert result.timeout_kind == "max_duration"
    assert (
        (tmp_path / ".devlab/logs/agents/test.stderr.log")
        .read_bytes()
        .startswith(b"\xff\xff\xff\xff\xff")
    )


def test_stream_eof_does_not_stop_monitoring_other_stream(tmp_path: Path) -> None:
    script = "import os,time; os.close(1); time.sleep(.2); os.write(2,b'partial'); time.sleep(.2)"
    provider = CliAgentProvider.from_command(
        sys.executable,
        args=("-c", script),
        inactivity_timeout_seconds=1,
        max_session_duration_seconds=3,
    )

    result = provider.invoke(_invocation(tmp_path))

    assert result.succeeded
    assert (tmp_path / ".devlab/logs/agents/test.stderr.log").read_bytes() == b"partial"


def test_large_stdin_and_output_do_not_deadlock(tmp_path: Path) -> None:
    script = "import sys; data=sys.stdin.buffer.read(); sys.stdout.write(str(len(data)))"
    provider = CliAgentProvider.from_command(
        sys.executable,
        args=("-c", script),
        stdin_template="{system_prompt}{session_prompt}",
        max_session_duration_seconds=3,
    )
    invocation = _invocation(
        tmp_path,
        system_prompt="s" * 500_000,
        session_prompt="p" * 500_000,
    )

    result = provider.invoke(invocation)

    assert result.succeeded
    # The trusted maximum-duration context is appended to the delivered prompt.
    assert int(invocation.stdout_log.read_text()) > 1_000_000


@pytest.mark.skipif(os.name != "posix", reason="process-group cleanup is POSIX-specific")
def test_timeout_kills_child_that_ignores_graceful_termination(tmp_path: Path) -> None:
    survived = tmp_path / "child-survived"
    child_script = (
        "import pathlib,signal,time; "
        "signal.signal(signal.SIGTERM, lambda *_: None); "
        "print('ready', flush=True); time.sleep(2.7); "
        f"pathlib.Path({str(survived)!r}).write_text('survived')"
    )
    parent_script = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_script!r}]); "
        "time.sleep(30)"
    )
    provider = CliAgentProvider.from_command(
        sys.executable,
        args=("-c", parent_script),
        max_session_duration_seconds=1,
    )

    result = provider.invoke(_invocation(tmp_path))
    time.sleep(1.5)

    assert result.timeout_kind == "max_duration"
    assert not survived.exists()


def test_output_capture_failure_cleans_up_and_returns_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_capture(_target: object, _chunk: bytes) -> None:
        raise OSError("capture failed")

    monkeypatch.setattr("devlab.agents._write_output", fail_capture)
    provider = CliAgentProvider.from_command(
        sys.executable,
        args=("-c", "import time; print('output', flush=True); time.sleep(30)"),
        max_session_duration_seconds=5,
    )

    result = provider.invoke(_invocation(tmp_path))

    assert result.failure_kind == "provider_error"
    assert "capture failed" in result.message
    assert result.duration_seconds is not None
    assert result.duration_seconds < 3


def test_deadline_decision_prefers_earlier_deadline_and_maximum_on_tie() -> None:
    assert (
        _expired_timeout_kind(
            12,
            started=0,
            last_output=5,
            inactivity_timeout_seconds=6,
            max_session_duration_seconds=20,
        )
        == "inactivity"
    )
    assert (
        _expired_timeout_kind(
            10,
            started=0,
            last_output=5,
            inactivity_timeout_seconds=5,
            max_session_duration_seconds=10,
        )
        == "max_duration"
    )

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from devlab.agents import (
    AgentInvocation,
    AgentResult,
    CliAgentProvider,
    MockProvider,
    claude_cli_provider,
    codex_cli_provider,
    pi_cli_provider,
    provider_for_role,
)


def _invocation(
    root: Path,
    role_name: str = "developer",
    base_prompt: str = "system",
    session_prompt: str = "session",
) -> AgentInvocation:
    return AgentInvocation(
        root=root,
        role_name=role_name,
        base_prompt=base_prompt,
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
    assert provider.calls[0].base_prompt == "system"
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

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)
    provider = CliAgentProvider.from_command(
        "pi -p",
        args=[
            "--no-context-files",
            "--system-prompt",
            "{base_prompt}",
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
        "{base_prompt}",
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
        "{base_prompt}",
        "{session_prompt}",
    )


def test_claude_cli_provider_uses_prompt_args() -> None:
    provider = claude_cli_provider()

    assert provider.argv == ("claude", "-p")
    assert provider.args == (
        "--system-prompt",
        "{base_prompt}",
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

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)
    provider = CliAgentProvider.from_command(
        "agent run",
        args=["--role", "{role_name}"],
        stdin_template="{base_prompt}\n---\n{session_prompt}",
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

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)
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

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)
    provider = CliAgentProvider.from_command("agent", timeout_seconds=5)

    result = provider.invoke(_invocation(tmp_path))

    assert result.return_code == 124
    assert result.failure_kind == "timeout"
    assert "timed out" in (tmp_path / ".devlab/logs/agents/test.stderr.log").read_text()


def test_cli_agent_provider_returns_missing_executable_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> object:
        raise FileNotFoundError("missing", "missing", "agent")

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)
    provider = CliAgentProvider.from_command("agent")

    result = provider.invoke(_invocation(tmp_path))

    assert result.return_code == 127
    assert result.failure_kind == "missing_executable"
    assert "not found" in result.message
    assert "not found" in (tmp_path / ".devlab/logs/agents/test.stderr.log").read_text()

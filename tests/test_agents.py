from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from harness.agents import (
    AgentResult,
    CliAgentProvider,
    MockProvider,
    claude_cli_provider,
    codex_cli_provider,
    pi_cli_provider,
    provider_for_role,
)


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(
        self,
        *,
        root: Path,
        role_name: str,
        system_prompt: str,
        session_prompt: str,
    ) -> AgentResult:
        self.calls.append(role_name)
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

    result = provider.invoke(
        root=tmp_path,
        role_name="developer",
        system_prompt="system",
        session_prompt="session",
    )

    assert result.return_code == 0
    assert provider.calls[0].role_name == "developer"
    assert provider.calls[0].system_prompt == "system"
    handoff = tmp_path / ".session-artifacts" / "developer" / "handoff.md"
    assert "## Open Issues" in handoff.read_text()


def test_mock_provider_supports_callable_handoff_text(tmp_path: Path) -> None:
    provider = MockProvider(handoff_text=lambda call: f"handoff for {call.role_name}")

    provider.invoke(root=tmp_path, role_name="reviewer", system_prompt="", session_prompt="")

    handoff = tmp_path / ".session-artifacts" / "reviewer" / "handoff.md"
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

    monkeypatch.setattr("harness.agents.subprocess.run", fake_run)
    provider = CliAgentProvider.from_command("pi -p", extra_args=["--no-context-files"])

    result = provider.invoke(
        root=tmp_path,
        role_name="developer",
        system_prompt="system",
        session_prompt="session",
    )

    assert result.return_code == 7
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


def test_pi_cli_provider_uses_pi_print_command(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = pi_cli_provider(extra_args=["--no-context-files"])

    assert provider.argv == ("pi", "-p")
    assert provider.extra_args == ("--no-context-files",)
    assert provider.prompt_args == ("--system-prompt", "{system_prompt}", "{session_prompt}")


def test_claude_cli_provider_adds_dangerous_skip_permissions() -> None:
    provider = claude_cli_provider(dangerous_skip_permissions=True)

    assert provider.argv == ("claude", "-p")
    assert provider.extra_args == ("--dangerously-skip-permissions",)


def test_cli_agent_provider_supports_stdin_prompt_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("harness.agents.subprocess.run", fake_run)
    provider = CliAgentProvider.from_command(
        "agent run",
        prompt_args=["--role", "{role_name}"],
        stdin_template="{system_prompt}\n---\n{session_prompt}",
    )

    provider.invoke(
        root=tmp_path,
        role_name="reviewer",
        system_prompt="system",
        session_prompt="session",
    )

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

    monkeypatch.setattr("harness.agents.subprocess.run", fake_run)
    provider = codex_cli_provider()

    provider.invoke(
        root=tmp_path,
        role_name="reviewer",
        system_prompt="system",
        session_prompt="session",
    )

    args, kwargs = calls[0]
    assert args[0] == ["codex", "exec", "-"]
    assert kwargs["input"] == "system\n\n---\n\nsession"
    assert kwargs["text"] is True

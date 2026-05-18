from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devlab.agent_config import format_resolved_agent_config, load_agent_configuration
from devlab.agents import AgentInvocation, CliAgentProvider


def test_missing_config_uses_fallback_cli_command(tmp_path: Path) -> None:
    config = load_agent_configuration(tmp_path)

    provider = config.providers[config.role_providers["developer"]]

    assert isinstance(provider, CliAgentProvider)
    assert provider.argv == ("claude", "-p")
    assert config.resolved["developer"].provider == "default"


def test_defaults_apply_to_all_roles(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "pi"
        model = "gpt-5-codex"
        effort = "medium"
        timeout_seconds = 120

        [providers.pi]
        command = "pi"
        args = ["-p", "--model", "{model}", "--effort", "{effort}"]
        """,
    )

    config = load_agent_configuration(tmp_path)

    assert config.resolved["developer"].provider == "pi"
    assert config.resolved["developer"].model == "gpt-5-codex"
    assert config.resolved["developer"].effort == "medium"
    assert config.resolved["developer"].timeout_seconds == 120
    assert config.resolved["developer"].command == (
        "pi",
        "-p",
        "--model",
        "gpt-5-codex",
        "--effort",
        "medium",
    )


def test_role_override_changes_one_role(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "pi"
        model = "gpt-5-codex"

        [roles.reviewer]
        provider = "claude"
        model = "claude-sonnet"
        effort = "high"

        [providers.pi]
        command = "pi"
        args = ["-p", "--model", "{model}"]

        [providers.claude]
        command = "claude"
        args = ["-p", "--model", "{model}", "--effort", "{effort}"]
        """,
    )

    config = load_agent_configuration(tmp_path)

    assert config.resolved["developer"].provider == "pi"
    assert config.resolved["reviewer"].provider == "claude"
    assert config.resolved["reviewer"].command == (
        "claude",
        "-p",
        "--model",
        "claude-sonnet",
        "--effort",
        "high",
    )


def test_cli_overrides_model_effort_and_provider(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "pi"
        model = "old"
        effort = "low"

        [providers.pi]
        command = "pi"
        args = ["--model", "{model}", "--effort", "{effort}"]

        [providers.claude]
        command = "claude"
        args = ["--model", "{model}", "--effort", "{effort}"]
        """,
    )

    config = load_agent_configuration(
        tmp_path,
        provider="claude",
        model="new-model",
        effort="high",
    )

    assert config.resolved["planner"].provider == "claude"
    assert config.resolved["planner"].command == (
        "claude",
        "--model",
        "new-model",
        "--effort",
        "high",
    )


def test_stdin_provider_is_configured(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "codex"
        model = "gpt-5-codex"

        [providers.codex]
        command = "codex"
        args = ["exec", "-", "--model", "{model}"]
        prompt_args = []
        stdin_template = "{system_prompt}\\n---\\n{session_prompt}"
        """,
    )

    config = load_agent_configuration(tmp_path)
    provider = config.providers[config.role_providers["developer"]]

    assert isinstance(provider, CliAgentProvider)
    assert provider.stdin_template == "{system_prompt}\n---\n{session_prompt}"
    assert config.resolved["developer"].uses_stdin is True


def test_unknown_provider_raises_clear_error(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "missing"
        """,
    )

    with pytest.raises(ValueError, match=r"providers\.missing must be a TOML table"):
        load_agent_configuration(tmp_path)


def test_format_resolved_agent_config_does_not_include_prompts(tmp_path: Path) -> None:
    config = load_agent_configuration(tmp_path)

    text = format_resolved_agent_config(config.resolved["developer"])

    assert 'role = "developer"' in text
    assert "command = " in text
    assert "system_prompt" not in text
    assert "session_prompt" not in text


def test_provider_renders_configured_template_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "pi"
        model = "gpt-5-codex"
        effort = "medium"

        [providers.pi]
        command = "pi"
        args = ["--model", "{model}", "--effort", "{effort}"]
        """,
    )
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)
    config = load_agent_configuration(tmp_path)
    provider = config.providers[config.role_providers["developer"]]

    provider.invoke(
        AgentInvocation(
            root=tmp_path,
            role_name="developer",
            system_prompt="system",
            session_prompt="session",
            invocation_id="test",
            stdout_log=tmp_path / ".devlab/logs/agents/test.stdout.log",
            stderr_log=tmp_path / ".devlab/logs/agents/test.stderr.log",
        )
    )

    assert calls[0][0][0] == [
        "pi",
        "--model",
        "gpt-5-codex",
        "--effort",
        "medium",
        "--system-prompt",
        "system",
        "session",
    ]


def _write_agents_config(root: Path, text: str) -> None:
    path = root / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text)

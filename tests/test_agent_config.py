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
    assert provider.argv == ("claude",)
    assert provider.args == (
        "-p",
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
    )
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
        args = [
            "-p",
            "--model", "{model}",
            "--effort", "{effort}",
            "--system-prompt", "{system_prompt}",
            "{session_prompt}",
        ]
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
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
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
        args = [
            "-p",
            "--model", "{model}",
            "--system-prompt", "{system_prompt}",
            "{session_prompt}",
        ]

        [providers.claude]
        command = "claude"
        args = [
            "-p",
            "--model", "{model}",
            "--effort", "{effort}",
            "--system-prompt", "{system_prompt}",
            "{session_prompt}",
        ]
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
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
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
        args = [
            "--model", "{model}",
            "--effort", "{effort}",
            "--system-prompt", "{system_prompt}",
            "{session_prompt}",
        ]

        [providers.claude]
        command = "claude"
        args = [
            "--model", "{model}",
            "--effort", "{effort}",
            "--system-prompt", "{system_prompt}",
            "{session_prompt}",
        ]
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
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
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
        args = ["--model", "{model}", "exec", "-"]
        stdin_template = "{system_prompt}\\n---\\n{session_prompt}"
        """,
    )

    config = load_agent_configuration(tmp_path)
    provider = config.providers[config.role_providers["developer"]]

    assert isinstance(provider, CliAgentProvider)
    assert provider.stdin_template == "{system_prompt}\n---\n{session_prompt}"
    assert config.resolved["developer"].uses_stdin is True


def test_provider_defaults_resolve_provider_without_role_policy(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "codex"
        model = "role-model"
        effort = "medium"

        [providers.codex]
        command = "codex"
        args = ["--model", "{model}", "--system-prompt", "{system_prompt}", "{session_prompt}"]

        [providers.unused]
        command = "unused-agent"
        args = ["--model", "{model}", "--system-prompt", "{system_prompt}", "{session_prompt}"]

        [providers.unused.defaults]
        model = "unused-model"
        effort = "low"
        timeout_seconds = 90
        """,
    )

    config = load_agent_configuration(tmp_path)

    assert "codex" not in config.provider_configs_with_defaults
    assert config.provider_configs_with_defaults["unused"].model == "unused-model"
    assert config.provider_configs_with_defaults["unused"].effort == "low"
    assert config.provider_configs_with_defaults["unused"].timeout_seconds == 90
    assert config.provider_configs_with_defaults["unused"].command == (
        "unused-agent",
        "--model",
        "unused-model",
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
    )


def test_config_path_loads_explicit_agents_toml(tmp_path: Path) -> None:
    config_path = tmp_path / ".local/live-eval/agents.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
        [defaults]
        provider = "pi"
        model = "custom"

        [providers.pi]
        command = "pi"
        args = ["--model", "{model}", "--system-prompt", "{system_prompt}", "{session_prompt}"]
        """
    )

    config = load_agent_configuration(tmp_path, config_path=config_path)

    assert config.resolved["developer"].provider == "pi"
    assert config.resolved["developer"].command == (
        "pi",
        "--model",
        "custom",
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
    )
    assert not (tmp_path / ".devlab/config/agents.toml").exists()


def test_role_provider_identity_command_preserves_role_placeholder(
    tmp_path: Path,
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "pi"
        model = "custom"

        [providers.pi]
        command = "pi"
        args = [
            "--role",
            "{role_name}",
            "--profile",
            "developer",
            "--model",
            "{model}",
            "--system-prompt",
            "{system_prompt}",
            "{session_prompt}",
        ]
        """,
    )

    config = load_agent_configuration(tmp_path)

    assert config.resolved["developer"].command == (
        "pi",
        "--role",
        "developer",
        "--profile",
        "developer",
        "--model",
        "custom",
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
    )
    assert config.resolved["developer"].provider_identity_command == (
        "pi",
        "--role",
        "{role_name}",
        "--profile",
        "developer",
        "--model",
        "custom",
        "--system-prompt",
        "{system_prompt}",
        "{session_prompt}",
    )


def test_missing_explicit_config_path_raises_clear_error(tmp_path: Path) -> None:
    missing = tmp_path / ".local/live-eval/missing.toml"

    with pytest.raises(FileNotFoundError, match="agent config not found"):
        load_agent_configuration(tmp_path, config_path=missing)


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


def test_prompt_args_are_rejected_by_loader(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "agent"
        args = ["--model", "{model}"]
        prompt_args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        """,
    )

    with pytest.raises(ValueError, match=r"providers\.test\.prompt_args is no longer supported"):
        load_agent_configuration(tmp_path)


def test_non_stdin_provider_must_deliver_prompts(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "agent"
        args = ["--model", "{model}"]
        """,
    )

    with pytest.raises(
        ValueError,
        match=r"providers\.test does not deliver required prompt placeholder",
    ):
        load_agent_configuration(tmp_path)


def test_provider_arg_placeholder_syntax_error_identifies_arg(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "agent"
        args = [
            "--effort",
            "{effort]",
            "--system-prompt",
            "{system_prompt}",
            "{session_prompt}",
        ]
        """,
    )

    with pytest.raises(
        ValueError,
        match=r"providers\.test\.args\[1\] has invalid placeholder syntax",
    ):
        load_agent_configuration(tmp_path)


def test_provider_arg_unknown_placeholder_identifies_arg(tmp_path: Path) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "agent"
        args = [
            "--model",
            "{unknown}",
            "--system-prompt",
            "{system_prompt}",
            "{session_prompt}",
        ]
        """,
    )

    with pytest.raises(
        ValueError,
        match=r"providers\.test\.args\[1\] references unknown placeholder \{unknown\}",
    ):
        load_agent_configuration(tmp_path)


def test_records_provider_version_from_configured_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "mock-agent run"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = "mock-agent version"
        """,
    )

    def fake_run(*args: Any, **kwargs: Any) -> object:
        assert args[0] == ["mock-agent", "version"]

        class Result:
            returncode = 0
            stdout = "mock-agent 1.2.3\n"
            stderr = ""

        return Result()

    monkeypatch.setattr("devlab.agent_config.subprocess.run", fake_run)

    config = load_agent_configuration(tmp_path, discover_provider_versions=True)

    assert config.resolved["developer"].provider_version == "mock-agent 1.2.3"
    assert 'provider_version = "mock-agent 1.2.3"' in format_resolved_agent_config(
        config.resolved["developer"]
    )


def test_provider_version_discovery_is_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "mock-agent run"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = "mock-agent version"
        """,
    )

    def fake_run(*args: Any, **kwargs: Any) -> object:
        raise AssertionError("version command should not run")

    monkeypatch.setattr("devlab.agent_config.subprocess.run", fake_run)

    config = load_agent_configuration(tmp_path)

    assert config.resolved["developer"].provider_version == ""


def test_provider_version_is_empty_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "missing-agent run"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        """,
    )

    def fake_run(*args: Any, **kwargs: Any) -> object:
        raise FileNotFoundError(args[0][0])

    monkeypatch.setattr("devlab.agent_config.subprocess.run", fake_run)

    config = load_agent_configuration(tmp_path, discover_provider_versions=True)

    assert config.resolved["developer"].provider_version == ""


def test_format_resolved_agent_config_does_not_include_prompts(tmp_path: Path) -> None:
    config = load_agent_configuration(tmp_path)

    text = format_resolved_agent_config(config.resolved["developer"])

    assert 'role = "developer"' in text
    assert "command = " in text
    assert '"{system_prompt}"' in text
    assert '"{session_prompt}"' in text


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
        args = [
            "--model", "{model}",
            "--effort", "{effort}",
            "--system-prompt", "{system_prompt}",
            "{session_prompt}",
        ]
        version_command = ""
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

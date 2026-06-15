from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devlab.agent_smoke import (
    SMOKE_MARKER,
    format_agent_smoke_report,
    run_agent_smoke_test,
)


def test_smoke_test_invokes_deduplicated_workflow_provider_configs_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"
        model = "model-a"
        effort = "medium"

        [roles.developer]
        provider = "other"

        [providers.test]
        command = "agent"
        args = [
            "--role", "{role_name}",
            "--model", "{model}",
            "--effort", "{effort}",
            "--system-prompt", "{system_prompt}",
            "{session_prompt}",
        ]
        version_command = ""

        [providers.other]
        command = "other-agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""

        [providers.unused]
        command = "unused-agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""
        """,
    )
    calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append(args[0])
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path)

    assert result.passed
    assert [check.check_name for check in result.check_results] == ["test", "other"]
    assert [check.role_names for check in result.check_results] == [
        ("architect", "planner", "reviewer", "integrator"),
        ("developer",),
    ]
    assert len(calls) == 2
    assert calls[0][:7] == [
        "agent",
        "--role",
        "test",
        "--model",
        "model-a",
        "--effort",
        "medium",
    ]
    assert calls[0][7] == "--system-prompt"
    assert SMOKE_MARKER in calls[0][8]
    assert calls[0][9] == (
        "This is a DevLab provider wiring check. "
        "Do not inspect files, edit files, run commands, or create artifacts. "
        "Check: test. Provider: test. "
        "Assigned roles: architect, planner, reviewer, integrator. "
        "Model: model-a. Effort: medium."
    )


def test_smoke_test_can_invoke_all_configured_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"
        model = "model-a"
        effort = "medium"

        [providers.test]
        command = "agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""

        [providers.unused]
        command = "unused-agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""

        [providers.unused.defaults]
        model = "unused-model"
        effort = "low"
        """,
    )
    calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append(args[0])
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path, all_providers=True)

    assert result.passed
    assert [provider.check_name for provider in result.check_results] == [
        "test",
        "unused",
    ]
    assert len(calls) == 2
    assert result.skipped_providers == ()


def test_smoke_test_can_select_unassigned_provider_with_provider_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"
        model = "model-a"
        effort = "medium"

        [providers.test]
        command = "agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""

        [providers.unused]
        command = "unused-agent"
        args = ["--model", "{model}", "--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""

        [providers.unused.defaults]
        model = "unused-model"
        effort = "low"
        """,
    )
    calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append(args[0])
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path, provider="unused")

    assert result.passed
    assert [check.check_name for check in result.check_results] == ["unused"]
    assert result.check_results[0].role_names == ()
    assert calls[0][:4] == ["unused-agent", "--model", "unused-model", "--system-prompt"]
    assert SMOKE_MARKER in calls[0][4]


def test_smoke_test_skips_unassigned_provider_without_provider_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"
        model = "model-a"
        effort = "medium"

        [providers.test]
        command = "agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""

        [providers.unused]
        command = "unused-agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""
        """,
    )
    calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append(args[0])
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path, all_providers=True)
    output = format_agent_smoke_report(result)

    assert result.passed
    assert [provider.check_name for provider in result.check_results] == ["test"]
    assert [skipped.provider for skipped in result.skipped_providers] == ["unused"]
    assert "Result: SKIPPED" in output
    assert "no [providers.unused.defaults]" in output
    assert len(calls) == 1


def test_smoke_test_supports_custom_config_without_changing_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / ".local/live-eval/agents.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
        [defaults]
        provider = "stdin"
        model = "model-a"
        effort = "low"

        [providers.stdin]
        command = "agent"
        args = ["--model", "{model}"]
        stdin_template = "{system_prompt}\\n---\\n{session_prompt}"
        version_command = ""
        """
    )
    seen: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> object:
        seen["cmd"] = args[0]
        seen["cwd"] = kwargs["cwd"]
        seen["input"] = kwargs["input"]
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path, config_path=config_path, role_names=("developer",))

    assert result.passed
    assert result.config_path == config_path
    assert seen["cmd"] == ["agent", "--model", "model-a"]
    assert seen["cwd"] == str(tmp_path)
    assert SMOKE_MARKER in seen["input"]
    assert (tmp_path / ".devlab/logs/agents").exists()
    assert not (tmp_path / ".devlab/config/agents.toml").exists()


def test_smoke_test_supports_role_specific_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"
        model = "model-a"
        effort = "medium"

        [providers.test]
        command = "agent"
        args = ["--role", "{role_name}", "--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""
        """,
    )
    calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> object:
        calls.append(args[0])
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path, role_names=("developer",))

    assert result.passed
    assert [role.check_name for role in result.check_results] == ["test"]
    assert result.check_results[0].role_names == (
        "architect",
        "planner",
        "developer",
        "reviewer",
        "integrator",
    )
    assert calls[0][2] == "test"


def test_smoke_test_deduplicates_role_configs_that_only_differ_by_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"
        model = "model-a"
        effort = "medium"
        timeout_seconds = 1200

        [roles.developer]
        timeout_seconds = 30

        [providers.test]
        command = "agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""
        """,
    )
    timeouts: list[int | None] = []

    def fake_run(*_args: Any, **kwargs: Any) -> object:
        timeouts.append(kwargs["timeout"])
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path)

    assert result.passed
    assert [check.check_name for check in result.check_results] == ["test"]
    assert result.check_results[0].config.timeout_seconds == 30
    assert timeouts == [30]


def test_smoke_report_includes_config_command_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"
        model = "model-a"
        effort = "medium"
        timeout_seconds = 30

        [providers.test]
        command = "agent"
        args = ["--model", "{model}", "--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""
        """,
    )

    def fake_run(*_args: Any, **kwargs: Any) -> object:
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path, role_names=("developer",))
    output = format_agent_smoke_report(result)

    assert "Agent smoke test" in output
    assert f"Workspace: {tmp_path}" in output
    assert f"Config: {tmp_path / '.devlab/config/agents.toml'}" in output
    assert "Checks: test" in output
    assert "[test]" in output
    assert "Provider: test" in output
    assert "Assigned roles: architect, planner, developer, reviewer, integrator" in output
    assert "Model: model-a" in output
    assert "Effort: medium" in output
    assert "Timeout: 30s" in output
    assert "Command: agent --model model-a" in output
    assert "Result: OK" in output
    assert ".stdout.log" in output
    assert ".stderr.log" in output
    assert "Summary: 1 passed, 0 failed" in output


def test_smoke_test_fails_when_marker_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""
        """,
    )

    def fake_run(*_args: Any, **kwargs: Any) -> object:
        kwargs["stdout"].write("different output")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path, role_names=("developer",))
    output = format_agent_smoke_report(result)

    assert not result.passed
    assert "Result: FAILED" in output
    assert "missing marker" in output


def test_smoke_test_does_not_accept_marker_echoed_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""
        """,
    )

    def fake_run(*_args: Any, **kwargs: Any) -> object:
        kwargs["stderr"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)

    result = run_agent_smoke_test(tmp_path, role_names=("developer",))

    assert not result.passed


def test_smoke_test_rejects_unknown_role(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown role"):
        run_agent_smoke_test(tmp_path, role_names=("bogus",))


def test_smoke_test_rejects_all_providers_with_roles(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="all_providers"):
        run_agent_smoke_test(tmp_path, role_names=("developer",), all_providers=True)


def test_smoke_test_rejects_provider_with_roles(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="provider"):
        run_agent_smoke_test(tmp_path, role_names=("developer",), provider="test")


def test_smoke_test_emits_progress_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_config(
        tmp_path,
        """
        [defaults]
        provider = "test"

        [providers.test]
        command = "agent"
        args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
        version_command = ""
        """,
    )

    def fake_run(*_args: Any, **kwargs: Any) -> object:
        kwargs["stdout"].write(SMOKE_MARKER)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("devlab.agents.subprocess.run", fake_run)
    events: list[tuple[str, str]] = []

    run_agent_smoke_test(
        tmp_path,
        on_progress=lambda event: events.append((event.event, event.check_name)),
    )

    assert events == [("start", "test"), ("finish", "test")]


def _write_agents_config(root: Path, text: str) -> None:
    path = root / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text)

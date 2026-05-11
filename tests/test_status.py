from __future__ import annotations

from pathlib import Path

from devlab.status import format_status


def test_status_verbose_includes_agent_configuration_without_prompts(tmp_path: Path) -> None:
    _setup_minimal_workspace(tmp_path)
    (tmp_path / ".devlab/config/agents.toml").write_text(
        "[defaults]\n"
        'provider = "codex"\n'
        'model = "gpt-5-codex"\n'
        'effort = "medium"\n'
        "timeout_seconds = 3600\n"
        "\n[providers.codex]\n"
        'command = "codex"\n'
        'args = ["exec", "-", "--model", "{model}"]\n'
        "prompt_args = []\n"
        'stdin_template = "{system_prompt}\\n\\n---\\n\\n{session_prompt}"\n'
    )

    text = format_status(tmp_path, verbose=True)

    assert "Next role: architect" in text
    assert "Agent configuration:" in text
    assert "Source: .devlab/config/agents.toml" in text
    assert '- developer: codex model="gpt-5-codex" effort="medium"' in text
    assert "stdin=true" in text
    assert "system_prompt" not in text
    assert "session_prompt" not in text


def test_status_verbose_reports_fallback_source(tmp_path: Path) -> None:
    _setup_minimal_workspace(tmp_path)

    text = format_status(tmp_path, verbose=True)

    assert "Source: built-in fallback defaults" in text
    assert '- developer: default model="" effort=""' in text


def _setup_minimal_workspace(root: Path) -> None:
    (root / ".devlab/plans").mkdir(parents=True)
    (root / ".devlab/config/profiles").mkdir(parents=True)
    (root / ".devlab/tasks").mkdir(parents=True)
    (root / ".devlab/findings").mkdir(parents=True)
    (root / ".devlab/history").mkdir(parents=True)
    (root / ".devlab/config/tooling.md").write_text("# Tooling\n")
    (root / ".devlab/config/profiles/default.toml").write_text(
        'version = 1\nid = "default"\ntitle = "Default"\n'
    )

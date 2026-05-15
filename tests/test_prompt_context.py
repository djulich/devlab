from __future__ import annotations

from pathlib import Path

from devlab.init import init_workspace
from devlab.prompt_context import (
    PromptContextThresholds,
    build_prompt_context_report,
    estimate_tokens,
    load_prompt_context_thresholds,
    measure_prompt,
)


def test_estimate_tokens_uses_stable_character_estimate() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_measure_prompt_reports_characters_lines_and_tokens() -> None:
    size = measure_prompt("abcd\nefgh")

    assert size.characters == 9
    assert size.lines == 2
    assert size.estimated_tokens == 3


def test_prompt_context_report_includes_all_roles(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    report = build_prompt_context_report(tmp_path)

    assert {role.role_name for role in report.roles} == {
        "architect",
        "planner",
        "developer",
        "reviewer",
        "integrator",
    }
    assert all(role.system.estimated_tokens > 0 for role in report.roles)
    assert all(role.session.estimated_tokens > 0 for role in report.roles)


def test_thresholds_can_be_configured_globally_and_per_role(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _append_prompt_context_config(
        tmp_path,
        "[prompt_context]\n"
        "warning_tokens = 10\n"
        "critical_tokens = 20\n"
        "\n[prompt_context.roles.planner]\n"
        "warning_tokens = 30\n"
        "critical_tokens = 40\n",
    )

    thresholds = load_prompt_context_thresholds(tmp_path)

    assert thresholds["default"] == PromptContextThresholds(10, 20)
    assert thresholds["planner"] == PromptContextThresholds(30, 40)


def test_role_prompt_context_reports_warning_and_critical_status(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _append_prompt_context_config(
        tmp_path,
        "[prompt_context]\n"
        "warning_tokens = 1\n"
        "critical_tokens = 1_000_000\n"
        "\n[prompt_context.roles.planner]\n"
        "warning_tokens = 1\n"
        "critical_tokens = 2\n",
    )

    report = build_prompt_context_report(tmp_path)
    by_role = {role.role_name: role for role in report.roles}

    assert by_role["architect"].status == "warning"
    assert by_role["planner"].status == "critical"


def _append_prompt_context_config(root: Path, text: str) -> None:
    path = root / ".devlab/config/agents.toml"
    path.write_text(path.read_text() + "\n" + text)

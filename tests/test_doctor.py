from __future__ import annotations

from pathlib import Path

from devlab.doctor import check_workspace, format_doctor_report


def test_doctor_accepts_missing_agents_config(tmp_path: Path) -> None:
    assert check_workspace(tmp_path) == []


def test_doctor_reports_multiple_agents_config_problems(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[defaults]\n"
        'provider = "missing"\n'
        "\n[roles.unknown]\n"
        'provider = "default"\n'
        "\n[providers.default]\n"
        "command = 123\n"
        'args = ["--bad", "{unknown_placeholder}"]\n'
    )

    problems = check_workspace(tmp_path)
    messages = [problem.message for problem in problems]

    assert "roles.unknown is not a known role" in messages
    assert "providers.default.command must be a string" in messages
    assert any("unsupported placeholder {unknown_placeholder}" in message for message in messages)
    assert any("references missing provider 'missing'" in message for message in messages)


def test_doctor_report_formats_success_and_failure(tmp_path: Path) -> None:
    assert format_doctor_report([]) == "DevLab doctor: OK"

    path = tmp_path / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[defaults\n")

    report = format_doctor_report(check_workspace(tmp_path))

    assert report.startswith("DevLab doctor: 1 problem(s)")
    assert ".devlab/config/agents.toml" in report
    assert "invalid TOML" in report

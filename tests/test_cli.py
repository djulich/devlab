from __future__ import annotations

from pathlib import Path

import pytest

from devlab.cli import main


def _run_cli(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr("sys.argv", ["devlab", *args])
    main()


def test_cli_init_creates_devlab_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))

    output = capsys.readouterr().out
    assert "created: .devlab/manifest.toml" in output
    assert (tmp_path / ".devlab/manifest.toml").exists()
    assert (tmp_path / ".devlab/config/profiles/default.toml").exists()
    assert (tmp_path / ".devlab/config/agents.toml").exists()


def test_cli_init_force_overwrites_starter_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()
    tooling = tmp_path / ".devlab/config/tooling.md"
    tooling.write_text("custom\n")

    _run_cli(monkeypatch, "init", "--root", str(tmp_path), "--force")

    output = capsys.readouterr().out
    assert "overwritten: .devlab/config/tooling.md" in output
    assert tooling.read_text().startswith("# Tooling Policy")


def test_cli_status_reports_next_role_for_initialized_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "status", "--root", str(tmp_path))

    assert capsys.readouterr().out.strip() == "Next role: architect"


def test_cli_status_verbose_reports_agent_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "status", "--verbose", "--root", str(tmp_path))

    output = capsys.readouterr().out
    assert "Next role: architect" in output
    assert "Agent configuration:" in output
    assert "Source: .devlab/config/agents.toml" in output


def test_cli_doctor_reports_ok_for_initialized_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()

    _run_cli(monkeypatch, "doctor", "--root", str(tmp_path))

    assert capsys.readouterr().out.strip() == "DevLab doctor: OK"


def test_cli_doctor_exits_nonzero_for_invalid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli(monkeypatch, "init", "--root", str(tmp_path))
    capsys.readouterr()
    (tmp_path / ".devlab/config/agents.toml").write_text("[defaults\n")

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "doctor", "--root", str(tmp_path))

    assert exc.value.code == 1
    assert "DevLab doctor: 1 problem(s)" in capsys.readouterr().out

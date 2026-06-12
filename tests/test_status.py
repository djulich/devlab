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
        'args = ["--model", "{model}", "exec", "-"]\n'
        "prompt_args = []\n"
        'stdin_template = "{base_prompt}\\n\\n---\\n\\n{session_prompt}"\n'
    )

    text = format_status(tmp_path, verbose=True)

    assert "Next role: architect" in text
    assert "Agent configuration:" in text
    assert "Prompt context:" in text
    assert "- architect: total ~" in text
    assert "Source: .devlab/config/agents.toml" in text
    assert '- developer: codex model="gpt-5-codex" effort="medium"' in text
    assert "stdin=true" in text
    assert "base_prompt" not in text
    assert "session_prompt" not in text


def test_status_verbose_reports_fallback_source(tmp_path: Path) -> None:
    _setup_minimal_workspace(tmp_path)

    text = format_status(tmp_path, verbose=True)

    assert "Source: built-in fallback defaults" in text
    assert '- developer: default model="" effort=""' in text


def test_status_verbose_includes_milestone_state(tmp_path: Path) -> None:
    _setup_minimal_workspace(tmp_path)
    (tmp_path / ".devlab/plans/project-plan.md").write_text("## M1: Foundation\n")
    _write_task(tmp_path, "T0001", "closed", "M1")
    _write_task(tmp_path, "T0002", "open", "M1")
    _write_milestone(
        tmp_path,
        "M1",
        status="integrated",
        integrated=True,
        architecture_reviewed=False,
        task_ids=["T0001", "T0002"],
        integration_handoff="20260101T000000_integrator_handoff.md",
        findings=["F0001"],
    )

    text = format_status(tmp_path, verbose=True)

    assert "Milestones:" in text
    assert "- M1: Foundation" in text
    assert "  status: integrated" in text
    assert "  tasks: 2 total, 1 closed, 1 active" in text
    assert "  integrated: true" in text
    assert "  architecture_reviewed: false" in text
    assert "  integration_handoff: 20260101T000000_integrator_handoff.md" in text
    assert "  findings: F0001" in text


def test_status_verbose_includes_finding_state(tmp_path: Path) -> None:
    _setup_minimal_workspace(tmp_path)
    _write_finding(tmp_path, "F0001", "Missing coverage", "planned", "M1")
    _write_task(tmp_path, "T0001", "open", "M1", addresses_findings=["F0001"])

    text = format_status(tmp_path, verbose=True)

    assert "Findings:" in text
    assert "- F0001: Missing coverage" in text
    assert "  status: planned" in text
    assert "  source: integrator" in text
    assert "  milestone: M1" in text
    assert "  addressing_tasks: T0001" in text


def test_status_verbose_reports_no_milestones(tmp_path: Path) -> None:
    _setup_minimal_workspace(tmp_path)

    text = format_status(tmp_path, verbose=True)

    assert "Milestones: none" in text


def test_status_verbose_reports_missing_milestone_without_creating_it(tmp_path: Path) -> None:
    _setup_minimal_workspace(tmp_path)
    _write_task(tmp_path, "T0001", "closed", "M1")

    text = format_status(tmp_path, verbose=True)

    assert "- M1: missing milestone state file" in text
    assert "  referenced_by_tasks: T0001" in text
    assert not (tmp_path / ".devlab/milestones/M1.toml").exists()


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


def _write_task(
    root: Path,
    task_id: str,
    status: str,
    milestone: str,
    *,
    addresses_findings: list[str] | None = None,
) -> None:
    addresses_findings = addresses_findings or []
    findings_text = ", ".join(f'"{finding_id}"' for finding_id in addresses_findings)
    path = root / ".devlab/tasks" / f"{task_id}_task.md"
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{task_id}"\n'
        f'status = "{status}"\n'
        f'milestone = "{milestone}"\n'
        "depends_on = []\n"
        f"addresses_findings = [{findings_text}]\n"
        "+++\n\n"
        f"# {task_id}\n"
    )


def _write_finding(
    root: Path,
    finding_id: str,
    title: str,
    status: str,
    milestone: str,
) -> None:
    path = root / ".devlab/findings" / f"{finding_id}_finding.md"
    path.write_text(
        "+++\n"
        f'id = "{finding_id}"\n'
        f'title = "{title}"\n'
        f'status = "{status}"\n'
        'source = "integrator"\n'
        f'milestone = "{milestone}"\n'
        'handoff = "handoff.md"\n'
        "+++\n\n"
        f"# {title}\n"
    )


def _write_milestone(
    root: Path,
    milestone_id: str,
    *,
    status: str,
    integrated: bool,
    architecture_reviewed: bool,
    task_ids: list[str],
    integration_handoff: str = "",
    architecture_review_handoff: str = "",
    findings: list[str] | None = None,
) -> None:
    findings = findings or []
    task_ids_text = ", ".join(f'"{task_id}"' for task_id in task_ids)
    findings_text = ", ".join(f'"{finding_id}"' for finding_id in findings)
    path = root / ".devlab/milestones" / f"{milestone_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version = 1\n"
        f'id = "{milestone_id}"\n'
        'title = "Foundation"\n'
        f'status = "{status}"\n'
        "integration_required = true\n"
        f"integrated = {str(integrated).lower()}\n"
        f"architecture_reviewed = {str(architecture_reviewed).lower()}\n"
        f"task_ids = [{task_ids_text}]\n"
        f'integration_handoff = "{integration_handoff}"\n'
        f'architecture_review_handoff = "{architecture_review_handoff}"\n'
        f"findings = [{findings_text}]\n"
    )

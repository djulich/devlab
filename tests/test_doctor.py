from __future__ import annotations

from pathlib import Path

from devlab.doctor import check_workspace, format_doctor_report
from devlab.init import init_workspace


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


def test_doctor_reports_prompt_context_configuration_problems(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[prompt_context]\n"
        "warning_tokens = 100\n"
        "critical_tokens = 50\n"
        "\n[prompt_context.roles.unknown]\n"
        "warning_tokens = 10\n"
        "critical_tokens = 20\n"
        "\n[prompt_context.roles.planner]\n"
        'warning_tokens = "many"\n'
    )

    messages = _messages(tmp_path)

    assert (
        "prompt_context.critical_tokens must be greater than or equal to warning_tokens"
        in messages
    )
    assert "prompt_context.roles.unknown is not a known role" in messages
    assert "prompt_context.roles.planner.warning_tokens must be an integer" in messages


def test_doctor_report_formats_success_and_failure(tmp_path: Path) -> None:
    assert format_doctor_report([]) == "DevLab doctor: OK"

    path = tmp_path / ".devlab/config/agents.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[defaults\n")

    report = format_doctor_report(check_workspace(tmp_path))

    assert report.startswith("DevLab doctor: 1 problem(s)")
    assert ".devlab/config/agents.toml" in report
    assert "invalid TOML" in report


def test_doctor_reports_oversized_prompt_context(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    path = tmp_path / ".devlab/config/agents.toml"
    path.write_text(
        path.read_text()
        + "\n[prompt_context]\n"
        + "warning_tokens = 1\n"
        + "critical_tokens = 1_000_000\n"
        + "\n[prompt_context.roles.planner]\n"
        + "warning_tokens = 1\n"
        + "critical_tokens = 2\n"
    )

    messages = _messages(tmp_path)

    assert any(message.startswith("architect prompt context warning") for message in messages)
    assert any(message.startswith("planner prompt context is critical") for message in messages)


def test_doctor_prompt_context_check_does_not_sync_milestone_files(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _write_task(tmp_path, "T0001", milestone="M1")

    check_workspace(tmp_path)

    assert not (tmp_path / ".devlab/milestones/M1.toml").exists()


def test_doctor_reports_unknown_task_domain(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M1", domain="infra")

    messages = _messages(tmp_path)

    assert any("unknown task domain 'infra'" in message for message in messages)


def test_doctor_allows_known_task_domains(tmp_path: Path) -> None:
    _write_default_profile(tmp_path)
    _write_task(tmp_path, "T0001", milestone="M1", domain="general")
    _write_task(tmp_path, "T0002", milestone="M1", domain="deployment")
    _write_milestone(tmp_path, "M1", task_ids=["T0001", "T0002"])

    messages = _messages(tmp_path)

    assert not any("unknown task domain" in message for message in messages)


def test_doctor_ignores_placeholder_deployment_spec_tools(tmp_path: Path, monkeypatch) -> None:
    init_workspace(tmp_path)
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: None)

    messages = _messages(tmp_path)

    assert not any("deployment spec mentions" in message for message in messages)


def test_doctor_reports_empty_active_deployment_spec(tmp_path: Path) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text("\n")

    messages = _messages(tmp_path)

    assert any(
        message.startswith("deployment spec is empty; keep the placeholder template")
        for message in messages
    )


def test_doctor_does_not_match_deployment_tool_names_inside_words(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Kindly document local verification steps for future configuration.\n"
    )
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: None)

    messages = _messages(tmp_path)

    assert not any("deployment spec mentions kind" in message for message in messages)


def test_doctor_reports_generic_container_spec_without_common_tool(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Build an OCI-compatible container image for local verification.\n"
        "Production deployment is out of scope.\n"
    )
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: None)

    messages = _messages(tmp_path)

    assert any("describes container artifacts but no common container tool" in m for m in messages)


def test_doctor_allows_generic_container_spec_when_common_tool_exists(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Build a containerized local runtime artifact.\n"
        "Production deployment is out of scope.\n"
    )
    monkeypatch.setattr(
        "devlab.doctor.shutil.which",
        lambda name: "/usr/bin/buildah" if name == "buildah" else None,
    )

    messages = _messages(tmp_path)

    assert not any("describes container artifacts" in m for m in messages)


def test_doctor_checks_additional_deployment_spec_files(tmp_path: Path, monkeypatch) -> None:
    spec_dir = tmp_path / ".devlab/specs/deployment"
    spec_dir.mkdir(parents=True)
    (spec_dir / "README.md").write_text(
        "<!-- devlab:placeholder -->\n"
        "# Deployment Specification\n\n"
        "Describe deployment requirements.\n"
    )
    (spec_dir / "compose.md").write_text(
        "# Compose Deployment\n\nVerify Compose artifacts with docker compose.\n"
        "Production deployment is out of scope.\n"
    )
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: None)

    messages = _messages(tmp_path)

    assert any("deployment spec mentions docker compose" in m for m in messages)


def test_doctor_reports_missing_deployment_tools(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Build a container image with Podman and verify Kubernetes manifests with kind.\n"
        "Production deployment is out of scope.\n"
    )
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: None)

    messages = _messages(tmp_path)

    assert any(
        "deployment spec mentions podman but 'podman' is not on PATH" in m
        for m in messages
    )
    assert any("deployment spec mentions kind but 'kind' is not on PATH" in m for m in messages)


def test_doctor_allows_docker_or_podman_when_one_is_available(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Build a local image with Docker or Podman.\n"
        "Production deployment is out of scope.\n"
    )
    monkeypatch.setattr(
        "devlab.doctor.shutil.which",
        lambda name: "/usr/bin/podman" if name == "podman" else None,
    )

    messages = _messages(tmp_path)

    assert not any("'docker' is not on PATH" in message for message in messages)
    assert not any("Docker or Podman but neither" in message for message in messages)


def test_doctor_reports_docker_or_podman_when_neither_is_available(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Build a local image with Docker or Podman.\n"
        "Production deployment is out of scope.\n"
    )
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: None)

    messages = _messages(tmp_path)

    assert any("Docker or Podman but neither 'docker' nor 'podman'" in m for m in messages)


def test_doctor_does_not_warn_for_non_deployment_production_mentions(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Use production-like sample configuration for local validation.\n"
    )
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: "/usr/bin/tool")

    messages = _messages(tmp_path)

    assert not any("mentions production without explicit" in message for message in messages)


def test_doctor_reports_production_claim_without_boundary(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Deploy to production with existing automation.\n"
    )
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: "/usr/bin/tool")

    messages = _messages(tmp_path)

    assert any("mentions production without explicit" in message for message in messages)


def test_doctor_allows_production_boundary_language(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / ".devlab/specs/deployment/README.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Deployment Specification\n\n"
        "Provide local Podman verification. Production deployment is out of scope.\n"
    )
    monkeypatch.setattr("devlab.doctor.shutil.which", lambda _name: "/usr/bin/tool")

    messages = _messages(tmp_path)

    assert not any("mentions production without explicit" in message for message in messages)


def test_doctor_reports_project_knowledge_problems(tmp_path: Path) -> None:
    (tmp_path / "CONTEXT-MAP.md").write_text(
        "# Context Map\n\n- [Missing](./src/missing/CONTEXT.md)\n"
    )
    adr_dir = tmp_path / "docs/adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-first.md").write_text("# First\n")
    (adr_dir / "0001-duplicate.md").write_text("# Duplicate\n")
    (adr_dir / "bad-name.md").write_text("# Bad\n")

    messages = _messages(tmp_path)

    assert "references missing context file 'src/missing/CONTEXT.md'" in messages
    assert any("duplicate ADR number 0001" in message for message in messages)
    assert "ADR filename must match NNNN-lowercase-slug.md" in messages


def test_doctor_reports_task_referencing_missing_milestone(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M1")

    messages = _messages(tmp_path)

    assert any("references missing milestone 'M1'" in message for message in messages)


def test_doctor_reports_stale_milestone_task_ids(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M1")
    _write_milestone(tmp_path, "M1", task_ids=[])

    messages = _messages(tmp_path)

    assert any("does not list task 'T0001'" in message for message in messages)


def test_doctor_reports_unknown_task_referenced_by_milestone(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1", task_ids=["T9999"])

    messages = _messages(tmp_path)

    assert "task_ids references unknown task 'T9999'" in messages


def test_doctor_reports_task_referenced_by_wrong_milestone(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M2")
    _write_milestone(tmp_path, "M1", task_ids=["T0001"])
    _write_milestone(tmp_path, "M2", task_ids=["T0001"])

    messages = _messages(tmp_path)

    assert any("task_ids references 'T0001' but task milestone is 'M2'" in m for m in messages)


def test_doctor_reports_integrated_milestone_missing_handoff(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1", status="integrated", integrated=True)

    messages = _messages(tmp_path)

    assert "integrated milestone is missing integration_handoff" in messages


def test_doctor_reports_architecture_reviewed_milestone_problems(tmp_path: Path) -> None:
    _write_milestone(
        tmp_path,
        "M1",
        status="architecture_reviewed",
        integrated=False,
        architecture_reviewed=True,
    )

    messages = _messages(tmp_path)

    assert "architecture-reviewed milestone is not integrated" in messages
    assert "architecture-reviewed milestone is missing architecture_review_handoff" in messages


def test_doctor_reports_missing_milestone_finding(tmp_path: Path) -> None:
    _write_milestone(tmp_path, "M1", findings=["F0001"])

    messages = _messages(tmp_path)

    assert "findings references unknown finding 'F0001'" in messages


def test_doctor_reports_unknown_finding_referenced_by_task(tmp_path: Path) -> None:
    _write_task(tmp_path, "T0001", milestone="M1", addresses_findings=["F0001"])

    messages = _messages(tmp_path)

    assert "addresses_findings references unknown finding 'F0001'" in messages


def test_doctor_reports_open_finding_with_addressing_tasks(tmp_path: Path) -> None:
    _write_finding(tmp_path, "F0001", status="open", milestone="M1")
    _write_task(tmp_path, "T0001", milestone="M1", addresses_findings=["F0001"])

    messages = _messages(tmp_path)

    assert "open finding has addressing tasks but is not planned" in messages


def test_doctor_reports_planned_finding_without_addressing_tasks(tmp_path: Path) -> None:
    _write_finding(tmp_path, "F0001", status="planned", milestone="M1")

    messages = _messages(tmp_path)

    assert "planned finding has no addressing tasks" in messages


def test_doctor_reports_planned_finding_with_all_addressing_tasks_closed(
    tmp_path: Path,
) -> None:
    _write_finding(tmp_path, "F0001", status="planned", milestone="M1")
    _write_task(
        tmp_path,
        "T0001",
        status="closed",
        milestone="M1",
        addresses_findings=["F0001"],
    )

    messages = _messages(tmp_path)

    assert "planned finding has all addressing tasks closed" in messages


def test_doctor_allows_task_addressing_finding_from_different_milestone(
    tmp_path: Path,
) -> None:
    _write_default_profile(tmp_path)
    _write_finding(tmp_path, "F0001", status="planned", milestone="M1")
    _write_task(tmp_path, "T0001", milestone="M2", addresses_findings=["F0001"])
    _write_milestone(tmp_path, "M2", task_ids=["T0001"])

    messages = _messages(tmp_path)

    assert "addresses finding 'F0001' from milestone 'M1'" not in messages


def test_doctor_accepts_consistent_milestone_state(tmp_path: Path) -> None:
    _write_default_profile(tmp_path)
    _write_task(tmp_path, "T0001", milestone="M1")
    _write_milestone(
        tmp_path,
        "M1",
        status="architecture_reviewed",
        integrated=True,
        architecture_reviewed=True,
        task_ids=["T0001"],
        integration_handoff="20260101T000000_integrator_handoff.md",
        architecture_review_handoff="20260101T000100_architect_handoff.md",
    )

    assert check_workspace(tmp_path) == []


def _messages(root: Path) -> list[str]:
    return [problem.message for problem in check_workspace(root)]


def _write_default_profile(root: Path) -> None:
    path = root / ".devlab/config/profiles/default.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('version = 1\nid = "default"\ntitle = "Default"\n')


def _write_task(
    root: Path,
    task_id: str,
    *,
    milestone: str,
    status: str = "open",
    domain: str | None = None,
    addresses_findings: list[str] | None = None,
) -> None:
    addresses_findings = addresses_findings or []
    findings_text = ", ".join(f'"{finding_id}"' for finding_id in addresses_findings)
    domain_text = f'domain = "{domain}"\n' if domain is not None else ""
    path = root / ".devlab/tasks" / f"{task_id}_task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{task_id}"\n'
        f'status = "{status}"\n'
        f'milestone = "{milestone}"\n'
        f"{domain_text}"
        "depends_on = []\n"
        f"addresses_findings = [{findings_text}]\n"
        "+++\n\n"
        f"# {task_id}\n"
    )


def _write_finding(
    root: Path,
    finding_id: str,
    *,
    status: str,
    milestone: str,
) -> None:
    path = root / ".devlab/findings" / f"{finding_id}_finding.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "+++\n"
        f'id = "{finding_id}"\n'
        f'title = "{finding_id}"\n'
        f'status = "{status}"\n'
        'source = "integrator"\n'
        f'milestone = "{milestone}"\n'
        "+++\n\n"
        f"# {finding_id}\n"
    )


def _write_milestone(
    root: Path,
    milestone_id: str,
    *,
    status: str = "planned",
    integrated: bool = False,
    architecture_reviewed: bool = False,
    task_ids: list[str] | None = None,
    integration_handoff: str = "",
    architecture_review_handoff: str = "",
    findings: list[str] | None = None,
) -> None:
    task_ids = task_ids or []
    findings = findings or []
    task_ids_text = ", ".join(f'"{task_id}"' for task_id in task_ids)
    findings_text = ", ".join(f'"{finding_id}"' for finding_id in findings)
    path = root / ".devlab/milestones" / f"{milestone_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version = 1\n"
        f'id = "{milestone_id}"\n'
        f'title = "{milestone_id}"\n'
        f'status = "{status}"\n'
        "integration_required = true\n"
        f"integrated = {str(integrated).lower()}\n"
        f"architecture_reviewed = {str(architecture_reviewed).lower()}\n"
        f"task_ids = [{task_ids_text}]\n"
        f'integration_handoff = "{integration_handoff}"\n'
        f'architecture_review_handoff = "{architecture_review_handoff}"\n'
        f"findings = [{findings_text}]\n"
    )

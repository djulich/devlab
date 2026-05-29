from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devlab.artifact_hygiene import ArtifactHygiene, collect_artifact_hygiene
from devlab.findings import FileFindingTracker, FindingStatus
from devlab.milestones import FileMilestoneTracker, MilestoneStatus
from devlab.task_tracker import FileTaskTracker, TaskStatus
from devlab.workflow_diagnostics import (
    TaskMetrics,
    collect_profile_metrics,
    format_workflow_diagnostics,
    quality_summary,
)
from devlab.workflow_history import (
    IntegratorReworkSummary,
    TaskCycleEntry,
    TaskReworkSummary,
    derive_integrator_rework_summary,
    derive_review_rejections,
    derive_role_sequence,
    derive_session_records,
    derive_task_cycle_metrics,
    derive_task_rework_summary,
)
from tests.evaluations.checks import (
    CheckResult,
    command_check,
    command_fails_check,
    file_contains_check,
)
from tests.evaluations.harness import (
    EvaluationDiagnostics,
    EvaluationScenario,
    init_target_workspace,
    run_scripted_evaluation,
)
from tests.evaluations.scripted_agents import (
    CalculatorScriptedAgent,
    DeploymentWebApiScriptedAgent,
    HttpApiScriptedAgent,
    StatefulWebApiScriptedAgent,
    StaticFrontendScriptedAgent,
    deployment_artifacts_check,
    stateful_todo_api_check,
    static_frontend_check,
    stdlib_http_api_check,
)


def test_scripted_cli_calculator_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-happy-path",
        title="CLI calculator happy path",
        system_spec="Build a Python CLI calculator with add and subtract commands.",
        max_sessions=10,
        scripted_agent=CalculatorScriptedAgent(),
        checks=_calculator_checks(),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="calculator.py")


def test_scripted_cli_calculator_reviewer_rework_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-reviewer-rework",
        title="CLI calculator reviewer rework",
        system_spec="Build a Python CLI calculator with add and subtract commands.",
        max_sessions=12,
        scripted_agent=CalculatorScriptedAgent(reject_first_review=True),
        checks=_calculator_checks(),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "developer", "reviewer",
            "integrator", "architect",
        ),
        expected_sessions=8,
        expected_rejections=1,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="calculator.py")


def test_scripted_cli_calculator_integration_finding_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="cli-calculator-integration-finding",
        title="CLI calculator integration finding",
        system_spec=(
            "Build a Python CLI calculator with add and subtract commands and keep a smoke "
            "test artifact in the repository."
        ),
        max_sessions=14,
        scripted_agent=CalculatorScriptedAgent(require_smoke_finding=True),
        checks=(
            *_calculator_checks(),
            file_contains_check("smoke test artifact", "test_calculator_smoke.py", "test_smoke"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "planner",
            "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=10,
        expected_findings=1,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="calculator.py")
    finding = FileFindingTracker(tmp_path).get("F0001")
    assert finding.status == FindingStatus.RESOLVED
    assert diagnostics.integrator_rework == IntegratorReworkSummary(
        findings_created=1,
        findings_resolved=1,
        findings_open=0,
        findings_planned=0,
        finding_ids=["F0001"],
        has_integrator_rework=True,
    )
    task = FileTaskTracker(tmp_path).get("T0002")
    assert task.addresses_findings == ("F0001",)


def test_scripted_tiny_http_api_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="tiny-http-api-happy-path",
        title="Tiny HTTP API happy path",
        system_spec=(
            "Build a tiny Python standard-library HTTP API with /health returning ok and "
            "/echo?value=TEXT returning TEXT."
        ),
        max_sessions=10,
        scripted_agent=HttpApiScriptedAgent(),
        checks=(stdlib_http_api_check,),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(tmp_path, diagnostics, scenario, expected_artifact="app.py")


def test_scripted_stateful_web_api_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="stateful-web-api-happy-path",
        title="Stateful web API happy path",
        system_spec=(
            "Build a small Python JSON HTTP API for todo items. It must expose /health, "
            "create todos, list todos, delete todos by id, keep data in memory, and "
            "provide project-owned run/test commands."
        ),
        max_sessions=10,
        scripted_agent=StatefulWebApiScriptedAgent(),
        checks=(
            stateful_todo_api_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
            file_contains_check("usage docs", "README.md", "GET /todos"),
            file_contains_check("python cache gitignore", ".gitignore", "__pycache__/"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(
        tmp_path,
        diagnostics,
        scenario,
        expected_artifact="src/todo_api/server.py",
    )


def test_scripted_static_frontend_todo_app_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="static-frontend-todo-app-happy-path",
        title="Static frontend todo app happy path",
        system_spec=(
            "Build a small Python standard-library JSON HTTP API for todo items plus a "
            "static vanilla HTML/CSS/JS frontend. Do not use React, Vite, npm, or a "
            "frontend build step. Implement the API in src/todo_api/server.py, runnable "
            "from the repository root with python -m src.todo_api.server --port <port>. "
            "The API must expose GET /health, POST /todos, GET /todos, and "
            "DELETE /todos/{id} with the exact stateful todo API response contract. "
            "Place frontend files at static/index.html, static/app.js, and "
            "static/styles.css. The UI must list todos, add todos, delete todos, display "
            "validation errors, and call the API routes directly. Provide project-owned "
            "run/test commands and README usage instructions."
        ),
        max_sessions=12,
        scripted_agent=StaticFrontendScriptedAgent(),
        checks=(
            stateful_todo_api_check,
            static_frontend_check,
            file_contains_check("project run command", "Makefile", "run:"),
            file_contains_check("project test command", "Makefile", "test:"),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "integrator", "architect",
        ),
        expected_sessions=6,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(
        tmp_path,
        diagnostics,
        scenario,
        expected_artifact="static/index.html",
    )


def test_scripted_deployable_web_api_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="deployable-web-api-happy-path",
        title="Deployable web API happy path",
        system_spec=(
            "Build a small Python JSON HTTP API for todo items and include "
            "project-owned local container deployment artifacts."
        ),
        deployment_spec=(
            "Deployment target: local OCI-compatible container image for the todo API. "
            "Provide a Containerfile, Makefile targets to build and verify deployment "
            "artifacts, and README deployment instructions. Do not deploy to production."
        ),
        max_sessions=12,
        scripted_agent=DeploymentWebApiScriptedAgent(),
        checks=(
            stateful_todo_api_check,
            deployment_artifacts_check,
            file_contains_check(
                "deployment task domain",
                ".devlab/tasks/T0002_add-container-deployment-artifacts.md",
                "domain = \"deployment\"",
            ),
        ),
        expected_roles=(
            "architect", "planner", "developer", "reviewer", "developer", "reviewer",
            "integrator", "architect",
        ),
        expected_sessions=8,
    )

    diagnostics = run_scripted_evaluation(tmp_path, scenario)

    _assert_diagnostics(
        tmp_path,
        diagnostics,
        scenario,
        expected_artifact="Containerfile",
    )


def test_static_frontend_check_accepts_served_static_frontend_docs(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        '<link rel="stylesheet" href="styles.css">\n'
        '<form><input name="title"></form><ul></ul>\n'
        '<p id="error"></p><script src="app.js"></script>\n'
    )
    (static_dir / "app.js").write_text(
        "async function load(){ await fetch('/todos'); }\n"
        "async function add(){ await fetch('/todos', {method: 'POST'}); }\n"
        "async function remove(id){ await fetch(`/todos/${id}`, {method: 'DELETE'}); }\n"
        "function showError(error){ console.log(error); }\n"
    )
    (static_dir / "styles.css").write_text("body { font-family: sans-serif; }\n")
    (tmp_path / "README.md").write_text(
        "# Todo API and Static Frontend\n\n"
        "Open the static frontend at http://127.0.0.1:8000/. The same server "
        "serves /index.html, /app.js, and /styles.css.\n"
    )

    result = static_frontend_check(tmp_path)

    assert result.passed is True


def test_static_frontend_check_rejects_frontend_build_artifacts(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        '<link rel="stylesheet" href="styles.css">\n'
        '<form><input name="title"></form><ul></ul>\n'
        '<p id="error"></p><script src="app.js"></script>\n'
    )
    (static_dir / "app.js").write_text(
        "fetch('/todos', {method: 'POST'});\n"
        "fetch('/todos/1', {method: 'DELETE'});\n"
    )
    (static_dir / "styles.css").write_text("body {}\n")
    (tmp_path / "README.md").write_text("Static frontend instructions.\n")
    (tmp_path / "package.json").write_text("{}\n")

    result = static_frontend_check(tmp_path)

    assert result.passed is False
    assert "package.json" in result.message


def test_integrator_rework_summary_counts_integrator_findings(tmp_path: Path) -> None:
    tracker = FileFindingTracker(tmp_path)
    integrator_open = tracker.create(
        title="Integrator open",
        source="integrator",
        milestone="M1",
        body="# Finding\n",
    )
    integrator_resolved = tracker.create(
        title="Integrator resolved",
        source="integrator",
        milestone="M1",
        body="# Finding\n",
    )
    tracker.mark_resolved(integrator_resolved.id)
    tracker.create(
        title="Architect finding",
        source="architect",
        milestone="M1",
        body="# Finding\n",
    )

    summary = derive_integrator_rework_summary(tracker.list_findings())

    assert summary == IntegratorReworkSummary(
        findings_created=2,
        findings_resolved=1,
        findings_open=1,
        findings_planned=0,
        finding_ids=[integrator_open.id, integrator_resolved.id],
        has_integrator_rework=True,
    )


def test_integrator_rework_summary_reports_clean_integration(tmp_path: Path) -> None:
    tracker = FileFindingTracker(tmp_path)
    tracker.create(
        title="Architect finding",
        source="architect",
        milestone="M1",
        body="# Finding\n",
    )

    summary = derive_integrator_rework_summary(tracker.list_findings())

    assert summary == IntegratorReworkSummary(
        findings_created=0,
        findings_resolved=0,
        findings_open=0,
        findings_planned=0,
        finding_ids=[],
        has_integrator_rework=False,
    )


def test_task_cycle_metrics_distinguish_planned_tasks_from_rework(tmp_path: Path) -> None:
    tasks_dir = tmp_path / ".devlab/tasks"
    history = tmp_path / ".devlab/history"
    tasks_dir.mkdir(parents=True)
    history.mkdir(parents=True)
    _write_minimal_task(tasks_dir / "T0001_first.md", "T0001", "First")
    _write_minimal_task(tasks_dir / "T0002_second.md", "T0002", "Second")
    _write_handoff(
        history / "20260519T091112_developer_handoff.md",
        "developer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091113_reviewer_handoff.md",
        "reviewer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091114_developer_handoff.md",
        "developer",
        ".devlab/tasks/T0002_second.md",
    )
    _write_handoff(
        history / "20260519T091115_reviewer_handoff.md",
        "reviewer",
        ".devlab/tasks/T0002_second.md",
    )

    sessions = derive_session_records(tmp_path)
    task_cycles = derive_task_cycle_metrics(tmp_path, sessions)
    rework = derive_task_rework_summary(task_cycles)

    assert [session.task_id for session in sessions] == [
        "T0001",
        "T0001",
        "T0002",
        "T0002",
    ]
    assert task_cycles.tasks["T0001"] == TaskCycleEntry(
        developer_sessions=1, reviewer_sessions=1, has_rework=False,
    )
    assert task_cycles.tasks["T0002"] == TaskCycleEntry(
        developer_sessions=1, reviewer_sessions=1, has_rework=False,
    )
    assert rework.tasks_with_rework == []
    assert rework.has_task_rework is False


def test_task_cycle_metrics_detect_repeated_same_task_cycles(tmp_path: Path) -> None:
    tasks_dir = tmp_path / ".devlab/tasks"
    history = tmp_path / ".devlab/history"
    tasks_dir.mkdir(parents=True)
    history.mkdir(parents=True)
    _write_minimal_task(tasks_dir / "T0001_first.md", "T0001", "First")
    _write_handoff(
        history / "20260519T091112_developer_handoff.md",
        "developer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091113_reviewer_handoff.md",
        "reviewer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091114_developer_handoff.md",
        "developer",
        ".devlab/tasks/T0001_first.md",
    )
    _write_handoff(
        history / "20260519T091115_reviewer_handoff.md",
        "reviewer",
        ".devlab/tasks/T0001_first.md",
    )

    task_cycles = derive_task_cycle_metrics(tmp_path)
    rework = derive_task_rework_summary(task_cycles)

    assert task_cycles.tasks["T0001"] == TaskCycleEntry(
        developer_sessions=2, reviewer_sessions=2, has_rework=True,
    )
    assert rework.tasks_with_rework == ["T0001"]
    assert rework.has_task_rework is True
    assert rework.max_developer_sessions_per_task == 2
    assert rework.max_reviewer_sessions_per_task == 2


def test_task_cycle_metrics_count_unattributed_task_sessions(tmp_path: Path) -> None:
    history = tmp_path / ".devlab/history"
    history.mkdir(parents=True)
    _write_handoff(history / "20260519T091112_developer_handoff.md", "developer", "README.md")

    task_cycles = derive_task_cycle_metrics(tmp_path)

    assert task_cycles.unattributed_developer_reviewer_sessions == 1


def test_live_review_rejections_count_reviewer_handoffs_with_open_issues(
    tmp_path: Path,
) -> None:
    history = tmp_path / ".devlab/history"
    history.mkdir(parents=True)
    (history / "20260519T091112_reviewer_handoff.md").write_text(
        "# Handoff: reviewer\n"
        "## Done\n- Reviewed.\n"
        "## Changed Artifacts\n- None\n"
        "## Open Issues\n- Response shape is wrong.\n"
        "## Addressed Findings\n- None\n"
        "## Next Session Hint\nFix response shape.\n"
    )
    (history / "20260519T091113_reviewer_handoff.md").write_text(
        "# Handoff: reviewer\n"
        "## Done\n- Reviewed.\n"
        "## Changed Artifacts\n- None\n"
        "## Open Issues\n- None\n"
        "## Addressed Findings\n- None\n"
        "## Next Session Hint\nContinue.\n"
    )

    assert derive_review_rejections(tmp_path) == 1


def test_live_role_sequence_handles_archive_collision_filenames(tmp_path: Path) -> None:
    history = tmp_path / ".devlab/history"
    history.mkdir(parents=True)
    (history / "20260519T091112_reviewer_handoff.md").write_text("reviewer")
    (history / "20260519T091112_2_developer_handoff.md").write_text("developer")

    assert derive_role_sequence(tmp_path) == ["reviewer", "developer"]


def test_collect_profile_metrics_lists_profiles_and_task_usage(tmp_path: Path) -> None:
    profiles_dir = tmp_path / ".devlab/config/profiles"
    tasks_dir = tmp_path / ".devlab/tasks"
    profiles_dir.mkdir(parents=True)
    tasks_dir.mkdir(parents=True)
    (profiles_dir / "default.toml").write_text(
        'version = 1\nid = "default"\ntitle = "Default"\n\n'
        '[tooling]\ndefault_validation = []\n\n'
        '[environment]\nmanaged_roles = []\n'
    )
    (profiles_dir / "python-app.toml").write_text(
        'version = 1\nid = "python-app"\ntitle = "Python App"\n\n'
        '[tooling]\ndefault_validation = ["uv run pytest"]\n\n'
        '[environment]\nmanaged_roles = ["developer"]\n'
    )
    _write_minimal_task(tasks_dir / "T0001_default.md", "T0001", "Default")
    _write_minimal_task(
        tasks_dir / "T0002_python.md",
        "T0002",
        "Python",
        profile="python-app",
    )

    metrics = collect_profile_metrics(tmp_path)

    assert metrics.count == 2
    assert metrics.ids == ["default", "python-app"]
    assert metrics.non_default_ids == ["python-app"]
    assert metrics.tasks_by_profile == {"default": ["T0001"], "python-app": ["T0002"]}
    assert metrics.items[1].default_validation_count == 1
    assert metrics.items[1].managed_roles == ["developer"]


def test_quality_summary_warns_for_rework_and_large_ignored_artifacts() -> None:
    summary = quality_summary(
        checks=[CheckResult("ok", True)],
        task_metrics=TaskMetrics(total=1, by_status={"closed": 1}, items=[]),
        artifact_hygiene=ArtifactHygiene(
            file_count=0, total_bytes=0, product_file_count=0, product_total_bytes=0,
            ignored_file_count=5_001, ignored_total_bytes=100_000_001,
            devlab_file_count=0, devlab_total_bytes=0,
            flagged_paths=[],
        ),
        sessions_run=7,
        task_rework=TaskReworkSummary(
            tasks_with_rework=["T0001"], has_task_rework=True,
            max_developer_sessions_per_task=0, max_reviewer_sessions_per_task=0,
            unattributed_developer_reviewer_sessions=0,
        ),
        integrator_rework=IntegratorReworkSummary(
            findings_created=1, findings_resolved=0, findings_open=1,
            findings_planned=0, finding_ids=[], has_integrator_rework=True,
        ),
    )

    assert summary.correctness_passed is True
    assert "task rework detected: T0001" in summary.warnings
    assert "integrator findings created: 1" in summary.warnings
    assert "high session count per closed task: 7/1" in summary.warnings
    assert "large ignored artifact footprint: 100000001 bytes" in summary.warnings
    assert "large ignored artifact file count: 5001" in summary.warnings


def test_artifact_hygiene_splits_git_product_ignored_and_devlab_files(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text(".venv/\n.pytest_cache/\n__pycache__/\n")
    (tmp_path / ".devlab/tasks").mkdir(parents=True)
    (tmp_path / ".devlab/tasks/T0001_task.md").write_text("workflow")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('ok')\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_app.py").write_text("def test_ok(): pass\n")
    (tmp_path / ".venv/lib").mkdir(parents=True)
    (tmp_path / ".venv/lib/site.py").write_text("ignored\n")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache/cache.txt").write_text("ignored\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/app.pyc").write_bytes(b"ignored")

    hygiene = collect_artifact_hygiene(tmp_path)

    assert hygiene.product_file_count == 3
    assert hygiene.ignored_file_count == 3
    assert hygiene.devlab_file_count == 1
    assert hygiene.flagged_paths == []
    assert {item.path for item in hygiene.product_top_contributors} == {
        ".gitignore", "src/", "tests/",
    }
    assert [(item.path, item.file_count) for item in hygiene.devlab_top_contributors] == [
        (".devlab/tasks/", 1),
    ]
    contributors = [
        (item.path, item.file_count, item.total_bytes)
        for item in hygiene.ignored_top_contributors
    ]
    assert contributors == [
        (".pytest_cache/", 1, 8),
        (".venv/", 1, 8),
        ("__pycache__/", 1, 7),
    ]


def test_diagnostics_verbose_reports_product_ignored_and_devlab_contributors(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text("cache/\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.txt").write_text("product\n")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache/data.bin").write_text("ignored\n")
    (tmp_path / ".devlab/logs").mkdir(parents=True)
    (tmp_path / ".devlab/logs/session.log").write_text("devlab\n")

    output = format_workflow_diagnostics(tmp_path, verbose=True)

    assert "Artifact contributors:" in output
    assert "- product: src/: 1 files, 8 bytes" in output
    assert "- ignored: cache/: 1 files, 8 bytes" in output
    assert "- devlab: .devlab/logs/: 1 files, 7 bytes" in output


def test_diagnostics_reports_top_ignored_artifact_contributors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text("build/\ncache/\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build/large.bin").write_bytes(b"x" * 10)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache/small.bin").write_bytes(b"x" * 5)
    monkeypatch.setattr("devlab.artifact_hygiene.LARGE_IGNORED_BYTES_WARNING", 1)
    monkeypatch.setattr("devlab.workflow_diagnostics.LARGE_IGNORED_BYTES_WARNING", 1)

    output = format_workflow_diagnostics(tmp_path)

    assert "large ignored artifact footprint: 15 bytes" in output
    assert "Top ignored artifact contributors:" in output
    assert "- build/: 1 files, 10 bytes" in output
    assert "- cache/: 1 files, 5 bytes" in output


def test_artifact_hygiene_counts_unignored_files_as_product(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    (tmp_path / ".venv/lib").mkdir(parents=True)
    (tmp_path / ".venv/lib/site.py").write_text("not ignored\n")

    hygiene = collect_artifact_hygiene(tmp_path)

    assert hygiene.product_file_count == 1
    assert hygiene.ignored_file_count == 0
    assert hygiene.flagged_paths == []


def test_evaluation_init_creates_git_repo_when_absent(tmp_path: Path) -> None:
    init_target_workspace(tmp_path, "Build something small.")

    assert (tmp_path / ".git").exists()
    assert _git(tmp_path, "rev-parse", "--verify", "HEAD").returncode == 0


def test_evaluation_init_commits_existing_git_repo_setup(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "devlab-eval@example.invalid")
    _git(tmp_path, "config", "user.name", "DevLab Eval")
    _git(tmp_path, "commit", "--allow-empty", "-m", "Existing baseline")
    before = int(_git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip())

    init_target_workspace(tmp_path, "Build something small.")

    after = int(_git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip())
    assert after > before
    assert _git(tmp_path, "status", "--porcelain").stdout.strip() == ""


def _write_minimal_task(
    path: Path,
    task_id: str,
    title: str,
    *,
    profile: str | None = None,
) -> None:
    profile_line = f'profile = "{profile}"\n' if profile else ""
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{title}"\n'
        'status = "closed"\n'
        f"{profile_line}"
        'domain = "general"\n'
        "depends_on = []\n"
        "addresses_findings = []\n"
        "+++\n\n"
        f"# {task_id}: {title}\n"
    )


def _write_handoff(path: Path, role: str, changed_artifact: str) -> None:
    path.write_text(
        f"# Handoff: {role}\n"
        "## Done\n- Done.\n"
        f"## Changed Artifacts\n- `{changed_artifact}` (modified)\n"
        "## Open Issues\n- None\n"
        "## Addressed Findings\n- None\n"
        "## Next Session Hint\nContinue.\n"
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root.as_posix(), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _calculator_checks():
    return (
        command_check("add command", ["calculator.py", "add", "2", "3"], "5"),
        command_check("subtract command", ["calculator.py", "subtract", "7", "4"], "3"),
        command_check("add negative command", ["calculator.py", "add", "-2", "5"], "3"),
        command_check("subtract negative result", ["calculator.py", "subtract", "2", "5"], "-3"),
        command_fails_check("missing args exits nonzero", ["calculator.py"]),
    )


def _assert_diagnostics(
    root: Path,
    diagnostics: EvaluationDiagnostics,
    scenario: EvaluationScenario,
    *,
    expected_artifact: str,
) -> None:
    diagnostics_path = root / ".devlab/evaluations" / f"{scenario.id}.json"
    assert diagnostics.completed is True, diagnostics_path.read_text()
    assert diagnostics.exit_code == 0, diagnostics_path.read_text()
    assert diagnostics.sessions_run == scenario.expected_sessions
    assert tuple(diagnostics.roles) == scenario.expected_roles
    assert diagnostics.review_rejections == scenario.expected_rejections
    assert diagnostics.findings_created == scenario.expected_findings
    assert all(check.passed for check in diagnostics.checks), diagnostics.checks
    assert diagnostics.max_prompt_chars > 0
    assert expected_artifact in diagnostics.artifacts
    assert diagnostics.agent_log_dir.endswith(".devlab/logs/agents")
    assert diagnostics.tasks.total >= 1
    assert diagnostics.quality.correctness_passed is True
    assert diagnostics.quality.all_tasks_closed is True
    assert diagnostics.artifact_hygiene.file_count >= 0
    assert diagnostics.agent_logs.stdout_count >= 0
    assert scenario.expected_sessions is not None
    assert diagnostics.git.repository is True
    assert diagnostics.git.clean_worktree is True
    assert diagnostics.git.commit_count > diagnostics.git.baseline_commit_count
    assert diagnostics.git.session_commit_count >= scenario.expected_sessions
    assert diagnostics.git.missing_milestone_tags == []
    assert "devlab/milestone/M1" in diagnostics.git.milestone_tags
    assert diagnostics.git.tag_targets["devlab/milestone/M1"]
    task = FileTaskTracker(root).get("T0001")
    assert task.status == TaskStatus.CLOSED
    milestone = FileMilestoneTracker(root).get("M1")
    assert milestone.status == MilestoneStatus.ARCHITECTURE_REVIEWED

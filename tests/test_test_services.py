from __future__ import annotations

import dataclasses
import json
import os
import shlex
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest

from devlab.agents import AgentInvocation, MockProvider
from devlab.environment import (
    FileTestServiceTracker,
    TestServiceError,
    parse_test_service,
    prepare_test_service_private,
    run_validation_commands,
)
from devlab.environment import (
    test_service_lock as service_lock,
)
from devlab.executable_config import (
    authorize_executable_config,
    build_executable_config_snapshot,
)
from devlab.executable_config import (
    test_service_cleanup_snapshot as cleanup_snapshot,
)
from devlab.init import init_test_service_storage, init_workspace
from devlab.orchestrator import _TestServicePreparation, run_loop
from devlab.profiles import load_profiles, load_test_services
from devlab.spec_reconciliation import latest_spec_commit
from devlab.version_control import commit_all
from devlab.workflow_events import load_workflow_events
from devlab.workflow_state import update_workflow_state
from devlab.workspace import Workspace
from tests.helpers import complete_acceptance
from tests.test_orchestrator import _write_task

SCRIPT = """import json, os, sys
from pathlib import Path
p = Path(os.environ['DEVLAB_TEST_SERVICE_STATE_DIR'])
identity = os.environ['DEVLAB_TEST_SERVICE_INSTANCE']
resource = p / 'resource'
controls = p.parent.parent
phase = sys.argv[1]
if phase == 'ensure':
    with (controls / 'attempts').open('a') as f: f.write(identity + '\\n')
    if resource.exists():
        assert resource.read_text() == identity
    else:
        resource.write_text(identity)
    if (controls / 'fail').exists(): sys.exit(1)
    data = {'schema': 1, 'instance': identity,
            'environment': {'TEST_DATABASE_URL': 'secret-canary-' + identity}}
    target = Path(os.environ['DEVLAB_TEST_SERVICE_RESULT'])
    staged = target.with_suffix('.tmp')
    staged.write_text(json.dumps(data))
    staged.replace(target)
elif phase == 'check':
    assert resource.read_text() == identity
    assert os.environ['TEST_DATABASE_URL'] == 'secret-canary-' + identity
    if (controls / 'unhealthy').exists(): sys.exit(1)
elif phase == 'destroy':
    if (controls / 'fail-cleanup').exists(): sys.exit(1)
    if resource.exists():
        assert resource.read_text() == identity
        resource.unlink()
"""


@pytest.fixture
def target(tmp_path: Path) -> Path:
    init_workspace(tmp_path, automatic_git=True)
    init_test_service_storage(tmp_path)
    script = tmp_path / ".devlab/config/service.py"
    script.write_text(SCRIPT)
    command = f"{shlex.quote(sys.executable)} .devlab/config/service.py"
    (tmp_path / ".devlab/config/test-services.toml").write_text(
        "[services.db]\n"
        f"ensure = {json.dumps(command + ' ensure')}\n"
        f"check = {json.dumps(command + ' check')}\n"
        f"destroy = {json.dumps(command + ' destroy')}\n"
        'exports = ["TEST_DATABASE_URL"]\n'
    )
    profile = tmp_path / ".devlab/config/profiles/default.toml"
    profile.write_text(
        profile.read_text() + '\n[[test_services]]\nid = "db"\n'
        'required_for = ["session", "setup", "validation"]\n'
    )
    commit_all(tmp_path, "Configure services")
    return tmp_path


def ensure(target: Path) -> dict[str, str]:
    with service_lock(target):
        return Workspace(target).test_services().ensure(load_test_services(target)["db"])


def record(target: Path) -> dict:
    result = FileTestServiceTracker(target).read("db")
    assert result is not None
    return result


def private(target: Path) -> Path:
    return target / ".devlab/local/test-services" / record(target)["instance"]


def test_reuse_preserves_data_and_secrets_across_restart(target: Path) -> None:
    exports = ensure(target)
    (private(target) / "test-data").write_text("preserve me")
    assert ensure(target) == exports
    assert (private(target) / "test-data").read_text() == "preserve me"
    assert len((target / ".devlab/local/attempts").read_text().splitlines()) == 1
    assert record(target)["outcome"] == "reused"
    committed = subprocess.check_output(["git", "show", "HEAD"], cwd=target)
    assert b"secret-canary" not in committed
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=target)
    assert (private(target) / "result.json").stat().st_mode & 0o077 == 0


def test_partial_setup_retry_uses_original_identity(target: Path) -> None:
    flag = target / ".devlab/local/fail"
    flag.touch()
    with pytest.raises(TestServiceError, match="ensure failed"):
        ensure(target)
    identity = record(target)["instance"]
    assert record(target)["state"] == "failed"
    assert (private(target) / "resource").read_text() == identity
    flag.unlink()
    ensure(target)
    assert record(target)["instance"] == identity
    assert (target / ".devlab/local/attempts").read_text().splitlines() == [identity, identity]


def test_missing_exports_recover_without_replacing_service(target: Path) -> None:
    ensure(target)
    identity = record(target)["instance"]
    (private(target) / "result.json").unlink()
    ensure(target)
    assert record(target)["instance"] == identity


def test_cleanup_failure_requires_explicit_retry_and_preserves_other_resources(
    target: Path,
) -> None:
    ensure(target)
    unrelated = target / ".devlab/local/unrelated"
    unrelated.write_text("keep")
    flag = target / ".devlab/local/fail-cleanup"
    flag.touch()
    service = load_test_services(target)["db"]
    with service_lock(target), pytest.raises(TestServiceError, match="cleanup failed"):
        Workspace(target).test_services().cleanup(service)
    assert record(target)["state"] == "cleanup_failed"
    with pytest.raises(TestServiceError, match="cleanup db"):
        ensure(target)
    flag.unlink()
    with service_lock(target):
        Workspace(target).test_services().cleanup(service)
        Workspace(target).test_services().cleanup(service)
    assert record(target)["state"] == "destroyed"
    assert unrelated.read_text() == "keep"
    assert not (private(target) / "resource").exists()
    assert not (private(target) / "result.json").exists()


def test_lock_contention_blocks_cleanup_and_releases_after_exit(target: Path) -> None:
    with (
        service_lock(target),
        pytest.raises(TestServiceError, match="in use"),
        service_lock(target),
    ):
        pytest.fail("lock acquired twice")
    ensure(target)


def test_host_check_failure_does_not_provision(target: Path) -> None:
    service = dataclasses.replace(load_test_services(target)["db"], host_checks=("exit 1",))
    with service_lock(target), pytest.raises(TestServiceError, match="host prerequisite"):
        Workspace(target).test_services().ensure(service)
    assert not (target / ".devlab/local/attempts").exists()


def test_changed_definition_and_moved_workspace_do_not_adopt(target: Path) -> None:
    ensure(target)
    original = load_test_services(target)["db"]
    with service_lock(target), pytest.raises(TestServiceError, match="changed"):
        Workspace(target).test_services().ensure(dataclasses.replace(original, ensure="false"))
    saved = record(target)
    saved["workspace"] = "/another/workspace"
    (target / ".devlab/test-services/db.json").write_text(json.dumps(saved))
    with service_lock(target), pytest.raises(TestServiceError, match="another workspace"):
        Workspace(target).test_services().ensure(original)
    with service_lock(target), pytest.raises(TestServiceError, match="original workspace"):
        Workspace(target).test_services().cleanup(original)


@pytest.mark.parametrize(
    "change",
    [
        {"ensure_timeout_seconds": True},
        {"check_timeout_seconds": 0},
        {"exports": ["PATH"]},
        {"exports": ["DEVLAB_SESSION_ENVELOPE"]},
        {"exports": ["TEST_DATABASE_URL", "TEST_DATABASE_URL"]},
        {"unknown": "value"},
    ],
)
def test_rejects_invalid_declarations(target: Path, change: dict) -> None:
    data = load_test_services(target)["db"].definition() | change
    with pytest.raises(TestServiceError):
        parse_test_service("db", data)


def test_services_are_frozen_and_authorized(target: Path) -> None:
    snapshot = build_executable_config_snapshot(target)
    with ExitStack() as stack:
        preparation = _TestServicePreparation(target, stack, snapshot)
        with pytest.raises(TestServiceError, match="authorized"):
            preparation.prepare(tuple(snapshot.profiles.values()), ("session",))
    authorized = dataclasses.replace(
        snapshot, authorization=authorize_executable_config(snapshot, accept_current=True)
    )
    source = target / ".devlab/config/test-services.toml"
    source.write_text(source.read_text().replace("service.py ensure", "service.py invalid"))
    assert build_executable_config_snapshot(target).digest != snapshot.digest
    with ExitStack() as stack:
        preparation = _TestServicePreparation(target, stack, authorized)
        result = preparation.prepare(tuple(snapshot.profiles.values()), ("session",))
        assert result["TEST_DATABASE_URL"].startswith("secret-canary-")
        with pytest.raises(TestServiceError, match="absent"):
            preparation.prepare(tuple(load_profiles(target).values()), ("session",))
    historical = cleanup_snapshot(target, snapshot.test_services["db"])
    assert historical.digest != cleanup_snapshot(target, load_test_services(target)["db"]).digest


def test_unignored_and_symlinked_private_storage_rejected(target: Path, tmp_path: Path) -> None:
    (target / ".devlab/.gitignore").unlink()
    with pytest.raises(TestServiceError, match="storage"):
        prepare_test_service_private(target)
    (target / ".devlab/.gitignore").write_text("/local/\n")
    external = target / "outside"
    external.mkdir()
    (target / ".devlab/local/test-services/trap").symlink_to(external, target_is_directory=True)
    # A result symlink must never be read, overwritten, or sourced.
    ensure(target)
    result = private(target) / "result.json"
    result.unlink()
    result.symlink_to(external / "secret")
    with pytest.raises(TestServiceError, match="symlinks"):
        ensure(target)
    assert not (external / "secret").exists()


def test_validation_receives_explicit_environment(
    target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = ensure(target)
    monkeypatch.setenv("TEST_DATABASE_URL", "production")
    code = "import os; assert os.environ['TEST_DATABASE_URL'].startswith('secret-canary-')"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    result = run_validation_commands(
        target,
        role_name="developer",
        task_id="T1",
        session_id="test",
        commands=(command,),
        environ=exports,
    )
    assert result.outcome == "passed"
    assert os.environ["TEST_DATABASE_URL"] == "production"


@pytest.mark.parametrize("fail_after_session", [False, True])
def test_provider_and_validation_receive_service_on_continue(
    target: Path, fail_after_session: bool
) -> None:
    (target / ".devlab/plans/design-plan.md").write_text("# Design\n")
    (target / ".devlab/plans/project-plan.md").write_text("# Plan\n")
    _write_task(target, "T0001", validation=["test -n $TEST_DATABASE_URL"])
    profile = target / ".devlab/config/profiles/default.toml"
    profile.write_text(
        profile.read_text() + '\n[[prerequisites]]\nid="database"\n'
        'required_for=["session", "validation"]\nenvironment="TEST_DATABASE_URL"\n'
    )
    update_workflow_state(
        target, planning_complete=True, last_planned_spec_commit=latest_spec_commit(target)
    )
    commit_all(target, "Ready test task")
    snapshot = build_executable_config_snapshot(target)
    snapshot = dataclasses.replace(
        snapshot, authorization=authorize_executable_config(snapshot, accept_current=True)
    )

    def invoke(call: AgentInvocation) -> None:
        assert call.environment["TEST_DATABASE_URL"].startswith("secret-canary-")
        assert "secret-canary" not in call.session_prompt
        complete_acceptance(target, "T0001")
        (target / "product.txt").write_text("implementation")
        if fail_after_session:
            (target / ".devlab/local/unhealthy").touch()
        with pytest.raises(TestServiceError, match="in use"), service_lock(target):
            pass

    provider = MockProvider(on_invoke=invoke)
    result = run_loop(
        target, max_sessions=1, agent_providers={"default": provider}, executable_config=snapshot
    )
    if fail_after_session:
        from devlab.orchestrator import RunStopReason

        assert result.stop_reason == RunStopReason.VALIDATION_INFRASTRUCTURE_ERROR
        assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=target)
        assert not Workspace(target).snapshot.list_findings()
        attempts = list((target / ".devlab/verification/tasks/T0001").glob("*.json"))
        assert len(attempts) == 1
        assert json.loads(attempts[0].read_text())["outcome"] == "infrastructure_error"
        (target / ".devlab/local/unhealthy").unlink()

        def review(call: AgentInvocation) -> None:
            assert call.role_name == "reviewer"
            outcomes = [
                json.loads(path.read_text())["outcome"]
                for path in (target / ".devlab/verification/tasks/T0001").glob("*.json")
            ]
            assert "passed" in outcomes
            assert call.environment["TEST_DATABASE_URL"].startswith("secret-canary-")

        reviewer = MockProvider(on_invoke=review, return_code=1, write_handoff=False)
        run_loop(
            target,
            max_sessions=1,
            agent_providers={"default": reviewer},
            executable_config=snapshot,
        )
        assert len(reviewer.calls) == 1
        return
    assert result.exit_code == 0, result.errors
    assert len(provider.calls) == 1
    assert result.test_service_duration_seconds > 0
    validations = list((target / ".devlab/verification/tasks/T0001").glob("*.json"))
    assert len(validations) == 1
    assert json.loads(validations[0].read_text())["outcome"] == "passed"
    assert record(target)["state"] == "ready"
    assert "secret-canary" not in subprocess.check_output(
        ["git", "show", "HEAD"], cwd=target, text=True
    )


def test_owned_service_prerequisite_initializes_before_agent(target: Path) -> None:
    (target / ".devlab/plans/design-plan.md").write_text("# Design\n")
    (target / ".devlab/plans/project-plan.md").write_text("# Plan\n")
    _write_task(target, "T0001")
    profile = target / ".devlab/config/profiles/default.toml"
    profile.write_text(
        profile.read_text()
        + "\n[[prerequisites]]\n"
        + 'id = "schema"\n'
        + 'required_for = ["session"]\n'
        + 'check = "test -f .devlab/local/schema-ready"\n'
        + 'prepare = "test -n $TEST_DATABASE_URL && touch .devlab/local/schema-ready"\n'
        + 'prepare_kind = "owned_service"\n'
    )
    update_workflow_state(
        target,
        planning_complete=True,
        last_planned_spec_commit=latest_spec_commit(target),
    )
    commit_all(target, "Add owned service initialization")
    snapshot = build_executable_config_snapshot(target)
    snapshot = dataclasses.replace(
        snapshot,
        authorization=authorize_executable_config(snapshot, accept_current=True),
    )

    def invoke(call: AgentInvocation) -> None:
        assert (target / ".devlab/local/schema-ready").exists()
        complete_acceptance(target, "T0001")
        (target / "product.txt").write_text("implementation")

    provider = MockProvider(on_invoke=invoke)
    result = run_loop(
        target,
        max_sessions=1,
        agent_providers={"default": provider},
        executable_config=snapshot,
    )

    assert result.exit_code == 0, result.errors
    assert len(provider.calls) == 1
    events = load_workflow_events(target)
    attempts = [event for event in events if event.type == "prerequisite_prepared"]
    assert len(attempts) == 1
    assert attempts[0].data["outcome"] == "succeeded"


def test_timeout_preserves_recoverable_record(target: Path) -> None:
    service = dataclasses.replace(
        load_test_services(target)["db"],
        ensure="sleep 30",
        ensure_timeout_seconds=1,
    )
    with service_lock(target), pytest.raises(TestServiceError, match="timed out"):
        Workspace(target).test_services().ensure(service)
    assert record(target)["state"] == "failed"


def test_malformed_exports_never_mark_ready(target: Path) -> None:
    service = dataclasses.replace(
        load_test_services(target)["db"],
        ensure='echo invalid > "$DEVLAB_TEST_SERVICE_RESULT"',
    )
    with service_lock(target), pytest.raises(TestServiceError, match="exports"):
        Workspace(target).test_services().ensure(service)
    assert record(target)["state"] == "failed"


def test_read_only_status_and_cleanup_authorization(target: Path, monkeypatch, capsys) -> None:
    from devlab.cli import main

    ensure(target)
    before = (target / ".devlab/local/attempts").read_text()
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(target / ".devlab/local/trust"))
    monkeypatch.setattr(sys, "argv", ["devlab", "test-service", "--root", str(target), "status"])
    main()
    assert "last observed" in capsys.readouterr().out
    assert (target / ".devlab/local/attempts").read_text() == before
    argv = ["devlab", "test-service", "--root", str(target), "cleanup", "db"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert (private(target) / "resource").exists()
    monkeypatch.setattr(sys, "argv", [*argv, "--accept-current-exec-config"])
    main()
    assert record(target)["state"] == "destroyed"


def test_milestone_deduplication_keeps_different_service_bindings(target: Path) -> None:
    from devlab.environment import TestServiceReference
    from devlab.profiles import effective_milestone_validation
    from devlab.task_tracker import FileTaskTracker

    _write_task(target, "T0001", validation=["echo check"], profile="default")
    _write_task(target, "T0002", validation=["echo check"], profile="other")
    profiles = load_profiles(target)
    profiles["other"] = dataclasses.replace(profiles["default"], id="other", test_services=())
    tasks = FileTaskTracker(target).list_tasks()
    result = effective_milestone_validation(tasks, profiles, root=target)
    assert len(result.commands) == 2
    assert {item.service_ids for item in result.commands} == {("db",), ()}
    profiles["other"] = dataclasses.replace(
        profiles["other"],
        test_services=(TestServiceReference(load_test_services(target)["db"], ("validation",)),),
    )
    result = effective_milestone_validation(tasks, profiles, root=target)
    assert len(result.commands) == 1
    assert result.commands[0].task_ids == ("T0001", "T0002")


@pytest.mark.skipif(
    os.environ.get("DEVLAB_TEST_DOCKER") != "1", reason="optional Docker integration"
)
def test_docker_postgres_reuse_and_cleanup(target: Path) -> None:
    import shutil

    if shutil.which("docker") is None:
        pytest.skip("Docker is an unverified operator prerequisite")
    for args in [("info",), ("image", "inspect", "postgres:16")]:
        if subprocess.run(["docker", *args], capture_output=True, timeout=20).returncode:
            pytest.skip("Docker daemon and local postgres:16 image are operator prerequisites")
    source = Path(__file__).parents[1] / "demos/managed-test-services/postgres.py"
    (target / ".devlab/config/postgres.py").write_text(source.read_text())
    prefix = f"{shlex.quote(sys.executable)} .devlab/config/postgres.py"
    service = dataclasses.replace(
        load_test_services(target)["db"],
        ensure=prefix + " ensure",
        check=prefix + " check",
        destroy=prefix + " destroy",
    )
    commit_all(target, "Install owned PostgreSQL fixture")
    with service_lock(target):
        try:
            first = Workspace(target).test_services().ensure(service)
            name = "devlab-test-" + record(target)["instance"]
            command = ["docker", "exec", name, "psql", "-U", "devlab", "-d", "devlab", "-Atc"]
            subprocess.run(
                [
                    *command,
                    "CREATE TABLE preserved (value integer); INSERT INTO preserved VALUES (42)",
                ],
                check=True,
            )
            assert Workspace(target).test_services().ensure(service) == first
            assert (
                subprocess.check_output(
                    [*command, "SELECT value FROM preserved"], text=True
                ).strip()
                == "42"
            )
        finally:
            Workspace(target).test_services().cleanup(service)
    assert record(target)["state"] == "destroyed"

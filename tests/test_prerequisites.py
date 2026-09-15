from __future__ import annotations

import dataclasses
import json
import shlex
import sys
from pathlib import Path

import pytest

from devlab.prerequisites import (
    FilePrerequisiteTracker,
    Prerequisite,
    PrerequisiteOperation,
    PrerequisiteStatus,
    attest_prerequisite,
    evaluate_prerequisites,
    format_prerequisite_result,
    prerequisite_is_attested,
    read_prerequisite_guide,
    resolve_prerequisites,
    revoke_prerequisite_attestation,
)


def test_automatic_prerequisites_check_environment_and_command(tmp_path: Path) -> None:
    environment = Prerequisite(
        "api",
        "database-url",
        (PrerequisiteOperation.VALIDATION,),
        "Database URL",
        environment="TEST_DATABASE_URL",
    )
    command = Prerequisite(
        "api",
        "service",
        (PrerequisiteOperation.SESSION,),
        "Service",
        check="true",
    )

    missing = evaluate_prerequisites(
        tmp_path, (environment,), PrerequisiteOperation.VALIDATION, environ={}
    )[0]
    present = evaluate_prerequisites(
        tmp_path,
        (environment,),
        PrerequisiteOperation.VALIDATION,
        environ={"TEST_DATABASE_URL": "secret"},
    )[0]
    checked = evaluate_prerequisites(tmp_path, (command,), PrerequisiteOperation.SESSION)[0]

    assert missing.status == PrerequisiteStatus.UNSATISFIED
    assert present.status == PrerequisiteStatus.SATISFIED
    assert "secret" not in present.detail
    assert checked.status == PrerequisiteStatus.SATISFIED


def test_resolvable_prerequisite_prepares_once_and_rechecks(tmp_path: Path) -> None:
    state = tmp_path / "ready"
    code = f"from pathlib import Path; Path({str(state)!r}).write_text('ready')"
    prerequisite = Prerequisite(
        "api",
        "test-config",
        (PrerequisiteOperation.SESSION,),
        "Local test configuration",
        check=f"test -f {shlex.quote(str(state))}",
        prepare=f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}",
        prepare_kind="workspace_local",
        prepare_outputs=("ready",),
    )

    first = resolve_prerequisites(tmp_path, (prerequisite,), PrerequisiteOperation.SESSION)
    second = resolve_prerequisites(tmp_path, (prerequisite,), PrerequisiteOperation.SESSION)

    assert first.results[0].status == PrerequisiteStatus.SATISFIED
    assert first.preparations[0].outcome == "succeeded"
    assert second.results[0].status == PrerequisiteStatus.SATISFIED
    assert second.preparations == ()


def test_missing_host_executable_is_not_prepared(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    prerequisite = Prerequisite(
        "api",
        "tool",
        (PrerequisiteOperation.SESSION,),
        "Host tool",
        check="devlab-command-that-does-not-exist",
        prepare=f"touch {shlex.quote(str(marker))}",
        prepare_kind="workspace_local",
        prepare_outputs=("must-not-exist",),
    )

    resolution = resolve_prerequisites(tmp_path, (prerequisite,), PrerequisiteOperation.SESSION)

    assert resolution.results[0].status == PrerequisiteStatus.UNVERIFIED
    assert resolution.preparations == ()
    assert not marker.exists()


def test_failed_and_sensitive_preparation_is_bounded_and_redacted(tmp_path: Path) -> None:
    prerequisite = Prerequisite(
        "api",
        "fixture",
        (PrerequisiteOperation.VALIDATION,),
        "Test fixture",
        check="false",
        prepare="printf secret-canary; exit 4",
        prepare_kind="workspace_local",
        prepare_outputs=("fixture",),
        sensitive=True,
    )

    resolution = resolve_prerequisites(tmp_path, (prerequisite,), PrerequisiteOperation.VALIDATION)

    assert resolution.results[0].status == PrerequisiteStatus.ERROR
    assert resolution.preparations[0].return_code == 4
    log = tmp_path / resolution.preparations[0].log_path
    assert "secret-canary" not in log.read_text()
    assert "output redacted" in log.read_text()


def test_successful_preparation_that_does_not_satisfy_check_still_blocks(
    tmp_path: Path,
) -> None:
    prerequisite = Prerequisite(
        "api",
        "fixture",
        (PrerequisiteOperation.VALIDATION,),
        "Test fixture",
        check="false",
        prepare="true",
        prepare_kind="workspace_local",
        prepare_outputs=("fixture",),
    )

    resolution = resolve_prerequisites(tmp_path, (prerequisite,), PrerequisiteOperation.VALIDATION)

    assert resolution.preparations[0].outcome == "succeeded"
    assert resolution.results[0].status == PrerequisiteStatus.UNSATISFIED
    assert "still unsatisfied after preparation" in resolution.results[0].detail


def test_operator_attestation_is_durable_until_revoked_or_definition_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVLAB_STATE_HOME", str(tmp_path / "operator-state"))
    prerequisite = Prerequisite(
        "deploy",
        "authorized",
        (PrerequisiteOperation.SESSION,),
        "Deployment authorization",
        attestation="I am authorized to deploy.",
    )

    assert not prerequisite_is_attested(tmp_path, prerequisite)
    record_path = attest_prerequisite(
        tmp_path, prerequisite, operator="tester", note="Approved test database."
    )
    assert prerequisite_is_attested(tmp_path, prerequisite)
    record_text = record_path.read_text()
    assert '"operator": "tester"' in record_text
    assert "Approved test database." in record_text
    changed = dataclasses.replace(prerequisite, attestation="I am authorized for production.")
    assert not prerequisite_is_attested(tmp_path, changed)
    assert revoke_prerequisite_attestation(tmp_path, prerequisite)
    assert not prerequisite_is_attested(tmp_path, prerequisite)


def test_unchanged_blocker_record_is_idempotent(tmp_path: Path) -> None:
    prerequisite = Prerequisite(
        "api",
        "database-url",
        (PrerequisiteOperation.SESSION,),
        "Database URL",
        environment="TEST_DATABASE_URL",
    )
    result = evaluate_prerequisites(
        tmp_path, (prerequisite,), PrerequisiteOperation.SESSION, environ={}
    )
    tracker = FilePrerequisiteTracker(tmp_path)

    first = tracker.record_blocker(
        command="implement",
        role="developer",
        task="T0001",
        milestone="",
        operation=PrerequisiteOperation.SESSION,
        results=result,
    )
    first_text = tracker.path.read_text()
    second = tracker.record_blocker(
        command="implement",
        role="developer",
        task="T0001",
        milestone="",
        operation=PrerequisiteOperation.SESSION,
        results=result,
    )

    assert first
    assert not second
    assert tracker.path.read_text() == first_text
    blocker = tracker.read_blocker()
    assert blocker is not None
    assert blocker.command == "implement"


def test_blocker_round_trip_preserves_resolution_mechanism(tmp_path: Path) -> None:
    prerequisite = Prerequisite(
        "deploy",
        "docker",
        (PrerequisiteOperation.SESSION,),
        "Reachable Docker daemon",
        check="make require-docker",
    )
    result = evaluate_prerequisites(tmp_path, (prerequisite,), PrerequisiteOperation.SESSION)
    tracker = FilePrerequisiteTracker(tmp_path)

    tracker.record_blocker(
        command="continue",
        role="developer",
        task="T0001",
        milestone="",
        operation=PrerequisiteOperation.SESSION,
        results=result,
    )

    blocker = tracker.read_blocker()
    assert blocker is not None
    assert blocker.results[0].prerequisite.check == "make require-docker"


def test_legacy_blocker_without_resolution_mechanism_remains_readable(tmp_path: Path) -> None:
    tracker = FilePrerequisiteTracker(tmp_path)
    tracker.path.parent.mkdir(parents=True)
    tracker.path.write_text(
        json.dumps(
            {
                "version": 1,
                "command": "continue",
                "role": "developer",
                "task": "T0001",
                "milestone": "",
                "operation": "session",
                "recorded_at": "2026-01-01T00:00:00+00:00",
                "results": [
                    {
                        "profile": "deploy",
                        "id": "docker",
                        "required_for": ["session"],
                        "summary": "Reachable Docker daemon",
                        "guide": "README.md",
                        "sensitive": False,
                        "status": "unsatisfied",
                        "detail": "check exited with 1",
                    }
                ],
            }
        )
    )

    blocker = tracker.read_blocker()

    assert blocker is not None
    assert blocker.results[0].prerequisite.check == ""


def test_prerequisite_guide_renders_only_referenced_markdown_section(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text(
        "# Project\n\nOverview.\n\n"
        "## Docker daemon\n\nInstall and start Docker.\n\n"
        "### Verify\n\nRun `docker info`.\n\n"
        "## Database\n\nProvision PostgreSQL.\n"
    )
    prerequisite = Prerequisite(
        "deploy",
        "docker",
        (PrerequisiteOperation.SESSION,),
        "Reachable Docker daemon",
        check="make require-docker",
        guide="README.md#docker-daemon",
    )
    result = evaluate_prerequisites(tmp_path, (prerequisite,), PrerequisiteOperation.SESSION)[0]

    guide = read_prerequisite_guide(tmp_path, prerequisite)
    rendered = format_prerequisite_result(tmp_path, result)

    assert guide is not None
    assert guide.startswith("## Docker daemon")
    assert "Run `docker info`." in guide
    assert "Provision PostgreSQL" not in guide
    assert "Check: make require-docker" in rendered
    assert "Resolution guide:\n## Docker daemon" in rendered


def test_prerequisite_guide_reports_missing_heading(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project\n")
    prerequisite = Prerequisite(
        "deploy",
        "docker",
        (PrerequisiteOperation.SESSION,),
        "Reachable Docker daemon",
        check="false",
        guide="README.md#docker-daemon",
    )
    result = evaluate_prerequisites(tmp_path, (prerequisite,), PrerequisiteOperation.SESSION)[0]

    rendered = format_prerequisite_result(tmp_path, result)

    assert "Resolution guide is invalid" in rendered
    assert "guide heading 'docker-daemon' was not found" in rendered

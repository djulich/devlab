from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from devlab.prerequisites import (
    FilePrerequisiteTracker,
    Prerequisite,
    PrerequisiteOperation,
    PrerequisiteStatus,
    attest_prerequisite,
    evaluate_prerequisites,
    prerequisite_is_attested,
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

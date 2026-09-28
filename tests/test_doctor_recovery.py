from __future__ import annotations

import json
from pathlib import Path

import pytest

from devlab.doctor_recovery import (
    DoctorAction,
    DoctorDiagnosis,
    DoctorRecovery,
    RecoveryStage,
    load_doctor_recovery,
    parse_doctor_diagnosis,
    save_doctor_recovery,
)


def test_doctor_result_requires_existing_workspace_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "task.md"
    evidence.write_text("# Task\n")
    result = tmp_path / "result.json"
    data = {
        "schema_version": 1,
        "task": "T0001",
        "cause": "task_ambiguity",
        "action": "revise_task",
        "summary": "Task conflicts with its specification",
        "guidance": "Revise the task against the specification",
        "evidence": ["task.md"],
    }
    result.write_text(json.dumps(data))

    diagnosis = parse_doctor_diagnosis(tmp_path, result, task="T0001")
    assert diagnosis.action == DoctorAction.REVISE_TASK
    assert diagnosis.evidence == ("task.md",)

    data["evidence"] = ["../outside.md"]
    result.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="evidence"):
        parse_doctor_diagnosis(tmp_path, result, task="T0001")


def test_doctor_recovery_preserves_bounded_route(tmp_path: Path) -> None:
    recovery = DoctorRecovery(
        "T0001",
        "developer_non_advancing",
        RecoveryStage.PENDING_PLANNER,
        DoctorDiagnosis(
            "task_ambiguity",
            DoctorAction.REVISE_TASK,
            "Task is ambiguous",
            "Revise against specs",
            ("task.md",),
        ),
    )
    save_doctor_recovery(tmp_path, recovery)
    assert load_doctor_recovery(tmp_path) == recovery

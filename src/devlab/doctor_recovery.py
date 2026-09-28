"""Durable, bounded doctor diagnosis for a stopped developer task."""

from __future__ import annotations

import dataclasses
import json
from enum import StrEnum
from pathlib import Path
from typing import cast

from devlab._files import atomic_write_text

RECOVERY_PATH = ".devlab/doctor-recovery.json"
MAX_DIAGNOSIS_TEXT = 2000
MAX_EVIDENCE_PATHS = 20


class RecoveryStage(StrEnum):
    PENDING_DOCTOR = "pending_doctor"
    PENDING_PLANNER = "pending_planner"
    PENDING_DEVELOPER = "pending_developer"
    BLOCKED = "blocked"


class DoctorAction(StrEnum):
    RETRY_DEVELOPER = "retry_developer"
    REVISE_TASK = "revise_task"
    OPERATOR = "operator"


@dataclasses.dataclass(frozen=True)
class DoctorDiagnosis:
    cause: str
    action: DoctorAction
    summary: str
    guidance: str
    evidence: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class DoctorRecovery:
    task: str
    trigger: str
    stage: RecoveryStage
    diagnosis: DoctorDiagnosis | None = None


def load_doctor_recovery(root: Path) -> DoctorRecovery | None:
    path = root / RECOVERY_PATH
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid doctor recovery record: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"invalid doctor recovery record: {path}")
    task = data.get("task")
    trigger = data.get("trigger")
    if (
        not isinstance(task, str)
        or not task
        or trigger not in {"developer_non_advancing", "validation_failed"}
    ):
        raise ValueError(f"invalid doctor recovery record: {path}")
    try:
        stage = RecoveryStage(data["stage"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid doctor recovery stage: {path}") from exc
    diagnosis = (
        _parse_diagnosis(data.get("diagnosis"), root, check_paths=False)
        if data.get("diagnosis")
        else None
    )
    if (stage == RecoveryStage.PENDING_DOCTOR) != (diagnosis is None):
        raise ValueError(f"invalid doctor recovery diagnosis: {path}")
    return DoctorRecovery(task, trigger, stage, diagnosis)


def save_doctor_recovery(root: Path, recovery: DoctorRecovery) -> None:
    data = {
        "schema_version": 1,
        "task": recovery.task,
        "trigger": recovery.trigger,
        "stage": recovery.stage.value,
        "diagnosis": (
            {
                **dataclasses.asdict(recovery.diagnosis),
                "action": recovery.diagnosis.action.value,
            }
            if recovery.diagnosis is not None
            else None
        ),
    }
    atomic_write_text(root / RECOVERY_PATH, json.dumps(data, indent=2, sort_keys=True) + "\n")


def clear_doctor_recovery(root: Path) -> None:
    (root / RECOVERY_PATH).unlink(missing_ok=True)


def parse_doctor_diagnosis(root: Path, path: Path, *, task: str) -> DoctorDiagnosis:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"doctor did not produce valid JSON at {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("task") != task:
        raise ValueError("doctor result has an invalid schema version or task")
    if set(data) != {
        "schema_version",
        "task",
        "cause",
        "action",
        "summary",
        "guidance",
        "evidence",
    }:
        raise ValueError("doctor result has missing or unexpected fields")
    return _parse_diagnosis(data, root, check_paths=True)


def _parse_diagnosis(data: object, root: Path, *, check_paths: bool) -> DoctorDiagnosis:
    if not isinstance(data, dict):
        raise ValueError("doctor diagnosis must be an object")
    data = cast("dict[str, object]", data)
    cause = data.get("cause")
    summary = data.get("summary")
    guidance = data.get("guidance")
    evidence = data.get("evidence")
    if (
        not isinstance(cause, str)
        or not cause.strip()
        or not isinstance(summary, str)
        or not summary.strip()
        or not isinstance(guidance, str)
        or not guidance.strip()
    ):
        raise ValueError("doctor diagnosis requires cause, summary, and guidance")
    if any(
        len(value) > MAX_DIAGNOSIS_TEXT or "\0" in value for value in (cause, summary, guidance)
    ):
        raise ValueError("doctor diagnosis text exceeds its bound")
    if (
        not isinstance(evidence, list | tuple)
        or not evidence
        or len(evidence) > MAX_EVIDENCE_PATHS
        or any(not isinstance(item, str) or not item.strip() for item in evidence)
    ):
        raise ValueError("doctor diagnosis requires evidence paths")
    try:
        action = DoctorAction(data["action"])
    except (KeyError, ValueError) as exc:
        raise ValueError("doctor diagnosis has an invalid action") from exc
    paths = tuple(cast("list[str] | tuple[str, ...]", evidence))
    if any(len(item) > 500 or "\0" in item for item in paths):
        raise ValueError("doctor evidence path exceeds its bound")
    if check_paths:
        for relative in paths:
            candidate = (root / relative).resolve()
            if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
                raise ValueError(f"doctor evidence does not identify a workspace file: {relative}")
    return DoctorDiagnosis(cause, action, summary, guidance, paths)

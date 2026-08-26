from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from devlab._files import atomic_write_text

PREREQUISITE_BLOCKER = ".devlab/prerequisite-blocker.json"
ATTESTATION_SCHEMA = 1
BLOCKER_SCHEMA = 1


class PrerequisiteOperation(StrEnum):
    SESSION = "session"
    SETUP = "setup"
    VALIDATION = "validation"


class PrerequisiteStatus(StrEnum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNVERIFIED = "unverified"
    ERROR = "error"


@dataclasses.dataclass(frozen=True)
class Prerequisite:
    profile_id: str
    id: str
    required_for: tuple[PrerequisiteOperation, ...]
    summary: str
    check: str = ""
    environment: str = ""
    attestation: str = ""
    guide: str = ""
    sensitive: bool = False
    timeout: int = 30

    @property
    def reference(self) -> str:
        return f"{self.profile_id}.{self.id}"

    @property
    def digest(self) -> str:
        payload = {
            "profile": self.profile_id,
            "id": self.id,
            "required_for": sorted(item.value for item in self.required_for),
            "check": self.check,
            "environment": self.environment,
            "attestation": self.attestation,
            "sensitive": self.sensitive,
            "timeout": self.timeout,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "prerequisite-v1:" + hashlib.sha256(canonical.encode()).hexdigest()


@dataclasses.dataclass(frozen=True)
class PrerequisiteResult:
    prerequisite: Prerequisite
    status: PrerequisiteStatus
    detail: str

    @property
    def blocks(self) -> bool:
        return self.status != PrerequisiteStatus.SATISFIED


@dataclasses.dataclass(frozen=True)
class PrerequisiteBlocker:
    command: str
    role: str
    task: str
    milestone: str
    operation: PrerequisiteOperation
    results: tuple[PrerequisiteResult, ...]
    recorded_at: str


class FilePrerequisiteTracker:
    """Store the latest workflow-blocking prerequisite observation."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / PREREQUISITE_BLOCKER

    def read_blocker(self) -> PrerequisiteBlocker | None:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        if not isinstance(data, dict) or data.get("version") != BLOCKER_SCHEMA:
            raise ValueError(f"invalid prerequisite blocker record: {self.path}")
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise ValueError(f"invalid prerequisite blocker results: {self.path}")
        results = tuple(_result_from_record(item, self.path) for item in raw_results)
        return PrerequisiteBlocker(
            command=str(data.get("command") or ""),
            role=str(data.get("role") or ""),
            task=str(data.get("task") or ""),
            milestone=str(data.get("milestone") or ""),
            operation=PrerequisiteOperation(str(data.get("operation") or "")),
            results=results,
            recorded_at=str(data.get("recorded_at") or ""),
        )

    def record_blocker(
        self,
        *,
        command: str,
        role: str,
        task: str,
        milestone: str,
        operation: PrerequisiteOperation,
        results: tuple[PrerequisiteResult, ...],
    ) -> bool:
        stable_record = {
            "version": BLOCKER_SCHEMA,
            "command": command,
            "role": role,
            "task": task,
            "milestone": milestone,
            "operation": operation.value,
            "results": [_result_record(item) for item in results],
        }
        try:
            current = json.loads(self.path.read_text())
        except (FileNotFoundError, OSError, ValueError):
            current = None
        if isinstance(current, dict):
            current = dict(current)
            current.pop("recorded_at", None)
            if current == stable_record:
                return False
        record = {**stable_record, "recorded_at": datetime.now(UTC).isoformat()}
        atomic_write_text(self.path, json.dumps(record, indent=2, sort_keys=True) + "\n")
        return True

    def clear_blocker(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True


def evaluate_prerequisites(
    root: Path,
    prerequisites: tuple[Prerequisite, ...],
    operation: PrerequisiteOperation,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[PrerequisiteResult, ...]:
    environment = os.environ if environ is None else environ
    return tuple(
        _evaluate_prerequisite(root, item, environment)
        for item in prerequisites
        if operation in item.required_for
    )


def attest_prerequisite(
    root: Path,
    prerequisite: Prerequisite,
    *,
    operator: str = "",
    note: str = "",
) -> Path:
    if not prerequisite.attestation:
        raise ValueError(f"prerequisite {prerequisite.reference} is not operator-attested")
    path = prerequisite_attestation_path(root, prerequisite)
    record = {
        "version": ATTESTATION_SCHEMA,
        "workspace": str(root.resolve()),
        "profile": prerequisite.profile_id,
        "prerequisite": prerequisite.id,
        "digest": prerequisite.digest,
        "statement": prerequisite.attestation,
        "operator": operator,
        "note": note,
        "attested_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_text(path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    return path


def revoke_prerequisite_attestation(root: Path, prerequisite: Prerequisite) -> bool:
    path = prerequisite_attestation_path(root, prerequisite)
    if not path.exists():
        return False
    path.unlink()
    return True


def prerequisite_is_attested(root: Path, prerequisite: Prerequisite) -> bool:
    path = prerequisite_attestation_path(root, prerequisite)
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, OSError, ValueError):
        return False
    return (
        isinstance(data, dict)
        and data.get("version") == ATTESTATION_SCHEMA
        and data.get("workspace") == str(root.resolve())
        and data.get("profile") == prerequisite.profile_id
        and data.get("prerequisite") == prerequisite.id
        and data.get("digest") == prerequisite.digest
    )


def prerequisite_attestation_path(root: Path, prerequisite: Prerequisite) -> Path:
    from devlab.executable_config import devlab_state_home

    identity = json.dumps(
        {
            "workspace": str(root.resolve()),
            "profile": prerequisite.profile_id,
            "prerequisite": prerequisite.id,
            "digest": prerequisite.digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    record_id = hashlib.sha256(identity.encode()).hexdigest()
    return devlab_state_home() / "prerequisite-attestations" / f"{record_id}.json"


def prerequisite_guide_path(root: Path, prerequisite: Prerequisite) -> Path | None:
    if not prerequisite.guide:
        return None
    path = (root / prerequisite.guide).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(
            f"prerequisite {prerequisite.reference} guide escapes the workspace: "
            f"{prerequisite.guide}"
        )
    return path


def format_prerequisite_result(root: Path, result: PrerequisiteResult) -> str:
    item = result.prerequisite
    lines = [
        f"Prerequisite: {item.reference}",
        f"Status: {result.status.value}",
        f"Required for: {', '.join(scope.value for scope in item.required_for)}",
        f"Summary: {item.summary}",
        f"Observed: {result.detail}",
    ]
    if item.sensitive:
        lines.append("Security: Do not commit or print sensitive values.")
    guide = prerequisite_guide_path(root, item)
    if guide is not None:
        lines.append(f"Guide: {guide}")
        try:
            guide_text = guide.read_text().strip()
        except FileNotFoundError:
            lines.append("Resolution guide is missing.")
        else:
            if guide_text:
                lines.extend(["", "Resolution guide:", guide_text[:8000]])
    return "\n".join(lines)


def _evaluate_prerequisite(
    root: Path, prerequisite: Prerequisite, environ: Mapping[str, str]
) -> PrerequisiteResult:
    if prerequisite.attestation:
        status = (
            PrerequisiteStatus.SATISFIED
            if prerequisite_is_attested(root, prerequisite)
            else PrerequisiteStatus.UNVERIFIED
        )
        detail = (
            "operator attestation is current"
            if status == PrerequisiteStatus.SATISFIED
            else "operator attestation has not been recorded"
        )
        return PrerequisiteResult(prerequisite, status, detail)
    if prerequisite.environment:
        present = bool(environ.get(prerequisite.environment))
        return PrerequisiteResult(
            prerequisite,
            PrerequisiteStatus.SATISFIED if present else PrerequisiteStatus.UNSATISFIED,
            f"{prerequisite.environment} is set"
            if present
            else f"{prerequisite.environment} is not set",
        )
    try:
        completed = subprocess.run(
            prerequisite.check,
            cwd=root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=prerequisite.timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return PrerequisiteResult(prerequisite, PrerequisiteStatus.ERROR, str(exc))
    if completed.returncode == 0:
        return PrerequisiteResult(
            prerequisite, PrerequisiteStatus.SATISFIED, "check exited successfully"
        )
    output = "\n".join(
        line.rstrip() for line in (completed.stdout + "\n" + completed.stderr).splitlines()
    ).strip()
    detail = f"check exited with {completed.returncode}"
    if output and not prerequisite.sensitive:
        detail += f": {output[-500:]}"
    return PrerequisiteResult(prerequisite, PrerequisiteStatus.UNSATISFIED, detail)


def _result_record(result: PrerequisiteResult) -> dict[str, Any]:
    item = result.prerequisite
    return {
        "profile": item.profile_id,
        "id": item.id,
        "digest": item.digest,
        "required_for": [scope.value for scope in item.required_for],
        "summary": item.summary,
        "guide": item.guide,
        "sensitive": item.sensitive,
        "status": result.status.value,
        "detail": result.detail,
    }


def _result_from_record(value: object, path: Path) -> PrerequisiteResult:
    if not isinstance(value, dict):
        raise ValueError(f"invalid prerequisite blocker result: {path}")
    value = cast("dict[str, Any]", value)
    prerequisite = Prerequisite(
        profile_id=str(value.get("profile") or ""),
        id=str(value.get("id") or ""),
        required_for=tuple(
            PrerequisiteOperation(str(item)) for item in value.get("required_for", [])
        ),
        summary=str(value.get("summary") or ""),
        guide=str(value.get("guide") or ""),
        sensitive=bool(value.get("sensitive")),
    )
    return PrerequisiteResult(
        prerequisite,
        PrerequisiteStatus(str(value.get("status") or "")),
        str(value.get("detail") or ""),
    )

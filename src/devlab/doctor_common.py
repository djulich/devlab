from __future__ import annotations

import dataclasses
from enum import StrEnum
from pathlib import Path


class DoctorOperation(StrEnum):
    """Operator actions that a workspace-health finding can prevent safely."""

    PLANNING = "planning"
    SESSION = "session"


MUTATING_DOCTOR_OPERATIONS = frozenset({DoctorOperation.PLANNING, DoctorOperation.SESSION})


@dataclasses.dataclass(frozen=True)
class DoctorProblem:
    path: str
    message: str
    blocks: frozenset[DoctorOperation] = MUTATING_DOCTOR_OPERATIONS

    def blocks_operation(self, operation: DoctorOperation) -> bool:
        return operation in self.blocks


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)

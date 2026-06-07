from __future__ import annotations

import dataclasses
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class DoctorProblem:
    path: str
    message: str


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)

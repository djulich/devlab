from __future__ import annotations

from pathlib import Path

from devlab.doctor_common import DoctorProblem, display_path
from devlab.knowledge import ADR_DIR, ADR_FILENAME_RE, CONTEXT_MAP, context_paths_from_map


def check_project_knowledge(root: Path) -> list[DoctorProblem]:
    problems: list[DoctorProblem] = []
    problems.extend(_check_context_map(root))
    problems.extend(_check_adrs(root))
    return problems


def _check_context_map(root: Path) -> list[DoctorProblem]:
    path = root / CONTEXT_MAP
    if not path.exists():
        return []
    problems: list[DoctorProblem] = []
    for context_path in context_paths_from_map(root, path.read_text()):
        if not context_path.exists():
            problems.append(
                DoctorProblem(
                    CONTEXT_MAP,
                    f"references missing context file {display_path(context_path, root)!r}",
                )
            )
    return problems


def _check_adrs(root: Path) -> list[DoctorProblem]:
    adr_dir = root / ADR_DIR
    if not adr_dir.exists():
        return []
    problems: list[DoctorProblem] = []
    seen_numbers: dict[str, str] = {}
    for path in sorted(adr_dir.glob("*.md")):
        path_display = display_path(path, root)
        match = ADR_FILENAME_RE.fullmatch(path.name)
        if match is None:
            problems.append(
                DoctorProblem(
                    path_display,
                    "ADR filename must match NNNN-lowercase-slug.md",
                )
            )
            continue
        number = match.group("number")
        if number in seen_numbers:
            problems.append(
                DoctorProblem(
                    path_display,
                    f"duplicate ADR number {number}; first seen in {seen_numbers[number]}",
                )
            )
        seen_numbers[number] = path_display
    return problems

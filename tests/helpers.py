from __future__ import annotations

from pathlib import Path

from devlab.task_tracker import FileTaskTracker


def handoff(
    role_name: str,
    *,
    changed: str = "- None",
    open_issues: str = "- None",
    addressed: str = "- None",
) -> str:
    return (
        f"# Handoff: {role_name}\n"
        "## Done\n"
        "- Session completed.\n"
        "## Changed Artifacts\n"
        f"{changed}\n"
        "## Open Issues\n"
        f"{open_issues}\n"
        "## Addressed Findings\n"
        f"{addressed}\n"
        "## Next Session Hint\n"
        "Continue.\n"
    )


def write_task(
    root: Path,
    task_id: str,
    title: str,
    milestone: str,
    *,
    depends_on: list[str] | None = None,
    addresses_findings: list[str] | None = None,
    domain: str = "general",
) -> Path:
    depends_on = depends_on or []
    addresses_findings = addresses_findings or []
    depends = ", ".join(f'"{dependency}"' for dependency in depends_on)
    findings = ", ".join(f'"{finding_id}"' for finding_id in addresses_findings)
    slug = title.lower().replace(" ", "-")
    path = root / ".devlab/tasks" / f"{task_id}_{slug}.md"
    path.write_text(
        "+++\n"
        f'id = "{task_id}"\n'
        f'title = "{title}"\n'
        'status = "open"\n'
        f'milestone = "{milestone}"\n'
        'profile = "default"\n'
        f'domain = "{domain}"\n'
        f'depends_on = [{depends}]\n'
        f'addresses_findings = [{findings}]\n'
        'validation = []\n'
        "+++\n\n"
        f"# {task_id}: {title}\n\n"
        "## Goal\n"
        f"Complete {title}.\n\n"
        "## Acceptance Criteria\n"
        "- [ ] Done\n"
    )
    return path


def complete_acceptance(root: Path, task_id: str) -> None:
    task = FileTaskTracker(root).get(task_id)
    task.path.write_text(task.path.read_text().replace("- [ ]", "- [x]"))


def approve_review_task(root: Path) -> None:
    task = FileTaskTracker(root).select_next_review_task()
    assert task is not None
    task.path.write_text(task.path.read_text() + "\n## Review\n- [x] Approved\n")

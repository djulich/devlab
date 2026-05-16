"""Prompt assembly for DevLab agent sessions.

Builds system and session prompts from workspace state (plans, tasks,
findings, profiles, specifications) and packaged prompt resources.
"""

from __future__ import annotations

from pathlib import Path

from devlab.profiles import Profile, load_profile
from devlab.prompt_resources import read_prompt_resource
from devlab.task_tracker import Task
from devlab.workspace import (
    DESIGN_PLAN,
    HISTORY_DIR,
    PROJECT_PLAN,
    RoleConfig,
    Workspace,
    WorkspaceSnapshot,
    read_file,
)

CONVENTIONS_RESOURCE = "conventions.md"
TOOLING_FILE = ".devlab/config/tooling.md"


def build_system_prompt(root: Path, role: RoleConfig) -> str:
    parts: list[str] = [
        read_prompt_resource(CONVENTIONS_RESOURCE),
        read_prompt_resource(role.prompt_resource),
    ]
    if role.reads_tooling:
        parts.append(read_file(root / TOOLING_FILE))
    return "\n\n---\n\n".join(p for p in parts if p)


def build_session_prompt(workspace: Path | WorkspaceSnapshot, role_name: str) -> str:
    snapshot = _ensure_snapshot(workspace)
    builders = {
        "architect": _build_architect_prompt,
        "planner": _build_planner_prompt,
        "developer": _build_developer_prompt,
        "reviewer": _build_reviewer_prompt,
        "integrator": _build_integrator_prompt,
    }
    return builders[role_name](snapshot) + _handoff_reminder(role_name)


def _ensure_snapshot(workspace: Path | WorkspaceSnapshot) -> WorkspaceSnapshot:
    if isinstance(workspace, WorkspaceSnapshot):
        return workspace
    return Workspace(workspace).snapshot()


def _handoff_reminder(role_name: str) -> str:
    return (
        "\n\nIMPORTANT: When done, write your handoff file to "
        f".devlab/session-artifacts/{role_name}/handoff.md "
        "using the template from conventions.md."
    )


def _latest_handoff(root: Path, role_name: str) -> str:
    history = root / HISTORY_DIR
    handoffs = sorted(history.glob(f"*_{role_name}_handoff.md"))
    if not handoffs:
        return ""
    return read_file(handoffs[-1])


def _session_profile(root: Path, task: Task | None) -> Profile:
    return load_profile(root, task.profile if task is not None else None)


def _build_architect_prompt(snapshot: WorkspaceSnapshot) -> str:
    root = snapshot.root
    parts: list[str] = []
    review_milestone = snapshot.select_architecture_review_milestone()
    if review_milestone is not None:
        parts.extend(_architecture_review_prompt_sections(snapshot, review_milestone))
    plan = read_file(root / DESIGN_PLAN)
    if plan.strip():
        parts.append(f"## Current Design Plan\n\n{plan}")
    project = read_file(root / PROJECT_PLAN)
    if project.strip():
        parts.append(f"## Current Project Plan\n\n{project}")
    handoff = _latest_handoff(root, "architect")
    if handoff:
        parts.append(f"## Latest Architect Handoff\n\n{handoff}")
    if not parts:
        parts.append("No design plan exists yet. Create one from the system specification.")
    return "\n\n".join(parts)


def _architecture_review_prompt_sections(
    snapshot: WorkspaceSnapshot, milestone_id: str
) -> list[str]:
    root = snapshot.root
    milestone = next(
        milestone for milestone in snapshot.list_milestones() if milestone.id == milestone_id
    )
    parts = [
        "## Assigned Integrated Milestone for Architecture Review\n\n"
        f"{milestone.id}: {milestone.title}\n\n"
        "Review whether the design plan still matches the implemented system, "
        "the system/deployment specifications, and the future project direction. "
        "Update the design plan if needed. If follow-up implementation or planning "
        "is required, report it in the handoff's Open Issues section."
    ]
    if milestone.integration_handoff:
        integration_handoff = root / HISTORY_DIR / milestone.integration_handoff
        handoff_text = read_file(integration_handoff)
        if handoff_text.strip():
            parts.append(f"## Integration Handoff\n\n{handoff_text}")
    task_sections = [
        f"### {task.path.name}\n\n{read_file(task.path)}"
        for task in snapshot.tasks_for_milestone(milestone_id)
    ]
    if task_sections:
        parts.append("## Milestone Task Files\n\n" + "\n\n".join(task_sections))
    specs = _format_spec_sections(root)
    if specs:
        parts.append(specs)
    return parts


def _format_spec_sections(root: Path) -> str:
    sections: list[str] = []
    specs_root = root / ".devlab/specs"
    for spec_dir in (specs_root / "system", specs_root / "deployment"):
        if not spec_dir.exists():
            continue
        files = sorted(path for path in spec_dir.rglob("*.md") if path.is_file())
        if files:
            file_sections = [
                f"### {path.relative_to(root)}\n\n{read_file(path)}" for path in files
            ]
            sections.append(
                f"## {spec_dir.name.title()} Specification\n\n" + "\n\n".join(file_sections)
            )
    return "\n\n".join(sections)


def _format_task_listing(tasks: list[Task]) -> str:
    return "\n".join(
        f"- {task.id} [{task.status.value}] {task.title} "
        f"({task.path.relative_to(task.path.parents[2])})"
        for task in tasks
    )


def _profile_prompt_sections(root: Path, task: Task) -> list[str]:
    profile = _session_profile(root, task)
    lines = [
        f"Profile: `{profile.id}`",
        f"Title: {profile.title}",
    ]
    if profile.tooling.summary:
        lines.extend(["", profile.tooling.summary])
    return ["## Task Profile\n\n" + "\n".join(lines)]


def _validation_prompt_section(task: Task, profile: Profile) -> str:
    if task.validation is None:
        commands = profile.tooling.default_validation
        if commands:
            command_lines = "\n".join(f"- `{command}`" for command in commands)
            return (
                "## Task Validation Commands\n\n"
                f"Task metadata omits `validation`; use default validation from "
                f"profile `{profile.id}`. Run from the workspace root:\n\n{command_lines}"
            )
        return ""
    if task.validation:
        commands = "\n".join(f"- `{command}`" for command in task.validation)
        return f"## Task Validation Commands\n\nRun from the workspace root:\n\n{commands}"
    return (
        "## Task Validation Commands\n\n"
        "Task metadata sets `validation = []`. No validation commands "
        "are required; state in the handoff whether any validation was "
        "run and why."
    )


def _format_profile_listing(root: Path) -> str:
    profiles_dir = root / ".devlab/config/profiles"
    if not profiles_dir.exists():
        return ""
    lines: list[str] = []
    for path in sorted(profiles_dir.glob("*.toml")):
        lines.append(f"### {path.name}\n\n{read_file(path).strip()}")
    return "\n\n".join(lines)


def _build_planner_prompt(snapshot: WorkspaceSnapshot) -> str:
    root = snapshot.root
    parts: list[str] = []
    plan = read_file(root / DESIGN_PLAN)
    if plan.strip():
        parts.append(f"## Design Plan\n\n{plan}")
    project = read_file(root / PROJECT_PLAN)
    if project.strip():
        parts.append(f"## Current Project Plan\n\n{project}")
    tasks = snapshot.list_tasks()
    if tasks:
        parts.append(f"## Current Tasks\n\n{_format_task_listing(tasks)}")
    profile_listing = _format_profile_listing(root)
    if profile_listing:
        parts.append(f"## Existing Profiles\n\n{profile_listing}")
    findings = snapshot.open_findings()
    if findings:
        finding_sections = [
            f"### {finding.path.name}\n\n{read_file(finding.path)}" for finding in findings
        ]
        parts.append("## Open Findings\n\n" + "\n\n".join(finding_sections))
    handoff = _latest_handoff(root, "planner")
    if handoff:
        parts.append(f"## Latest Planner Handoff\n\n{handoff}")
    return "\n\n".join(parts)


def _build_developer_prompt(snapshot: WorkspaceSnapshot) -> str:
    root = snapshot.root
    parts: list[str] = []
    task = snapshot.select_next_development_task()
    if task:
        content = read_file(task.path)
        parts.append(f"## Assigned Task ({task.path.name})\n\n{content}")
        parts.extend(_profile_prompt_sections(root, task))
        validation_section = _validation_prompt_section(task, _session_profile(root, task))
        if validation_section:
            parts.append(validation_section)
    else:
        parts.append("No open eligible tasks.")
    handoff = _latest_handoff(root, "developer")
    if handoff:
        parts.append(f"## Latest Developer Handoff\n\n{handoff}")
    reviewer_handoff = _latest_handoff(root, "reviewer")
    if reviewer_handoff:
        parts.append(f"## Latest Reviewer Handoff\n\n{reviewer_handoff}")
    return "\n\n".join(parts)


def _build_integrator_prompt(snapshot: WorkspaceSnapshot) -> str:
    root = snapshot.root
    parts: list[str] = []
    milestone = snapshot.select_integration_milestone()
    if milestone is None:
        parts.append("No completed milestone requires integration.")
    else:
        parts.append(
            "## Assigned Completed Milestone\n\n"
            f"{milestone}\n\n"
            "Validate the current repository state at this milestone boundary. "
            "Confirm that this milestone's changes work correctly with the "
            "previously implemented system."
        )
        task_sections = []
        for task in snapshot.tasks_for_milestone(milestone):
            task_sections.append(f"### {task.path.name}\n\n{read_file(task.path)}")
        if task_sections:
            parts.append("## Milestone Task Files\n\n" + "\n\n".join(task_sections))
    plan = read_file(root / DESIGN_PLAN)
    if plan.strip():
        parts.append(f"## Design Plan\n\n{plan}")
    project = read_file(root / PROJECT_PLAN)
    if project.strip():
        parts.append(f"## Project Plan\n\n{project}")
    for role_name in ("developer", "reviewer", "integrator"):
        handoff = _latest_handoff(root, role_name)
        if handoff:
            parts.append(f"## Latest {role_name.title()} Handoff\n\n{handoff}")
    return "\n\n".join(parts)


def _build_reviewer_prompt(snapshot: WorkspaceSnapshot) -> str:
    root = snapshot.root
    parts: list[str] = []
    task = snapshot.select_next_review_task()
    if task:
        content = read_file(task.path)
        parts.append(f"## Task Awaiting Review ({task.path.name})\n\n{content}")
        parts.extend(_profile_prompt_sections(root, task))
        validation_section = _validation_prompt_section(task, _session_profile(root, task))
        if validation_section:
            parts.append(validation_section)
    else:
        parts.append("No tasks are awaiting review.")
    developer_handoff = _latest_handoff(root, "developer")
    if developer_handoff:
        parts.append(f"## Latest Developer Handoff\n\n{developer_handoff}")
    reviewer_handoff = _latest_handoff(root, "reviewer")
    if reviewer_handoff:
        parts.append(f"## Latest Reviewer Handoff\n\n{reviewer_handoff}")
    return "\n\n".join(parts)

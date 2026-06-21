"""Prompt assembly for DevLab agent sessions.

Builds base and session prompts from workspace state (plans, tasks,
findings, profiles, specifications) and packaged prompt resources.
"""

from __future__ import annotations

from pathlib import Path

from devlab.findings import FindingStatus
from devlab.knowledge import ProjectKnowledge, discover_project_knowledge
from devlab.profiles import Profile, load_profile
from devlab.prompt_resources import read_optional_prompt_resource, read_prompt_resource
from devlab.task_tracker import Task
from devlab.workspace import (
    DESIGN_PLAN,
    HISTORY_DIR,
    PROJECT_PLAN,
    RoleConfig,
    WorkspaceSnapshot,
    read_file,
)

CONVENTIONS_RESOURCE = "conventions.md"
TOOLING_FILE = ".devlab/config/tooling.md"


def build_base_prompt(
    root: Path,
    role: RoleConfig,
    *,
    snapshot: WorkspaceSnapshot | None = None,
    role_name: str | None = None,
) -> str:
    parts: list[str] = [
        read_prompt_resource(CONVENTIONS_RESOURCE),
        read_prompt_resource(role.prompt_resource),
    ]
    if snapshot is not None and role_name is not None:
        parts.extend(_domain_prompt_sections(snapshot, role_name))
    if role.reads_tooling:
        parts.append(read_file(root / TOOLING_FILE))
    return "\n\n---\n\n".join(p for p in parts if p)


def build_session_prompt(
    snapshot: WorkspaceSnapshot,
    role_name: str,
    *,
    planning_revision: bool = False,
    adopt_existing: bool = False,
    fresh_generation: bool = False,
    spec_reconciliation: bool = False,
) -> str:
    builders = {
        "architect": _build_architect_prompt,
        "planner": _build_planner_prompt,
        "developer": _build_developer_prompt,
        "reviewer": _build_reviewer_prompt,
        "integrator": _build_integrator_prompt,
    }
    prompt = builders[role_name](snapshot)
    knowledge = _format_project_knowledge(discover_project_knowledge(snapshot.root))
    if knowledge:
        prompt = knowledge + "\n\n" + prompt
    if planning_revision:
        prompt += _planning_revision_section(
            role_name,
            adopt_existing=adopt_existing,
            fresh_generation=fresh_generation,
            spec_reconciliation=spec_reconciliation,
        )
    return prompt + _handoff_reminder(role_name)


def _planning_revision_section(
    role_name: str,
    *,
    adopt_existing: bool,
    fresh_generation: bool,
    spec_reconciliation: bool,
) -> str:
    mode_text = ""
    if spec_reconciliation:
        mode_text = (
            "\n\nThis is spec reconciliation. DevLab archived the previous active "
            "planning graph before this session. Create a complete fresh active plan "
            "for the current specifications and repository state. Use previous DevLab "
            "state only as historical context if it appears in the prompt."
        )
    elif fresh_generation:
        mode_text = (
            "\n\nThis is replacement planning. DevLab archived the previous active "
            "planning graph before this session. Create a complete fresh active plan "
            "for the current specifications and repository state."
        )
    elif adopt_existing:
        mode_text = (
            "\n\nThis is existing-project adoption. Inspect existing source, tests, "
            "tooling, packaging, and deployment files before creating planning state. "
            "Preserve the existing project's development stack and validation approach "
            "when one is present; do not replace it with DevLab's preferred tooling "
            "just because the reusable tooling policy recommends it. Validation must "
            "use target-owned commands, scripts, profiles, or documented prerequisites, "
            "not globally installed or harness-inherited tools."
        )
    if role_name == "architect":
        if adopt_existing:
            mode_text += (
                " Create a current-state design baseline in the design plan before "
                "describing target changes. The baseline must summarize the existing "
                "source structure, runtime/tooling, tests, deployment-relevant files, "
                "implemented behavior, and the gaps between current behavior and the "
                "current specifications. If the existing project has no reliable "
                "target-owned validation path, say so explicitly and describe what kind "
                "of validation/profile work planning should add."
            )
        return (
            "\n\n## Planning Revision Mode\n\n"
            "Review the existing design plan against the current specifications and "
            "workflow state. Edit the design plan only when it materially improves "
            "accuracy, clarity, or implementation guidance."
            f"{mode_text}"
        )
    if role_name == "planner":
        if adopt_existing:
            mode_text += (
                " Plan implementation tasks around the existing project's validation "
                "path when it is reliable. If no reliable target-owned validation path "
                "exists, plan explicit tooling/profile work before tasks that depend on "
                "that validation. Do not silently rely on host-global or "
                "DevLab-harness tools."
            )
        return (
            "\n\n## Planning Revision Mode\n\n"
            "Review the existing project plan and task files against the current design "
            "plan and specifications. Edit plans or tasks only when it materially improves "
            "accuracy, sequencing, scope, or acceptance criteria. Do not recreate tasks "
            "that already exist."
            f"{mode_text}"
        )
    return ""


def _domain_prompt_sections(snapshot: WorkspaceSnapshot, role_name: str) -> list[str]:
    domains = _active_domains_for_role(snapshot, role_name)
    sections = []
    for domain in domains:
        resource = f"domains/{domain}/{role_name}.md"
        prompt = read_optional_prompt_resource(resource)
        if prompt.strip():
            sections.append(prompt)
    return sections


def _active_domains_for_role(snapshot: WorkspaceSnapshot, role_name: str) -> tuple[str, ...]:
    if role_name == "developer":
        task = snapshot.select_next_development_task()
        return _task_domains(task)
    if role_name == "reviewer":
        task = snapshot.select_next_review_task()
        return _task_domains(task)
    if role_name == "integrator":
        milestone = snapshot.select_integration_milestone()
        if milestone is not None:
            domains = {
                task.domain
                for task in snapshot.tasks_for_milestone(milestone)
                if task.domain != "general"
            }
            if domains:
                return tuple(sorted(domains))
        return ("deployment",) if _deployment_spec_has_requirements(snapshot.root) else ()
    if role_name in {"architect", "planner"}:
        return ("deployment",) if _deployment_spec_has_requirements(snapshot.root) else ()
    return ()


def _task_domains(task: Task | None) -> tuple[str, ...]:
    if task is None or task.domain == "general":
        return ()
    return (task.domain,)


DEPLOYMENT_PLACEHOLDER_SENTINEL = "<!-- devlab:placeholder -->"


def _deployment_spec_has_requirements(root: Path) -> bool:
    spec_root = root / ".devlab/specs/deployment"
    if not spec_root.exists():
        return False
    for path in sorted(spec_root.rglob("*.md")):
        text = read_file(path)
        if not text.strip():
            continue
        if DEPLOYMENT_PLACEHOLDER_SENTINEL not in text:
            return True
    return False


def _format_project_knowledge(knowledge: ProjectKnowledge) -> str:
    if not knowledge.has_documents:
        return ""
    sections = [
        f"### {document.display_path}\n\n{document.content.strip()}"
        for document in knowledge.documents
        if document.content.strip()
    ]
    if not sections:
        return ""
    return "## Durable Project Knowledge\n\n" + "\n\n".join(sections)


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
    findings = _format_milestone_finding_sections(snapshot, milestone_id)
    if findings:
        parts.append(findings)
    specs = _format_spec_sections(root)
    if specs:
        parts.append(specs)
    return parts


def _format_milestone_finding_sections(
    snapshot: WorkspaceSnapshot, milestone_id: str
) -> str:
    findings = [
        finding
        for finding in snapshot.list_findings()
        if finding.milestone == milestone_id and finding.status != FindingStatus.RESOLVED
    ]
    if not findings:
        return ""
    tasks = snapshot.list_tasks()
    sections = []
    for finding in findings:
        addressing = [task.id for task in tasks if finding.id in task.addresses_findings]
        lines = [read_file(finding.path).strip()]
        lines.append("Addressing tasks: " + (", ".join(addressing) if addressing else "none"))
        sections.append(f"### {finding.path.name}\n\n" + "\n\n".join(lines))
    return "## Unresolved Findings for Reviewed Milestone\n\n" + "\n\n".join(sections)


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
        f"domain={task.domain} ({task.path.relative_to(task.path.parents[2])})"
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
    workflow_state = snapshot.workflow_state()
    parts.append(
        "## Workflow Planning State\n\n"
        f"Current `[planning].complete`: "
        f"`{str(workflow_state.planning.complete).lower()}`.\n\n"
        "Report the next value in handoff `## Planning State`: "
        "`planning_complete = false` if future planner sessions are still needed, "
        "or `planning_complete = true` when all required in-scope spec work is "
        "durably planned or explicitly out of scope."
    )
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

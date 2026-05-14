from __future__ import annotations

import dataclasses
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from devlab.agent_config import (
    ResolvedAgentConfig,
    format_resolved_agent_config,
    load_agent_configuration,
)
from devlab.agents import AgentProvider, provider_for_role
from devlab.environment import EnvironmentCommandError, EnvironmentManager
from devlab.findings import FileFindingTracker
from devlab.milestones import FileMilestoneTracker, sync_milestones_from_tasks
from devlab.profiles import Profile, ProfileNotFoundError, load_profile
from devlab.prompt_resources import read_prompt_resource
from devlab.task_tracker import FileTaskTracker, Task

DEFAULT_PROJECT_ROOT = Path.cwd()

CONVENTIONS_RESOURCE = "conventions.md"
TOOLING_FILE = ".devlab/config/tooling.md"
DESIGN_PLAN = ".devlab/plans/design-plan.md"
PROJECT_PLAN = ".devlab/plans/project-plan.md"
HISTORY_DIR = ".devlab/history"
FINDINGS_DIR = ".devlab/findings"
ARTIFACTS_DIR = ".devlab/session-artifacts"
AGENT_LOG_DIR = ".devlab/logs/agents"

REQUIRED_HANDOFF_HEADINGS = (
    "## Done",
    "## Changed Artifacts",
    "## Open Issues",
    "## Addressed Findings",
    "## Next Session Hint",
)


@dataclasses.dataclass(frozen=True)
class RoleConfig:
    name: str
    prompt_resource: str
    reads_tooling: bool
    needs_environment: bool


ROLES: dict[str, RoleConfig] = {
    "architect": RoleConfig(
        "architect",
        "role-architect.md",
        reads_tooling=True,
        needs_environment=False,
    ),
    "planner": RoleConfig(
        "planner",
        "role-planner.md",
        reads_tooling=True,
        needs_environment=False,
    ),
    "developer": RoleConfig(
        "developer",
        "role-developer.md",
        reads_tooling=True,
        needs_environment=True,
    ),
    "reviewer": RoleConfig(
        "reviewer",
        "role-reviewer.md",
        reads_tooling=True,
        needs_environment=True,
    ),
    "integrator": RoleConfig(
        "integrator",
        "role-integrator.md",
        reads_tooling=True,
        needs_environment=True,
    ),
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _read_file(path: Path) -> str:
    try:
        return path.read_text()
    except (FileNotFoundError, OSError):
        return ""


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def task_tracker(root: Path) -> FileTaskTracker:
    return FileTaskTracker(root)


def finding_tracker(root: Path) -> FileFindingTracker:
    return FileFindingTracker(root)


def milestone_tracker(root: Path) -> FileMilestoneTracker:
    return FileMilestoneTracker(root)


def _sync_milestones(root: Path) -> None:
    sync_milestones_from_tasks(root, project_plan_text=_read_file(root / PROJECT_PLAN))


def _log_resolved_agent_config(root: Path, role_name: str, config: ResolvedAgentConfig) -> Path:
    path = root / AGENT_LOG_DIR / f"{_timestamp()}_{role_name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_resolved_agent_config(config))
    return path


def select_task(root: Path) -> Path | None:
    """Select the lowest-numbered task eligible for development."""
    task = task_tracker(root).select_next_development_task()
    return task.path if task else None


def select_review_task(root: Path) -> Path | None:
    task = task_tracker(root).select_next_review_task()
    return task.path if task else None


def select_integration_milestone(root: Path) -> str | None:
    _sync_milestones(root)
    tasks = task_tracker(root)
    milestones = milestone_tracker(root)
    for milestone in milestones.list_milestones():
        if (
            milestone.integration_required
            and not milestone.integrated
            and tasks.milestone_complete(milestone.id)
        ):
            milestones.mark_tasks_complete(milestone.id)
            return milestone.id
    return None


def select_architecture_review_milestone(root: Path) -> str | None:
    _sync_milestones(root)
    for milestone in milestone_tracker(root).list_milestones():
        if milestone.integrated and not milestone.architecture_approved:
            return milestone.id
    return None


def _latest_handoff(root: Path, role_name: str) -> str:
    history = root / HISTORY_DIR
    handoffs = sorted(history.glob(f"*_{role_name}_handoff.md"))
    if not handoffs:
        return ""
    return _read_file(handoffs[-1])


def _all_milestones_complete(root: Path) -> bool:
    tracker = task_tracker(root)
    if tracker.has_tasks():
        return tracker.all_tasks_closed()
    text = _read_file(root / PROJECT_PLAN)
    checked = text.count("- [x]")
    unchecked = text.count("- [ ]")
    if checked == 0 and unchecked == 0:
        return False
    return unchecked == 0


# ---------------------------------------------------------------------------
# State assessment and role selection
# ---------------------------------------------------------------------------


def assess_state(root: Path) -> str | None:
    design_plan = root / DESIGN_PLAN
    if not design_plan.exists() or design_plan.stat().st_size == 0:
        return "architect"

    tracker = task_tracker(root)

    if tracker.select_next_review_task() is not None:
        return "reviewer"

    if finding_tracker(root).open_findings():
        return "planner"

    if select_architecture_review_milestone(root) is not None:
        return "architect"

    if select_integration_milestone(root) is not None:
        return "integrator"

    if tracker.select_next_development_task() is not None:
        return "developer"

    if tracker.blocked_tasks():
        print("No task is eligible; remaining development tasks are blocked by dependencies.")
        return None

    if _all_milestones_complete(root):
        return None

    return "planner"


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def build_system_prompt(root: Path, role: RoleConfig) -> str:
    parts: list[str] = [
        read_prompt_resource(CONVENTIONS_RESOURCE),
        read_prompt_resource(role.prompt_resource),
    ]
    if role.reads_tooling:
        parts.append(_read_file(root / TOOLING_FILE))
    return "\n\n---\n\n".join(p for p in parts if p)


def _handoff_reminder(role_name: str) -> str:
    return (
        "\n\nIMPORTANT: When done, write your handoff file to "
        f".devlab/session-artifacts/{role_name}/handoff.md "
        "using the template from conventions.md."
    )


def build_session_prompt(root: Path, role_name: str) -> str:
    builders = {
        "architect": _build_architect_prompt,
        "planner": _build_planner_prompt,
        "developer": _build_developer_prompt,
        "reviewer": _build_reviewer_prompt,
        "integrator": _build_integrator_prompt,
    }
    return builders[role_name](root) + _handoff_reminder(role_name)


def _build_architect_prompt(root: Path) -> str:
    parts: list[str] = []
    review_milestone = select_architecture_review_milestone(root)
    if review_milestone is not None:
        parts.extend(_architecture_review_prompt_sections(root, review_milestone))
    plan = _read_file(root / DESIGN_PLAN)
    if plan.strip():
        parts.append(f"## Current Design Plan\n\n{plan}")
    project = _read_file(root / PROJECT_PLAN)
    if project.strip():
        parts.append(f"## Current Project Plan\n\n{project}")
    handoff = _latest_handoff(root, "architect")
    if handoff:
        parts.append(f"## Latest Architect Handoff\n\n{handoff}")
    if not parts:
        parts.append("No design plan exists yet. Create one from the system specification.")
    return "\n\n".join(parts)


def _architecture_review_prompt_sections(root: Path, milestone_id: str) -> list[str]:
    milestone = milestone_tracker(root).get(milestone_id)
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
        handoff_text = _read_file(integration_handoff)
        if handoff_text.strip():
            parts.append(f"## Integration Handoff\n\n{handoff_text}")
    task_sections = [
        f"### {task.path.name}\n\n{_read_file(task.path)}"
        for task in task_tracker(root).tasks_for_milestone(milestone_id)
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
                f"### {path.relative_to(root)}\n\n{_read_file(path)}" for path in files
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


def _session_profile(root: Path, task: Task | None) -> Profile:
    return load_profile(root, task.profile if task is not None else None)


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
        lines.append(f"### {path.name}\n\n{_read_file(path).strip()}")
    return "\n\n".join(lines)


def _build_planner_prompt(root: Path) -> str:
    parts: list[str] = []
    plan = _read_file(root / DESIGN_PLAN)
    if plan.strip():
        parts.append(f"## Design Plan\n\n{plan}")
    project = _read_file(root / PROJECT_PLAN)
    if project.strip():
        parts.append(f"## Current Project Plan\n\n{project}")
    tasks = task_tracker(root).list_tasks()
    if tasks:
        parts.append(f"## Current Tasks\n\n{_format_task_listing(tasks)}")
    profile_listing = _format_profile_listing(root)
    if profile_listing:
        parts.append(f"## Existing Profiles\n\n{profile_listing}")
    findings = finding_tracker(root).open_findings()
    if findings:
        finding_sections = [
            f"### {finding.path.name}\n\n{_read_file(finding.path)}" for finding in findings
        ]
        parts.append("## Open Findings\n\n" + "\n\n".join(finding_sections))
    handoff = _latest_handoff(root, "planner")
    if handoff:
        parts.append(f"## Latest Planner Handoff\n\n{handoff}")
    return "\n\n".join(parts)


def _build_developer_prompt(root: Path) -> str:
    parts: list[str] = []
    task = task_tracker(root).select_next_development_task()
    if task:
        content = _read_file(task.path)
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


def _build_integrator_prompt(root: Path) -> str:
    parts: list[str] = []
    milestone = select_integration_milestone(root)
    tracker = task_tracker(root)
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
        for task in tracker.tasks_for_milestone(milestone):
            task_sections.append(f"### {task.path.name}\n\n{_read_file(task.path)}")
        if task_sections:
            parts.append("## Milestone Task Files\n\n" + "\n\n".join(task_sections))
    plan = _read_file(root / DESIGN_PLAN)
    if plan.strip():
        parts.append(f"## Design Plan\n\n{plan}")
    project = _read_file(root / PROJECT_PLAN)
    if project.strip():
        parts.append(f"## Project Plan\n\n{project}")
    for role_name in ("developer", "reviewer", "integrator"):
        handoff = _latest_handoff(root, role_name)
        if handoff:
            parts.append(f"## Latest {role_name.title()} Handoff\n\n{handoff}")
    return "\n\n".join(parts)


def _build_reviewer_prompt(root: Path) -> str:
    parts: list[str] = []
    task = task_tracker(root).select_next_review_task()
    if task:
        content = _read_file(task.path)
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


# ---------------------------------------------------------------------------
# Session invocation
# ---------------------------------------------------------------------------


def invoke_session(
    root: Path,
    role_name: str,
    system_prompt: str,
    session_prompt: str,
    *,
    agent_provider: AgentProvider,
) -> int:
    print(f"--- Invoking {role_name} session ---")
    try:
        result = agent_provider.invoke(
            root=root,
            role_name=role_name,
            system_prompt=system_prompt,
            session_prompt=session_prompt,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: agent command not found: {exc.filename!r}")
        sys.exit(1)
    print(f"--- {role_name} session exited with code {result.return_code} ---")
    return result.return_code


# ---------------------------------------------------------------------------
# Post-session processing
# ---------------------------------------------------------------------------


def validate_handoff(handoff_path: Path) -> tuple[bool, str]:
    if not handoff_path.exists():
        return False, "handoff file does not exist"
    text = _read_file(handoff_path)
    if not text.strip():
        return False, "handoff file is empty"
    missing = [heading for heading in REQUIRED_HANDOFF_HEADINGS if heading not in text]
    if missing:
        return False, f"handoff is missing required heading(s): {', '.join(missing)}"
    open_issues = text.split("## Open Issues", 1)[1].split("##", 1)[0].lower()
    if "unrecoverable" in open_issues:
        return False, "handoff reports an unrecoverable issue"
    return True, ""


def archive_handoff(root: Path, role_name: str) -> Path:
    src = root / ARTIFACTS_DIR / role_name / "handoff.md"
    history = root / HISTORY_DIR
    history.mkdir(parents=True, exist_ok=True)
    dest = history / f"{_timestamp()}_{role_name}_handoff.md"
    shutil.copy2(src, dest)
    return dest


def _task_is_complete(task_path: Path) -> bool:
    text = _read_file(task_path)
    checked = text.count("- [x]") + text.count("- [X]")
    unchecked = text.count("- [ ]")
    return checked > 0 and unchecked == 0


def _task_is_approved(task_path: Path) -> bool:
    text = _read_file(task_path)
    review_match = re.search(r"^## Review[ \t]*$([\s\S]*?)(?=^##\s|\Z)", text, flags=re.MULTILINE)
    if not review_match:
        return False
    review_text = review_match.group(1).lower()
    return "- [x] approved" in review_text


def mark_task_in_review(root: Path, task_path: Path) -> None:
    tracker = task_tracker(root)
    task = tracker.get(task_path.stem.split("_")[0])
    tracker.mark_in_review(task.id)
    print(f"  Task {task.path.name} completed by developer; status set to in_review")


def mark_task_changes_requested(root: Path, task_path: Path) -> None:
    tracker = task_tracker(root)
    task = tracker.get(task_path.stem.split("_")[0])
    tracker.mark_changes_requested(task.id)
    print(f"  Task {task.path.name} rejected by reviewer; status set to changes_requested")


def close_task(root: Path, task_path: Path, role_name: str = "reviewer") -> None:
    tracker = task_tracker(root)
    task = tracker.get(task_path.stem.split("_")[0])
    tracker.close(task.id)
    print(f"  Task {task.path.name} closed by {role_name}; status set to closed")


def _handoff_has_open_issues(handoff_path: Path) -> bool:
    text = _read_file(handoff_path)
    if "## Open Issues" not in text:
        return False
    open_issues = text.split("## Open Issues", 1)[1].split("##", 1)[0].strip().lower()
    return bool(open_issues and "none" not in open_issues)


def _handoff_section(handoff_path: Path, heading: str) -> str:
    text = _read_file(handoff_path)
    match = re.search(
        rf"^## {re.escape(heading)}[ \t]*$([\s\S]*?)(?=^##\s|\Z)",
        text,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def _addressed_finding_ids(handoff_path: Path) -> list[str]:
    return re.findall(
        r"(?<![A-Z0-9])F\d{4,5}(?!\d)",
        _handoff_section(handoff_path, "Addressed Findings"),
    )


def _mark_addressed_findings_planned(root: Path, handoff_path: Path) -> None:
    tracker = finding_tracker(root)
    for finding_id in _addressed_finding_ids(handoff_path):
        try:
            tracker.mark_planned(finding_id)
        except KeyError:
            print(f"WARNING: planner handoff referenced unknown finding {finding_id}")


def _mark_milestone_findings_resolved(root: Path, milestone: str) -> None:
    tracker = finding_tracker(root)
    for finding in tracker.planned_findings_for_milestone(milestone):
        tracker.mark_resolved(finding.id)


def _mark_milestone_integrated(root: Path, milestone: str, handoff_path: Path) -> None:
    milestone_tracker(root).mark_integrated(milestone, handoff_path)
    print(f"  Milestone {milestone} marked integrated")


def process_handoff(root: Path, role_name: str) -> None:
    archived = archive_handoff(root, role_name)
    print(f"  Handoff archived to {archived.name}")

    if role_name == "architect":
        milestone = select_architecture_review_milestone(root)
        if milestone is not None:
            if _handoff_has_open_issues(archived):
                finding_tracker(root).create_from_handoff(
                    source="architect",
                    milestone=milestone,
                    handoff_path=archived,
                )
                print("  Architecture review reported open issues; finding created")
            else:
                milestone_tracker(root).mark_architecture_approved(milestone, archived)
                print(f"  Milestone {milestone} marked architecture-approved")
    elif role_name == "developer":
        task_path = select_task(root)
        if task_path and _task_is_complete(task_path):
            mark_task_in_review(root, task_path)
    elif role_name == "planner":
        handoff_path = root / ARTIFACTS_DIR / role_name / "handoff.md"
        _mark_addressed_findings_planned(root, handoff_path)
    elif role_name == "reviewer":
        task_path = select_review_task(root)
        handoff_path = root / ARTIFACTS_DIR / role_name / "handoff.md"
        if task_path and _task_is_approved(task_path):
            close_task(root, task_path, role_name)
        elif task_path and _handoff_has_open_issues(handoff_path):
            mark_task_changes_requested(root, task_path)
    elif role_name == "integrator":
        handoff_path = root / ARTIFACTS_DIR / role_name / "handoff.md"
        milestone = select_integration_milestone(root)
        if _handoff_has_open_issues(handoff_path):
            finding = finding_tracker(root).create_from_handoff(
                source="integrator",
                milestone=milestone,
                handoff_path=archived,
            )
            if milestone is not None:
                milestone_tracker(root).mark_integration_failed(milestone, finding.id)
            print("  Integration reported open issues; finding created for planner follow-up")
            return
        if milestone is not None:
            _mark_milestone_integrated(root, milestone, archived)
            _mark_milestone_findings_resolved(root, milestone)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _task_for_role(root: Path, role_name: str) -> Task | None:
    tracker = task_tracker(root)
    if role_name == "developer":
        return tracker.select_next_development_task()
    if role_name == "reviewer":
        return tracker.select_next_review_task()
    return None


def _environment_for_session(root: Path, role_name: str) -> EnvironmentManager:
    task = _task_for_role(root, role_name)
    profile = load_profile(root, task.profile if task is not None else None)
    return EnvironmentManager(root, profile.environment)


def run_loop(
    root: Path,
    *,
    auto: bool,
    max_sessions: int,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    dangerous_skip_permissions: bool = False,
    agent_providers: dict[str, AgentProvider] | None = None,
    role_agent_providers: dict[str, str] | None = None,
) -> None:
    sessions_run = 0
    resolved_agent_configs = None
    if agent_providers is None:
        agent_configuration = load_agent_configuration(
            root,
            provider=provider,
            model=model,
            effort=effort,
            dangerous_skip_permissions=dangerous_skip_permissions,
        )
        agent_providers = agent_configuration.providers
        role_agent_providers = agent_configuration.role_providers
        resolved_agent_configs = agent_configuration.resolved

    while sessions_run < max_sessions:
        role_name = assess_state(root)
        if role_name is None:
            print("All milestones complete or no task can proceed. Stopping.")
            break

        role = ROLES[role_name]
        print(f"\n{'=' * 60}")
        print(f"Session {sessions_run + 1}: selecting role '{role_name}'")
        print(f"{'=' * 60}")
        if resolved_agent_configs is not None:
            _log_resolved_agent_config(root, role_name, resolved_agent_configs[role_name])

        artifacts_dir = root / ARTIFACTS_DIR / role_name
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        try:
            system_prompt = build_system_prompt(root, role)
            session_prompt = build_session_prompt(root, role_name)
            environment = _environment_for_session(root, role_name)
        except ProfileNotFoundError as exc:
            print(f"ERROR: {exc}. Stopping.")
            sys.exit(1)
        manage_environment = role.needs_environment and environment.manages_role(role_name)
        if manage_environment:
            try:
                print(f"--- Preparing environment for {role_name} session ---")
                environment.pre_session(role_name)
                environment.setup(role_name)
            except EnvironmentCommandError as exc:
                print(f"ERROR: {exc}. Stopping.")
                sys.exit(1)

        return_code = 0
        try:
            return_code = invoke_session(
                root,
                role_name,
                system_prompt,
                session_prompt,
                agent_provider=provider_for_role(role_name, agent_providers, role_agent_providers),
            )
        finally:
            if manage_environment:
                try:
                    print(f"--- Tearing down environment for {role_name} session ---")
                    environment.post_session(role_name)
                except EnvironmentCommandError as exc:
                    print(f"ERROR: {exc}. Stopping.")
                    sys.exit(1)
        if return_code != 0:
            print(f"ERROR: {role_name} session failed with exit code {return_code}. Stopping.")
            sys.exit(return_code)

        handoff_path = artifacts_dir / "handoff.md"
        is_valid, error = validate_handoff(handoff_path)
        if not is_valid:
            print(f"ERROR: Invalid handoff produced by {role_name}: {error}. Stopping.")
            sys.exit(1)

        process_handoff(root, role_name)
        sessions_run += 1

        if not auto:
            handoff_text = _read_file(handoff_path)
            print(f"\n{'- ' * 30}")
            print(handoff_text[:2000])
            print(f"{'- ' * 30}")
            answer = input("Continue? [Y/n]: ").strip().lower()
            if answer in ("n", "q"):
                print("Stopped by user.")
                break

    print(f"\nOrchestrator finished after {sessions_run} session(s).")



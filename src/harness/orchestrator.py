from __future__ import annotations

import argparse
import dataclasses
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from harness.agents import AgentProvider, CliAgentProvider, provider_for_role
from harness.task_tracker import FileTaskTracker, Task

DEFAULT_PROJECT_ROOT = Path.cwd()

CONVENTIONS_FILE = "specs/development/conventions.md"
TOOLING_FILE = "specs/development/tooling.md"
DESIGN_PLAN = "work/plans/design-plan.md"
PROJECT_PLAN = "work/plans/project-plan.md"
HISTORY_DIR = "work/history"
ARTIFACTS_DIR = ".session-artifacts"

REQUIRED_HANDOFF_HEADINGS = (
    "## Done",
    "## Changed Artifacts",
    "## Open Issues",
    "## Next Session Hint",
)


@dataclasses.dataclass(frozen=True)
class RoleConfig:
    name: str
    role_file: str
    reads_tooling: bool


ROLES: dict[str, RoleConfig] = {
    "architect": RoleConfig(
        "architect", "specs/development/role-architect.md", reads_tooling=True
    ),
    "planner": RoleConfig("planner", "specs/development/role-planner.md", reads_tooling=False),
    "developer": RoleConfig(
        "developer", "specs/development/role-developer.md", reads_tooling=True
    ),
    "reviewer": RoleConfig("reviewer", "specs/development/role-reviewer.md", reads_tooling=True),
    "integrator": RoleConfig(
        "integrator", "specs/development/role-integrator.md", reads_tooling=True
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


def select_task(root: Path) -> Path | None:
    """Select the lowest-numbered task eligible for development."""
    task = task_tracker(root).select_next_development_task()
    return task.path if task else None


def select_review_task(root: Path) -> Path | None:
    task = task_tracker(root).select_next_review_task()
    return task.path if task else None


def _safe_marker_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _integration_marker(root: Path, milestone: str) -> Path:
    return root / HISTORY_DIR / f"integrated_{_safe_marker_part(milestone)}.md"


def _milestone_integrated(root: Path, milestone: str) -> bool:
    return _integration_marker(root, milestone).exists()


def select_integration_milestone(root: Path) -> str | None:
    tracker = task_tracker(root)
    for milestone in tracker.completed_milestones():
        if not _milestone_integrated(root, milestone):
            return milestone
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
        _read_file(root / CONVENTIONS_FILE),
        _read_file(root / role.role_file),
    ]
    if role.reads_tooling:
        parts.append(_read_file(root / TOOLING_FILE))
    return "\n\n---\n\n".join(p for p in parts if p)


def _handoff_reminder(role_name: str) -> str:
    return (
        f"\n\nIMPORTANT: When done, write your handoff file to "
        f".session-artifacts/{role_name}/handoff.md using the template from conventions.md."
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
    plan = _read_file(root / DESIGN_PLAN)
    if plan.strip():
        parts.append(f"## Current Design Plan\n\n{plan}")
    handoff = _latest_handoff(root, "architect")
    if handoff:
        parts.append(f"## Latest Architect Handoff\n\n{handoff}")
    if not parts:
        parts.append("No design plan exists yet. Create one from the system specification.")
    return "\n\n".join(parts)


def _format_task_listing(tasks: list[Task]) -> str:
    return "\n".join(
        f"- {task.id} [{task.status.value}] {task.title} "
        f"({task.path.relative_to(task.path.parents[2])})"
        for task in tasks
    )


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
        if task.validation:
            commands = "\n".join(f"- `{command}`" for command in task.validation)
            parts.append(
                f"## Task Validation Commands\n\nRun from the workspace root:\n\n{commands}"
            )
        elif task.validation == ():
            parts.append(
                "## Task Validation Commands\n\n"
                "Task metadata sets `validation = []`. No validation commands "
                "are required; state in the handoff whether any validation was "
                "run and why."
            )
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


def _mark_milestone_integrated(root: Path, milestone: str, handoff_path: Path) -> None:
    marker = _integration_marker(root, milestone)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        f"# Integration Complete: {milestone}\n\n"
        f"- Handoff: {handoff_path.name}\n"
    )
    print(f"  Milestone {milestone} marked integrated")


def process_handoff(root: Path, role_name: str) -> None:
    archived = archive_handoff(root, role_name)
    print(f"  Handoff archived to {archived.name}")

    if role_name == "developer":
        task_path = select_task(root)
        if task_path and _task_is_complete(task_path):
            mark_task_in_review(root, task_path)
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
            print("ERROR: Integration reported open issues. Stopping.")
            sys.exit(1)
        if milestone is not None:
            _mark_milestone_integrated(root, milestone, archived)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_loop(
    root: Path,
    *,
    auto: bool,
    max_sessions: int,
    agent_cmd: str = "claude -p",
    dangerous_skip_permissions: bool = False,
    agent_providers: dict[str, AgentProvider] | None = None,
    role_agent_providers: dict[str, str] | None = None,
) -> None:
    sessions_run = 0
    if agent_providers is None:
        extra_args = ("--dangerously-skip-permissions",) if dangerous_skip_permissions else ()
        agent_providers = {
            "default": CliAgentProvider.from_command(agent_cmd, extra_args=extra_args)
        }

    while sessions_run < max_sessions:
        role_name = assess_state(root)
        if role_name is None:
            print("All milestones complete or no task can proceed. Stopping.")
            break

        role = ROLES[role_name]
        print(f"\n{'=' * 60}")
        print(f"Session {sessions_run + 1}: selecting role '{role_name}'")
        print(f"{'=' * 60}")

        artifacts_dir = root / ARTIFACTS_DIR / role_name
        if artifacts_dir.exists():
            shutil.rmtree(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        system_prompt = build_system_prompt(root, role)
        session_prompt = build_session_prompt(root, role_name)
        return_code = invoke_session(
            root,
            role_name,
            system_prompt,
            session_prompt,
            agent_provider=provider_for_role(role_name, agent_providers, role_agent_providers),
        )
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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Orchestrate agentic development sessions.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run autonomously without pausing between sessions.",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=20,
        help="Maximum number of sessions to run (default: 20).",
    )
    parser.add_argument(
        "--agent-cmd",
        default="claude -p",
        help="Agent command prefix (default: 'claude -p').",
    )
    parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        help="Pass --dangerously-skip-permissions to the agent command.",
    )
    args = parser.parse_args()
    run_loop(
        args.root.resolve(),
        auto=args.auto,
        max_sessions=args.max_sessions,
        agent_cmd=args.agent_cmd,
        dangerous_skip_permissions=args.dangerously_skip_permissions,
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import dataclasses
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONVENTIONS_FILE = "specs/development/conventions.md"
TOOLING_FILE = "specs/development/tooling.md"
DESIGN_PLAN = "work/plans/design-plan.md"
PROJECT_PLAN = "work/plans/project-plan.md"
BACKLOG_DIR = "work/backlog"
HISTORY_DIR = "work/history"
ARTIFACTS_DIR = ".session-artifacts"


@dataclasses.dataclass(frozen=True)
class RoleConfig:
    name: str
    role_file: str
    reads_tooling: bool


ROLES: dict[str, RoleConfig] = {
    "architect": RoleConfig(
        "architect", "specs/development/role-architect.md", reads_tooling=True
    ),
    "planner": RoleConfig(
        "planner", "specs/development/role-planner.md", reads_tooling=False
    ),
    "developer": RoleConfig(
        "developer", "specs/development/role-developer.md", reads_tooling=True
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


def select_task(root: Path) -> Path | None:
    backlog = root / BACKLOG_DIR
    tasks = sorted(backlog.glob("T*.md"))
    return tasks[0] if tasks else None


def _latest_handoff(root: Path, role_name: str) -> str:
    history = root / HISTORY_DIR
    handoffs = sorted(history.glob(f"*_{role_name}_handoff.md"))
    if not handoffs:
        return ""
    return _read_file(handoffs[-1])


def _all_milestones_complete(root: Path) -> bool:
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

    task = select_task(root)
    if task is None:
        if _all_milestones_complete(root):
            return None
        return "planner"

    return "developer"


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


def _build_planner_prompt(root: Path) -> str:
    parts: list[str] = []
    plan = _read_file(root / DESIGN_PLAN)
    if plan.strip():
        parts.append(f"## Design Plan\n\n{plan}")
    project = _read_file(root / PROJECT_PLAN)
    if project.strip():
        parts.append(f"## Current Project Plan\n\n{project}")
    backlog = root / BACKLOG_DIR
    tasks = sorted(backlog.glob("T*.md"))
    if tasks:
        listing = "\n".join(f"- {t.name}" for t in tasks)
        parts.append(f"## Open Tasks in Backlog\n\n{listing}")
    handoff = _latest_handoff(root, "planner")
    if handoff:
        parts.append(f"## Latest Planner Handoff\n\n{handoff}")
    return "\n\n".join(parts)


def _build_developer_prompt(root: Path) -> str:
    parts: list[str] = []
    task_path = select_task(root)
    if task_path:
        content = _read_file(task_path)
        parts.append(f"## Assigned Task ({task_path.name})\n\n{content}")
    else:
        parts.append("No open tasks in backlog.")
    handoff = _latest_handoff(root, "developer")
    if handoff:
        parts.append(f"## Latest Developer Handoff\n\n{handoff}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Session invocation
# ---------------------------------------------------------------------------


def invoke_session(root: Path, role_name: str, system_prompt: str, session_prompt: str) -> int:
    cmd = [
        "claude",
        "-p",
        "--dangerously-skip-permissions",
        "--system-prompt",
        system_prompt,
        session_prompt,
    ]
    print(f"--- Invoking {role_name} session ---")
    try:
        result = subprocess.run(cmd, cwd=str(root))
    except FileNotFoundError:
        print("ERROR: 'claude' command not found. Is Claude Code installed?")
        sys.exit(1)
    print(f"--- {role_name} session exited with code {result.returncode} ---")
    return result.returncode


# ---------------------------------------------------------------------------
# Post-session processing
# ---------------------------------------------------------------------------


def archive_handoff(root: Path, role_name: str) -> Path:
    src = root / ARTIFACTS_DIR / role_name / "handoff.md"
    history = root / HISTORY_DIR
    history.mkdir(parents=True, exist_ok=True)
    dest = history / f"{_timestamp()}_{role_name}_handoff.md"
    shutil.copy2(src, dest)
    return dest


def _task_is_complete(task_path: Path) -> bool:
    text = _read_file(task_path)
    checked = text.count("- [x]")
    unchecked = text.count("- [ ]")
    return checked > 0 and unchecked == 0


def close_task(root: Path, task_path: Path, role_name: str) -> None:
    history = root / HISTORY_DIR
    history.mkdir(parents=True, exist_ok=True)
    dest = history / f"{_timestamp()}_{role_name}_closed-task.md"
    shutil.copy2(task_path, dest)
    task_path.unlink()
    print(f"  Task {task_path.name} closed and archived to {dest.name}")


def process_handoff(root: Path, role_name: str) -> None:
    archived = archive_handoff(root, role_name)
    print(f"  Handoff archived to {archived.name}")

    if role_name == "developer":
        task_path = select_task(root)
        if task_path and _task_is_complete(task_path):
            close_task(root, task_path, role_name)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_loop(root: Path, *, auto: bool, max_sessions: int) -> None:
    sessions_run = 0

    while sessions_run < max_sessions:
        role_name = assess_state(root)
        if role_name is None:
            print("All milestones complete. Stopping.")
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
        invoke_session(root, role_name, system_prompt, session_prompt)

        handoff_path = artifacts_dir / "handoff.md"
        if not handoff_path.exists():
            print(f"ERROR: No handoff produced by {role_name}. Stopping.")
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
    args = parser.parse_args()
    run_loop(PROJECT_ROOT, auto=args.auto, max_sessions=args.max_sessions)


if __name__ == "__main__":
    main()

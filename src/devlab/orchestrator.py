from __future__ import annotations

import dataclasses
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from devlab.agent_config import (
    ResolvedAgentConfig,
    format_resolved_agent_config,
    load_agent_configuration,
)
from devlab.agents import AgentProvider, provider_for_role
from devlab.environment import EnvironmentCommandError, EnvironmentManager
from devlab.profiles import ProfileNotFoundError, load_profile
from devlab.prompts import build_session_prompt, build_system_prompt
from devlab.task_tracker import Task
from devlab.workspace import (
    AGENT_LOG_DIR,
    ARTIFACTS_DIR,
    HISTORY_DIR,
    ROLES,
    assess_state,
    finding_tracker,
    milestone_tracker,
    read_file,
    select_architecture_review_milestone,
    select_integration_milestone,
    select_review_task,
    select_task,
    task_tracker,
)

DEFAULT_PROJECT_ROOT = Path.cwd()

REQUIRED_HANDOFF_HEADINGS = (
    "## Done",
    "## Changed Artifacts",
    "## Open Issues",
    "## Addressed Findings",
    "## Next Session Hint",
)


@dataclasses.dataclass(frozen=True)
class SessionError:
    """An error that stopped the orchestrator loop."""

    phase: str
    message: str
    exit_code: int


@dataclasses.dataclass(frozen=True)
class RunResult:
    """Outcome of a run_loop execution.

    Callers inspect ``completed`` to determine whether the workflow finished
    normally (all milestones done, max sessions reached, or user quit) or was
    stopped by an error.
    """

    sessions_run: int
    completed: bool
    exit_code: int
    errors: tuple[SessionError, ...]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _log_resolved_agent_config(
    root: Path, role_name: str, config: ResolvedAgentConfig,
) -> Path:
    path = root / AGENT_LOG_DIR / f"{_timestamp()}_{role_name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_resolved_agent_config(config))
    return path


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
    """Invoke an agent session. Raises FileNotFoundError if the agent command is missing."""
    print(f"--- Invoking {role_name} session ---")
    result = agent_provider.invoke(
        root=root,
        role_name=role_name,
        system_prompt=system_prompt,
        session_prompt=session_prompt,
    )
    print(f"--- {role_name} session exited with code {result.return_code} ---")
    return result.return_code


# ---------------------------------------------------------------------------
# Post-session processing
# ---------------------------------------------------------------------------


def validate_handoff(handoff_path: Path) -> tuple[bool, str]:
    if not handoff_path.exists():
        return False, "handoff file does not exist"
    text = read_file(handoff_path)
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
    text = read_file(task_path)
    checked = text.count("- [x]") + text.count("- [X]")
    unchecked = text.count("- [ ]")
    return checked > 0 and unchecked == 0


def _task_is_approved(task_path: Path) -> bool:
    text = read_file(task_path)
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
    text = read_file(handoff_path)
    if "## Open Issues" not in text:
        return False
    open_issues = text.split("## Open Issues", 1)[1].split("##", 1)[0].strip().lower()
    return bool(open_issues and "none" not in open_issues)


def _handoff_section(handoff_path: Path, heading: str) -> str:
    text = read_file(handoff_path)
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
) -> RunResult:
    """Run the orchestrator loop, returning a structured result."""
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
            return RunResult(sessions_run, False, 1,
                             (SessionError("profile_resolution", str(exc), 1),))

        manage_environment = role.needs_environment and environment.manages_role(role_name)
        if manage_environment:
            try:
                print(f"--- Preparing environment for {role_name} session ---")
                environment.pre_session(role_name)
                environment.setup(role_name)
            except EnvironmentCommandError as exc:
                print(f"ERROR: {exc}. Stopping.")
                return RunResult(sessions_run, False, 1,
                                 (SessionError("environment_setup", str(exc), 1),))

        return_code = 0
        agent_error: SessionError | None = None
        try:
            return_code = invoke_session(
                root,
                role_name,
                system_prompt,
                session_prompt,
                agent_provider=provider_for_role(role_name, agent_providers, role_agent_providers),
            )
        except FileNotFoundError as exc:
            print(f"ERROR: agent command not found: {exc.filename!r}")
            agent_error = SessionError(
                "agent_invocation", f"agent command not found: {exc.filename!r}", 1,
            )

        teardown_error: SessionError | None = None
        if manage_environment:
            try:
                print(f"--- Tearing down environment for {role_name} session ---")
                environment.post_session(role_name)
            except EnvironmentCommandError as exc:
                print(f"ERROR: {exc}. Stopping.")
                teardown_error = SessionError("environment_teardown", str(exc), 1)

        if agent_error is not None:
            errors = (agent_error,) + ((teardown_error,) if teardown_error else ())
            return RunResult(sessions_run, False, agent_error.exit_code, errors)
        if teardown_error is not None:
            return RunResult(sessions_run, False, return_code or 1, (teardown_error,))
        if return_code != 0:
            msg = f"{role_name} session failed with exit code {return_code}"
            print(f"ERROR: {msg}. Stopping.")
            return RunResult(sessions_run, False, return_code,
                             (SessionError("agent_invocation", msg, return_code),))

        handoff_path = artifacts_dir / "handoff.md"
        is_valid, error = validate_handoff(handoff_path)
        if not is_valid:
            print(f"ERROR: Invalid handoff produced by {role_name}: {error}. Stopping.")
            return RunResult(sessions_run, False, 1,
                             (SessionError("handoff_validation", error, 1),))

        process_handoff(root, role_name)
        sessions_run += 1

        if not auto:
            handoff_text = read_file(handoff_path)
            print(f"\n{'- ' * 30}")
            print(handoff_text[:2000])
            print(f"{'- ' * 30}")
            answer = input("Continue? [Y/n]: ").strip().lower()
            if answer in ("n", "q"):
                print("Stopped by user.")
                break

    print(f"\nOrchestrator finished after {sessions_run} session(s).")
    return RunResult(sessions_run, True, 0, ())



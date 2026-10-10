# PYTHON_ARGCOMPLETE_OK
from __future__ import annotations

import argparse
import os
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import argcomplete
from argcomplete.completers import ChoicesCompleter

from devlab._console import ConsoleArgumentParser
from devlab._logging import DEFAULT_HEARTBEAT_INTERVAL_SECONDS
from devlab.resources.init import INIT_TEMPLATES

DEFAULT_PROJECT_ROOT = Path(".")
IMPLEMENT_MAX_SESSIONS = 20
PLAN_MAX_SESSIONS = 2
DEFAULT_CLARIFICATION_MODE = "operator"


def _devlab_version() -> str:
    """Return the installed distribution version used by this CLI."""
    try:
        return version("devlab")
    except PackageNotFoundError:
        return "unknown"


def _heartbeat_interval(value: str) -> int:
    try:
        interval = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "heartbeat interval must be a nonnegative integer"
        ) from exc
    if interval < 0:
        raise argparse.ArgumentTypeError("heartbeat interval must be a nonnegative integer")
    return interval


def _run_parent_parser(
    *, max_sessions: int, session_kind: str = "sessions"
) -> ConsoleArgumentParser:
    parser = ConsoleArgumentParser(add_help=False)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=max_sessions,
        help=f"Maximum number of {session_kind} to run (default: {max_sessions}).",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override provider resolution from the target agents configuration.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override model resolution from the target agents configuration.",
    )
    parser.add_argument(
        "--effort",
        default=None,
        help="Override effort resolution from the target agents configuration.",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=_heartbeat_interval,
        default=DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        metavar="SECONDS",
        help=(
            "Report subprocess output activity every SECONDS (default: 60; 0 disables heartbeats)."
        ),
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Show only warnings and errors instead of the default INFO logging.",
    )
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show debug diagnostics instead of the default INFO logging.",
    )
    parser.add_argument(
        "--log-file", type=Path, default=None, help="Write detailed DevLab logs to this file."
    )
    parser.add_argument(
        "--retain-prompts",
        action="store_true",
        help="Write full base/session prompts to .devlab/logs/agents/ for debugging.",
    )
    parser.add_argument(
        "--clarification-mode",
        choices=("operator", "agent"),
        default=DEFAULT_CLARIFICATION_MODE,
        help=(
            "Stop for operator clarification or use a bounded resolver agent "
            f"(default: {DEFAULT_CLARIFICATION_MODE})."
        ),
    )
    parser.add_argument(
        "--unattended",
        action="store_true",
        help="Run without operator clarification stops; implies --clarification-mode=agent.",
    )
    parser.add_argument(
        "--handoff-correction",
        action="store_true",
        help="Allow one correction-only invocation for a missing accepted result.",
    )
    _add_executable_config_authorization_options(parser)
    return parser


def _add_executable_config_authorization_options(
    parser: argparse.ArgumentParser,
) -> None:
    authorization = parser.add_mutually_exclusive_group()
    authorization.add_argument(
        "--require-exec-config-digest",
        default=None,
        metavar="DIGEST",
        help="Run only when executable configuration matches this approved digest.",
    )
    authorization.add_argument(
        "--accept-current-exec-config",
        action="store_true",
        help=(
            "Accept current executable configuration for this invocation without "
            "persistent trust; intended for externally contained environments."
        ),
    )


def build_parser() -> ConsoleArgumentParser:
    parser = ConsoleArgumentParser(
        prog="devlab",
        description="Orchestrate agentic development sessions.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_devlab_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    completion = subparsers.add_parser(
        "completion", help="Print shell completion registration code."
    )
    completion.add_argument("shell", choices=("bash", "zsh"))

    init_parser = subparsers.add_parser("init", help="Create a target-local .devlab tree.")
    init_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to initialize (default: current working directory).",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing starter files.",
    )
    init_parser.add_argument(
        "--template",
        choices=INIT_TEMPLATES,
        default="neutral",
        help="Starter tooling template (default: neutral).",
    )
    init_parser.add_argument(
        "--git-user-name",
        default=None,
        help="Git user.name for DevLab-created commits.",
    )
    init_parser.add_argument(
        "--git-user-email",
        default=None,
        help="Git user.email for DevLab-created commits.",
    )

    subparsers.add_parser(
        "implement",
        parents=[_run_parent_parser(max_sessions=IMPLEMENT_MAX_SESSIONS)],
        help="Implement planned DevLab workflow tasks.",
    )

    continue_parser = subparsers.add_parser(
        "continue",
        parents=[_run_parent_parser(max_sessions=IMPLEMENT_MAX_SESSIONS)],
        help="Recover if necessary and perform the next valid workflow action.",
    )
    continue_parser.add_argument(
        "--discard-interrupted-session",
        action="store_true",
        help="Discard an observed interrupted session without prompting.",
    )
    continue_parser.add_argument(
        "--require-interrupted-head",
        default=None,
        metavar="COMMIT",
        help="Discard only when the observed restart boundary is this exact commit.",
    )
    continue_parser.add_argument(
        "--retry-stopped-task",
        action="store_true",
        help="Explicitly retry a task stopped after bounded developer recovery.",
    )

    plan_parser = subparsers.add_parser(
        "plan",
        parents=[
            _run_parent_parser(
                max_sessions=PLAN_MAX_SESSIONS,
                session_kind="planning sessions",
            )
        ],
        help="Run planning sessions and stop before implementation.",
    )
    plan_parser.add_argument(
        "--revise",
        action="store_true",
        help="Review and possibly update existing design and project plans.",
    )
    plan_parser.add_argument(
        "--adopt-existing",
        action="store_true",
        help="Treat the first planning run as adoption of an already-started project.",
    )
    plan_parser.add_argument(
        "--replace-plan",
        action="store_true",
        help="Archive the active DevLab plan and create a fresh current plan.",
    )
    plan_parser.add_argument(
        "--mark-specs-planned",
        action="store_true",
        help=(
            "Mark the current committed specs as planned without running "
            "architect/planner reconciliation."
        ),
    )

    status_parser = subparsers.add_parser("status", help="Show workspace status.")
    status_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to inspect (default: current working directory).",
    )
    status_view = status_parser.add_mutually_exclusive_group()
    status_view.add_argument(
        "--verbose",
        action="store_true",
        help="Show lifecycle provenance and detailed workspace state.",
    )
    status_view.add_argument(
        "--digest",
        action="store_true",
        help="Emit a Markdown operator digest.",
    )
    status_view.add_argument(
        "--next-command",
        action="store_true",
        help="Emit one safe command for the next workflow action.",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the selected status view as JSON.",
    )

    diagnostics_parser = subparsers.add_parser(
        "diagnostics", help="Show workflow diagnostics and quality warnings."
    )
    diagnostics_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to inspect (default: current working directory).",
    )
    diagnostics_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-session, per-task, profile, and log details.",
    )
    diagnostics_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit diagnostics as JSON for tools and agents.",
    )

    history_parser = subparsers.add_parser(
        "history",
        help="Show session history.",
    )
    history_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to inspect (default: current working directory).",
    )
    history_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit session history as JSON.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Validate DevLab workspace configuration."
    )
    doctor_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to inspect (default: current working directory).",
    )

    smoke_parser = subparsers.add_parser(
        "agent-smoke-test", help="Start configured agent providers with a tiny prompt."
    )
    smoke_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help=(
            "Workspace root for provider execution and logs (default: current working directory)."
        ),
    )
    smoke_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=("Agent config TOML path (default: .devlab/config/agents.toml under --root)."),
    )
    smoke_selection = smoke_parser.add_mutually_exclusive_group()
    smoke_selection.add_argument(
        "--role",
        action="append",
        default=None,
        help=(
            "Role resolution to test. May be passed more than once; "
            "defaults to deduplicated workflow provider configurations."
        ),
    )
    smoke_selection.add_argument(
        "--all-providers",
        action="store_true",
        help="Test every configured provider entry, including providers not assigned to roles.",
    )
    smoke_selection.add_argument(
        "--provider",
        default=None,
        help="Configured provider name to smoke-test.",
    )
    smoke_parser.add_argument(
        "--use-provider-defaults",
        action="store_true",
        help=(
            "Use [providers.<name>.defaults] instead of role-derived policy. "
            "Valid with --provider or --all-providers."
        ),
    )
    smoke_parser.add_argument(
        "--model",
        default=None,
        help=(
            "Override the role-derived model for this smoke test; with "
            "--use-provider-defaults, override the provider default."
        ),
    )
    smoke_parser.add_argument(
        "--effort",
        default=None,
        help=(
            "Override the role-derived effort for this smoke test; with "
            "--use-provider-defaults, override the provider default."
        ),
    )
    _add_executable_config_authorization_options(smoke_parser)

    trust_parser = subparsers.add_parser("trust", help="Inspect and manage operator-local trust.")
    trust_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Workspace root (default: current working directory).",
    )
    trust_subparsers = trust_parser.add_subparsers(dest="trust_command", required=True)
    trust_exec = trust_subparsers.add_parser(
        "executable-config",
        help="Inspect, approve, or revoke executable configuration.",
    )
    trust_exec.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Agent config TOML path (default: target .devlab/config/agents.toml).",
    )
    trust_exec.add_argument(
        "--provider",
        default=None,
        help="Override provider resolution from the target agents configuration.",
    )
    trust_exec.add_argument(
        "--model",
        default=None,
        help="Override model resolution from the target agents configuration.",
    )
    trust_exec.add_argument(
        "--effort",
        default=None,
        help="Override effort resolution from the target agents configuration.",
    )
    trust_action = trust_exec.add_mutually_exclusive_group()
    trust_action.add_argument(
        "--show",
        action="store_true",
        help="Show effective executable configuration and trust status without changing it.",
    )
    trust_action.add_argument(
        "--show-new",
        action="store_true",
        help="Show only added executable configuration entries without changing trust.",
    )
    trust_action.add_argument(
        "--show-changes",
        action="store_true",
        help="Show added and removed executable configuration entries without changing trust.",
    )
    trust_action.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke stored trust for this workspace and config source.",
    )
    trust_exec.epilog = (
        "With no action, display the effective configuration and prompt to trust it."
    )

    clean_parser = subparsers.add_parser(
        "clean-failed-session",
        help="Remove untracked logs/artifacts from failed sessions.",
    )
    clean_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to clean (default: current working directory).",
    )

    service_parser = subparsers.add_parser("test-service", help="Manage workspace test services.")
    service_parser.add_argument("--root", type=Path, default=DEFAULT_PROJECT_ROOT)
    service_actions = service_parser.add_subparsers(dest="service_action", required=True)
    service_actions.add_parser("init", help="Prepare ignored private service storage.")
    service_actions.add_parser("status", help="Show last observed service states.")
    service_cleanup = service_actions.add_parser("cleanup", help="Remove one owned service.")
    service_cleanup.add_argument("service_id")
    service_cleanup.add_argument("--show", action="store_true")
    service_cleanup.add_argument(
        "--trust",
        action="store_true",
        help="Trust the displayed cleanup definition without running it.",
    )
    _add_executable_config_authorization_options(service_cleanup)

    prerequisite_parser = subparsers.add_parser(
        "prerequisite", help="Inspect, check, approve, or revoke profile prerequisites."
    )
    prerequisite_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    prerequisite_subparsers = prerequisite_parser.add_subparsers(
        dest="prerequisite_command", required=True
    )
    prerequisite_subparsers.add_parser("list", help="List configured prerequisites.")
    prerequisite_subparsers.add_parser(
        "blocked", help="Show the latest durable prerequisite blocker."
    )
    for action, help_text in (
        ("show", "Show a prerequisite without executing its check."),
        ("check", "Evaluate a prerequisite now."),
        ("approve", "Record an operator attestation."),
        ("revoke", "Revoke an operator attestation."),
    ):
        action_parser = prerequisite_subparsers.add_parser(action, help=help_text)
        action_parser.add_argument("profile_id")
        action_parser.add_argument("prerequisite_id")
        if action == "approve":
            action_parser.add_argument(
                "--yes", action="store_true", help="Approve without an interactive prompt."
            )
            action_parser.add_argument(
                "--operator", default="", help="Optional operator identity for local provenance."
            )
            action_parser.add_argument(
                "--note", default="", help="Optional local evidence or rationale."
            )

    clarify_parser = subparsers.add_parser(
        "clarify", help="Inspect and answer operator clarifications."
    )
    clarify_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    clarify_subparsers = clarify_parser.add_subparsers(dest="clarify_command", required=True)
    clarify_subparsers.add_parser("list", help="List clarifications.")
    clarify_show = clarify_subparsers.add_parser("show", help="Show a clarification file.")
    clarify_show.add_argument("clarification_id")
    clarify_answer = clarify_subparsers.add_parser(
        "answer", help="Answer a pending clarification."
    )
    clarify_answer.add_argument("clarification_id", help="Clarification ID to answer.")
    answer_value = clarify_answer.add_mutually_exclusive_group(required=True)
    answer_value.add_argument(
        "--choice", default=None, help="Select an option declared by the clarification."
    )
    answer_value.add_argument(
        "--text", default=None, help="Supply a free-text clarification answer."
    )
    clarify_answer.add_argument(
        "--note", default="", help="Optional rationale recorded with the answer."
    )
    clarify_answer.add_argument(
        "--operator", default="", help="Optional operator identity recorded with the answer."
    )
    clarify_answer.add_argument(
        "--resume", action="store_true", help="Resume the blocked workflow after answering."
    )
    clarify_answer.add_argument(
        "--max-sessions",
        type=int,
        default=IMPLEMENT_MAX_SESSIONS,
        help=(
            f"Maximum sessions to run when --resume is used (default: {IMPLEMENT_MAX_SESSIONS})."
        ),
    )
    _add_executable_config_authorization_options(clarify_answer)
    clarify_supersede = clarify_subparsers.add_parser(
        "supersede", help="Mark a clarification superseded."
    )
    clarify_supersede.add_argument("clarification_id")
    clarify_supersede.add_argument("--reason", required=True)

    resume_parser = subparsers.add_parser(
        "resume", help="Resume the workflow blocked by an answered clarification."
    )
    resume_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    _add_executable_config_authorization_options(resume_parser)
    resume_parser.add_argument(
        "--max-sessions",
        type=int,
        default=IMPLEMENT_MAX_SESSIONS,
        help=(f"Maximum number of sessions to run (default: {IMPLEMENT_MAX_SESSIONS})."),
    )

    session_parser = subparsers.add_parser(
        "session", help="Commands used inside an active DevLab role session."
    )
    session_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Target workspace root (default: current working directory).",
    )
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    handoff_parser = session_subparsers.add_parser(
        "handoff", help="Initialize or submit the active session handoff candidate."
    )
    handoff_subparsers = handoff_parser.add_subparsers(dest="handoff_command", required=True)
    for command_name in ("init", "submit"):
        command_parser = handoff_subparsers.add_parser(command_name)
        command_parser.add_argument(
            "--session-envelope",
            type=Path,
            default=None,
            help=argparse.SUPPRESS,
        )

    _configure_completers(parser)
    return parser


def _complete_path(prefix: str, *, directories_only: bool = False, **_kwargs: object) -> list[str]:
    """List local paths without launching a shell or interpreting wildcard patterns."""
    directory, name_prefix = os.path.split(prefix)
    candidates = []
    try:
        with os.scandir(os.path.expanduser(directory) or ".") as entries:
            for entry in entries:
                if not entry.name.startswith(name_prefix):
                    continue
                if entry.name.startswith(".") and not name_prefix.startswith("."):
                    continue
                is_directory = entry.is_dir()
                if directories_only and not is_directory:
                    continue
                candidates.append(
                    os.path.join(directory, entry.name) + ("/" if is_directory else "")
                )
    except OSError:
        return []
    return sorted(candidates)


def _configure_completers(parser: argparse.ArgumentParser) -> None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                _configure_completers(child)
        elif action.type is Path:
            # Argcomplete's documented extension adds this attribute to argparse actions.
            action.completer = partial(  # ty: ignore[invalid-assignment]
                _complete_path, directories_only=action.dest == "root"
            )


def main() -> None:
    """Complete and parse arguments before loading workflow command handlers."""
    parser = build_parser()
    argcomplete.autocomplete(parser, default_completer=ChoicesCompleter({}))
    args = parser.parse_args()
    if args.command == "completion":
        print(argcomplete.shellcode(["devlab"], shell=args.shell), end="")
        return

    import sys

    from devlab._console import print_prose
    from devlab.cli_commands import dispatch
    from devlab.workspace import WorkspaceCompatibilityError

    try:
        dispatch(parser, args)
    except WorkspaceCompatibilityError as exc:
        print_prose(f"DevLab: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

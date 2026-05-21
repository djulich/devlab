from __future__ import annotations

import argparse
import logging
from pathlib import Path

from devlab._logging import configure_logging
from devlab.doctor import check_workspace, format_doctor_report
from devlab.init import format_init_result, init_workspace
from devlab.orchestrator import DEFAULT_PROJECT_ROOT, run_loop
from devlab.status import format_status


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="devlab",
        description="Orchestrate agentic development sessions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
        "--git-user-name",
        default=None,
        help="Git user.name for DevLab-created commits.",
    )
    init_parser.add_argument(
        "--git-user-email",
        default=None,
        help="Git user.email for DevLab-created commits.",
    )

    run_parser = subparsers.add_parser("run", help="Run the DevLab workflow loop.")
    run_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    run_parser.add_argument(
        "--auto",
        action="store_true",
        help="Run autonomously without pausing between sessions.",
    )
    run_parser.add_argument(
        "--max-sessions",
        type=int,
        default=20,
        help="Maximum number of sessions to run (default: 20).",
    )
    run_parser.add_argument(
        "--provider",
        default=None,
        help="Override the configured provider for this run.",
    )
    run_parser.add_argument(
        "--model",
        default=None,
        help="Override the configured model for this run.",
    )
    run_parser.add_argument(
        "--effort",
        default=None,
        help="Override the configured effort for this run.",
    )
    run_parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        help="Pass --dangerously-skip-permissions to the agent command.",
    )
    verbosity = run_parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Show only warnings and errors during the run.",
    )
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show debug diagnostics during the run.",
    )
    run_parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Write detailed DevLab run logs to this file.",
    )
    run_parser.add_argument(
        "--retain-prompts",
        action="store_true",
        help="Write full system/session prompts to .devlab/logs/agents/ for debugging.",
    )

    status_parser = subparsers.add_parser("status", help="Show workspace status.")
    status_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to inspect (default: current working directory).",
    )
    status_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show resolved agent configuration details.",
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

    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "init":
        result = init_workspace(
            root,
            force=args.force,
            automatic_git=True,
            git_user_name=args.git_user_name,
            git_user_email=args.git_user_email,
        )
        print(format_init_result(result, root))
    elif args.command == "run":
        configure_logging(_run_log_level(quiet=args.quiet, verbose=args.verbose), args.log_file)
        result = run_loop(
            root,
            auto=args.auto,
            max_sessions=args.max_sessions,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
            dangerous_skip_permissions=args.dangerously_skip_permissions,
            retain_prompts=args.retain_prompts,
            automatic_version_control=True,
        )
        if result.exit_code != 0:
            raise SystemExit(result.exit_code)
    elif args.command == "status":
        print(format_status(root, verbose=args.verbose))
    elif args.command == "doctor":
        problems = check_workspace(root)
        print(format_doctor_report(problems))
        if problems:
            raise SystemExit(1)


def _run_log_level(*, quiet: bool, verbose: bool) -> int:
    if quiet:
        return logging.WARNING
    if verbose:
        return logging.DEBUG
    return logging.INFO


if __name__ == "__main__":
    main()

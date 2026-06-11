from __future__ import annotations

import argparse
import logging
from pathlib import Path

from devlab._logging import configure_logging
from devlab.agent_smoke import format_agent_smoke_report, run_agent_smoke_test
from devlab.cleanup import clean_failed_session_artifacts, format_cleanup_result
from devlab.doctor import check_workspace, format_doctor_report
from devlab.history import format_history
from devlab.init import format_init_next_steps, format_init_result, init_workspace
from devlab.orchestrator import DEFAULT_PROJECT_ROOT, run_loop
from devlab.status import format_status
from devlab.workflow_diagnostics import build_workflow_diagnostics, format_workflow_diagnostics


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

    plan_parser = subparsers.add_parser(
        "plan", help="Run planning sessions and stop before implementation."
    )
    plan_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    plan_parser.add_argument(
        "--max-sessions",
        type=int,
        default=2,
        help="Maximum number of sessions to run (default: 2).",
    )
    plan_parser.add_argument(
        "--revise",
        action="store_true",
        help="Review and possibly update existing design and project plans.",
    )
    plan_parser.add_argument(
        "--provider",
        default=None,
        help="Override the configured provider for this plan run.",
    )
    plan_parser.add_argument(
        "--model",
        default=None,
        help="Override the configured model for this plan run.",
    )
    plan_parser.add_argument(
        "--effort",
        default=None,
        help="Override the configured effort for this plan run.",
    )
    plan_parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        help="Pass --dangerously-skip-permissions to the agent command.",
    )
    plan_verbosity = plan_parser.add_mutually_exclusive_group()
    plan_verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Show only warnings and errors during the plan run.",
    )
    plan_verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show debug diagnostics during the plan run.",
    )
    plan_parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Write detailed DevLab plan logs to this file.",
    )
    plan_parser.add_argument(
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
        "history", help="Show session history.",
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
            "Workspace root for provider execution and logs "
            "(default: current working directory)."
        ),
    )
    smoke_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Agent config TOML path. Defaults to .devlab/config/agents.toml under --root.",
    )
    smoke_parser.add_argument(
        "--role",
        action="append",
        default=None,
        help="Role to test. May be passed more than once; defaults to all roles.",
    )
    smoke_parser.add_argument(
        "--provider",
        default=None,
        help="Override the configured provider for this smoke test.",
    )
    smoke_parser.add_argument(
        "--model",
        default=None,
        help="Override the configured model for this smoke test.",
    )
    smoke_parser.add_argument(
        "--effort",
        default=None,
        help="Override the configured effort for this smoke test.",
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
        print()
        print(format_init_next_steps())
    elif args.command == "run":
        configure_logging(_run_log_level(quiet=args.quiet, verbose=args.verbose), args.log_file)
        result = run_loop(
            root,
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
    elif args.command == "plan":
        configure_logging(_run_log_level(quiet=args.quiet, verbose=args.verbose), args.log_file)
        result = run_loop(
            root,
            max_sessions=args.max_sessions,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
            dangerous_skip_permissions=args.dangerously_skip_permissions,
            retain_prompts=args.retain_prompts,
            automatic_version_control=True,
            planning_only=True,
            revise_plan=args.revise,
        )
        if result.exit_code != 0:
            raise SystemExit(result.exit_code)
    elif args.command == "status":
        print(format_status(root, verbose=args.verbose))
    elif args.command == "diagnostics":
        if args.json:
            print(build_workflow_diagnostics(root).to_json())
        else:
            print(format_workflow_diagnostics(root, verbose=args.verbose))
    elif args.command == "history":
        print(format_history(root, json_output=args.json))
    elif args.command == "doctor":
        problems = check_workspace(root)
        print(format_doctor_report(problems))
        if problems:
            raise SystemExit(1)
    elif args.command == "agent-smoke-test":
        result = run_agent_smoke_test(
            root,
            config_path=args.config.resolve() if args.config is not None else None,
            role_names=tuple(args.role) if args.role is not None else None,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
        )
        print(format_agent_smoke_report(result))
        if not result.passed:
            raise SystemExit(1)
    elif args.command == "clean-failed-session":
        result = clean_failed_session_artifacts(root)
        print(format_cleanup_result(result))


def _run_log_level(*, quiet: bool, verbose: bool) -> int:
    if quiet:
        return logging.WARNING
    if verbose:
        return logging.DEBUG
    return logging.INFO


if __name__ == "__main__":
    main()

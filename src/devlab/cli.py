from __future__ import annotations

import argparse
import logging
from pathlib import Path

from devlab._logging import configure_logging
from devlab.agent_smoke import (
    AgentSmokeProgressEvent,
    format_agent_smoke_report,
    run_agent_smoke_test,
)
from devlab.clarification_ops import (
    answer_clarification,
    format_clarification_list,
    resume_workflow,
    supersede_clarification,
)
from devlab.clarifications import FileClarificationTracker
from devlab.cleanup import clean_failed_session_artifacts, format_cleanup_result
from devlab.doctor import check_workspace, format_doctor_report
from devlab.history import format_history
from devlab.init import format_init_next_steps, format_init_result, init_workspace
from devlab.orchestrator import DEFAULT_PROJECT_ROOT, run_loop
from devlab.status import format_status
from devlab.workflow_diagnostics import build_workflow_diagnostics, format_workflow_diagnostics
from devlab.workflow_state_report import (
    build_workflow_state_digest,
    build_workflow_state_report,
    format_workflow_state_digest,
    format_workflow_state_report,
)


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

    implement_parser = subparsers.add_parser(
        "implement", help="Implement planned DevLab workflow tasks."
    )
    implement_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    implement_parser.add_argument(
        "--max-sessions",
        type=int,
        default=20,
        help="Maximum number of sessions to run (default: 20).",
    )
    implement_parser.add_argument(
        "--provider",
        default=None,
        help="Override the configured provider for this implementation run.",
    )
    implement_parser.add_argument(
        "--model",
        default=None,
        help="Override the configured model for this implementation run.",
    )
    implement_parser.add_argument(
        "--effort",
        default=None,
        help="Override the configured effort for this implementation run.",
    )
    verbosity = implement_parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Show only warnings and errors during implementation.",
    )
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show debug diagnostics during implementation.",
    )
    implement_parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Write detailed DevLab implementation logs to this file.",
    )
    implement_parser.add_argument(
        "--retain-prompts",
        action="store_true",
        help="Write full base/session prompts to .devlab/logs/agents/ for debugging.",
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
        help="Write full base/session prompts to .devlab/logs/agents/ for debugging.",
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

    workflow_state_parser = subparsers.add_parser(
        "workflow-state", help="Show workflow lifecycle state."
    )
    workflow_state_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to inspect (default: current working directory).",
    )
    workflow_state_parser.add_argument(
        "--digest",
        action="store_true",
        help="Emit a compact operator digest instead of the full workflow report.",
    )
    workflow_state_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the selected workflow-state view as JSON.",
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

    clarify_parser = subparsers.add_parser(
        "clarify", help="Inspect and answer operator clarifications."
    )
    clarify_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    clarify_subparsers = clarify_parser.add_subparsers(
        dest="clarify_command", required=True
    )
    clarify_subparsers.add_parser("list", help="List clarifications.")
    clarify_show = clarify_subparsers.add_parser("show", help="Show a clarification file.")
    clarify_show.add_argument("clarification_id")
    clarify_answer = clarify_subparsers.add_parser(
        "answer", help="Answer a pending clarification."
    )
    clarify_answer.add_argument("clarification_id")
    answer_value = clarify_answer.add_mutually_exclusive_group(required=True)
    answer_value.add_argument("--choice", default=None)
    answer_value.add_argument("--text", default=None)
    clarify_answer.add_argument("--note", default="")
    clarify_answer.add_argument("--operator", default="")
    clarify_answer.add_argument("--resume", action="store_true")
    clarify_answer.add_argument("--max-sessions", type=int, default=20)
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
    resume_parser.add_argument(
        "--max-sessions",
        type=int,
        default=20,
        help="Maximum number of sessions to run (default: 20).",
    )

    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "agent-smoke-test":
        if args.use_provider_defaults and args.role is not None:
            parser.error(
                "agent-smoke-test cannot combine --use-provider-defaults with --role"
            )
        if (
            args.use_provider_defaults
            and args.provider is None
            and not args.all_providers
        ):
            parser.error(
                "agent-smoke-test --use-provider-defaults requires "
                "--provider or --all-providers"
            )
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
    elif args.command == "implement":
        configure_logging(_run_log_level(quiet=args.quiet, verbose=args.verbose), args.log_file)
        result = run_loop(
            root,
            max_sessions=args.max_sessions,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
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
            retain_prompts=args.retain_prompts,
            automatic_version_control=True,
            planning_only=True,
            revise_plan=args.revise,
            adopt_existing=args.adopt_existing,
            replace_plan=args.replace_plan,
            mark_specs_planned=args.mark_specs_planned,
        )
        if result.exit_code != 0:
            raise SystemExit(result.exit_code)
    elif args.command == "status":
        print(format_status(root, verbose=args.verbose))
    elif args.command == "workflow-state":
        report = build_workflow_state_report(root)
        if args.digest:
            digest = build_workflow_state_digest(report)
            if args.json:
                print(digest.to_json())
            else:
                print(format_workflow_state_digest(digest))
        elif args.json:
            print(report.to_json())
        else:
            print(format_workflow_state_report(report))
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
        try:
            result = run_agent_smoke_test(
                root,
                config_path=args.config.resolve() if args.config is not None else None,
                role_names=tuple(args.role) if args.role is not None else None,
                provider=args.provider,
                model=args.model,
                effort=args.effort,
                all_providers=args.all_providers,
                use_provider_defaults=args.use_provider_defaults,
                on_progress=_print_agent_smoke_progress,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(format_agent_smoke_report(result))
        if not result.passed:
            raise SystemExit(1)
    elif args.command == "clean-failed-session":
        result = clean_failed_session_artifacts(root)
        print(format_cleanup_result(result))
    elif args.command == "clarify":
        tracker = FileClarificationTracker(root)
        if args.clarify_command == "list":
            print(format_clarification_list(tracker.list_clarifications()))
        elif args.clarify_command == "show":
            print(tracker.get(args.clarification_id).path.read_text(), end="")
        elif args.clarify_command == "answer":
            try:
                result = answer_clarification(
                    root,
                    args.clarification_id,
                    choice=args.choice,
                    text=args.text,
                    note=args.note,
                    operator=args.operator,
                    resume=args.resume,
                    max_sessions=args.max_sessions,
                )
            except ValueError as exc:
                parser.error(str(exc))
            print(f"Answered {result.clarification.id}: {result.clarification.title}")
            if result.resumed is not None and result.resumed.exit_code != 0:
                raise SystemExit(result.resumed.exit_code)
        elif args.clarify_command == "supersede":
            try:
                clarification = supersede_clarification(
                    root,
                    args.clarification_id,
                    args.reason,
                )
            except ValueError as exc:
                parser.error(str(exc))
            print(f"Superseded {clarification.id}: {clarification.title}")
    elif args.command == "resume":
        configure_logging(logging.INFO, None)
        result = resume_workflow(root, max_sessions=args.max_sessions)
        print(result.message)
        if not result.resumed:
            raise SystemExit(1)
        if result.run_result is not None and result.run_result.exit_code != 0:
            raise SystemExit(result.run_result.exit_code)


def _run_log_level(*, quiet: bool, verbose: bool) -> int:
    if quiet:
        return logging.WARNING
    if verbose:
        return logging.DEBUG
    return logging.INFO


def _print_agent_smoke_progress(event: AgentSmokeProgressEvent) -> None:
    if event.event == "start":
        roles = _format_agent_smoke_progress_roles(event.role_names)
        print(
            f"Starting [{event.check_name}] "
            f"provider={event.config.provider} model={event.config.model}{roles}...",
            flush=True,
        )
        return
    if event.result is None:
        return
    status = "OK" if event.result.passed else "FAILED"
    duration = event.result.result.duration_seconds
    duration_text = "" if duration is None else f" in {duration:.1f}s"
    print(f"Finished [{event.check_name}] {status}{duration_text}", flush=True)


def _format_agent_smoke_progress_roles(role_names: tuple[str, ...]) -> str:
    if not role_names:
        return ""
    return " roles=" + ",".join(role_names)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from importlib.metadata import PackageNotFoundError, version
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
from devlab.executable_config import (
    ExecutableConfigSnapshot,
    ExecutableConfigTrustError,
    authorize_executable_config,
    build_executable_config_snapshot,
    executable_config_is_trusted,
    format_executable_config,
    revoke_executable_config_trust,
    trust_executable_config,
)
from devlab.handoffs import (
    HandoffError,
    HandoffSubmissionError,
    initialize_handoff_candidate,
)
from devlab.history import format_history
from devlab.init import INIT_TEMPLATES, format_init_next_steps, format_init_result, init_workspace
from devlab.orchestrator import DEFAULT_PROJECT_ROOT, RunResult, run_loop, submit_session_handoff
from devlab.run_summary import build_run_summary, format_run_summary
from devlab.status import format_status
from devlab.workflow_diagnostics import build_workflow_diagnostics, format_workflow_diagnostics
from devlab.workflow_state_report import (
    build_next_command_advice,
    build_workflow_state_digest,
    build_workflow_state_report,
    format_next_command,
    format_workflow_state_digest,
    format_workflow_state_report,
)

IMPLEMENT_MAX_SESSIONS = 20
PLAN_MAX_SESSIONS = 2
DEFAULT_CLARIFICATION_MODE = "operator"


def _devlab_version() -> str:
    """Return the installed distribution version used by this CLI."""
    try:
        return version("devlab")
    except PackageNotFoundError:
        return "unknown"


def _run_parent_parser(
    *, max_sessions: int, session_kind: str = "sessions"
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="devlab",
        description="Orchestrate agentic development sessions.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_devlab_version()}",
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
    workflow_state_view = workflow_state_parser.add_mutually_exclusive_group()
    workflow_state_view.add_argument(
        "--digest",
        action="store_true",
        help="Emit a compact operator digest instead of the full workflow report.",
    )
    workflow_state_view.add_argument(
        "--next-command",
        action="store_true",
        help="Emit one safe command for the next workflow action.",
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

    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "agent-smoke-test":
        if args.use_provider_defaults and args.role is not None:
            parser.error("agent-smoke-test cannot combine --use-provider-defaults with --role")
        if args.use_provider_defaults and args.provider is None and not args.all_providers:
            parser.error(
                "agent-smoke-test --use-provider-defaults requires --provider or --all-providers"
            )
    if args.command in {"plan", "implement"} and args.unattended:
        args.clarification_mode = "agent"
    if args.command == "init":
        result = init_workspace(
            root,
            template=args.template,
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
        executable_config = _authorized_executable_config(
            root,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
            expected_digest=args.require_exec_config_digest,
            accept_current=args.accept_current_exec_config,
            allow_prompt=not args.unattended,
        )
        result = run_loop(
            root,
            max_sessions=args.max_sessions,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
            retain_prompts=args.retain_prompts,
            clarification_mode=args.clarification_mode,
            handoff_correction=args.handoff_correction,
            executable_config=executable_config,
        )
        if isinstance(result, RunResult):
            print(
                format_run_summary(
                    build_run_summary(
                        root,
                        command="implement",
                        result=result,
                        initial_executable_config=executable_config,
                    )
                )
            )
        if result.exit_code != 0:
            raise SystemExit(result.exit_code)
    elif args.command == "plan":
        configure_logging(_run_log_level(quiet=args.quiet, verbose=args.verbose), args.log_file)
        executable_config = (
            None
            if args.mark_specs_planned
            else _authorized_executable_config(
                root,
                provider=args.provider,
                model=args.model,
                effort=args.effort,
                expected_digest=args.require_exec_config_digest,
                accept_current=args.accept_current_exec_config,
                allow_prompt=not args.unattended,
            )
        )
        result = run_loop(
            root,
            max_sessions=args.max_sessions,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
            retain_prompts=args.retain_prompts,
            planning_only=True,
            revise_plan=args.revise,
            adopt_existing=args.adopt_existing,
            replace_plan=args.replace_plan,
            mark_specs_planned=args.mark_specs_planned,
            clarification_mode=args.clarification_mode,
            handoff_correction=args.handoff_correction,
            executable_config=executable_config,
        )
        if isinstance(result, RunResult):
            print(
                format_run_summary(
                    build_run_summary(
                        root,
                        command="plan",
                        result=result,
                        initial_executable_config=executable_config,
                    )
                )
            )
        if result.exit_code != 0:
            raise SystemExit(result.exit_code)
    elif args.command == "status":
        print(format_status(root, verbose=args.verbose))
    elif args.command == "workflow-state":
        report = build_workflow_state_report(root)
        if args.next_command:
            advice = build_next_command_advice(report)
            if args.json:
                print(advice.to_json())
            else:
                command = format_next_command(advice)
                if command:
                    print(command)
        elif args.digest:
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
        if not problems:
            try:
                executable_config = build_executable_config_snapshot(root)
            except (OSError, ValueError, KeyError) as exc:
                print(f"Executable configuration: invalid ({exc})")
                raise SystemExit(1) from exc
            trust_status = (
                "trusted" if executable_config_is_trusted(executable_config) else "not trusted"
            )
            print(f"Executable configuration: {trust_status} ({executable_config.digest})")
        if problems:
            raise SystemExit(1)
    elif args.command == "agent-smoke-test":
        config_path = args.config.resolve() if args.config is not None else None
        executable_config = _authorized_executable_config(
            root,
            config_path=config_path,
            model=args.model,
            effort=args.effort,
            expected_digest=args.require_exec_config_digest,
            accept_current=args.accept_current_exec_config,
            allow_prompt=True,
        )
        try:
            result = run_agent_smoke_test(
                root,
                config_path=config_path,
                role_names=tuple(args.role) if args.role is not None else None,
                provider=args.provider,
                model=args.model,
                effort=args.effort,
                all_providers=args.all_providers,
                use_provider_defaults=args.use_provider_defaults,
                on_progress=_print_agent_smoke_progress,
                executable_config=executable_config,
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
                    executable_config_factory=(
                        (
                            lambda: _authorized_executable_config(
                                root,
                                expected_digest=args.require_exec_config_digest,
                                accept_current=args.accept_current_exec_config,
                                allow_prompt=False,
                            )
                        )
                        if args.resume
                        else None
                    ),
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
        result = resume_workflow(
            root,
            max_sessions=args.max_sessions,
            executable_config_factory=lambda: _authorized_executable_config(
                root,
                expected_digest=args.require_exec_config_digest,
                accept_current=args.accept_current_exec_config,
                allow_prompt=False,
            ),
        )
        print(result.message)
        if not result.resumed:
            raise SystemExit(1)
        if result.run_result is not None and result.run_result.exit_code != 0:
            raise SystemExit(result.run_result.exit_code)
    elif args.command == "trust":
        _run_trust_command(args, root)
    elif args.command == "session":
        try:
            if args.handoff_command == "init":
                path = initialize_handoff_candidate(root, args.session_envelope)
                print(f"Initialized handoff candidate: {path.relative_to(root)}")
            else:
                result = submit_session_handoff(root, envelope_path=args.session_envelope)
                print(f"Accepted handoff for {result.role_name} session {result.session_id}.")
        except HandoffSubmissionError as exc:
            print("Handoff rejected:\n")
            for index, issue in enumerate(exc.issues, start=1):
                print(f"{index}. {issue}")
            print("\nCorrect the candidate and submit it again.")
            raise SystemExit(1) from exc
        except HandoffError as exc:
            print(f"Handoff submission failed: {exc}")
            raise SystemExit(1) from exc


def _run_log_level(*, quiet: bool, verbose: bool) -> int:
    if quiet:
        return logging.WARNING
    if verbose:
        return logging.DEBUG
    return logging.INFO


def _authorized_executable_config(
    root: Path,
    *,
    config_path: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    expected_digest: str | None = None,
    accept_current: bool = False,
    allow_prompt: bool,
) -> ExecutableConfigSnapshot:
    try:
        snapshot = build_executable_config_snapshot(
            root,
            config_path=config_path,
            provider=provider,
            model=model,
            effort=effort,
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"DevLab trust: could not load executable configuration: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        authorization = authorize_executable_config(
            snapshot,
            expected_digest=expected_digest,
            accept_current=accept_current,
        )
    except ExecutableConfigTrustError as exc:
        if expected_digest is not None or accept_current or not allow_prompt:
            print(f"DevLab trust: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if not sys.stdin.isatty():
            print(
                f"DevLab trust: {exc}\n"
                "Non-interactive execution cannot create trust. Run "
                "'devlab trust executable-config' first, supply "
                "--require-exec-config-digest, or explicitly use "
                "--accept-current-exec-config in an externally contained environment.",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        print(format_executable_config(snapshot))
        answer = input("\nTrust this executable configuration for this workspace? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            raise SystemExit(1) from exc
        trust_executable_config(snapshot)
        authorization = authorize_executable_config(snapshot)
    if accept_current:
        print(
            "WARNING: accepting current executable configuration for this invocation "
            f"without persistent trust ({snapshot.digest}).",
            file=sys.stderr,
        )
    return dataclasses.replace(snapshot, authorization=authorization)


def _run_trust_command(args: argparse.Namespace, root: Path) -> None:
    try:
        snapshot = build_executable_config_snapshot(
            root,
            config_path=args.config.resolve() if args.config is not None else None,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"DevLab trust: could not load executable configuration: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if args.show:
        print(format_executable_config(snapshot))
        return
    if args.revoke:
        revoked = revoke_executable_config_trust(snapshot)
        print(
            "Revoked executable-configuration trust."
            if revoked
            else "No executable-configuration trust record existed."
        )
        return
    print(format_executable_config(snapshot))
    if executable_config_is_trusted(snapshot):
        print("\nThis executable configuration is already trusted.")
        return
    answer = input("\nTrust this executable configuration for this workspace? [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        print("Executable configuration was not trusted.")
        raise SystemExit(1)
    path = trust_executable_config(snapshot)
    print(f"Trusted executable configuration {snapshot.digest}.")
    print(f"Operator-local record: {path}")


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

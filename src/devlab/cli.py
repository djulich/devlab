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
from devlab.doctor_common import DoctorOperation, DoctorProblem
from devlab.environment import (
    FileTestServiceTracker,
    parse_test_service,
    test_service_lock,
)
from devlab.executable_config import (
    ExecutableConfigSnapshot,
    ExecutableConfigTrustError,
    authorize_executable_config,
    build_executable_config_snapshot,
    executable_config_is_trusted,
    format_executable_config,
    revoke_executable_config_trust,
    test_service_cleanup_snapshot,
    trust_executable_config,
)
from devlab.git import VersionControlError
from devlab.handoffs import (
    HandoffError,
    HandoffSubmissionError,
    initialize_handoff_candidate,
)
from devlab.history import format_history
from devlab.init import (
    INIT_TEMPLATES,
    format_init_next_steps,
    format_init_result,
    init_test_service_storage,
    init_workspace,
)
from devlab.orchestrator import DEFAULT_PROJECT_ROOT, RunResult, run_loop, submit_session_handoff
from devlab.prerequisites import (
    FilePrerequisiteTracker,
    Prerequisite,
    attest_prerequisite,
    evaluate_prerequisites,
    format_prerequisite_result,
    prerequisite_is_attested,
    revoke_prerequisite_attestation,
)
from devlab.profiles import Profile, load_profiles
from devlab.recovery import (
    IncompleteDiscardError,
    discard_interrupted_session,
    format_discard_proposal,
    format_operator_guidance,
    inspect_recovery,
)
from devlab.run_summary import build_run_summary, format_run_summary
from devlab.status import format_status
from devlab.workflow_diagnostics import build_workflow_diagnostics, format_workflow_diagnostics
from devlab.workflow_state_report import (
    NextCommandAdvice,
    WorkflowStateReport,
    build_next_command_advice,
    build_workflow_state_digest,
    build_workflow_state_report,
    format_next_command,
    format_workflow_state_digest,
    format_workflow_state_report,
)
from devlab.workspace import Workspace

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

    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "agent-smoke-test":
        if args.use_provider_defaults and args.role is not None:
            parser.error("agent-smoke-test cannot combine --use-provider-defaults with --role")
        if args.use_provider_defaults and args.provider is None and not args.all_providers:
            parser.error(
                "agent-smoke-test --use-provider-defaults requires --provider or --all-providers"
            )
    if args.command == "continue" and (
        args.discard_interrupted_session != (args.require_interrupted_head is not None)
    ):
        parser.error(
            "continue requires --discard-interrupted-session and "
            "--require-interrupted-head together"
        )
    if args.command in {"continue", "plan", "implement"} and args.unattended:
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
    elif args.command == "continue":
        _run_continue_command(args, root)
    elif args.command == "implement":
        _require_healthy_operation(root, DoctorOperation.SESSION)
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
        _require_healthy_operation(root, DoctorOperation.PLANNING)
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
    elif args.command == "test-service":
        _run_test_service_command(args, root)
    elif args.command == "prerequisite":
        _run_prerequisite_command(args, root)
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


def _run_continue_command(args: argparse.Namespace, root: Path) -> None:
    report = build_workflow_state_report(root)
    if report.lifecycle_phase == "uninitialized":
        print("Workspace is not initialized. Run devlab init, then devlab continue.")
        raise SystemExit(1)
    inspection = inspect_recovery(root)
    if inspection.proposal is not None:
        proposal = inspection.proposal
        print(format_discard_proposal(proposal))
        approved = False
        if args.discard_interrupted_session:
            if args.require_interrupted_head != proposal.head:
                print(
                    "DevLab refused discard because --require-interrupted-head does not "
                    f"match {proposal.head}.",
                    file=sys.stderr,
                )
                if inspection.guidance is not None:
                    print("\n" + format_operator_guidance(inspection.guidance), file=sys.stderr)
                raise SystemExit(1)
            approved = True
        if not approved and not args.unattended and sys.stdin.isatty():
            answer = input("\nDiscard the uncommitted repository state and restart? [y/N] ")
            approved = answer.strip().lower() in {"y", "yes"}
        if not approved:
            if inspection.guidance is not None:
                print("\nNo files were changed.\n", file=sys.stderr)
                print(format_operator_guidance(inspection.guidance), file=sys.stderr)
            raise SystemExit(1)
        try:
            commit = discard_interrupted_session(root, proposal)
        except IncompleteDiscardError as exc:
            print(f"DevLab could not complete the discard: {exc}.", file=sys.stderr)
            print("\n" + format_operator_guidance(exc.guidance), file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Discarded interrupted repository state and recorded commit {commit}.")
    elif inspection.reason != "clean":
        print(f"DevLab cannot continue safely: {inspection.reason}.", file=sys.stderr)
        if inspection.guidance is not None:
            print("\nNo files were changed.\n", file=sys.stderr)
            print(format_operator_guidance(inspection.guidance), file=sys.stderr)
        raise SystemExit(1)

    report = build_workflow_state_report(root)
    advice = build_next_command_advice(report)
    if advice.action == "none":
        _report_workspace_health(root)
        print("Workflow is complete.")
        return
    if advice.action == "inspect_clarification":
        clarification_id = report.clarifications.pending_blockers[0].id
        clarification = FileClarificationTracker(root).get(clarification_id)
        print(clarification.path.read_text(), end="")
        print("\nAnswer the clarification, then run devlab continue.")
        raise SystemExit(1)
    if advice.action in {"inspect_dirty_specs", "inspect_workflow"}:
        print(
            f"DevLab cannot continue automatically: {advice.reason}.\n"
            "No files were changed.\n\n"
            "Inspect:\n"
            "  devlab status --verbose\n"
            "  devlab doctor\n"
            "  git status --short\n\n"
            "After resolving the reported condition, run:\n"
            "  devlab continue",
            file=sys.stderr,
        )
        raise SystemExit(1)
    operation = _doctor_operation_for_advice(advice, report)
    _require_healthy_operation(root, operation)
    if advice.action == "resume_workflow":
        configure_logging(_run_log_level(quiet=args.quiet, verbose=args.verbose), args.log_file)
        resumed = resume_workflow(
            root,
            max_sessions=args.max_sessions,
            executable_config_factory=lambda: _authorized_executable_config(
                root,
                provider=args.provider,
                model=args.model,
                effort=args.effort,
                expected_digest=args.require_exec_config_digest,
                accept_current=args.accept_current_exec_config,
                allow_prompt=not args.unattended,
            ),
        )
        print(resumed.message)
        if not resumed.resumed or (
            resumed.run_result is not None and resumed.run_result.exit_code != 0
        ):
            raise SystemExit(resumed.run_result.exit_code if resumed.run_result is not None else 1)
        return

    planning_only = advice.action in {"continue_planning", "reconcile_specifications"} or (
        advice.action == "continue_research_route"
        and report.research is not None
        and report.research.command == "plan"
    )
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
        planning_only=planning_only,
        clarification_mode=args.clarification_mode,
        handoff_correction=args.handoff_correction,
        executable_config=executable_config,
    )
    if isinstance(result, RunResult):
        print(
            format_run_summary(
                build_run_summary(
                    root,
                    command="continue",
                    result=result,
                    initial_executable_config=executable_config,
                )
            )
        )
    if result.exit_code != 0:
        raise SystemExit(result.exit_code)


def _doctor_operation_for_advice(
    advice: NextCommandAdvice, report: WorkflowStateReport
) -> DoctorOperation:
    if advice.action in {"continue_planning", "reconcile_specifications"}:
        return DoctorOperation.PLANNING
    if (
        advice.action == "continue_research_route"
        and report.research is not None
        and report.research.command == "plan"
    ):
        return DoctorOperation.PLANNING
    return DoctorOperation.SESSION


def _require_healthy_operation(root: Path, operation: DoctorOperation) -> None:
    health_findings = check_workspace(root)
    blocking_findings = [
        finding for finding in health_findings if finding.blocks_operation(operation)
    ]
    if blocking_findings:
        print(
            "DevLab cannot continue because workspace health findings block "
            f"{operation.value}:\n\n{format_doctor_report(blocking_findings)}\n\n"
            "Inspect all findings with:\n  devlab doctor",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if health_findings:
        print(_format_nonblocking_health_findings(health_findings, operation), file=sys.stderr)


def _report_workspace_health(root: Path) -> None:
    health_findings = check_workspace(root)
    if health_findings:
        print(
            _format_nonblocking_health_findings(health_findings, "workflow completion"),
            file=sys.stderr,
        )


def _format_nonblocking_health_findings(
    findings: list[DoctorProblem], operation: DoctorOperation | str
) -> str:
    operation_name = operation.value if isinstance(operation, DoctorOperation) else operation
    lines = [
        "Workspace health findings do not block " + operation_name + ":",
        *(f"- {finding.path}: {finding.message}" for finding in findings),
        "Run 'devlab doctor' for the authoritative workspace-health result.",
    ]
    return "\n".join(lines)


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


def _run_prerequisite_command(args: argparse.Namespace, root: Path) -> None:
    try:
        profiles = load_profiles(root)
    except (OSError, ValueError) as exc:
        print(f"DevLab prerequisite: could not load profiles: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if args.prerequisite_command == "list":
        items = [item for profile in profiles.values() for item in profile.prerequisites]
        if not items:
            print("No profile prerequisites are configured.")
            return
        for item in items:
            kind = "attested" if item.attestation else "automatic"
            state = (
                " (approved)" if item.attestation and prerequisite_is_attested(root, item) else ""
            )
            print(
                f"- {item.reference}: {item.summary} "
                f"[{kind}; {', '.join(scope.value for scope in item.required_for)}]{state}"
            )
        return
    if args.prerequisite_command == "blocked":
        blocker = FilePrerequisiteTracker(root).read_blocker()
        if blocker is None:
            print("No workflow prerequisite blocker is recorded.")
            return
        print(
            f"Workflow blocked before {blocker.operation.value}: "
            f"role={blocker.role or 'none'} task={blocker.task or 'none'} "
            f"milestone={blocker.milestone or 'none'}"
        )
        for result in blocker.results:
            print("\n" + format_prerequisite_result(root, result))
        print(
            "\nAfter resolving the prerequisites, continue with:\n"
            f"  devlab {blocker.command or 'implement'}"
        )
        return
    prerequisite = _find_prerequisite(profiles, args.profile_id, args.prerequisite_id)
    if args.prerequisite_command == "show":
        status = (
            "approved"
            if prerequisite.attestation and prerequisite_is_attested(root, prerequisite)
            else "not approved"
            if prerequisite.attestation
            else "not checked"
        )
        print(_format_prerequisite_definition(root, prerequisite, status))
        return
    if args.prerequisite_command == "check":
        results = evaluate_prerequisites(
            root,
            (prerequisite,),
            prerequisite.required_for[0],
        )
        result = results[0]
        print(format_prerequisite_result(root, result))
        if result.blocks:
            raise SystemExit(1)
        return
    if args.prerequisite_command == "revoke":
        revoked = revoke_prerequisite_attestation(root, prerequisite)
        print("Prerequisite approval revoked." if revoked else "No approval record existed.")
        return
    if not prerequisite.attestation:
        print(
            f"DevLab prerequisite: {prerequisite.reference} is automatically checked "
            "and cannot be operator-approved.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(_format_prerequisite_definition(root, prerequisite, "not approved"))
    if not args.yes:
        answer = input("\nApprove this prerequisite for this workspace? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Prerequisite was not approved.")
            raise SystemExit(1)
    path = attest_prerequisite(root, prerequisite, operator=args.operator, note=args.note)
    print(f"Approved {prerequisite.reference}.")
    print(f"Operator-local record: {path}")


def _find_prerequisite(
    profiles: dict[str, Profile], profile_id: str, prerequisite_id: str
) -> Prerequisite:
    profile = profiles.get(profile_id)
    if profile is None:
        raise SystemExit(f"unknown profile: {profile_id}")
    for item in profile.prerequisites:
        if item.id == prerequisite_id:
            return item
    raise SystemExit(f"unknown prerequisite: {profile_id}.{prerequisite_id}")


def _format_prerequisite_definition(root: Path, prerequisite: Prerequisite, status: str) -> str:
    mechanism = (
        f"check command: {prerequisite.check}"
        if prerequisite.check
        else f"environment variable: {prerequisite.environment}"
        if prerequisite.environment
        else f"operator attestation: {prerequisite.attestation}"
    )
    lines = [
        f"Prerequisite: {prerequisite.reference}",
        f"Status: {status}",
        f"Required for: {', '.join(item.value for item in prerequisite.required_for)}",
        f"Summary: {prerequisite.summary}",
        f"Mechanism: {mechanism}",
    ]
    if prerequisite.guide:
        lines.append(f"Guide: {(root / prerequisite.guide).resolve()}")
    if prerequisite.sensitive:
        lines.append("Security: Do not commit or print sensitive values.")
    return "\n".join(lines)


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


def _run_test_service_command(args: argparse.Namespace, root: Path) -> None:
    try:
        if args.service_action == "init":
            init_test_service_storage(root)
            print(
                "Private test service storage prepared; "
                "commit .devlab/.gitignore before continuing."
            )
            return
        if args.service_action == "status":
            records = Workspace(root).snapshot.test_service_records()
            for record in records:
                print(
                    f"{record['service']}: {record['state']} "
                    f"(last observed {record['updated_at']}); instance {record['instance']}"
                )
            if not records:
                print("No managed test service instances recorded.")
            return
        record = FileTestServiceTracker(root).read(args.service_id)
        if record is None or record["state"] == "destroyed":
            print("No live owned instance recorded.")
            return
        service = parse_test_service(args.service_id, record["definition"])
        snapshot = test_service_cleanup_snapshot(root, service)
        print(f"Cleanup {service.id}: {service.destroy}\nFingerprint: {snapshot.digest}")
        if args.show:
            return
        if args.trust:
            trust_executable_config(snapshot)
            print("Cleanup definition trusted; no resource was removed.")
            return
        # Existing full-configuration trust also covers its unchanged destroy
        # entry point. Otherwise authorize the exact saved cleanup definition.
        if not args.require_exec_config_digest and not args.accept_current_exec_config:
            try:
                current = build_executable_config_snapshot(root)
                if current.test_services.get(service.id) == service:
                    authorization = authorize_executable_config(current)
                else:
                    authorization = authorize_executable_config(snapshot)
            except (OSError, ValueError):
                authorization = authorize_executable_config(snapshot)
        else:
            authorization = authorize_executable_config(
                snapshot,
                expected_digest=args.require_exec_config_digest,
                accept_current=args.accept_current_exec_config,
            )
        with test_service_lock(root):
            Workspace(root).test_services().cleanup(service)
        print(f"Cleaned up test service {service.id} ({authorization.source.value}).")
    except (OSError, ValueError, VersionControlError) as exc:
        print(f"DevLab test service: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

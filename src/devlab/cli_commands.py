from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from pathlib import Path

from devlab._console import ConsoleArgumentParser, console_width, print_prose, wrap_prose
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
from devlab.doctor import check_workspace, format_doctor_problem, format_doctor_report
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
    format_init_next_steps,
    format_init_result,
    init_test_service_storage,
    init_workspace,
)
from devlab.orchestrator import RunResult, run_loop, submit_session_handoff
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
)
from devlab.workspace import WORKSPACE_MANIFEST, Workspace


def dispatch(parser: ConsoleArgumentParser, args: argparse.Namespace) -> None:
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
        print(format_init_next_steps(width=console_width(sys.stdout)))
    elif args.command == "continue":
        _run_continue_command(args, root)
    elif args.command == "implement":
        _require_healthy_operation(root, DoctorOperation.SESSION)
        configure_logging(
            _run_log_level(quiet=args.quiet, verbose=args.verbose),
            args.log_file,
            heartbeat_interval_seconds=args.heartbeat_interval,
        )
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
                    ),
                    width=console_width(sys.stdout),
                )
            )
        if result.exit_code != 0:
            raise SystemExit(result.exit_code)
    elif args.command == "plan":
        _require_healthy_operation(root, DoctorOperation.PLANNING)
        configure_logging(
            _run_log_level(quiet=args.quiet, verbose=args.verbose),
            args.log_file,
            heartbeat_interval_seconds=args.heartbeat_interval,
        )
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
                    ),
                    width=console_width(sys.stdout),
                )
            )
        if result.exit_code != 0:
            raise SystemExit(result.exit_code)
    elif args.command == "status":
        if args.verbose and args.json:
            parser.error("--verbose cannot be combined with --json")
        if args.next_command:
            report = build_workflow_state_report(root)
            advice = build_next_command_advice(report)
            if args.json:
                print(advice.to_json())
            else:
                command = format_next_command(advice)
                if command:
                    print(command)
        elif args.digest:
            report = build_workflow_state_report(root)
            digest = build_workflow_state_digest(report)
            if args.json:
                print(digest.to_json())
            else:
                print(format_workflow_state_digest(digest, width=console_width(sys.stdout)))
        elif args.json:
            report = build_workflow_state_report(root)
            print(report.to_json())
        else:
            print(format_status(root, verbose=args.verbose, width=console_width(sys.stdout)))
    elif args.command == "diagnostics":
        if args.json:
            print(build_workflow_diagnostics(root).to_json())
        else:
            print(
                format_workflow_diagnostics(
                    root, verbose=args.verbose, width=console_width(sys.stdout)
                )
            )
    elif args.command == "history":
        print(format_history(root, json_output=args.json, width=console_width(sys.stdout)))
    elif args.command == "doctor":
        problems = check_workspace(root)
        print(format_doctor_report(problems, width=console_width(sys.stdout)))
        if not problems:
            try:
                executable_config = build_executable_config_snapshot(root)
            except (OSError, ValueError, KeyError) as exc:
                print_prose(f"Executable configuration: invalid ({exc})")
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
        print(format_agent_smoke_report(result, width=console_width(sys.stdout)))
        if not result.passed:
            raise SystemExit(1)
    elif args.command == "clean-failed-session":
        result = clean_failed_session_artifacts(root)
        print(format_cleanup_result(result, width=console_width(sys.stdout)))
    elif args.command == "test-service":
        _run_test_service_command(args, root)
    elif args.command == "prerequisite":
        _run_prerequisite_command(args, root)
    elif args.command == "clarify":
        tracker = FileClarificationTracker(root)
        if args.clarify_command == "list":
            print(
                format_clarification_list(
                    tracker.list_clarifications(), width=console_width(sys.stdout)
                )
            )
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
            print_prose(f"Answered {result.clarification.id}: {result.clarification.title}")
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
            print_prose(f"Superseded {clarification.id}: {clarification.title}")
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
        print_prose(result.message)
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
                print_prose(
                    f"Accepted handoff for {result.role_name} session {result.session_id}."
                )
        except HandoffSubmissionError as exc:
            print_prose("Handoff rejected:\n")
            for index, issue in enumerate(exc.issues, start=1):
                print_prose(f"{index}. {issue}")
            print_prose("\nCorrect the candidate and submit it again.")
            raise SystemExit(1) from exc
        except HandoffError as exc:
            print_prose(f"Handoff submission failed: {exc}")
            raise SystemExit(1) from exc


def _run_log_level(*, quiet: bool, verbose: bool) -> int:
    if quiet:
        return logging.WARNING
    if verbose:
        return logging.DEBUG
    return logging.INFO


def _run_continue_command(args: argparse.Namespace, root: Path) -> None:
    if not (root / WORKSPACE_MANIFEST).exists():
        print_prose("Workspace is not initialized. Run devlab init, then devlab continue.")
        raise SystemExit(1)
    inspection = inspect_recovery(root)
    if inspection.proposal is not None:
        proposal = inspection.proposal
        if inspection.guidance is not None:
            print(format_operator_guidance(inspection.guidance, width=console_width(sys.stdout)))
            print()
        print(format_discard_proposal(proposal, width=console_width(sys.stdout)))
        approved = False
        if args.discard_interrupted_session:
            if args.require_interrupted_head != proposal.head:
                print_prose(
                    "DevLab refused discard because --require-interrupted-head does not "
                    f"match {proposal.head}.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            approved = True
        if not approved and not args.unattended and sys.stdin.isatty():
            answer = input(
                wrap_prose(
                    "\nDiscard the uncommitted repository state and restart? [y/N] ",
                    console_width(sys.stdout),
                ).rstrip()
                + " "
            )
            approved = answer.strip().lower() in {"y", "yes"}
        if not approved:
            print_prose("No files were changed.", file=sys.stderr)
            raise SystemExit(1)
        try:
            commit = discard_interrupted_session(root, proposal)
        except IncompleteDiscardError as exc:
            print_prose(f"DevLab could not complete the discard: {exc}.", file=sys.stderr)
            print(
                "\n" + format_operator_guidance(exc.guidance, width=console_width(sys.stderr)),
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        print_prose(f"Discarded interrupted repository state and recorded commit {commit}.")
    elif inspection.reason != "clean":
        print_prose(f"DevLab cannot continue safely: {inspection.reason}.", file=sys.stderr)
        if inspection.guidance is not None:
            print_prose("\nNo files were changed.\n", file=sys.stderr)
            print(
                format_operator_guidance(inspection.guidance, width=console_width(sys.stderr)),
                file=sys.stderr,
            )
        raise SystemExit(1)

    report = build_workflow_state_report(root)
    advice = build_next_command_advice(report)
    if advice.action == "none":
        _report_workspace_health(root)
        print_prose("Workflow is complete.")
        return
    if advice.action == "inspect_clarification":
        clarification_id = report.clarifications.pending_blockers[0].id
        clarification = FileClarificationTracker(root).get(clarification_id)
        print(clarification.path.read_text(), end="")
        print_prose("\nAnswer the clarification, then run devlab continue.")
        raise SystemExit(1)
    if advice.action in {"inspect_dirty_specs", "inspect_workflow"}:
        width = console_width(sys.stderr)
        print(
            wrap_prose(
                f"DevLab cannot continue automatically: {advice.reason}.\n"
                "No files were changed.\n\nInspect:",
                width,
            )
            + "\n  devlab status --verbose\n  devlab doctor\n  git status --short\n\n"
            + wrap_prose("After resolving the reported condition, run:", width)
            + "\n  devlab continue",
            file=sys.stderr,
        )
        raise SystemExit(1)
    operation = _doctor_operation_for_advice(advice, report)
    _require_healthy_operation(root, operation)
    if advice.action == "resume_workflow":
        configure_logging(
            _run_log_level(quiet=args.quiet, verbose=args.verbose),
            args.log_file,
            heartbeat_interval_seconds=args.heartbeat_interval,
        )
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
        print_prose(resumed.message)
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
    configure_logging(
        _run_log_level(quiet=args.quiet, verbose=args.verbose),
        args.log_file,
        heartbeat_interval_seconds=args.heartbeat_interval,
    )
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
        retry_stopped_task=args.retry_stopped_task,
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
                ),
                width=console_width(sys.stdout),
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
        width = console_width(sys.stderr)
        print(
            wrap_prose(
                "DevLab cannot continue because workspace health findings block "
                f"{operation.value}:",
                width,
            )
            + "\n\n"
            + format_doctor_report(blocking_findings, width=width)
            + "\n\n"
            + wrap_prose("Inspect all findings with:", width)
            + "\n  devlab doctor",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if health_findings:
        print(
            _format_nonblocking_health_findings(
                health_findings, operation, width=console_width(sys.stderr)
            ),
            file=sys.stderr,
        )


def _report_workspace_health(root: Path) -> None:
    health_findings = check_workspace(root)
    if health_findings:
        print(
            _format_nonblocking_health_findings(
                health_findings, "workflow completion", width=console_width(sys.stderr)
            ),
            file=sys.stderr,
        )


def _format_nonblocking_health_findings(
    findings: list[DoctorProblem], operation: DoctorOperation | str, *, width: int | None = None
) -> str:
    operation_name = operation.value if isinstance(operation, DoctorOperation) else operation
    lines = [
        wrap_prose("Workspace health findings do not block " + operation_name + ":", width),
        *(format_doctor_problem(finding, width=width) for finding in findings),
        wrap_prose("Run 'devlab doctor' for the authoritative workspace-health result.", width),
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
        print_prose(
            f"DevLab trust: could not load executable configuration: {exc}", file=sys.stderr
        )
        raise SystemExit(1) from exc
    try:
        authorization = authorize_executable_config(
            snapshot,
            expected_digest=expected_digest,
            accept_current=accept_current,
        )
    except ExecutableConfigTrustError as exc:
        if expected_digest is not None or accept_current or not allow_prompt:
            print_prose(f"DevLab trust: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if not sys.stdin.isatty():
            print_prose(
                f"DevLab trust: {exc}\n"
                "Non-interactive execution cannot create trust. Run "
                "'devlab trust executable-config' first, supply "
                "--require-exec-config-digest, or explicitly use "
                "--accept-current-exec-config in an externally contained environment.",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        print(format_executable_config(snapshot, width=console_width(sys.stdout)))
        answer = input(
            wrap_prose(
                "\nTrust this executable configuration for this workspace? [y/N] ",
                console_width(sys.stdout),
            ).rstrip()
            + " "
        )
        if answer.strip().lower() not in {"y", "yes"}:
            raise SystemExit(1) from exc
        trust_executable_config(snapshot)
        authorization = authorize_executable_config(snapshot)
    if accept_current:
        print_prose(
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
        print_prose(
            f"DevLab trust: could not load executable configuration: {exc}", file=sys.stderr
        )
        raise SystemExit(1) from exc
    if args.show or args.show_new or args.show_changes:
        view = "new" if args.show_new else "changes" if args.show_changes else "all"
        print(format_executable_config(snapshot, view=view, width=console_width(sys.stdout)))
        return
    if args.revoke:
        revoked = revoke_executable_config_trust(snapshot)
        print_prose(
            "Revoked executable-configuration trust."
            if revoked
            else "No executable-configuration trust record existed."
        )
        return
    print(format_executable_config(snapshot, width=console_width(sys.stdout)))
    if executable_config_is_trusted(snapshot):
        print_prose("\nThis executable configuration is already trusted.")
        return
    answer = input(
        wrap_prose(
            "\nTrust this executable configuration for this workspace? [y/N] ",
            console_width(sys.stdout),
        ).rstrip()
        + " "
    )
    if answer.strip().lower() not in {"y", "yes"}:
        print_prose("Executable configuration was not trusted.")
        raise SystemExit(1)
    path = trust_executable_config(snapshot)
    print_prose(f"Trusted executable configuration {snapshot.digest}.")
    print(f"Operator-local record: {path}")


def _run_prerequisite_command(args: argparse.Namespace, root: Path) -> None:
    try:
        profiles = load_profiles(root)
    except (OSError, ValueError) as exc:
        print_prose(f"DevLab prerequisite: could not load profiles: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if args.prerequisite_command == "list":
        items = [item for profile in profiles.values() for item in profile.prerequisites]
        if not items:
            print_prose("No profile prerequisites are configured.")
            return
        for item in items:
            kind = (
                "attested"
                if item.attestation
                else "automatically resolvable"
                if item.prepare
                else "automatic check"
            )
            state = (
                " (approved)" if item.attestation and prerequisite_is_attested(root, item) else ""
            )
            print_prose(
                f"- {item.reference}: {item.summary} "
                f"[{kind}; {', '.join(scope.value for scope in item.required_for)}]{state}"
            )
        return
    if args.prerequisite_command == "blocked":
        blocker = FilePrerequisiteTracker(root).read_blocker()
        if blocker is None:
            print_prose("No workflow prerequisite blocker is recorded.")
            return
        print_prose(
            f"Workflow blocked before {blocker.operation.value}: "
            f"role={blocker.role or 'none'} task={blocker.task or 'none'} "
            f"milestone={blocker.milestone or 'none'}"
        )
        for result in blocker.results:
            print("\n" + format_prerequisite_result(root, result, width=console_width(sys.stdout)))
        print(
            wrap_prose(
                "\nAfter resolving the prerequisites, continue with:", console_width(sys.stdout)
            )
            + f"\n  devlab {blocker.command or 'implement'}"
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
        print(
            _format_prerequisite_definition(
                root, prerequisite, status, width=console_width(sys.stdout)
            )
        )
        return
    if args.prerequisite_command == "check":
        results = evaluate_prerequisites(
            root,
            (prerequisite,),
            prerequisite.required_for[0],
        )
        result = results[0]
        print(format_prerequisite_result(root, result, width=console_width(sys.stdout)))
        if result.blocks:
            raise SystemExit(1)
        return
    if args.prerequisite_command == "revoke":
        revoked = revoke_prerequisite_attestation(root, prerequisite)
        print_prose("Prerequisite approval revoked." if revoked else "No approval record existed.")
        return
    if not prerequisite.attestation:
        print_prose(
            f"DevLab prerequisite: {prerequisite.reference} is automatically checked "
            "and cannot be operator-approved.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(
        _format_prerequisite_definition(
            root, prerequisite, "not approved", width=console_width(sys.stdout)
        )
    )
    if not args.yes:
        answer = input(
            wrap_prose(
                "\nApprove this prerequisite for this workspace? [y/N] ", console_width(sys.stdout)
            ).rstrip()
            + " "
        )
        if answer.strip().lower() not in {"y", "yes"}:
            print_prose("Prerequisite was not approved.")
            raise SystemExit(1)
    path = attest_prerequisite(root, prerequisite, operator=args.operator, note=args.note)
    print_prose(f"Approved {prerequisite.reference}.")
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


def _format_prerequisite_definition(
    root: Path, prerequisite: Prerequisite, status: str, *, width: int | None = None
) -> str:
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
        wrap_prose(f"Summary: {prerequisite.summary}", width),
        f"Mechanism: {mechanism}",
    ]
    if prerequisite.prepare:
        lines.extend(
            [
                f"Automatic preparation: {prerequisite.prepare}",
                f"Preparation kind: {prerequisite.prepare_kind}",
                f"Preparation timeout: {prerequisite.prepare_timeout}s",
            ]
        )
        if prerequisite.prepare_outputs:
            lines.append(f"Preparation outputs: {', '.join(prerequisite.prepare_outputs)}")
    if prerequisite.guide:
        lines.append(f"Guide: {(root / prerequisite.guide).resolve()}")
    if prerequisite.sensitive:
        lines.append(wrap_prose("Security: Do not commit or print sensitive values.", width))
    return "\n".join(lines)


def _print_agent_smoke_progress(event: AgentSmokeProgressEvent) -> None:
    if event.event == "start":
        roles = _format_agent_smoke_progress_roles(event.role_names)
        print_prose(
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
    print_prose(f"Finished [{event.check_name}] {status}{duration_text}", flush=True)


def _format_agent_smoke_progress_roles(role_names: tuple[str, ...]) -> str:
    if not role_names:
        return ""
    return " roles=" + ",".join(role_names)


def _run_test_service_command(args: argparse.Namespace, root: Path) -> None:
    try:
        if args.service_action == "init":
            init_test_service_storage(root)
            print_prose(
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
                print_prose("No managed test service instances recorded.")
            return
        record = FileTestServiceTracker(root).read(args.service_id)
        if record is None or record["state"] == "destroyed":
            print_prose("No live owned instance recorded.")
            return
        service = parse_test_service(args.service_id, record["definition"])
        snapshot = test_service_cleanup_snapshot(root, service)
        print(f"Cleanup {service.id}: {service.destroy}\nFingerprint: {snapshot.digest}")
        if args.show:
            return
        if args.trust:
            trust_executable_config(snapshot)
            print_prose("Cleanup definition trusted; no resource was removed.")
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
        print_prose(f"Cleaned up test service {service.id} ({authorization.source.value}).")
    except (OSError, ValueError, VersionControlError) as exc:
        print_prose(f"DevLab test service: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

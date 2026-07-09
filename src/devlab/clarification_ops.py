from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path

from devlab.clarifications import (
    Clarification,
    ClarificationAnswerShape,
    ClarificationStatus,
    FileClarificationTracker,
    choice_option_texts,
)
from devlab.orchestrator import RunResult, run_loop
from devlab.workflow_state import ResumeState, clear_resume_state, load_workflow_state


@dataclasses.dataclass(frozen=True)
class ClarificationAnswerResult:
    clarification: Clarification
    resumed: RunResult | None = None


@dataclasses.dataclass(frozen=True)
class ResumeDispatchResult:
    resumed: bool
    message: str
    run_result: RunResult | None = None


@dataclasses.dataclass(frozen=True)
class ClarificationAnswerValidation:
    valid: bool
    message: str
    clarification: Clarification | None = None


def validate_clarification_answer(
    root: Path,
    clarification_id: str,
) -> ClarificationAnswerValidation:
    tracker = FileClarificationTracker(root)
    try:
        clarification = tracker.get(clarification_id)
    except KeyError:
        return ClarificationAnswerValidation(
            False,
            f"Clarification {clarification_id} does not exist.",
        )
    except ValueError as exc:
        message = str(exc)
        if "answered clarification requires a non-empty ## Answer section" in message:
            return ClarificationAnswerValidation(
                False,
                f"Clarification {clarification_id} is answered but has an empty "
                "## Answer section.",
            )
        return ClarificationAnswerValidation(
            False,
            f"Clarification {clarification_id} is malformed: {exc}",
        )
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return ClarificationAnswerValidation(
            False,
            f"Clarification {clarification_id} is malformed: {exc}",
        )

    if clarification.status == ClarificationStatus.PENDING:
        return ClarificationAnswerValidation(
            False,
            f"Clarification {clarification.id} is still pending. Add an answer first.",
            clarification,
        )
    if clarification.status == ClarificationStatus.SUPERSEDED:
        return ClarificationAnswerValidation(
            False,
            f"Clarification {clarification.id} is superseded and cannot be used to resume.",
            clarification,
        )

    answer = clarification.answer_text.strip()
    if not answer:
        return ClarificationAnswerValidation(
            False,
            f"Clarification {clarification.id} is answered but has an empty ## Answer section.",
            clarification,
        )

    if clarification.answer_shape == ClarificationAnswerShape.CHOICE:
        options = choice_option_texts(clarification.body)
        first_answer_line = answer.splitlines()[0].strip()
        if first_answer_line not in options:
            allowed = ", ".join(options) if options else "no listed options"
            return ClarificationAnswerValidation(
                False,
                f"Clarification {clarification.id} choice answer must match one listed "
                f"option. Found {first_answer_line!r}; expected one of: {allowed}.",
                clarification,
            )

    return ClarificationAnswerValidation(
        True,
        f"Clarification {clarification.id} answer is valid.",
        clarification,
    )


def answer_clarification(
    root: Path,
    clarification_id: str,
    *,
    choice: str | None = None,
    text: str | None = None,
    note: str = "",
    operator: str = "",
    resume: bool = False,
    max_sessions: int = 20,
) -> ClarificationAnswerResult:
    tracker = FileClarificationTracker(root)
    if choice is not None and text is not None:
        raise ValueError("choose either --choice or --text, not both")
    if choice is None and text is None:
        raise ValueError("answer requires --choice or --text")
    if choice is not None:
        clarification = tracker.answer_choice(
            clarification_id,
            choice,
            note=note,
            operator=operator,
        )
    else:
        assert text is not None
        clarification = tracker.answer(clarification_id, text, operator=operator)
    run_result = None
    if resume:
        dispatch = resume_workflow(root, max_sessions=max_sessions)
        run_result = dispatch.run_result
        if not dispatch.resumed:
            raise ValueError(dispatch.message)
    return ClarificationAnswerResult(clarification=clarification, resumed=run_result)


def supersede_clarification(root: Path, clarification_id: str, reason: str) -> Clarification:
    return FileClarificationTracker(root).supersede(clarification_id, reason)


def resume_workflow(root: Path, *, max_sessions: int = 20) -> ResumeDispatchResult:
    state = load_workflow_state(root)
    if state.resume is None:
        return ResumeDispatchResult(
            False,
            "No active clarification resume pointer. Run `devlab workflow-state` "
            "to inspect the next workflow action.",
        )
    validation = validate_clarification_answer(root, state.resume.blocked_by)
    if not validation.valid:
        return ResumeDispatchResult(
            False,
            _resume_validation_message(state.resume, validation.message),
        )
    result = run_loop(
        root,
        max_sessions=max_sessions,
        automatic_version_control=True,
        planning_only=state.resume.command == "plan",
    )
    if result.exit_code != 0:
        message = (
            result.errors[0].message
            if result.errors
            else "Resume failed before workflow could continue."
        )
        return ResumeDispatchResult(False, message, result)
    if result.exit_code == 0 and result.sessions_run > 0:
        clear_resume_state(root)
    return ResumeDispatchResult(True, "Resumed workflow.", result)


def _resume_validation_message(resume: ResumeState, validation_message: str) -> str:
    return (
        f"Workflow is waiting to resume after {resume.blocked_by} "
        f"({_resume_context(resume)}). {validation_message} "
        f"Answer it with `devlab clarify answer {resume.blocked_by} ...`, "
        "then run `devlab resume`."
    )


def _resume_context(resume: ResumeState) -> str:
    details = [f"command=devlab {resume.command}"]
    if resume.role:
        details.append(f"role={resume.role}")
    if resume.task:
        details.append(f"task={resume.task}")
    if resume.milestone:
        details.append(f"milestone={resume.milestone}")
    return ", ".join(details)


def format_clarification_list(clarifications: list[Clarification]) -> str:
    if not clarifications:
        return "No clarifications."
    ordered = sorted(
        clarifications,
        key=lambda clarification: (
            clarification.status != ClarificationStatus.PENDING,
            clarification.id,
        ),
    )
    lines = ["ID      Status      Blocks          Scope           Role       Title"]
    for clarification in ordered:
        lines.append(
            f"{clarification.id:<7} "
            f"{clarification.status.value:<11} "
            f"{clarification.blocks:<15} "
            f"{clarification.scope:<15} "
            f"{clarification.asking_role:<10} "
            f"{clarification.title}"
        )
    return "\n".join(lines)

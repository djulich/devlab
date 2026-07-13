from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from devlab.clarifications import (
    Clarification,
    ClarificationAnswerShape,
    ClarificationStatus,
    choice_option_texts,
)
from devlab.workflow_state import ResumeState, clear_resume_state, load_workflow_state
from devlab.workspace import Workspace

if TYPE_CHECKING:
    from devlab.orchestrator import RunResult


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
    try:
        clarification = Workspace(root).clarifications().get(clarification_id).read()
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

    validation_error = validate_clarification_answer_text(
        clarification, clarification.answer_text
    )
    if validation_error is not None:
        return ClarificationAnswerValidation(False, validation_error, clarification)

    return ClarificationAnswerValidation(
        True,
        f"Clarification {clarification.id} answer is valid.",
        clarification,
    )


def validate_clarification_answer_text(
    clarification: Clarification, answer_text: str
) -> str | None:
    """Validate answer content without mutating its clarification record."""
    answer = answer_text.strip()
    if not answer:
        return (
            f"Clarification {clarification.id} is answered but has an empty "
            "## Answer section."
        )
    if clarification.answer_shape == ClarificationAnswerShape.CHOICE:
        first_answer_line = answer.splitlines()[0].strip()
        options = choice_option_texts(clarification.body)
        if first_answer_line not in options:
            allowed = ", ".join(options) if options else "no listed options"
            return (
                f"Clarification {clarification.id} choice answer must match one listed "
                f"option. Found {first_answer_line!r}; expected one of: {allowed}."
            )
    return None


def apply_validated_clarification_answer(
    root: Path,
    clarification_id: str,
    answer: str,
    *,
    operator: str = "",
) -> Clarification:
    """Validate and apply one answer through the workspace mutation boundary."""
    workspace = Workspace(root)
    handle = workspace.clarifications().get(clarification_id)
    clarification = handle.read()
    validation_error = validate_clarification_answer_text(clarification, answer)
    if validation_error is not None:
        raise ValueError(validation_error)
    answered = handle.answer(answer, operator=operator)
    validation = validate_clarification_answer(root, clarification_id)
    if not validation.valid:
        raise ValueError(validation.message)
    return answered


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
    workspace = Workspace(root)
    clarification_handle = workspace.clarifications().get(clarification_id)
    if choice is not None and text is not None:
        raise ValueError("choose either --choice or --text, not both")
    if choice is None and text is None:
        raise ValueError("answer requires --choice or --text")
    if choice is not None:
        clarification = clarification_handle.answer_choice(
            choice,
            note=note,
            operator=operator,
        )
    else:
        assert text is not None
        clarification = apply_validated_clarification_answer(
            root, clarification_id, text, operator=operator
        )
    run_result = None
    if resume:
        dispatch = resume_workflow(root, max_sessions=max_sessions)
        run_result = dispatch.run_result
        if not dispatch.resumed:
            raise ValueError(dispatch.message)
    return ClarificationAnswerResult(clarification=clarification, resumed=run_result)


def supersede_clarification(root: Path, clarification_id: str, reason: str) -> Clarification:
    return Workspace(root).clarifications().get(clarification_id).supersede(reason)


def resume_workflow(root: Path, *, max_sessions: int = 20) -> ResumeDispatchResult:
    from devlab.orchestrator import run_loop

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

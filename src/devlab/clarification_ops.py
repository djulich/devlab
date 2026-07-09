from __future__ import annotations

import dataclasses
from pathlib import Path

from devlab.clarifications import Clarification, ClarificationStatus, FileClarificationTracker
from devlab.orchestrator import RunResult, run_loop
from devlab.workflow_state import clear_resume_state, load_workflow_state


@dataclasses.dataclass(frozen=True)
class ClarificationAnswerResult:
    clarification: Clarification
    resumed: RunResult | None = None


@dataclasses.dataclass(frozen=True)
class ResumeDispatchResult:
    resumed: bool
    message: str
    run_result: RunResult | None = None


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
        return ResumeDispatchResult(False, "No active clarification resume pointer.")
    tracker = FileClarificationTracker(root)
    try:
        clarification = tracker.get(state.resume.blocked_by)
    except KeyError:
        return ResumeDispatchResult(
            False,
            f"Resume points at unknown clarification {state.resume.blocked_by}.",
        )
    if clarification.status != ClarificationStatus.ANSWERED:
        return ResumeDispatchResult(
            False,
            f"Clarification {clarification.id} is not answered.",
        )
    result = run_loop(
        root,
        max_sessions=max_sessions,
        automatic_version_control=True,
        planning_only=state.resume.command == "plan",
    )
    if result.exit_code == 0 and result.sessions_run > 0:
        clear_resume_state(root)
    return ResumeDispatchResult(True, "Resumed workflow.", result)


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

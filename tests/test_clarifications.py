from __future__ import annotations

from pathlib import Path

import pytest

from devlab.clarification_ops import resume_workflow, validate_clarification_answer
from devlab.clarifications import (
    CLARIFICATIONS_DIR,
    ClarificationAnswerShape,
    ClarificationStatus,
    FileClarificationTracker,
)
from devlab.workflow_state import ResumeState, set_resume_state


def _setup_clarifications_dir(root: Path) -> None:
    (root / CLARIFICATIONS_DIR).mkdir(parents=True)


def _body(title: str = "Auth session timeout") -> str:
    return (
        f"# {title}\n\n"
        "## Context\n"
        "The specification requires sessions but does not define expiry.\n\n"
        "## Question\n"
        "Should sessions expire?\n\n"
        "## Options\n"
        "- A: 24-hour idle timeout.\n"
        "- B: No expiry for MVP.\n"
    )


def test_create_clarification_writes_pending_file(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)

    clarification = FileClarificationTracker(tmp_path).create(
        title="Auth session timeout",
        asking_role="planner",
        session_id="20260707T101500_002_planner",
        scope="milestone:M1",
        blocks="planning",
        answer_shape=ClarificationAnswerShape.CHOICE,
        recommended_option="A",
        body=_body(),
        created_at="2026-07-07T10:15:00Z",
    )

    assert clarification.id == "CL0001"
    assert clarification.status == ClarificationStatus.PENDING
    assert clarification.answer_shape == ClarificationAnswerShape.CHOICE
    assert clarification.recommended_option == "A"
    assert clarification.answered_at is None
    text = clarification.path.read_text()
    assert 'status = "pending"' in text
    assert "answered_at" not in text
    assert "## Answer\n- Pending" in text


def test_lists_clarifications_sorted_by_id(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    (tmp_path / CLARIFICATIONS_DIR / "CL0002_second.md").write_text(
        "+++\n"
        'id = "CL0002"\n'
        'title = "Second"\n'
        'status = "pending"\n'
        'asking_role = "developer"\n'
        'session_id = "s2"\n'
        'scope = "task:T0001"\n'
        'blocks = "task:T0001"\n'
        'answer_shape = "text"\n'
        'recommended_option = ""\n'
        "decision_refs = []\n"
        'created_at = "2026-07-07T10:05:00Z"\n'
        "+++\n\n"
        "# Second\n\n"
        "## Context\nC\n\n"
        "## Question\nQ\n\n"
        "## Expected Answer\nA\n\n"
        "## Answer\n- Pending\n"
    )
    (tmp_path / CLARIFICATIONS_DIR / "CL0001_first.md").write_text(
        "+++\n"
        'id = "CL0001"\n'
        'title = "First"\n'
        'status = "pending"\n'
        'asking_role = "planner"\n'
        'session_id = "s1"\n'
        'scope = "planning"\n'
        'blocks = "planning"\n'
        'answer_shape = "text"\n'
        'recommended_option = ""\n'
        "decision_refs = []\n"
        'created_at = "2026-07-07T10:00:00Z"\n'
        "+++\n\n"
        "# First\n\n"
        "## Context\nC\n\n"
        "## Question\nQ\n\n"
        "## Expected Answer\nA\n\n"
        "## Answer\n- Pending\n"
    )

    clarifications = FileClarificationTracker(tmp_path).list_clarifications()

    assert [clarification.id for clarification in clarifications] == ["CL0001", "CL0002"]


def test_answer_choice_records_option_and_answered_at(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    tracker = FileClarificationTracker(tmp_path)
    clarification = tracker.create(
        title="Auth session timeout",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="choice",
        recommended_option="A",
        body=_body(),
    )

    answered = tracker.answer_choice(
        clarification.id,
        "A",
        note="Use this for MVP.",
        answered_at="2026-07-07T10:20:00Z",
    )

    assert answered.status == ClarificationStatus.ANSWERED
    assert answered.answered_at == "2026-07-07T10:20:00Z"
    assert "A: 24-hour idle timeout." in answered.answer_text
    assert "Operator note: Use this for MVP." in answered.answer_text
    text = answered.path.read_text()
    assert 'status = "answered"' in text
    assert 'answered_at = "2026-07-07T10:20:00Z"' in text


def test_answer_text_updates_answer_section(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    tracker = FileClarificationTracker(tmp_path)
    clarification = tracker.create(
        title="Auth policy",
        asking_role="developer",
        session_id="s1",
        scope="task:T0001",
        blocks="implementation",
        answer_shape="text",
        body=(
            "# Auth policy\n\n"
            "## Context\nC\n\n"
            "## Question\nQ\n\n"
            "## Expected Answer\nA\n"
        ),
    )  # fmt: skip

    answered = tracker.answer(
        clarification.id,
        "Use a 24-hour idle timeout.",
        answered_at="2026-07-07T10:20:00Z",
    )

    assert answered.status == ClarificationStatus.ANSWERED
    assert answered.answer_text == "Use a 24-hour idle timeout."


def test_supersede_sets_status_and_appends_reason(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    tracker = FileClarificationTracker(tmp_path)
    clarification = tracker.create(
        title="Auth policy",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="text",
        body="# Auth policy\n\n## Context\nC\n\n## Question\nQ\n\n## Expected Answer\nA\n",
    )

    superseded = tracker.supersede(
        clarification.id,
        "Spec was edited to remove auth.",
        superseded_at="2026-07-07T10:30:00Z",
    )

    assert superseded.status == ClarificationStatus.SUPERSEDED
    assert "## Superseded\nSpec was edited to remove auth." in superseded.body
    assert 'superseded_at = "2026-07-07T10:30:00Z"' in superseded.path.read_text()


def test_pending_and_answered_filters(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    tracker = FileClarificationTracker(tmp_path)
    pending = tracker.create(
        title="Pending",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="text",
        body="# Pending\n\n## Context\nC\n\n## Question\nQ\n\n## Expected Answer\nA\n",
    )
    answered = tracker.create(
        title="Answered",
        asking_role="planner",
        session_id="s2",
        scope="planning",
        blocks="none",
        answer_shape="text",
        body="# Answered\n\n## Context\nC\n\n## Question\nQ\n\n## Expected Answer\nA\n",
    )
    tracker.answer(answered.id, "Answer", answered_at="2026-07-07T10:20:00Z")

    assert [clarification.id for clarification in tracker.pending()] == [pending.id]
    assert [clarification.id for clarification in tracker.answered()] == [answered.id]
    assert [clarification.id for clarification in tracker.blocking()] == [pending.id]


def test_rejects_invalid_status(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    path = tmp_path / CLARIFICATIONS_DIR / "CL0001_bad.md"
    path.write_text(
        "+++\n"
        'id = "CL0001"\n'
        'title = "Bad"\n'
        'status = "bad"\n'
        'asking_role = "planner"\n'
        'session_id = "s1"\n'
        'scope = "planning"\n'
        'blocks = "planning"\n'
        'answer_shape = "text"\n'
        'recommended_option = ""\n'
        "decision_refs = []\n"
        'created_at = "2026-07-07T10:00:00Z"\n'
        "+++\n\n"
        "# Bad\n"
    )

    with pytest.raises(ValueError, match="invalid clarification status"):
        FileClarificationTracker(tmp_path).list_clarifications()


def test_rejects_invalid_scope_and_blocks(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    tracker = FileClarificationTracker(tmp_path)

    with pytest.raises(ValueError, match="invalid clarification scope"):
        tracker.create(
            title="Bad",
            asking_role="planner",
            session_id="s1",
            scope="../bad",
            blocks="planning",
            answer_shape="text",
            body="# Bad\n",
        )

    with pytest.raises(ValueError, match="invalid clarification blocks"):
        tracker.create(
            title="Bad",
            asking_role="planner",
            session_id="s1",
            scope="planning",
            blocks="all",
            answer_shape="text",
            body="# Bad\n",
        )


def test_rejects_choice_answer_when_option_is_unknown(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    tracker = FileClarificationTracker(tmp_path)
    clarification = tracker.create(
        title="Auth session timeout",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="choice",
        recommended_option="A",
        body=_body(),
    )

    with pytest.raises(ValueError, match="unknown clarification option"):
        tracker.answer_choice(clarification.id, "C")


def test_create_choice_rejects_invalid_recommended_option(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)

    with pytest.raises(ValueError, match="must match one listed option"):
        FileClarificationTracker(tmp_path).create(
            title="Auth session timeout",
            asking_role="planner",
            session_id="s1",
            scope="planning",
            blocks="planning",
            answer_shape="choice",
            recommended_option="C",
            body=_body(),
        )


def test_create_rejects_multiline_title(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)

    with pytest.raises(ValueError, match="title must be a single line"):
        FileClarificationTracker(tmp_path).create(
            title="Auth policy\n## Answer",
            asking_role="planner",
            session_id="s1",
            scope="planning",
            blocks="planning",
            answer_shape="text",
            body="# Auth policy\n\n## Expected Answer\nA\n",
        )


def test_answer_demotes_level_two_headings_to_preserve_answer_section(
    tmp_path: Path,
) -> None:
    _setup_clarifications_dir(tmp_path)
    tracker = FileClarificationTracker(tmp_path)
    clarification = tracker.create(
        title="Auth policy",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="text",
        body="# Auth policy\n\n## Expected Answer\nA\n",
    )

    answered = tracker.answer(clarification.id, "Use 24 hours.\n\n## Caveat\nReversible.")

    assert answered.answer_text == "Use 24 hours.\n\n### Caveat\nReversible."


def test_file_edit_rejects_workflow_state_path(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)

    with pytest.raises(ValueError, match="targets DevLab workflow state"):
        FileClarificationTracker(tmp_path).create(
            title="Planning decision",
            asking_role="planner",
            session_id="s1",
            scope="planning",
            blocks="planning",
            answer_shape="file-edit",
            body=(
                "# Planning decision\n\n"
                "## Expected File Edits\n"
                "- `.devlab/workflow.toml`: update workflow state.\n"
            ),
        )


def test_validate_clarification_answer_rejects_pending_record(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    clarification = FileClarificationTracker(tmp_path).create(
        title="Auth session timeout",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="choice",
        recommended_option="A",
        body=_body(),
    )

    result = validate_clarification_answer(tmp_path, clarification.id)

    assert result.valid is False
    assert "still pending" in result.message


def test_validate_clarification_answer_rejects_empty_manual_answer(
    tmp_path: Path,
) -> None:
    _setup_clarifications_dir(tmp_path)
    path = tmp_path / CLARIFICATIONS_DIR / "CL0001_empty.md"
    path.write_text(
        "+++\n"
        'id = "CL0001"\n'
        'title = "Empty"\n'
        'status = "answered"\n'
        'asking_role = "planner"\n'
        'session_id = "s1"\n'
        'scope = "planning"\n'
        'blocks = "planning"\n'
        'answer_shape = "text"\n'
        'recommended_option = ""\n'
        "decision_refs = []\n"
        'created_at = "2026-07-07T10:00:00Z"\n'
        'answered_at = "2026-07-07T10:20:00Z"\n'
        "+++\n\n"
        "# Empty\n\n"
        "## Context\nC\n\n"
        "## Question\nQ\n\n"
        "## Answer\n"
    )

    result = validate_clarification_answer(tmp_path, "CL0001")

    assert result.valid is False
    assert "empty ## Answer section" in result.message


def test_validate_clarification_answer_rejects_choice_mismatch(
    tmp_path: Path,
) -> None:
    _setup_clarifications_dir(tmp_path)
    path = tmp_path / CLARIFICATIONS_DIR / "CL0001_choice.md"
    path.write_text(
        "+++\n"
        'id = "CL0001"\n'
        'title = "Choice"\n'
        'status = "answered"\n'
        'asking_role = "planner"\n'
        'session_id = "s1"\n'
        'scope = "planning"\n'
        'blocks = "planning"\n'
        'answer_shape = "choice"\n'
        'recommended_option = "A"\n'
        "decision_refs = []\n"
        'created_at = "2026-07-07T10:00:00Z"\n'
        'answered_at = "2026-07-07T10:20:00Z"\n'
        "+++\n\n"
        "# Choice\n\n"
        "## Context\nC\n\n"
        "## Question\nQ\n\n"
        "## Options\n"
        "- A: 24-hour idle timeout.\n"
        "- B: No expiry for MVP.\n\n"
        "## Answer\n"
        "C: Something else.\n"
    )

    result = validate_clarification_answer(tmp_path, "CL0001")

    assert result.valid is False
    assert "choice answer must match one listed option" in result.message


def test_validate_clarification_answer_accepts_manual_choice_answer(
    tmp_path: Path,
) -> None:
    _setup_clarifications_dir(tmp_path)
    path = tmp_path / CLARIFICATIONS_DIR / "CL0001_choice.md"
    path.write_text(
        "+++\n"
        'id = "CL0001"\n'
        'title = "Choice"\n'
        'status = "answered"\n'
        'asking_role = "planner"\n'
        'session_id = "s1"\n'
        'scope = "planning"\n'
        'blocks = "planning"\n'
        'answer_shape = "choice"\n'
        'recommended_option = "A"\n'
        "decision_refs = []\n"
        'created_at = "2026-07-07T10:00:00Z"\n'
        'answered_at = "2026-07-07T10:20:00Z"\n'
        "+++\n\n"
        "# Choice\n\n"
        "## Context\nC\n\n"
        "## Question\nQ\n\n"
        "## Options\n"
        "- A: 24-hour idle timeout.\n"
        "- B: No expiry for MVP.\n\n"
        "## Answer\n"
        "A: 24-hour idle timeout.\n\n"
        "Operator note: Use this for MVP.\n"
    )

    result = validate_clarification_answer(tmp_path, "CL0001")

    assert result.valid is True


def test_resume_workflow_validates_answer_before_invoking_role(tmp_path: Path) -> None:
    _setup_clarifications_dir(tmp_path)
    clarification = FileClarificationTracker(tmp_path).create(
        title="Auth session timeout",
        asking_role="planner",
        session_id="s1",
        scope="planning",
        blocks="planning",
        answer_shape="choice",
        recommended_option="A",
        body=_body(),
    )
    set_resume_state(
        tmp_path,
        ResumeState(
            blocked_by=clarification.id,
            command="plan",
            role="planner",
        ),
    )

    result = resume_workflow(tmp_path)

    assert result.resumed is False
    assert "still pending" in result.message
    assert "Workflow is waiting to resume after CL0001" in result.message
    assert "command=devlab plan" in result.message
    assert "role=planner" in result.message
    assert "devlab clarify answer CL0001 ..." in result.message
    assert "devlab resume" in result.message

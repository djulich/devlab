from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from devlab.research import (
    RESEARCH_DIR,
    FileResearchTracker,
    Research,
    ResearchConfidence,
    ResearchEvidence,
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)


def _create_request(
    root: Path,
    *,
    title: str = "PostgreSQL advisory-lock semantics",
    scope: str = "milestone:M2",
    command: str = "plan",
    task: str = "",
    milestone: str = "M2",
) -> tuple[FileResearchTracker, Research]:
    tracker = FileResearchTracker(root)
    research = tracker.create(
        title=title,
        asking_role="planner",
        asking_session_id="20260812T101500_002_planner",
        command=command,
        scope=scope,
        task=task,
        milestone=milestone,
        question="Can a session-scoped advisory lock safely serialize these workers?",
        context="The design needs one active scheduler across service replicas.",
        desired_outcome="Recommend a locking approach and explain cleanup behavior.",
        acceptance_criteria=[
            "Compare session-level and transaction-level locks.",
            "Use PostgreSQL primary documentation.",
        ],
        created_at="2026-08-12T10:15:00+00:00",
    )
    return tracker, research


def _result(
    *,
    unresolved_questions: tuple[str, ...] = (
        "Does the selected pool guarantee connection affinity?",
    ),
) -> ResearchResult:
    return ResearchResult(
        summary="Session locks are released when the database session ends.",
        evidence=(
            ResearchEvidence(
                claim="Session locks survive transactions and end with the session.",
                source_ids=("S1",),
            ),
            ResearchEvidence(
                claim="Transaction locks end with the transaction.",
                source_ids=("S1", "S2"),
            ),
        ),
        sources=(
            ResearchSource(
                id="S1",
                source_type="primary",
                title="PostgreSQL advisory-lock documentation",
                location="https://example.invalid/postgresql/locks",
            ),
            ResearchSource(
                id="S2",
                source_type="repository",
                title="Scheduler design",
                location="docs/design.md",
            ),
        ),
        recommendation="Use a dedicated connection when affinity is guaranteed.",
        confidence=ResearchConfidence.MEDIUM,
        unresolved_questions=unresolved_questions,
    )


def _complete(tracker: FileResearchTracker, research_id: str = "RS0001") -> Research:
    return tracker.complete(
        research_id,
        _result(),
        researcher_session_id="20260812T102000_003_researcher",
        researcher_provider="codex",
        researcher_model="gpt-5",
        completed_at="2026-08-12T10:25:00+00:00",
    )


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def test_create_request_writes_exact_canonical_record(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)

    assert research.id == "RS0001"
    assert research.status == ResearchStatus.REQUESTED
    assert research.result is None
    assert research.completed_at is None
    assert tracker.requested() == [research]
    assert research.path.read_text() == (
        "+++\n"
        'id = "RS0001"\n'
        'title = "PostgreSQL advisory-lock semantics"\n'
        'status = "requested"\n'
        'asking_role = "planner"\n'
        'asking_session_id = "20260812T101500_002_planner"\n'
        'command = "plan"\n'
        'scope = "milestone:M2"\n'
        'task = ""\n'
        'milestone = "M2"\n'
        'created_at = "2026-08-12T10:15:00+00:00"\n'
        "+++\n\n"
        "# RS0001: PostgreSQL advisory-lock semantics\n\n"
        "## Question\n"
        "Can a session-scoped advisory lock safely serialize these workers?\n\n"
        "## Context\n"
        "The design needs one active scheduler across service replicas.\n\n"
        "## Desired Outcome\n"
        "Recommend a locking approach and explain cleanup behavior.\n\n"
        "## Acceptance Criteria\n"
        "- Compare session-level and transaction-level locks.\n"
        "- Use PostgreSQL primary documentation.\n"
    )


def test_complete_writes_and_round_trips_canonical_result(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)

    completed = _complete(tracker)

    assert completed.status == ResearchStatus.COMPLETED
    assert completed.researcher_session_id == "20260812T102000_003_researcher"
    assert completed.researcher_provider == "codex"
    assert completed.researcher_model == "gpt-5"
    assert completed.completed_at == "2026-08-12T10:25:00+00:00"
    assert completed.result == _result()
    assert tracker.requested() == []
    text = research.path.read_text()
    assert 'status = "completed"\n' in text
    assert 'researcher_model = "gpt-5"\n' in text
    assert (
        "- Session locks survive transactions and end with the session. [S1]\n" in text
    )
    assert "- S2 | repository | Scheduler design | docs/design.md\n" in text
    assert text.endswith(
        "## Unresolved Questions\n"
        "- Does the selected pool guarantee connection affinity?\n"
    )


def test_complete_allows_empty_model_and_no_unresolved_questions(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)

    completed = tracker.complete(
        research.id,
        _result(unresolved_questions=()),
        researcher_session_id="session",
        researcher_provider="provider",
        researcher_model="",
        completed_at="2026-08-12T10:25:00Z",
    )

    assert completed.researcher_model == ""
    assert completed.result is not None
    assert completed.result.unresolved_questions == ()
    assert completed.path.read_text().endswith("## Unresolved Questions\n- None\n")


def test_list_is_numerically_sorted_and_filters_requested(tmp_path: Path) -> None:
    tracker, first = _create_request(tmp_path)
    second = tracker.create(
        title="Second",
        asking_role="developer",
        asking_session_id="session-2",
        command="implement",
        scope="task:T0010",
        task="T0010",
        question="Question?",
        context="Context.",
        desired_outcome="An answer.",
        acceptance_criteria=["Find evidence."],
        created_at="2026-08-12T10:16:00+00:00",
    )
    _complete(tracker, first.id)

    assert [item.id for item in tracker.list_research()] == ["RS0001", "RS0002"]
    assert [item.id for item in tracker.requested()] == [second.id]


def test_slug_fallback_and_id_transition_to_five_digits(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path, title="💡")
    assert research.path.name == "RS0001_research.md"

    target = research.path.with_name("RS9999_research.md")
    text = research.path.read_text().replace("RS0001", "RS9999")
    research.path.rename(target)
    target.write_text(text)

    created = tracker.create(
        title="Next",
        asking_role="planner",
        asking_session_id="session",
        command="plan",
        scope="planning",
        question="Question?",
        context="Context.",
        desired_outcome="Outcome.",
        acceptance_criteria=["Criterion."],
        created_at="2026-08-12T10:20:00+00:00",
    )

    assert created.id == "RS10000"


def test_id_allocation_fails_after_rs99999(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)
    target = research.path.with_name("RS99999_research.md")
    text = research.path.read_text().replace("RS0001", "RS99999")
    research.path.rename(target)
    target.write_text(text)

    with pytest.raises(ValueError, match="exhausted"):
        tracker.create(
            title="No ID",
            asking_role="planner",
            asking_session_id="session",
            command="plan",
            scope="planning",
            question="Question?",
            context="Context.",
            desired_outcome="Outcome.",
            acceptance_criteria=["Criterion."],
        )


def test_get_rejects_unknown_and_duplicate_ids(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)
    duplicate = research.path.with_name("RS0001_duplicate.md")
    duplicate.write_text(research.path.read_text())

    with pytest.raises(ValueError, match=r"duplicate research id.*RS0001"):
        tracker.list_research()

    duplicate.unlink()
    with pytest.raises(KeyError, match="unknown research id: RS9000"):
        tracker.get("RS9000")


def test_complete_rejects_unknown_and_completed_records(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)

    with pytest.raises(KeyError, match="unknown research id: RS9000"):
        _complete(tracker, "RS9000")

    _complete(tracker, research.id)
    with pytest.raises(ValueError, match="RS0001 is not requested"):
        _complete(tracker, research.id)


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (
            ResearchResult(
                summary="Summary",
                evidence=(ResearchEvidence("Claim", ("S2",)),),
                sources=(ResearchSource("S1", "Title", "path", "primary"),),
                recommendation="Recommendation",
                confidence=ResearchConfidence.HIGH,
                unresolved_questions=(),
            ),
            "unknown source.*S2",
        ),
        (
            ResearchResult(
                summary="Summary",
                evidence=(ResearchEvidence("Claim", ("S1", "S1")),),
                sources=(ResearchSource("S1", "Title", "path", "primary"),),
                recommendation="Recommendation",
                confidence=ResearchConfidence.HIGH,
                unresolved_questions=(),
            ),
            "duplicate source ids",
        ),
        (
            ResearchResult(
                summary="Summary",
                evidence=(),
                sources=(ResearchSource("S1", "Title", "path", "primary"),),
                recommendation="Recommendation",
                confidence=ResearchConfidence.HIGH,
                unresolved_questions=(),
            ),
            "at least one evidence",
        ),
        (
            ResearchResult(
                summary="Summary",
                evidence=(ResearchEvidence("Claim", ("S1",)),),
                sources=(
                    ResearchSource("S1", "Title", "path", "primary"),
                    ResearchSource("S1", "Other", "other", "primary"),
                ),
                recommendation="Recommendation",
                confidence=ResearchConfidence.HIGH,
                unresolved_questions=(),
            ),
            "duplicate source id",
        ),
    ],
)
def test_failed_completion_preserves_requested_bytes(
    tmp_path: Path, result: ResearchResult, message: str
) -> None:
    tracker, research = _create_request(tmp_path)
    before = research.path.read_bytes()

    with pytest.raises(ValueError, match=message):
        tracker.complete(
            research.id,
            result,
            researcher_session_id="session",
            researcher_provider="provider",
            completed_at="2026-08-12T10:25:00+00:00",
        )

    assert research.path.read_bytes() == before


def test_completion_preserves_unknown_metadata_in_sorted_order(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)
    _replace(
        research.path,
        'created_at = "2026-08-12T10:15:00+00:00"\n',
        'created_at = "2026-08-12T10:15:00+00:00"\n'
        'z_extension = "last"\n'
        'a_extension = "first"\n',
    )

    completed = _complete(tracker)
    text = completed.path.read_text()

    assert text.index('a_extension = "first"') < text.index('z_extension = "last"')
    assert completed.metadata["a_extension"] == "first"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('status = "requested"', 'status = "invalid"', "invalid status"),
        ('command = "plan"', 'command = "run"', "invalid command"),
        ('scope = "milestone:M2"', 'scope = "milestone:M3"', "must match milestone"),
        ('milestone = "M2"', 'milestone = "bad"', "invalid milestone"),
        (
            'created_at = "2026-08-12T10:15:00+00:00"',
            'created_at = "2026-08-12T10:15:00"',
            "timezone-aware",
        ),
        ("## Context", "## Unknown", "requires H2 sections in order"),
        ("## Context", "## Question", "requires H2 sections in order"),
        ("# RS0001:", "# RS0002:", "requires exact heading"),
    ],
)
def test_malformed_disk_records_fail_closed(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    tracker, research = _create_request(tmp_path)
    _replace(research.path, old, new)

    with pytest.raises(ValueError, match=message):
        tracker.list_research()


def test_missing_and_invalid_front_matter_fail_closed(tmp_path: Path) -> None:
    research_dir = tmp_path / RESEARCH_DIR
    research_dir.mkdir(parents=True)
    missing = research_dir / "RS0001_missing.md"
    missing.write_text("# RS0001: Missing\n")

    with pytest.raises(ValueError, match="requires TOML front matter"):
        FileResearchTracker(tmp_path).list_research()

    missing.write_text("+++\nid = [\n+++\n# RS0001: Invalid\n")
    with pytest.raises(ValueError, match="invalid TOML front matter") as error:
        FileResearchTracker(tmp_path).list_research()
    assert error.value.__cause__ is not None


def test_filename_and_metadata_identity_must_match(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)
    renamed = research.path.with_name("RS0002_wrong.md")
    research.path.rename(renamed)

    with pytest.raises(ValueError, match="filename must start with RS0001"):
        tracker.list_research()


def test_requested_record_forbids_result_and_provenance(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)
    _replace(
        research.path,
        'created_at = "2026-08-12T10:15:00+00:00"',
        'created_at = "2026-08-12T10:15:00+00:00"\n'
        'researcher_session_id = "unexpected"',
    )

    with pytest.raises(ValueError, match="requested status forbids provenance"):
        tracker.list_research()


def test_completed_record_requires_all_provenance_and_result_sections(tmp_path: Path) -> None:
    tracker, completed = _create_request(tmp_path)
    completed = _complete(tracker)
    _replace(completed.path, 'researcher_provider = "codex"\n', "")

    with pytest.raises(ValueError, match="researcher_provider"):
        tracker.list_research()

    completed = _complete(_create_request(tmp_path / "other")[0])
    text = completed.path.read_text()
    completed.path.write_text(text[: text.index("\n## Summary") + 1])
    with pytest.raises(ValueError, match="requires H2 sections in order"):
        FileResearchTracker(tmp_path / "other").list_research()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"title": "bad\ntitle"}, "single line"),
        ({"scope": "task:T0001", "command": "plan", "task": "T0001"}, "implement"),
        ({"scope": "planning", "command": "implement", "milestone": ""}, "planning scope"),
    ],
)
def test_create_validates_request_before_writing(
    tmp_path: Path, kwargs: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _create_request(tmp_path, **kwargs)
    assert not (tmp_path / RESEARCH_DIR).exists()


def test_create_rejects_duplicate_and_multiline_acceptance_criteria(tmp_path: Path) -> None:
    tracker = FileResearchTracker(tmp_path)
    base = {
        "title": "Title",
        "asking_role": "planner",
        "asking_session_id": "session",
        "command": "plan",
        "scope": "planning",
        "question": "Question?",
        "context": "Context.",
        "desired_outcome": "Outcome.",
    }

    with pytest.raises(ValueError, match="duplicates"):
        tracker.create(**base, acceptance_criteria=["Same", "Same"])
    with pytest.raises(ValueError, match="single line"):
        tracker.create(**base, acceptance_criteria=["First\nSecond"])


def test_free_text_headings_are_normalized_to_h3(tmp_path: Path) -> None:
    tracker = FileResearchTracker(tmp_path)
    research = tracker.create(
        title="Heading safety",
        asking_role="planner",
        asking_session_id="session",
        command="plan",
        scope="planning",
        question="Question?\n## Embedded detail",
        context="# Context detail",
        desired_outcome="Outcome.",
        acceptance_criteria=["Criterion."],
        created_at="2026-08-12T10:15:00+00:00",
    )

    assert "### Embedded detail" in research.question
    assert "### Context detail" in research.context
    assert "\n## Embedded detail\n" not in research.path.read_text()


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda result: dataclasses.replace(
                result, confidence=cast(ResearchConfidence, "certain")
            ),
            "confidence",
        ),
        (
            lambda result: dataclasses.replace(
                result,
                sources=(ResearchSource("S0", "Title", "path", "primary"),),
                evidence=(ResearchEvidence("Claim", ("S0",)),),
            ),
            "invalid source id",
        ),
        (
            lambda result: dataclasses.replace(
                result,
                sources=(ResearchSource("S1", "Bad | title", "path", "primary"),),
                evidence=(ResearchEvidence("Claim", ("S1",)),),
            ),
            "must not contain",
        ),
        (
            lambda result: dataclasses.replace(result, unresolved_questions=("None",)),
            "reserves the value",
        ),
    ],
)
def test_result_validation_rejects_invalid_values(
    tmp_path: Path,
    mutator: Callable[[ResearchResult], ResearchResult],
    message: str,
) -> None:
    tracker, research = _create_request(tmp_path)
    invalid = mutator(_result())

    with pytest.raises(ValueError, match=message):
        tracker.complete(
            research.id,
            invalid,
            researcher_session_id="session",
            researcher_provider="provider",
            completed_at="2026-08-12T10:25:00+00:00",
        )


def test_completion_rejects_earlier_timestamp_and_multiline_provenance(tmp_path: Path) -> None:
    tracker, research = _create_request(tmp_path)

    with pytest.raises(ValueError, match="earlier than created_at"):
        tracker.complete(
            research.id,
            _result(),
            researcher_session_id="session",
            researcher_provider="provider",
            completed_at="2026-08-12T10:14:59+00:00",
        )
    with pytest.raises(ValueError, match="single line"):
        tracker.complete(
            research.id,
            _result(),
            researcher_session_id="bad\nsession",
            researcher_provider="provider",
        )

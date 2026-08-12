from __future__ import annotations

from pathlib import Path

import pytest

from devlab.handoffs import (
    HANDOFF_CANDIDATE_FILE,
    SESSION_RESULT_FILE,
    HandoffError,
    HandoffSubmissionError,
    SessionEnvelope,
    load_session_result,
    parse_handoff,
    parse_handoff_candidate,
    publish_session_result,
    section_is_none,
    write_session_envelope,
)


def test_session_envelope_initializes_role_aware_candidate(tmp_path: Path) -> None:
    envelope_path = tmp_path / "planner" / "session.toml"

    write_session_envelope(
        envelope_path,
        SessionEnvelope(1, "s1", "planner", task="", milestone="M0001"),
    )

    candidate = envelope_path.with_name(HANDOFF_CANDIDATE_FILE).read_text()
    assert 'outcome = "completed"' in candidate
    assert "planning_complete = false" in candidate
    assert "session_id" not in candidate


def test_candidate_validation_reports_all_independent_errors(tmp_path: Path) -> None:
    path = tmp_path / HANDOFF_CANDIDATE_FILE
    path.write_text(
        'schema_version = 1\noutcome = "unknown"\ncommit_message = "ok"\n'
        'done = []\nchanged_artifacts = []\nopen_issues = []\n'
        'addressed_findings = []\nnext_session_hint = ""\nextra = true\n'
    )

    with pytest.raises(HandoffSubmissionError) as exc:
        parse_handoff_candidate(path, "developer")

    assert any("unexpected field" in issue for issue in exc.value.issues)
    assert any("outcome must be one of" in issue for issue in exc.value.issues)
    assert any("done must contain" in issue for issue in exc.value.issues)
    assert any("next_session_hint must be non-empty" in issue for issue in exc.value.issues)


def test_publish_and_load_session_result_round_trip(tmp_path: Path) -> None:
    envelope_path = tmp_path / "developer" / "session.toml"
    envelope = SessionEnvelope(1, "s1", "developer", task="T0001")
    write_session_envelope(envelope_path, envelope)
    candidate_path = envelope_path.with_name(HANDOFF_CANDIDATE_FILE)
    candidate_path.write_text(
        'schema_version = 1\noutcome = "completed"\n'
        'commit_message = "Implement behavior"\n'
        'done = ["Implemented behavior"]\nchanged_artifacts = ["src/app.py"]\n'
        'open_issues = []\naddressed_findings = []\n'
        'next_session_hint = "Review the behavior."\n'
    )
    candidate = parse_handoff_candidate(candidate_path, "developer")

    publish_session_result(envelope_path, envelope, candidate)
    result = load_session_result(envelope_path.with_name(SESSION_RESULT_FILE))
    handoff = result.as_handoff(envelope_path.with_name("handoff.md"))

    assert result.envelope.task == "T0001"
    assert handoff.commit_message == "Implement behavior"
    assert handoff.has_open_issues is False
    assert "## Done\n- Implemented behavior" in handoff.path.read_text()


def test_research_candidate_publish_and_handoff_round_trip(tmp_path: Path) -> None:
    envelope_path = tmp_path / "developer" / "session.toml"
    envelope = SessionEnvelope(1, "s1", "developer", task="T0001", milestone="M1")
    write_session_envelope(envelope_path, envelope)
    candidate_path = envelope_path.with_name(HANDOFF_CANDIDATE_FILE)
    candidate_path.write_text(_research_candidate_text())

    candidate = parse_handoff_candidate(candidate_path, "developer")
    assert candidate.outcome == "needs_research"
    assert candidate.research is not None
    assert candidate.research.title == "Lock behavior"
    assert candidate.research.scope == "task:T0001"
    assert candidate.research.acceptance_criteria == (
        "Use primary documentation.",
        "Explain connection-pool implications.",
    )

    publish_session_result(envelope_path, envelope, candidate)
    result = load_session_result(envelope_path.with_name(SESSION_RESULT_FILE))
    handoff = result.as_handoff(envelope_path.with_name("handoff.md"))

    assert result.candidate.research == candidate.research
    assert handoff.research_request == candidate.research
    assert "## Research Request\nresearch_required = true" in handoff.path.read_text()
    assert "[research]\n" in envelope_path.with_name(SESSION_RESULT_FILE).read_text()


def test_research_candidate_requires_matching_outcome_and_table(tmp_path: Path) -> None:
    path = tmp_path / HANDOFF_CANDIDATE_FILE
    path.write_text(_research_candidate_text().split("\n[research]", 1)[0] + "\n")

    with pytest.raises(HandoffSubmissionError) as error:
        parse_handoff_candidate(path, "developer")
    assert "outcome needs_research requires [research]" in error.value.issues

    path.write_text(
        _research_candidate_text().replace(
            'outcome = "needs_research"', 'outcome = "completed"'
        )
    )
    with pytest.raises(HandoffSubmissionError) as error:
        parse_handoff_candidate(path, "developer")
    assert "[research] is only allowed for outcome needs_research" in error.value.issues


@pytest.mark.parametrize("role_name", ["reviewer", "integrator"])
def test_research_candidate_rejects_ineligible_roles(
    tmp_path: Path, role_name: str
) -> None:
    path = tmp_path / HANDOFF_CANDIDATE_FILE
    text = _research_candidate_text()
    if role_name == "integrator":
        text = text.replace(
            "\n[research]",
            "\nsemantic_integration_concerns = []\nuntested_claims = []\n\n[research]",
        )
    path.write_text(text)

    with pytest.raises(HandoffSubmissionError) as error:
        parse_handoff_candidate(path, role_name)

    assert any(
        "only allowed for architect, planner, and developer" in issue
        for issue in error.value.issues
    )


@pytest.mark.parametrize("role_name", ["architect", "planner"])
def test_research_candidate_accepts_other_eligible_roles(
    tmp_path: Path, role_name: str
) -> None:
    path = tmp_path / HANDOFF_CANDIDATE_FILE
    text = _research_candidate_text()
    if role_name == "planner":
        text = text.replace("\n[research]", "\nplanning_complete = false\n\n[research]")
    path.write_text(text)

    candidate = parse_handoff_candidate(path, role_name)

    assert candidate.research is not None
    assert candidate.outcome == "needs_research"


def test_research_candidate_is_mutually_exclusive_with_clarification(tmp_path: Path) -> None:
    path = tmp_path / HANDOFF_CANDIDATE_FILE
    path.write_text(
        _research_candidate_text()
        + "\n[clarification]\n"
        'title = "Choice"\n'
        'scope = "planning"\n'
        'blocks = "planning"\n'
        'answer_shape = "text"\n'
        'recommended_option = ""\n'
        'details = "### Context\\nC\\n\\n### Question\\nQ\\n\\n### Expected Answer\\nA"\n'
    )

    with pytest.raises(HandoffSubmissionError) as error:
        parse_handoff_candidate(path, "developer")

    assert "[clarification] and [research] are mutually exclusive" in error.value.issues


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('scope = "task:T0001"', 'scope = "finding:F0001"', "scope must be"),
        (
            'acceptance_criteria = ["Use primary documentation.", '
            '"Explain connection-pool implications."]',
            'acceptance_criteria = ["Same.", "Same."]',
            "must be unique",
        ),
        ('title = "Lock behavior"', 'title = "First\\nSecond"', "single line"),
        ('question = "How do session locks behave?"\n', "", "question must be a string"),
        (
            "[research]\n",
            "[research]\nunexpected = true\n",
            "unexpected field",
        ),
    ],
)
def test_research_candidate_rejects_malformed_request(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / HANDOFF_CANDIDATE_FILE
    text = _research_candidate_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))

    with pytest.raises(HandoffSubmissionError) as error:
        parse_handoff_candidate(path, "developer")

    assert any(message in issue for issue in error.value.issues)


def test_parse_handoff_reads_and_validates_research_request(tmp_path: Path) -> None:
    section = (
        "## Research Request\n"
        "research_required = true\n"
        'title = "Lock behavior"\n'
        'scope = "task:T0001"\n'
        'question = "How do session locks behave?"\n'
        'context = "The implementation needs a cross-process lock."\n'
        'desired_outcome = "Recommend a safe approach."\n'
        'acceptance_criteria = ["Use primary documentation."]\n'
    )
    path = _write_handoff(tmp_path, extra_after=section)

    request = parse_handoff(path, "developer").research_request

    assert request is not None
    assert request.question == "How do session locks behave?"
    assert request.acceptance_criteria == ("Use primary documentation.",)


def test_parse_handoff_rejects_research_for_ineligible_role(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="reviewer",
        extra_after=(
            "## Research Request\n"
            "research_required = true\n"
            'title = "Lock behavior"\n'
            'scope = "task:T0001"\n'
            'question = "Question?"\n'
            'context = "Context."\n'
            'desired_outcome = "Outcome."\n'
            'acceptance_criteria = ["Criterion."]\n'
        ),
    )

    with pytest.raises(HandoffError, match="only allowed for architect, planner, and developer"):
        parse_handoff(path, "reviewer")


def test_parse_valid_handoff(tmp_path: Path) -> None:
    path = _write_handoff(tmp_path)

    handoff = parse_handoff(path, "developer")

    assert handoff.section("Done") == "- Completed work."
    assert handoff.has_open_issues is False
    assert handoff.addressed_finding_tasks() == {}


def test_parse_handoff_requires_file(tmp_path: Path) -> None:
    with pytest.raises(HandoffError, match="handoff file does not exist"):
        parse_handoff(tmp_path / "missing.md", "developer")


def test_parse_handoff_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "handoff.md"
    path.write_text("\n")

    with pytest.raises(HandoffError, match="handoff file is empty"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_missing_heading(tmp_path: Path) -> None:
    path = _write_handoff(tmp_path, include_open_issues=False)

    with pytest.raises(HandoffError, match="missing required heading"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_duplicate_required_heading(tmp_path: Path) -> None:
    path = _write_handoff(tmp_path, extra_after="## Open Issues\n- None\n")

    with pytest.raises(HandoffError, match="duplicate required heading"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_out_of_order_heading(tmp_path: Path) -> None:
    path = tmp_path / "handoff.md"
    path.write_text(
        "# Handoff: developer\n"
        "## Done\n- Completed work.\n"
        "## Open Issues\n- None\n"
        "## Changed Artifacts\n- None\n"
        "## Addressed Findings\n- None\n"
        "## Next Session Hint\nContinue.\n"
    )

    with pytest.raises(HandoffError, match="not in the required order"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_extra_section_between_required_headings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "handoff.md"
    path.write_text(
        "# Handoff: developer\n"
        "## Done\n- Completed work.\n"
        "## Extra\nUnexpected.\n"
        "## Changed Artifacts\n- None\n"
        "## Open Issues\n- None\n"
        "## Addressed Findings\n- None\n"
        "## Next Session Hint\nContinue.\n"
    )

    with pytest.raises(HandoffError, match="unexpected ## section"):
        parse_handoff(path, "developer")


def test_parse_handoff_allows_extra_section_after_required_headings(tmp_path: Path) -> None:
    path = _write_handoff(tmp_path, extra_after="## Extra\nAllowed.\n")

    handoff = parse_handoff(path, "developer")

    assert handoff.section("Next Session Hint") == "Continue."


def test_parse_handoff_reads_optional_commit_message(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after="## Commit Message\n- Implement calculator CLI\n\nDetailed notes.\n",
    )

    handoff = parse_handoff(path, "developer")

    assert handoff.commit_message == "Implement calculator CLI"


def test_parse_handoff_reads_choice_clarification_request(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        open_issues="- Blocked pending operator clarification.",
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = true\n"
            'title = "Auth session timeout"\n'
            'scope = "milestone:M1"\n'
            'blocks = "planning"\n'
            'answer_shape = "choice"\n'
            'recommended_option = "A"\n\n'
            "### Context\n"
            "The spec requires sessions but not expiry.\n\n"
            "### Question\n"
            "Should sessions expire?\n\n"
            "### Options\n"
            "- A: 24-hour idle timeout.\n"
            "- B: No expiry for MVP.\n"
        ),
    )

    request = parse_handoff(path, "developer").clarification_request

    assert request is not None
    assert request.title == "Auth session timeout"
    assert request.scope == "milestone:M1"
    assert request.blocks == "planning"
    assert request.answer_shape == "choice"
    assert request.recommended_option == "A"
    assert "### Options" in request.details


def test_parse_handoff_reads_text_clarification_request(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = true\n"
            'title = "Auth policy"\n'
            'scope = "task:T0001"\n'
            'blocks = "implementation"\n'
            'answer_shape = "text"\n\n'
            "### Context\nC\n\n"
            "### Question\nQ\n\n"
            "### Expected Answer\nA\n"
        ),
    )

    request = parse_handoff(path, "developer").clarification_request

    assert request is not None
    assert request.answer_shape == "text"
    assert request.recommended_option == ""


def test_parse_handoff_reads_file_edit_clarification_request(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = true\n"
            'title = "Deployment target"\n'
            'scope = "planning"\n'
            'blocks = "planning"\n'
            'answer_shape = "file-edit"\n\n'
            "### Context\nC\n\n"
            "### Question\nQ\n\n"
            "### Expected File Edits\n"
            "- `.devlab/specs/system/deployment.md`: define the target.\n"
        ),
    )

    request = parse_handoff(path, "developer").clarification_request

    assert request is not None
    assert request.answer_shape == "file-edit"


def test_parse_handoff_rejects_malformed_clarification_toml(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = maybe\n\n"
            "### Context\nC\n\n"
            "### Question\nQ\n\n"
            "### Expected Answer\nA\n"
        ),
    )

    with pytest.raises(HandoffError, match="must start with TOML"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_clarification_missing_context(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = true\n"
            'title = "Auth policy"\n'
            'scope = "planning"\n'
            'blocks = "planning"\n'
            'answer_shape = "text"\n\n'
            "### Question\nQ\n\n"
            "### Expected Answer\nA\n"
        ),
    )

    with pytest.raises(HandoffError, match="missing ### Context"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_choice_clarification_without_options(
    tmp_path: Path,
) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = true\n"
            'title = "Auth policy"\n'
            'scope = "planning"\n'
            'blocks = "planning"\n'
            'answer_shape = "choice"\n'
            'recommended_option = "A"\n\n'
            "### Context\nC\n\n"
            "### Question\nQ\n"
        ),
    )

    with pytest.raises(HandoffError, match="missing ### Options"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_choice_clarification_with_invalid_recommendation(
    tmp_path: Path,
) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = true\n"
            'title = "Auth policy"\n'
            'scope = "planning"\n'
            'blocks = "planning"\n'
            'answer_shape = "choice"\n'
            'recommended_option = "C"\n\n'
            "### Context\nC\n\n"
            "### Question\nQ\n\n"
            "### Options\n"
            "- A: 24-hour idle timeout.\n"
            "- B: No expiry for MVP.\n"
        ),
    )

    with pytest.raises(HandoffError, match="must match one listed option"):
        parse_handoff(path, "developer")


def test_parse_handoff_does_not_find_recommendation_outside_options(
    tmp_path: Path,
) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = true\n"
            'title = "Auth policy"\n'
            'scope = "planning"\n'
            'blocks = "planning"\n'
            'answer_shape = "choice"\n'
            'recommended_option = "C"\n\n'
            "### Context\n- C: Mentioned here, but not an option.\n\n"
            "### Question\nQ\n\n"
            "### Options\n- A: First.\n- B: Second.\n"
        ),
    )

    with pytest.raises(HandoffError, match="must match one listed option"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_duplicate_clarification_request(tmp_path: Path) -> None:
    request = (
        "## Clarification Request\n"
        "clarification_required = true\n"
        'title = "Auth policy"\n'
        'scope = "planning"\n'
        'blocks = "planning"\n'
        'answer_shape = "text"\n\n'
        "### Context\nC\n\n### Question\nQ\n\n### Expected Answer\nA\n"
    )
    path = _write_handoff(tmp_path, extra_after=request + request)

    with pytest.raises(HandoffError, match="duplicate heading: ## Clarification Request"):
        parse_handoff(path, "developer")


def test_parse_handoff_rejects_invalid_clarification_enum(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after=(
            "## Clarification Request\n"
            "clarification_required = true\n"
            'title = "Auth policy"\n'
            'scope = "planning"\n'
            'blocks = "planning"\n'
            'answer_shape = "boolean"\n\n'
            "### Context\nC\n\n"
            "### Question\nQ\n\n"
            "### Expected Answer\nA\n"
        ),
    )

    with pytest.raises(HandoffError, match="answer_shape must be one of"):
        parse_handoff(path, "developer")


def test_parse_planner_handoff_requires_planning_state(tmp_path: Path) -> None:
    path = _write_handoff(tmp_path)

    with pytest.raises(HandoffError, match="missing required heading: ## Planning State"):
        parse_handoff(path, "planner")


def test_parse_planner_handoff_reads_planning_state(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        extra_after="## Planning State\nplanning_complete = true\n",
    )

    handoff = parse_handoff(path, "planner")

    assert handoff.planning_complete is True


def test_parse_planner_handoff_rejects_malformed_planning_state(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        extra_after="## Planning State\nplanning_complete = maybe\n",
    )

    with pytest.raises(HandoffError, match="must be TOML"):
        parse_handoff(path, "planner")


def test_parse_planner_handoff_rejects_extra_planning_state_keys(
    tmp_path: Path,
) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        extra_after=(
            "## Planning State\n"
            "planning_complete = true\n"
            "other = false\n"
        ),
    )

    with pytest.raises(HandoffError, match="must contain only planning_complete"):
        parse_handoff(path, "planner")


def test_parse_planner_handoff_rejects_non_boolean_planning_state(
    tmp_path: Path,
) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        extra_after='## Planning State\nplanning_complete = "true"\n',
    )

    with pytest.raises(HandoffError, match="planning_complete must be a boolean"):
        parse_handoff(path, "planner")


def test_parse_non_planner_handoff_rejects_planning_state(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after="## Planning State\nplanning_complete = true\n",
    )

    with pytest.raises(HandoffError, match="only allowed for planner"):
        parse_handoff(path, "developer")


def test_parse_handoff_allows_missing_commit_message(tmp_path: Path) -> None:
    path = _write_handoff(tmp_path)

    handoff = parse_handoff(path, "developer")

    assert handoff.commit_message == ""


def test_parse_handoff_rejects_empty_required_section(tmp_path: Path) -> None:
    path = _write_handoff(tmp_path, done="")

    with pytest.raises(HandoffError, match="section ## Done is empty"):
        parse_handoff(path, "developer")


def test_section_is_none_is_strict() -> None:
    assert section_is_none("- None") is True
    assert section_is_none("None") is True
    assert section_is_none("- No tests exist") is False
    assert section_is_none("- None, but deployment is missing") is False


def test_parse_handoff_rejects_open_issues_mixing_none_and_real_content(
    tmp_path: Path,
) -> None:
    path = _write_handoff(tmp_path, open_issues="- None\n- Missing test coverage.")

    with pytest.raises(HandoffError, match="mixes None with real content"):
        parse_handoff(path, "integrator")


def test_parse_handoff_rejects_malformed_addressed_findings(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        addressed="- F0001 T0002",
        extra_after="## Planning State\nplanning_complete = false\n",
    )

    with pytest.raises(HandoffError, match="Addressed Findings entries must use"):
        parse_handoff(path, "planner")


def test_parse_handoff_parses_addressed_finding_mappings(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        addressed="- F0001: T0002, T0003",
        extra_after="## Planning State\nplanning_complete = false\n",
    )

    handoff = parse_handoff(path, "planner")

    assert handoff.addressed_finding_tasks() == {"F0001": ("T0002", "T0003")}


def test_parse_handoff_rejects_duplicate_addressed_finding(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        addressed="- F0001: T0002\n- F0001: T0003",
        extra_after="## Planning State\nplanning_complete = false\n",
    )

    with pytest.raises(HandoffError, match="lists F0001 more than once"):
        parse_handoff(path, "planner")


def test_parse_handoff_rejects_duplicate_addressing_task(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        addressed="- F0001: T0002, T0002",
        extra_after="## Planning State\nplanning_complete = false\n",
    )

    with pytest.raises(HandoffError, match="lists duplicate task"):
        parse_handoff(path, "planner")


def test_parse_handoff_rejects_mixed_none_and_addressed_findings(
    tmp_path: Path,
) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        addressed="- None\n- F0001: T0002",
        extra_after="## Planning State\nplanning_complete = false\n",
    )

    with pytest.raises(HandoffError, match="cannot mix"):
        parse_handoff(path, "planner")


def _write_handoff(
    root: Path,
    *,
    role_name: str = "developer",
    done: str = "- Completed work.",
    changed: str = "- None",
    open_issues: str = "- None",
    addressed: str = "- None",
    hint: str = "Continue.",
    include_open_issues: bool = True,
    extra_after: str = "",
) -> Path:
    path = root / "handoff.md"
    text = (
        f"# Handoff: {role_name}\n"
        f"## Done\n{done}\n"
        f"## Changed Artifacts\n{changed}\n"
    )
    if include_open_issues:
        text += f"## Open Issues\n{open_issues}\n"
    text += (
        f"## Addressed Findings\n{addressed}\n"
        f"## Next Session Hint\n{hint}\n"
        f"{extra_after}"
    )
    path.write_text(text)
    return path


def _research_candidate_text() -> str:
    return (
        'schema_version = 1\noutcome = "needs_research"\n'
        'commit_message = ""\n'
        'done = ["Identified a bounded research question."]\n'
        'changed_artifacts = []\nopen_issues = ["Research is required."]\n'
        'addressed_findings = []\nnext_session_hint = "Research lock behavior."\n\n'
        "[research]\n"
        'title = "Lock behavior"\n'
        'scope = "task:T0001"\n'
        'question = "How do session locks behave?"\n'
        'context = "The implementation needs a cross-process lock."\n'
        'desired_outcome = "Recommend a safe approach."\n'
        'acceptance_criteria = ["Use primary documentation.", '
        '"Explain connection-pool implications."]\n'
    )

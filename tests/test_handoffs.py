from __future__ import annotations

from pathlib import Path

import pytest

from devlab.handoffs import HandoffError, parse_handoff, section_is_none


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


def test_parse_planner_handoff_requires_planning_state(tmp_path: Path) -> None:
    path = _write_handoff(tmp_path)

    with pytest.raises(HandoffError, match="missing required heading: ## Planning State"):
        parse_handoff(path, "planner")


def test_parse_planner_handoff_reads_planning_state(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        extra_after=(
            "## Planned Tasks\n- T0001\n"
            "## Planning State\nplanning_complete = true\n"
        ),
    )

    handoff = parse_handoff(path, "planner")

    assert handoff.planning_complete is True
    assert handoff.planned_task_ids() == ("T0001",)


def test_parse_planner_handoff_requires_planned_tasks(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        extra_after="## Planning State\nplanning_complete = true\n",
    )

    with pytest.raises(HandoffError, match="missing required heading: ## Planned Tasks"):
        parse_handoff(path, "planner")


def test_parse_planner_handoff_rejects_malformed_planned_tasks(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        extra_after=(
            "## Planned Tasks\n- T0001: Build feature\n"
            "## Planning State\nplanning_complete = true\n"
        ),
    )

    with pytest.raises(HandoffError, match="Planned Tasks entries must use"):
        parse_handoff(path, "planner")


def test_parse_planner_handoff_rejects_duplicate_planned_tasks(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        extra_after=(
            "## Planned Tasks\n- T0001\n- T0001\n"
            "## Planning State\nplanning_complete = true\n"
        ),
    )

    with pytest.raises(HandoffError, match="duplicate task T0001"):
        parse_handoff(path, "planner")


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


def test_parse_non_planner_handoff_rejects_planned_tasks(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        extra_after="## Planned Tasks\n- T0001\n",
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
        extra_after=(
            "## Planned Tasks\n- T0002\n"
            "## Planning State\nplanning_complete = false\n"
        ),
    )

    with pytest.raises(HandoffError, match="Addressed Findings entries must use"):
        parse_handoff(path, "planner")


def test_parse_handoff_parses_addressed_finding_mappings(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        addressed="- F0001: T0002, T0003",
        extra_after=(
            "## Planned Tasks\n- T0002\n- T0003\n"
            "## Planning State\nplanning_complete = false\n"
        ),
    )

    handoff = parse_handoff(path, "planner")

    assert handoff.addressed_finding_tasks() == {"F0001": ("T0002", "T0003")}


def test_parse_handoff_rejects_duplicate_addressed_finding(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        addressed="- F0001: T0002\n- F0001: T0003",
        extra_after=(
            "## Planned Tasks\n- T0002\n- T0003\n"
            "## Planning State\nplanning_complete = false\n"
        ),
    )

    with pytest.raises(HandoffError, match="lists F0001 more than once"):
        parse_handoff(path, "planner")


def test_parse_handoff_rejects_duplicate_addressing_task(tmp_path: Path) -> None:
    path = _write_handoff(
        tmp_path,
        role_name="planner",
        addressed="- F0001: T0002, T0002",
        extra_after=(
            "## Planned Tasks\n- T0002\n"
            "## Planning State\nplanning_complete = false\n"
        ),
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
        extra_after=(
            "## Planned Tasks\n- None\n"
            "## Planning State\nplanning_complete = false\n"
        ),
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

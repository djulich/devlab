from __future__ import annotations

from pathlib import Path

import pytest

from devlab.findings import FINDINGS_DIR, FileFindingTracker, FindingStatus


def _setup_findings_dir(root: Path) -> None:
    (root / FINDINGS_DIR).mkdir(parents=True)


def test_create_finding_writes_open_finding_file(tmp_path: Path) -> None:
    _setup_findings_dir(tmp_path)

    finding = FileFindingTracker(tmp_path).create(
        title="Missing E2E coverage",
        source="integrator",
        milestone="M1",
        body="# Missing E2E coverage\n",
        handoff="handoff.md",
    )

    assert finding.id == "F0001"
    assert finding.status == FindingStatus.OPEN
    assert finding.milestone == "M1"
    assert finding.path.exists()
    assert 'status = "open"' in finding.path.read_text()


def test_create_from_handoff_uses_open_issues_section(tmp_path: Path) -> None:
    _setup_findings_dir(tmp_path)
    handoff = tmp_path / "handoff.md"
    handoff.write_text(
        "# Handoff: integrator\n"
        "## Done\n- Ran checks.\n"
        "## Changed Artifacts\n- None\n"
        "## Open Issues\n- Missing frontend/API E2E coverage.\n"
        "## Next Session Hint\nPlan follow-up task.\n"
    )

    finding = FileFindingTracker(tmp_path).create_from_handoff(
        source="integrator",
        milestone="M2",
        handoff_path=handoff,
    )

    assert finding.id == "F0001"
    assert finding.source == "integrator"
    assert finding.milestone == "M2"
    assert finding.handoff == "handoff.md"
    assert "Missing frontend/API E2E coverage" in finding.body


def test_mark_planned_and_resolved_update_status(tmp_path: Path) -> None:
    _setup_findings_dir(tmp_path)
    tracker = FileFindingTracker(tmp_path)
    finding = tracker.create(title="Finding", source="integrator", milestone="M1", body="# Body\n")

    tracker.mark_planned(finding.id)
    assert tracker.get(finding.id).status == FindingStatus.PLANNED

    tracker.mark_resolved(finding.id)
    assert tracker.get(finding.id).status == FindingStatus.RESOLVED


def test_open_findings_returns_only_open_findings(tmp_path: Path) -> None:
    _setup_findings_dir(tmp_path)
    tracker = FileFindingTracker(tmp_path)
    open_finding = tracker.create(title="Open", source="integrator", milestone="M1", body="")
    planned_finding = tracker.create(title="Planned", source="integrator", milestone="M1", body="")
    tracker.mark_planned(planned_finding.id)

    assert [finding.id for finding in tracker.open_findings()] == [open_finding.id]


def test_planned_findings_for_milestone_filters_by_milestone(tmp_path: Path) -> None:
    _setup_findings_dir(tmp_path)
    tracker = FileFindingTracker(tmp_path)
    m1 = tracker.create(title="M1", source="integrator", milestone="M1", body="")
    m2 = tracker.create(title="M2", source="integrator", milestone="M2", body="")
    tracker.mark_planned(m1.id)
    tracker.mark_planned(m2.id)

    assert [finding.id for finding in tracker.planned_findings_for_milestone("M1")] == [m1.id]


def test_rejects_invalid_finding_status(tmp_path: Path) -> None:
    _setup_findings_dir(tmp_path)
    path = tmp_path / FINDINGS_DIR / "F0001_bad.md"
    path.write_text(
        "+++\n"
        'id = "F0001"\n'
        'title = "Bad"\n'
        'status = "bad"\n'
        'source = "integrator"\n'
        "+++\n\n"
        "# Bad\n"
    )

    with pytest.raises(ValueError, match="invalid finding status"):
        FileFindingTracker(tmp_path).list_findings()

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from scripts import release_check

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_dist_dir_creates_empty_directory(tmp_path: Path) -> None:
    dist = tmp_path / "nested" / "dist"

    assert release_check._prepare_dist_dir(dist) == dist
    assert dist.is_dir()


def test_prepare_dist_dir_rejects_existing_content(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "old.whl").write_text("stale")

    with pytest.raises(release_check.ReleaseCheckError, match="is not empty"):
        release_check._prepare_dist_dir(dist)


def test_verify_release_tag_requires_version_tag_and_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: dict[tuple[str, ...], str] = {
        ("git", "rev-list", "-n", "1", "refs/tags/v0.1.0"): "abc123",
        ("git", "rev-parse", "HEAD"): "abc123",
    }
    commands: list[tuple[str, ...]] = []

    def fake_run(command: list[str], **_kwargs: object) -> str:
        key = tuple(command)
        commands.append(key)
        return responses[key]

    monkeypatch.setattr(release_check, "_run", fake_run)

    release_check._verify_release_tag("v0.1.0", "0.1.0")

    assert commands == list(responses)


def test_verify_release_tag_rejects_mismatch_before_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_run(_command: list[str], **_kwargs: object) -> str:
        pytest.fail("git must not run for a mismatched tag")

    monkeypatch.setattr(release_check, "_run", unexpected_run)

    with pytest.raises(release_check.ReleaseCheckError, match="must match package version"):
        release_check._verify_release_tag("v0.2.0", "0.1.0")


def test_verify_release_tag_rejects_tag_for_another_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(("tagged-commit", "head-commit"))
    monkeypatch.setattr(release_check, "_run", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(release_check.ReleaseCheckError, match="does not resolve to HEAD"):
        release_check._verify_release_tag("v0.1.0", "0.1.0")


def test_write_checksums_uses_sorted_artifact_names(tmp_path: Path) -> None:
    wheel = tmp_path / "devlab-0.1.0-py3-none-any.whl"
    source = tmp_path / "devlab-0.1.0.tar.gz"
    wheel.write_bytes(b"wheel")
    source.write_bytes(b"source")

    checksum_path = release_check._write_checksums((wheel, source), tmp_path)

    expected = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted((wheel, source), key=lambda item: item.name)
    )
    assert checksum_path.read_text() == expected


def test_release_workflow_hands_verified_artifacts_to_draft_job() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text()

    build = workflow.index("  build-release:")
    verify = workflow.index("      - name: Build and verify release artifacts", build)
    upload = workflow.index("      - name: Store verified release artifacts", verify)
    draft = workflow.index("  draft-release:", upload)
    download = workflow.index("      - name: Download verified release artifacts", draft)
    create = workflow.index("      - name: Create draft GitHub Release", download)

    assert verify < upload < draft < download < create
    assert workflow.count("scripts/release_check.py") == 1
    assert "    needs: build-release\n" in workflow[draft:download]
    assert "    permissions:\n      contents: write\n" in workflow[draft:download]
    assert "          name: release-artifacts\n" in workflow[upload:draft]
    assert "          name: release-artifacts\n" in workflow[download:create]

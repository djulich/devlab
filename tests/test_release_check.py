from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from scripts import release_check

ROOT = Path(__file__).resolve().parents[1]


def test_run_reports_failure_without_captured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release_check.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1),
    )

    with pytest.raises(
        release_check.ReleaseCheckError,
        match="command failed with exit code 1: failing-command",
    ):
        release_check._run(["failing-command"])


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


def test_verify_index_metadata_uses_strict_twine_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = tmp_path / "devlab-0.1.0-py3-none-any.whl"
    source = tmp_path / "devlab-0.1.0.tar.gz"
    commands: list[list[str]] = []
    environments: list[dict[str, str] | None] = []

    def fake_run(command: list[str], *, env: dict[str, str] | None = None) -> str:
        commands.append(command)
        environments.append(env)
        return ""

    monkeypatch.setattr(release_check, "_run", fake_run)

    release_check._verify_index_metadata("/usr/bin/uv", wheel, source, {"RELEASE_CHECK": "1"})

    assert commands == [
        [
            "/usr/bin/uv",
            "tool",
            "run",
            "--from",
            f"twine=={release_check.TWINE_VERSION}",
            "twine",
            "check",
            "--strict",
            str(wheel),
            str(source),
        ]
    ]
    assert environments == [{"RELEASE_CHECK": "1"}]


def test_release_workflow_hands_verified_artifacts_to_consumers() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text()

    build = workflow.index("  build-release:")
    verify = workflow.index("      - name: Build and verify release artifacts", build)
    distributions = workflow.index("      - name: Store verified Python distributions", verify)
    checksums = workflow.index("      - name: Store release checksums", distributions)
    draft = workflow.index("  draft-release:", checksums)
    create = workflow.index("      - name: Create draft GitHub Release", draft)
    testpypi = workflow.index("  publish-testpypi:", create)

    assert verify < distributions < checksums < draft < create < testpypi
    assert workflow.count("scripts/release_check.py") == 1
    assert "          name: python-distributions\n" in workflow[distributions:checksums]
    assert "            dist/SHA256SUMS\n" not in workflow[distributions:checksums]
    assert "          name: release-checksums\n" in workflow[checksums:draft]

    draft_job = workflow[draft:testpypi]
    assert "    needs: build-release\n" in draft_job
    assert "    permissions:\n      contents: write\n" in draft_job
    assert "          name: python-distributions\n" in draft_job
    assert "          name: release-checksums\n" in draft_job

    testpypi_job = workflow[testpypi:]
    assert "    needs: build-release\n" in testpypi_job
    assert "      name: testpypi\n" in testpypi_job
    assert "    permissions:\n      id-token: write\n" in testpypi_job
    assert "          name: python-distributions\n" in testpypi_job
    assert "release-checksums" not in testpypi_job
    assert (
        "        uses: pypa/gh-action-pypi-publish@"
        "dc37677b2e1c63e2034f94d8a5b11f265b73ba33 # v1.14.2\n" in testpypi_job
    )
    assert "          attestations: true\n" in testpypi_job
    assert "          packages-dir: dist\n" in testpypi_job
    assert "          repository-url: https://test.pypi.org/legacy/\n" in testpypi_job

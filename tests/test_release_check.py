from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
import yaml
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


def test_verify_readme_links_rejects_repository_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "README.md").write_text(
        "[guide](docs/guide.md) [site](https://example.com/guide) [section](#usage)"
    )
    monkeypatch.setattr(release_check, "ROOT", tmp_path)

    with pytest.raises(release_check.ReleaseCheckError, match=r"docs/guide\.md"):
        release_check._verify_readme_links({"readme": "README.md"})


def test_verify_readme_links_accepts_absolute_urls_and_anchors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "README.md").write_text("[guide](https://example.com/guide) [section](#usage)")
    monkeypatch.setattr(release_check, "ROOT", tmp_path)

    release_check._verify_readme_links({"readme": "README.md"})


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
    workflow = yaml.load(
        (ROOT / ".github/workflows/release.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert workflow["permissions"] == {"contents": "read"}

    jobs = workflow["jobs"]
    assert workflow["on"] == {"push": {"tags": ["v*"]}}
    assert set(jobs) == {"build-release", "draft-release", "publish-testpypi", "publish-pypi"}

    build = jobs["build-release"]
    build_steps = {step["name"]: step for step in build["steps"]}
    verify = build_steps["Build and verify release artifacts"]
    assert "scripts/release_check.py" in verify["run"]

    distributions = build_steps["Store verified Python distributions"]
    assert distributions["with"]["name"] == "python-distributions"
    assert set(distributions["with"]["path"].splitlines()) == {
        "dist/*.whl",
        "dist/*.tar.gz",
    }
    assert distributions["with"]["if-no-files-found"] == "error"

    checksums = build_steps["Store release checksums"]
    assert checksums["with"] == {
        "name": "release-checksums",
        "path": "dist/SHA256SUMS",
        "if-no-files-found": "error",
    }

    draft = jobs["draft-release"]
    assert draft["needs"] == "build-release"
    assert draft["permissions"] == {"contents": "write"}
    draft_steps = {step["name"]: step for step in draft["steps"]}
    assert set(draft_steps) == {
        "Check out tagged commit for release metadata",
        "Download verified Python distributions",
        "Download release checksums",
        "Create draft GitHub Release",
    }
    checkout = draft_steps["Check out tagged commit for release metadata"]
    assert checkout["uses"] == ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
    assert checkout["with"] == {
        "fetch-depth": "0",
        "persist-credentials": "false",
    }
    assert draft_steps["Download verified Python distributions"]["with"] == {
        "name": "python-distributions",
        "path": "dist",
    }
    assert draft_steps["Download release checksums"]["with"] == {
        "name": "release-checksums",
        "path": "dist",
    }
    create_release = draft_steps["Create draft GitHub Release"]["run"]
    assert "gh release create" in create_release
    assert "--verify-tag" in create_release
    assert "--notes-from-tag" in create_release
    assert "--repo" not in create_release

    testpypi = jobs["publish-testpypi"]
    assert testpypi["needs"] == "build-release"
    assert testpypi["environment"] == {
        "name": "testpypi",
        "url": "https://test.pypi.org/p/devlab",
    }
    assert testpypi["permissions"] == {"id-token": "write"}
    testpypi_steps = {step["name"]: step for step in testpypi["steps"]}
    assert set(testpypi_steps) == {
        "Download verified Python distributions",
        "Publish distributions to TestPyPI",
    }
    assert testpypi_steps["Download verified Python distributions"]["with"] == {
        "name": "python-distributions",
        "path": "dist",
    }
    publish = testpypi_steps["Publish distributions to TestPyPI"]
    assert publish["uses"] == (
        "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
    )
    assert publish["with"] == {
        "attestations": "true",
        "packages-dir": "dist",
        "repository-url": "https://test.pypi.org/legacy/",
    }

    pypi = jobs["publish-pypi"]
    assert set(pypi["needs"]) == {"build-release", "draft-release", "publish-testpypi"}
    assert "if" not in pypi  # Preserve the default success gate for prerequisite jobs.
    assert pypi["environment"] == {
        "name": "pypi",
        "url": "https://pypi.org/p/devlab",
    }
    assert pypi["permissions"] == {"id-token": "write"}
    pypi_steps = pypi["steps"]
    assert pypi_steps == [
        {
            "name": "Download verified Python distributions",
            "uses": "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
            "with": {"name": "python-distributions", "path": "dist"},
        },
        {
            "name": "Publish distributions to PyPI",
            "uses": "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
            "with": {"attestations": "true", "packages-dir": "dist"},
        },
    ]

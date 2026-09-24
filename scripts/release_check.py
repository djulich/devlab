#!/usr/bin/env python3
"""Build and verify installable DevLab release artifacts."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NAME = "devlab"
EXPECTED_LICENSE = "Apache-2.0"
EXPECTED_PYTHON = ">=3.12"
EXPECTED_CLASSIFIERS = {
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Topic :: Software Development",
}
EXPECTED_URLS = {
    "Documentation": "https://github.com/djulich/devlab/blob/main/docs/README.md",
    "Release Notes": "https://github.com/djulich/devlab/releases",
    "Issues": "https://github.com/djulich/devlab/issues",
    "Source": "https://github.com/djulich/devlab",
}
TWINE_VERSION = "7.0.0"


class ReleaseCheckError(RuntimeError):
    """A release artifact does not satisfy the repository contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseCheckError(message)


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> str:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if result.returncode != 0:
        details = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part and part.strip()
        )
        suffix = f"\n{details}" if details else ""
        raise ReleaseCheckError(
            f"command failed with exit code {result.returncode}: {' '.join(command)}{suffix}"
        )
    return result.stdout.strip() if result.stdout else ""


def _git_status() -> str:
    return _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        capture=True,
    )


def _project_metadata() -> tuple[dict[str, Any], str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    _require(project["name"] == EXPECTED_NAME, "pyproject package name must be devlab")
    version = project["version"]
    _require(isinstance(version, str) and version, "pyproject version must be non-empty text")
    _require(project["requires-python"] == EXPECTED_PYTHON, "unexpected Python requirement")
    _require(project["license"] == EXPECTED_LICENSE, "unexpected license expression")
    _require(set(project["classifiers"]) == EXPECTED_CLASSIFIERS, "unexpected classifiers")
    _require(project["urls"] == EXPECTED_URLS, "unexpected project URLs")

    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = [package for package in lock["package"] if package.get("name") == EXPECTED_NAME]
    _require(len(locked) == 1, "uv.lock must contain exactly one devlab package")
    _require(locked[0].get("version") == version, "pyproject.toml and uv.lock versions disagree")
    return project, version


def _verify_readme_links(project: dict[str, Any]) -> None:
    _require(project["readme"] == "README.md", "project description must use README.md")
    readme = (ROOT / "README.md").read_text()
    for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", readme):
        target = match.group(1)
        if target.startswith("#"):
            continue
        parsed = urlsplit(target)
        _require(
            bool(parsed.scheme and parsed.netloc),
            f"README link must use an absolute URL for PyPI: {target}",
        )


def _artifact_paths(dist: Path) -> tuple[Path, Path]:
    wheels = list(dist.glob("*.whl"))
    sources = list(dist.glob("*.tar.gz"))
    _require(len(wheels) == 1, f"expected one wheel, found {len(wheels)}")
    _require(len(sources) == 1, f"expected one source distribution, found {len(sources)}")
    return wheels[0], sources[0]


def _prepare_dist_dir(dist: Path) -> Path:
    dist = dist.resolve()
    if dist.exists():
        _require(dist.is_dir(), f"artifact output path is not a directory: {dist}")
        _require(not any(dist.iterdir()), f"artifact output directory is not empty: {dist}")
    else:
        dist.mkdir(parents=True)
    return dist


def _verify_release_tag(tag: str, version: str) -> None:
    expected = f"v{version}"
    _require(tag == expected, f"release tag {tag!r} must match package version as {expected!r}")
    reference = f"refs/tags/{tag}"
    tagged_commit = _run(["git", "rev-list", "-n", "1", reference], capture=True)
    head = _run(["git", "rev-parse", "HEAD"], capture=True)
    _require(tagged_commit == head, f"release tag {tag!r} does not resolve to HEAD")


def _metadata_urls(message: email.message.Message) -> dict[str, str]:
    urls: dict[str, str] = {}
    for value in message.get_all("Project-URL", []):
        label, separator, url = value.partition(",")
        _require(bool(separator), f"invalid Project-URL metadata: {value!r}")
        urls[label.strip()] = url.strip()
    return urls


def _verify_wheel(wheel: Path, project: dict[str, Any], version: str) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        _require(len(metadata_paths) == 1, "wheel must contain exactly one METADATA file")
        message = email.parser.Parser().parsestr(archive.read(metadata_paths[0]).decode())
        _require(message["Name"] == project["name"], "wheel package name disagrees")
        _require(message["Version"] == version, "wheel version disagrees")
        _require(
            message["Requires-Python"] == project["requires-python"],
            "wheel Python requirement disagrees",
        )
        _require(message["License-Expression"] == project["license"], "wheel license disagrees")
        _require(
            set(message.get_all("Classifier", [])) == set(project["classifiers"]),
            "wheel classifiers disagree",
        )
        _require(_metadata_urls(message) == project["urls"], "wheel project URLs disagree")

        expected_package = {
            f"devlab/{path.relative_to(ROOT / 'src/devlab').as_posix()}"
            for path in (ROOT / "src/devlab").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        missing = sorted(expected_package - names)
        _require(not missing, "wheel is missing package files: " + ", ".join(missing))
        _require(
            any(name.endswith(".dist-info/licenses/LICENSE") for name in names),
            "wheel is missing LICENSE",
        )
        entry_points = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        _require(len(entry_points) == 1, "wheel must contain console entry-point metadata")
        _require(
            "devlab = devlab.cli:main" in archive.read(entry_points[0]).decode(),
            "wheel does not define the devlab console script",
        )
        for excluded in ("tests", "demos", "Makefile", "uv.lock", "scripts"):
            _require(not _contains(names, excluded), f"wheel unexpectedly contains {excluded}")


def _verify_source(source: Path) -> None:
    with tarfile.open(source, "r:gz") as archive:
        names = set(archive.getnames())
    roots = {name.split("/", 1)[0] for name in names}
    _require(len(roots) == 1, "source distribution must have one root directory")
    root = next(iter(roots))
    required = {
        f"{root}/LICENSE",
        f"{root}/Makefile",
        f"{root}/README.md",
        f"{root}/pyproject.toml",
        f"{root}/scripts/release_check.py",
        f"{root}/uv.lock",
    }
    required.update(
        f"{root}/{path.relative_to(ROOT).as_posix()}"
        for base in (ROOT / "src/devlab", ROOT / "tests")
        for path in base.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    missing = sorted(required - names)
    _require(not missing, "source distribution is missing files: " + ", ".join(missing))
    _require(not _contains(names, f"{root}/demos"), "source distribution contains demos")


def _contains(names: set[str], path: str) -> bool:
    return path in names or any(name.startswith(f"{path}/") for name in names)


def _verify_index_metadata(uv: str, wheel: Path, source: Path, env: dict[str, str]) -> None:
    # Twine's upload-oriented dependency tree does not belong in DevLab's lean
    # development environment; run a pinned release verifier in isolation instead.
    _run(
        [
            uv,
            "tool",
            "run",
            "--from",
            f"twine=={TWINE_VERSION}",
            "twine",
            "check",
            "--strict",
            str(wheel),
            str(source),
        ],
        env=env,
    )


def _verify_clean_install(
    uv: str, wheel: Path, temporary: Path, version: str, env: dict[str, str]
) -> None:
    environment = temporary / "installed"
    _run([uv, "venv", "--python", sys.executable, str(environment)], env=env)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    executable = environment / ("Scripts/devlab.exe" if os.name == "nt" else "bin/devlab")
    _run([uv, "pip", "install", "--python", str(python), str(wheel)], env=env)
    reported = _run([str(executable), "--version"], env=env, capture=True)
    _require(reported == f"devlab {version}", f"installed CLI reported {reported!r}")
    help_text = _run([str(executable), "--help"], env=env, capture=True)
    _require("usage: devlab" in help_text, "installed CLI help is unavailable")


def _write_checksums(paths: tuple[Path, ...], dist: Path) -> Path:
    checksum_path = dist / "SHA256SUMS"
    lines = []
    for path in sorted(paths, key=lambda item: item.name):
        with path.open("rb") as artifact:
            digest = hashlib.file_digest(artifact, "sha256").hexdigest()
        lines.append(f"{digest}  {path.name}\n")
    checksum_path.write_text("".join(lines))
    return checksum_path


def check_release(*, dist_dir: Path | None = None, expected_tag: str | None = None) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise ReleaseCheckError("uv is required for release verification")
    project, version = _project_metadata()
    _verify_readme_links(project)
    if expected_tag is not None:
        _verify_release_tag(expected_tag, version)
    with tempfile.TemporaryDirectory(prefix="devlab-release-check-") as directory:
        temporary = Path(directory)
        dist = _prepare_dist_dir(dist_dir if dist_dir is not None else temporary / "dist")
        env = {
            **os.environ,
            "UV_CACHE_DIR": str(temporary / "uv-cache"),
            "UV_TOOL_BIN_DIR": str(temporary / "uv-tool-bin"),
            "UV_TOOL_DIR": str(temporary / "uv-tools"),
        }
        _run([uv, "build", "--out-dir", str(dist)], env=env)
        wheel, source = _artifact_paths(dist)
        _verify_wheel(wheel, project, version)
        _verify_source(source)
        _verify_index_metadata(uv, wheel, source, env)
        _verify_clean_install(uv, wheel, temporary, version, env)
        if dist_dir is not None:
            _write_checksums((wheel, source), dist)
    suffix = f" in {dist}" if dist_dir is not None else ""
    print(f"Release artifacts verified for {EXPECTED_NAME} {version}{suffix}.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        type=Path,
        help=(
            "retain the verified wheel, source distribution, and checksums in this empty directory"
        ),
    )
    parser.add_argument(
        "--expected-tag",
        help="require this vX.Y.Z tag to match the package version and HEAD",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    before = _git_status()
    error: Exception | None = None
    try:
        check_release(dist_dir=args.dist_dir, expected_tag=args.expected_tag)
    except Exception as exc:  # report worktree mutation alongside the primary failure
        error = exc
    after = _git_status()
    if after != before:
        mutation = ReleaseCheckError("release verification changed the Git worktree")
        error = ReleaseCheckError(f"{error}; {mutation}") if error else mutation
    if error:
        print(f"release-check: FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

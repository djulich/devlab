from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path


def test_distribution_development_content_boundary(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "repository validation requires uv"
    root = Path(__file__).parents[1]
    environment = dict(os.environ)
    environment["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    subprocess.run(
        [uv, "build", "--out-dir", str(tmp_path)],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=True,
    )

    wheel = next(tmp_path.glob("*.whl"))
    source = next(tmp_path.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    with tarfile.open(source, "r:gz") as archive:
        source_names = set(archive.getnames())

    source_root = next(
        name for name in source_names if name.endswith("/pyproject.toml")
    ).removesuffix("/pyproject.toml")
    assert any(name.startswith("devlab/") for name in wheel_names)
    assert "devlab/resources/init/.gitignore" in wheel_names
    assert not _contains(wheel_names, "tests")
    assert not _contains(wheel_names, "demos")
    assert "Makefile" not in wheel_names
    assert "uv.lock" not in wheel_names

    assert _contains(source_names, f"{source_root}/src/devlab")
    assert _contains(source_names, f"{source_root}/tests")
    assert f"{source_root}/Makefile" in source_names
    assert f"{source_root}/uv.lock" in source_names
    assert not _contains(source_names, f"{source_root}/demos")


def _contains(names: set[str], path: str) -> bool:
    return path in names or any(name.startswith(f"{path}/") for name in names)

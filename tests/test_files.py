import stat
from pathlib import Path

import pytest

from devlab import _files


def test_atomic_write_text_replaces_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "state.toml"
    path.write_text("old")
    path.chmod(0o640)

    _files.atomic_write_text(path, "new")

    assert path.read_text() == "new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert list(tmp_path.glob(".state.toml.*.tmp")) == []


def test_atomic_write_text_preserves_existing_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.toml"
    path.write_text("old")

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        _files.atomic_write_text(path, "new")

    assert path.read_text() == "old"
    assert list(tmp_path.glob(".state.toml.*.tmp")) == []

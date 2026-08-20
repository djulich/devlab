from __future__ import annotations

from pathlib import Path

from devlab.dependency_diagnostics import (
    introduced_dependencies,
    snapshot_direct_dependencies,
)
from devlab.init import init_workspace


def test_detects_direct_additions_across_supported_manifests(tmp_path: Path) -> None:
    init_workspace(tmp_path, automatic_git=True)
    before = snapshot_direct_dependencies(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\n'
        'dependencies = ["httpx>=0.28"]\n\n'
        '[dependency-groups]\ndev = ["pytest>=8"]\n'
    )
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"react":"^19"},"devDependencies":{"vite":"^7"}}\n'
    )
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\n\n'
        '[dependencies]\nserde = { version = "1", features = ["derive"] }\n'
    )
    (tmp_path / "go.mod").write_text(
        "module example.invalid/app\n\ngo 1.25\n\nrequire (\n\tgithub.com/google/uuid v1.6.0\n)\n"
    )

    additions = introduced_dependencies(before, snapshot_direct_dependencies(tmp_path))

    assert {(item.ecosystem, item.name, item.scope) for item in additions} == {
        ("python", "httpx", "project"),
        ("python", "pytest", "group:dev"),
        ("node", "react", "dependencies"),
        ("node", "vite", "devDependencies"),
        ("rust", "serde", "dependencies"),
        ("go", "github.com/google/uuid", "require"),
    }


def test_ignores_existing_dependencies_and_constraint_changes(tmp_path: Path) -> None:
    init_workspace(tmp_path, automatic_git=True)
    manifest = tmp_path / "package.json"
    manifest.write_text('{"dependencies":{"react":"^18"}}\n')
    before = snapshot_direct_dependencies(tmp_path)

    manifest.write_text('{"dependencies":{"react":"^19"}}\n')

    assert introduced_dependencies(before, snapshot_direct_dependencies(tmp_path)) == ()


def test_ignores_lockfiles_and_malformed_manifests(tmp_path: Path) -> None:
    init_workspace(tmp_path, automatic_git=True)
    before = snapshot_direct_dependencies(tmp_path)
    (tmp_path / "package-lock.json").write_text('{"packages":{"node_modules/x":{}}}\n')
    (tmp_path / "package.json").write_text("not json\n")

    assert introduced_dependencies(before, snapshot_direct_dependencies(tmp_path)) == ()

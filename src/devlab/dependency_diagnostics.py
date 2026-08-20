"""Advisory detection of direct dependency introductions by role sessions."""

from __future__ import annotations

import dataclasses
import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from devlab.git import git_ls_files


@dataclasses.dataclass(frozen=True)
class DirectDependency:
    ecosystem: str
    manifest: str
    scope: str
    name: str
    constraint: str


@dataclasses.dataclass(frozen=True)
class DependencyIntroduction:
    ecosystem: str
    manifest: str
    scope: str
    name: str
    constraint: str


DependencySnapshot = dict[tuple[str, str, str, str], DirectDependency]

_PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_GO_REQUIRE = re.compile(r"^\s*([^\s/]+(?:/[^\s]+)*)\s+([^\s]+)")
_MANIFEST_NAMES = {"Cargo.toml", "go.mod", "package.json", "pyproject.toml"}


def snapshot_direct_dependencies(root: Path) -> DependencySnapshot:
    """Read supported manifests without resolving or installing dependencies."""
    dependencies: DependencySnapshot = {}
    paths = _manifest_paths(root)
    for relative in paths:
        if Path(relative).name not in _MANIFEST_NAMES:
            continue
        path = root / relative
        if not path.is_file():
            continue
        try:
            parsed = _parse_manifest(path, relative)
        except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
            continue
        for dependency in parsed:
            key = (
                dependency.ecosystem,
                dependency.manifest,
                dependency.scope,
                dependency.name,
            )
            dependencies[key] = dependency
    return dependencies


def _manifest_paths(root: Path) -> list[str]:
    paths = git_ls_files(
        root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    )
    return sorted(path for path in paths if Path(path).name in _MANIFEST_NAMES)


def introduced_dependencies(
    before: DependencySnapshot,
    after: DependencySnapshot,
) -> tuple[DependencyIntroduction, ...]:
    """Return direct dependencies absent from the pre-session snapshot."""
    return tuple(
        DependencyIntroduction(
            ecosystem=item.ecosystem,
            manifest=item.manifest,
            scope=item.scope,
            name=item.name,
            constraint=item.constraint,
        )
        for key, item in sorted(after.items())
        if key not in before
    )


def _parse_manifest(path: Path, relative: str) -> list[DirectDependency]:
    if path.name == "package.json":
        return _parse_package_json(path, relative)
    if path.name == "go.mod":
        return _parse_go_mod(path, relative)
    data = tomllib.loads(path.read_text())
    if path.name == "pyproject.toml":
        return _parse_pyproject(data, relative)
    return _parse_cargo(data, relative)


def _parse_package_json(path: Path, relative: str) -> list[DirectDependency]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return []
    result: list[DirectDependency] = []
    for scope in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        values = data.get(scope)
        if not isinstance(values, dict):
            continue
        for name, constraint in values.items():
            if isinstance(name, str) and isinstance(constraint, str):
                result.append(DirectDependency("node", relative, scope, name, constraint))
    return result


def _parse_pyproject(data: dict[str, object], relative: str) -> list[DirectDependency]:
    result: list[DirectDependency] = []
    project = _mapping(data.get("project"))
    result.extend(_pep508_dependencies(project.get("dependencies"), relative, "project"))
    optional = _mapping(project.get("optional-dependencies"))
    for group, values in optional.items():
        result.extend(_pep508_dependencies(values, relative, f"optional:{group}"))
    for group, values in _mapping(data.get("dependency-groups")).items():
        result.extend(_pep508_dependencies(values, relative, f"group:{group}"))
    poetry = _mapping(_mapping(data.get("tool")).get("poetry"))
    for scope, values in (
        ("poetry", poetry.get("dependencies")),
        ("poetry:dev", poetry.get("dev-dependencies")),
    ):
        for name, constraint in _mapping(values).items():
            if name.lower() == "python":
                continue
            result.append(
                DirectDependency("python", relative, scope, name.lower(), _constraint(constraint))
            )
    return result


def _pep508_dependencies(value: object, relative: str, scope: str) -> list[DirectDependency]:
    if not isinstance(value, list):
        return []
    result: list[DirectDependency] = []
    for specification in value:
        if not isinstance(specification, str):
            continue
        match = _PEP508_NAME.match(specification)
        if match:
            name = match.group(1).lower().replace("_", "-")
            result.append(DirectDependency("python", relative, scope, name, specification))
    return result


def _parse_cargo(data: dict[str, object], relative: str) -> list[DirectDependency]:
    result: list[DirectDependency] = []
    for scope in ("dependencies", "dev-dependencies", "build-dependencies"):
        result.extend(_cargo_table(_mapping(data.get(scope)), relative, scope))
    for target, target_data in _mapping(data.get("target")).items():
        for scope in ("dependencies", "dev-dependencies", "build-dependencies"):
            values = _mapping(_mapping(target_data).get(scope))
            result.extend(_cargo_table(values, relative, f"target:{target}:{scope}"))
    return result


def _cargo_table(
    values: Mapping[str, object], relative: str, scope: str
) -> list[DirectDependency]:
    return [
        DirectDependency("rust", relative, scope, name, _constraint(constraint))
        for name, constraint in values.items()
    ]


def _parse_go_mod(path: Path, relative: str) -> list[DirectDependency]:
    result: list[DirectDependency] = []
    in_block = False
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if line == "require (":
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        candidate = (
            line
            if in_block
            else line.removeprefix("require ")
            if line.startswith("require ")
            else ""
        )
        match = _GO_REQUIRE.match(candidate)
        if match:
            result.append(
                DirectDependency("go", relative, "require", match.group(1), match.group(2))
            )
    return result


def _mapping(value: object) -> Mapping[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _constraint(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)

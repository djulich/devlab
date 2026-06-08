from __future__ import annotations

import re
import shutil
from pathlib import Path

from devlab.doctor_common import DoctorProblem, display_path

DEPLOYMENT_SPEC_DIR = ".devlab/specs/deployment"
DEPLOYMENT_PLACEHOLDER_SENTINEL = "<!-- devlab:placeholder -->"
_DEPLOYMENT_TOOL_EXECUTABLES = {
    "podman": "podman",
    "docker": "docker",
    "docker compose": "docker",
    "buildah": "buildah",
    "nerdctl": "nerdctl",
    "kind": "kind",
    "kubectl": "kubectl",
    "kubeconform": "kubeconform",
    "rpmbuild": "rpmbuild",
    "rpmlint": "rpmlint",
    "systemd-analyze": "systemd-analyze",
}
_CONTAINER_TOOL_EXECUTABLES = ("podman", "docker", "buildah", "nerdctl")
_CONTAINER_FAMILY_RE = re.compile(
    r"\b(?:container(?:ized|\s+(?:image|runtime|deployment|artifact)s?)?|"
    r"oci(?:-compatible)?\s+image)\b"
)
_PRODUCTION_CLAIM_RE = re.compile(
    r"\b(?:deploy(?:ment|ing)?\s+to\s+production|production\s+deploy(?:ment|ing)?)\b"
)
_PRODUCTION_BOUNDARY_RE = re.compile(
    r"\b(?:production(?:\s+deployment)?\s+(?:is\s+)?out\s+of\s+scope|"
    r"production(?:\s+deployment)?\s+(?:is\s+)?(?:documentation|documented)-only|"
    r"(?:documentation|documented)-only|"
    r"no\s+production\s+deploy(?:ment|ing)?|"
    r"(?:is\s+)?not\s+(?:a\s+)?production\s+deploy(?:ment|ing)?|"
    r"future\s+(?:explicit\s+)?configuration|requires\s+explicit)\b"
)


def check_deployment_spec(root: Path) -> list[DoctorProblem]:
    spec_root = root / DEPLOYMENT_SPEC_DIR
    if not spec_root.exists():
        return []
    spec_files = sorted(spec_root.rglob("*.md"))
    if not spec_files:
        return [
            DoctorProblem(
                DEPLOYMENT_SPEC_DIR,
                "deployment spec directory has no Markdown files",
            )
        ]

    active_specs: list[tuple[Path, str]] = []
    empty_specs: list[Path] = []
    for path in spec_files:
        text = path.read_text()
        if DEPLOYMENT_PLACEHOLDER_SENTINEL in text:
            continue
        if text.strip():
            active_specs.append((path, text))
        else:
            empty_specs.append(path)

    if not active_specs:
        return [
            DoctorProblem(
                display_path(path, root),
                "deployment spec is empty; keep the placeholder template or describe "
                "deployment requirements",
            )
            for path in empty_specs
        ]

    problems: list[DoctorProblem] = []
    for path, text in active_specs:
        path_display = display_path(path, root)
        lower_text = text.lower()
        if _PRODUCTION_CLAIM_RE.search(lower_text) and not _PRODUCTION_BOUNDARY_RE.search(
            lower_text
        ):
            problems.append(
                DoctorProblem(
                    path_display,
                    "deployment spec mentions production without explicit out-of-scope, "
                    "documentation-only, or future-configuration boundary",
                )
            )
        uses_container_alternative = _uses_container_runtime_alternative(lower_text)
        mentioned_tools = _mentioned_deployment_tools(lower_text)
        if uses_container_alternative and all(
            shutil.which(executable) is None for executable in ("docker", "podman")
        ):
            problems.append(
                DoctorProblem(
                    path_display,
                    "deployment spec mentions Docker or Podman but neither 'docker' nor "
                    "'podman' is on PATH; install or configure one in the user/CI "
                    "environment before claiming verification",
                )
            )
        if (
            _CONTAINER_FAMILY_RE.search(lower_text)
            and not any(label in _CONTAINER_TOOL_EXECUTABLES for label, _ in mentioned_tools)
            and all(shutil.which(executable) is None for executable in _CONTAINER_TOOL_EXECUTABLES)
        ):
            problems.append(
                DoctorProblem(
                    path_display,
                    "deployment spec describes container artifacts but no common container "
                    "tool ('podman', 'docker', 'buildah', or 'nerdctl') is on PATH; "
                    "install or configure one in the user/CI environment before claiming "
                    "container verification",
                )
            )
        for label, executable in mentioned_tools:
            if uses_container_alternative and label in {"docker", "podman"}:
                continue
            if shutil.which(executable) is None:
                problems.append(
                    DoctorProblem(
                        path_display,
                        f"deployment spec mentions {label} but {executable!r} is not on PATH; "
                        "install or configure it in the user/CI environment before "
                        "claiming verification",
                    )
                )
    return problems


def _uses_container_runtime_alternative(lower_text: str) -> bool:
    pattern = r"\b(?:docker\s*(?:/|or)\s*podman|podman\s*(?:/|or)\s*docker)\b"
    return bool(re.search(pattern, lower_text))


def _mentioned_deployment_tools(lower_text: str) -> list[tuple[str, str]]:
    mentioned: list[tuple[str, str]] = []
    seen: set[str] = set()
    sorted_tools = sorted(_DEPLOYMENT_TOOL_EXECUTABLES.items(), key=lambda item: -len(item[0]))
    for label, executable in sorted_tools:
        if _tool_label_mentioned(lower_text, label) and executable not in seen:
            mentioned.append((label, executable))
            seen.add(executable)
    return mentioned


def _tool_label_mentioned(lower_text: str, label: str) -> bool:
    pattern = re.escape(label).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<![a-z0-9-]){pattern}(?![a-z0-9-])", lower_text))

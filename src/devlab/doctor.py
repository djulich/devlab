from __future__ import annotations

import tomllib
from pathlib import Path

from devlab.doctor_agent_config import check_agents_config
from devlab.doctor_common import DoctorProblem
from devlab.doctor_deployment import check_deployment_spec
from devlab.doctor_project_knowledge import check_project_knowledge
from devlab.doctor_workflow_state import (
    check_clarifications,
    check_git_worktree,
    check_milestones,
    check_research_resume_state,
    check_task_contracts,
    check_task_domains,
    check_workflow_state,
)
from devlab.prerequisites import (
    MAX_PREREQUISITE_GUIDE_CHARS,
    prerequisite_guide_reference,
    read_prerequisite_guide,
)
from devlab.profiles import load_profiles
from devlab.prompt_context import RolePromptContext, build_prompt_context_report
from devlab.workspace import Workspace, WorkspaceSnapshot


def check_workspace(root: Path) -> list[DoctorProblem]:
    problems: list[DoctorProblem] = []
    problems.extend(check_git_worktree(root))
    workflow_problems = check_workflow_state(root)
    problems.extend(workflow_problems)
    agent_problems = check_agents_config(root)
    problems.extend(agent_problems)
    snapshot = Workspace(root).snapshot
    if not agent_problems and not workflow_problems:
        problems.extend(_check_prompt_context_sizes(snapshot))
    problems.extend(check_clarifications(root))
    problems.extend(check_research_resume_state(root))
    problems.extend(check_milestones(root, snapshot))
    problems.extend(check_task_domains(snapshot))
    problems.extend(check_task_contracts(snapshot))
    problems.extend(_check_prerequisite_guides(root))
    problems.extend(check_deployment_spec(root))
    problems.extend(check_project_knowledge(root))
    return problems


def format_doctor_report(problems: list[DoctorProblem]) -> str:
    if not problems:
        return "DevLab doctor: OK"
    lines = [f"DevLab doctor: {len(problems)} problem(s)"]
    lines.extend(f"- {problem.path}: {problem.message}" for problem in problems)
    return "\n".join(lines)


def _check_prompt_context_sizes(snapshot: WorkspaceSnapshot) -> list[DoctorProblem]:
    try:
        report = build_prompt_context_report(snapshot)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
        return [DoctorProblem(".devlab", f"could not build prompt context report: {exc}")]
    problems: list[DoctorProblem] = []
    for role in report.roles:
        if role.status != "ok":
            problems.append(_prompt_context_problem(role))
    return problems


def _prompt_context_problem(role: RolePromptContext) -> DoctorProblem:
    total = _format_count(role.total.estimated_tokens)
    if role.status == "critical":
        threshold = _format_count(role.thresholds.critical_tokens)
        return DoctorProblem(
            ".devlab",
            f"{role.role_name} prompt context is critical: ~{total} tokens exceeds "
            f"critical threshold {threshold}",
        )
    threshold = _format_count(role.thresholds.warning_tokens)
    return DoctorProblem(
        ".devlab",
        f"{role.role_name} prompt context warning: ~{total} tokens exceeds "
        f"warning threshold {threshold}",
    )


def _format_count(value: int) -> str:
    return f"{value:,}"


def _check_prerequisite_guides(root: Path) -> list[DoctorProblem]:
    try:
        profiles = load_profiles(root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return [DoctorProblem(".devlab/config/profiles", str(exc))]
    problems: list[DoctorProblem] = []
    for profile in profiles.values():
        for prerequisite in profile.prerequisites:
            if not prerequisite.guide:
                continue
            try:
                reference = prerequisite_guide_reference(root, prerequisite)
                guide_text = read_prerequisite_guide(root, prerequisite)
            except (OSError, ValueError) as exc:
                problems.append(
                    DoctorProblem(
                        prerequisite.guide,
                        f"{prerequisite.reference} resolution guide is invalid: {exc}",
                        blocks=frozenset(),
                    )
                )
                continue
            if (
                reference is not None
                and guide_text is not None
                and len(guide_text) > MAX_PREREQUISITE_GUIDE_CHARS
            ):
                problems.append(
                    DoctorProblem(
                        prerequisite.guide,
                        f"{prerequisite.reference} resolution guide has {len(guide_text)} "
                        f"characters; limit focused guides to {MAX_PREREQUISITE_GUIDE_CHARS} "
                        "characters by using a dedicated file or Markdown heading reference",
                        blocks=frozenset(),
                    )
                )
            if (
                reference is not None
                and not reference.heading
                and not _is_dedicated_prerequisite_guide(root, reference.path)
            ):
                problems.append(
                    DoctorProblem(
                        prerequisite.guide,
                        f"{prerequisite.reference} whole-file resolution guide must be under "
                        ".devlab/config/prerequisites/; use a dedicated file or add a "
                        "Markdown heading reference",
                        blocks=frozenset(),
                    )
                )
    return problems


def _is_dedicated_prerequisite_guide(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return relative.parts[:3] == (".devlab", "config", "prerequisites")

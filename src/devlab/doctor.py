from __future__ import annotations

import tomllib
from pathlib import Path

from devlab.doctor_agent_config import check_agents_config
from devlab.doctor_common import DoctorProblem
from devlab.doctor_deployment import check_deployment_spec
from devlab.doctor_project_knowledge import check_project_knowledge
from devlab.doctor_workflow_state import check_git_worktree, check_milestones, check_task_domains
from devlab.prompt_context import RolePromptContext, build_prompt_context_report
from devlab.workspace import Workspace, WorkspaceSnapshot


def check_workspace(root: Path) -> list[DoctorProblem]:
    problems: list[DoctorProblem] = []
    problems.extend(check_git_worktree(root))
    agent_problems = check_agents_config(root)
    problems.extend(agent_problems)
    snapshot = Workspace(root).snapshot
    if not agent_problems:
        problems.extend(_check_prompt_context_sizes(snapshot))
    problems.extend(check_milestones(root, snapshot))
    problems.extend(check_task_domains(snapshot))
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

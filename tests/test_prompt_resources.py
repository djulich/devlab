from __future__ import annotations

from devlab.prompt_resources import read_prompt_resource


def test_reads_packaged_conventions() -> None:
    assert "# Conventions" in read_prompt_resource("conventions.md")


def test_task_template_inherits_profile_validation_by_default() -> None:
    conventions = read_prompt_resource("conventions.md")
    task_template = conventions.split("## Task Template", 1)[1].split("## Finding Template", 1)[0]

    assert "validation = []" not in task_template.split("Dependencies are task IDs", 1)[0]
    assert "Omit `validation` by default" in task_template


def test_planner_prompt_reserves_empty_validation_for_deliberate_suppression() -> None:
    planner = read_prompt_resource("role-planner.md")

    assert "do not copy it as task boilerplate" in planner


def test_role_prompts_require_validation_to_cross_claimed_boundaries() -> None:
    conventions = read_prompt_resource("conventions.md")
    planner = read_prompt_resource("role-planner.md")
    reviewer = read_prompt_resource("role-reviewer.md")
    integrator = read_prompt_resource("role-integrator.md")

    assert "cross the same boundary" in conventions
    assert "Match validation to the boundary" in planner
    assert "Validation crosses every boundary" in reviewer
    assert "crosses the same" in integrator


def test_reads_packaged_role_prompt() -> None:
    assert "# Role: Developer" in read_prompt_resource("role-developer.md")

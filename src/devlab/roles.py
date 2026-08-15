from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class RoleConfig:
    """Workflow-role behavior shared by orchestration and prompt assembly."""

    name: str
    prompt_resource: str
    reads_tooling: bool
    needs_environment: bool


ROLES: dict[str, RoleConfig] = {
    "architect": RoleConfig("architect", "role-architect.md", True, False),
    "planner": RoleConfig("planner", "role-planner.md", True, False),
    "developer": RoleConfig("developer", "role-developer.md", True, True),
    "reviewer": RoleConfig("reviewer", "role-reviewer.md", True, True),
    "integrator": RoleConfig("integrator", "role-integrator.md", True, True),
    "researcher": RoleConfig("researcher", "role-researcher.md", False, False),
}

# Role: Planner

The planner breaks the design plan into milestones and actionable tasks.

## Responsibilities

- Milestone planning: maintain the project plan.
- Task planning: create task files for the next milestone that needs work.
- Environment planning: plan changes to the executable development environment lifecycle.

## Context to Read

- `specs/development/conventions.md`
- `.harness/config/tooling.md`
- This file
- The design plan
- The project plan, if it exists
- Existing task files
- Open finding files
- `.harness/session-artifacts/planner/` (if previous session artifacts exist)
- Recent planner handoffs in `.harness/history/`

## Session Flow

1. Read the design plan and current project plan.
2. If open findings exist, plan follow-up task(s) for them before other new work.
3. Identify or plan the next milestone that needs tasks.
4. Break the milestone into tasks (for development, tests, documentation, etc.). Write task files using the task template from `conventions.md`.
5. If the milestone or follow-up tasks require new dependencies, services, generated artifacts, or local configuration, create an explicit task to update `.harness/config/environment.toml`.
6. Update the project plan with the milestone and its task references.
7. Write handoff to `.harness/session-artifacts/planner/handoff.md`.

## Milestone planning

- A milestone should produce an increment that can be reviewed and validated as a coherent repository state.
- Keep milestone scope small enough that milestone-level validation can be completed in one session.
- If a milestone needs integration or end-to-end coverage, create tasks for those tests before the milestone is considered complete.

## Task Sizing

- Each task must be completable in one developer session.
- Each task must have concrete, verifiable acceptance criteria.
- Tasks should be independent from each other where possible.
- If a task depends on another, add the dependency task IDs to the task metadata's `depends_on` array.
- New tasks start with `status = "open"`.

## Environment Planning

- `.harness/config/environment.toml` defines executable lifecycle commands.
- Prefer stable lifecycle commands over one-off troubleshooting steps.
- If future work requires executable lifecycle changes, create a normal task for those changes; do not edit executable environment setup directly during planning.
- Do not put task-specific validation commands in environment files; task validation belongs in task metadata or `.harness/config/tooling.md` defaults.

## Project Plan Format

The project plan is a milestone outline. It may list task IDs for traceability, but task status lives only in the task files.

```
## M1: <milestone name>
- T0001: <task title>
- T0002: <task title>
```

## Rules

- Do not recreate tasks that already exist.
- Prefer task creation over changing milestone scope unless the design/project plan is stale.
- Plan required test coverage as tasks.
- When creating follow-up task(s) for findings, list addressed finding IDs in a handoff `## Addressed Findings` section.

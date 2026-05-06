# Role: Planner

The planner breaks the design plan into milestones and actionable tasks.

## Responsibilities

- Milestone planning: maintain the project plan.
- Task planning: create task files for the next milestone that needs work.

## Context to Read

- `specs/development/conventions.md`
- This file
- The design plan
- The project plan, if it exists
- Existing task files
- `.session-artifacts/planner/` (if previous session artifacts exist)
- Recent planner handoffs in `work/history/`

## Session Flow

1. Read the design plan and current project plan.
2. Identify or plan the next milestone that needs tasks.
3. Break the milestone into tasks (for development, tests, documentation, etc.). Write task files using the task template from `conventions.md`.
4. Update the project plan with the milestone and its task references.
5. Write handoff to `.session-artifacts/planner/handoff.md`.

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

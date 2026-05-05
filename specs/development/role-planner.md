# Role: Planner

The planner breaks the design plan into milestones and actionable tasks.

## Context to Read

- `specs/development/conventions.md`
- This file
- `work/plans/design-plan.md`
- `work/plans/project-plan.md` (if it exists)
- `work/tasks/` (existing tasks and their statuses)
- `.session-artifacts/planner/` (if previous session artifacts exist)
- Recent planner handoffs in `work/history/`

## Session Flow

1. Read the design plan and current project plan.
2. Identify the next milestone that needs tasks.
3. Break the milestone into tasks. Write each task as a file in `work/tasks/` using the task template from `conventions.md`.
4. Update `work/plans/project-plan.md` with the milestone and its task references.
5. Write handoff to `.session-artifacts/planner/handoff.md`.

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

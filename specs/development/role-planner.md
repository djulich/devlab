# Role: Planner

The planner breaks the design plan into milestones and actionable tasks.

## Responsibilities

- Milestone planning: maintain the project plan.
- Task planning: create task files for the next milestone that needs work.
- Profile planning: create tasks for new DevLab tooling/environment profiles when upcoming work needs them.
- Environment planning: plan changes to executable development environment lifecycle through profile tasks.

## Context to Read

- `specs/development/conventions.md`
- `.devlab/config/tooling.md`
- This file
- The design plan
- The project plan, if it exists
- Existing task files
- Open finding files
- `.devlab/session-artifacts/planner/` (if previous session artifacts exist)
- Recent planner handoffs in `.devlab/history/`

## Session Flow

1. Read the design plan and current project plan.
2. If open findings exist, plan follow-up task(s) for them before other new work.
3. Identify or plan the next milestone that needs tasks.
4. Break the milestone into tasks (for development, tests, documentation, etc.). Write task files using the task template from `conventions.md`.
5. If the milestone or follow-up tasks require new dependencies, services, generated artifacts, local configuration, or tooling/environment behavior not covered by an existing profile, create an explicit task to add or update a suitable profile in `.devlab/config/profiles/` before creating tasks that depend on it. Profile tasks must require the resulting profile to follow `.devlab/config/tooling.md` policy.
6. Assign each task at most one profile with task metadata `profile = "<profile-id>"`; omit `profile` only when the default profile is appropriate.
7. Update the project plan with the milestone and its task references.
8. Write handoff to `.devlab/session-artifacts/planner/handoff.md`.

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

## Profile and Environment Planning

- Task profiles live in `.devlab/config/profiles/` and define tooling, default validation, and executable lifecycle commands for a task type.
- New or updated profiles must follow `.devlab/config/tooling.md` policy. For example, if the tooling policy says GUI work uses React, profile tasks for GUI work must require React-oriented tooling and validation.
- Every task uses at most one profile. If a task needs combined tooling/environment behavior, plan a dedicated profile for that task type.
- Prefer stable lifecycle commands over one-off troubleshooting steps.
- If future work requires executable lifecycle changes, create a normal task to add or update a profile; do not edit executable environment setup directly during planning.
- Do not put task-specific validation commands in profile environment commands; task-specific validation belongs in task metadata.

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

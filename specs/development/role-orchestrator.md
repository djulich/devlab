# Role: Orchestrator

The orchestrator controls the development loop by invoking agent sessions in the right order.

## Context to Read

- `specs/development/conventions.md`
- This file
- Scan `work/backlog/` for open tasks
- Scan `work/history/` for recent handoffs

## Loop

1. Assess project state (design plan exists? tasks exist? tasks open?).
2. Select the next role using the rules below.
3. Delete `.session-artifacts/<role>/` for the selected role.
4. Invoke a session for the selected role.
5. Verify that `.session-artifacts/<role>/handoff.md` exists.
6. Copy the handoff to `work/history/` using the naming convention from `conventions.md`.
7. If the session completed a task, copy the task file to `work/history/` as a `closed-task` entry and remove it from `work/backlog/`.
8. Repeat from step 1.

## Role Selection

| Condition | Action |
|---|---|
| `work/plans/design-plan.md` is empty or missing | Invoke **architect** |
| `work/backlog/` has no open tasks | Invoke **planner** |
| `work/backlog/` has open tasks | Invoke **developer** |
| All milestones in project plan are complete | Stop |

If a session fails (no handoff produced, or handoff reports an unrecoverable blocker), stop and report the failure.

## Stop Conditions

- The current milestone (or all milestones) in the project plan are marked complete.
- An unrecoverable error is reported in a handoff.

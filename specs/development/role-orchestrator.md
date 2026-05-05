# Role: Orchestrator

The orchestrator controls the development loop by invoking agent sessions in the right order.

## Context to Read

- `specs/development/conventions.md`
- This file
- Scan `work/tasks/` for task state
- Scan `work/history/` for recent handoffs

## Loop

1. Assess project state (design plan exists? tasks exist? tasks open? tasks awaiting review?).
2. Select the next role using the rules below.
3. Delete `.session-artifacts/<role>/` for the selected role.
4. Invoke a session for the selected role.
5. Verify that `.session-artifacts/<role>/handoff.md` exists, is non-empty, follows the handoff template, and does not report an unrecoverable issue.
6. Copy the handoff to `work/history/` using the naming convention from `conventions.md`.
7. If a developer completed a task, set the task status to `in_review`.
8. If a reviewer approved a task, set the task status to `closed`; if rejected, set it to `changes_requested`.
9. Repeat from step 1.

## Role Selection

| Condition | Action |
|---|---|
| `work/plans/design-plan.md` is empty or missing | Invoke **architect** |
| Any task has `status = "in_review"` | Invoke **reviewer** |
| Any task with `status = "open"` or `status = "changes_requested"` has all dependencies closed | Invoke **developer** |
| No active tasks exist and milestones remain to plan | Invoke **planner** |
| All tasks are closed | Stop |
| Remaining development tasks are blocked by dependencies | Stop and report blockage |

If a session fails (no handoff produced, or handoff reports an unrecoverable blocker), stop and report the failure.

## Stop Conditions

- All task files in `work/tasks/` have `status = "closed"`.
- An unrecoverable error is reported in a handoff.
- No development task is eligible because all remaining development tasks depend on tasks that are not closed.

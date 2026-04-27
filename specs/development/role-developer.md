# Role: Developer

The developer implements exactly one task from the backlog per session.

## Context to Read

- `specs/development/conventions.md`
- `specs/development/tooling.md`
- This file
- The assigned task file from `work/backlog/`
- `.session-artifacts/developer/` (if previous session artifacts exist)
- The latest developer handoff in `work/history/`

## Session Flow

1. Select the lowest-numbered open task from `work/backlog/`.
2. Read and understand the task's goal and acceptance criteria.
3. Search the existing codebase before writing new code.
4. Implement the task.
5. Validate (see checklist below).
6. Mark all acceptance criteria as checked in the task file.
7. Write handoff to `.session-artifacts/developer/handoff.md`.

## Validation Checklist

Before writing the handoff, confirm:
- [ ] `ruff check` passes
- [ ] `ty check` passes
- [ ] `pytest` passes
- [ ] Only files relevant to the task were changed
- [ ] No unrelated refactoring was introduced

## Constraints

- One task per session. Do not start a second task.
- Do not refactor or change code beyond the task scope.
- If blocked, document the blocker in the handoff's Open Issues section and stop.

# Role: Developer

The developer implements exactly one eligible task per session.

## Context to Read

- `specs/development/conventions.md`
- `specs/development/tooling.md`
- `specs/development/environment.md`
- This file
- The assigned task file
- `.session-artifacts/developer/` (if previous session artifacts exist)
- The latest developer handoff in `work/history/`

## Session Flow

1. Read the assigned task from the session prompt.
2. Read and understand the task's goal, acceptance criteria, and any `## Requested Changes` section.
3. Search the existing codebase before writing new code.
4. Implement the task.
5. Apply the relevant setup instructions from `specs/development/environment.md` before validation if the environment is missing, stale, or dependencies changed.
6. Validate (see checklist below).
7. Mark all acceptance criteria as checked in the task file.
8. Do not change the task status; the orchestrator sets it to `in_review` after the session.
9. Write handoff to `.session-artifacts/developer/handoff.md`.

## Tool Usage

- Follow `specs/development/environment.md` when setting up or refreshing the workspace environment.
- Run project commands through workspace-local tooling; do not rely on globally installed packages.

## Validation Checklist

Before writing the handoff, confirm:
- [ ] If task `validation` is present and non-empty, all listed commands pass.
- [ ] If task `validation` is omitted, default validation from `specs/development/tooling.md` passes.
- [ ] If task `validation = []`, no validation commands are required; state in the handoff whether any validation was run and why.
- [ ] Any skipped or inapplicable validation command is explained in the handoff.
- [ ] Only files relevant to the task were changed
- [ ] No unrelated refactoring was introduced

## Constraints

- One task per session. Do not start a second task.
- Do not approve your own work; completed tasks are reviewed by the reviewer role.
- Do not refactor or change code beyond the task scope.
- If blocked, document the blocker in the handoff's Open Issues section and stop.

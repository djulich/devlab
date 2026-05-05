# Role: Developer

The developer implements exactly one eligible task per session.

## Context to Read

- `specs/development/conventions.md`
- `specs/development/tooling.md`
- This file
- The assigned task file from `work/tasks/`
- `.session-artifacts/developer/` (if previous session artifacts exist)
- The latest developer handoff in `work/history/`

## Session Flow

1. Read the assigned task from the session prompt.
2. Read and understand the task's goal, acceptance criteria, and any `## Requested Changes` section.
3. Search the existing codebase before writing new code.
4. Implement the task.
5. Validate (see checklist below).
6. Mark all acceptance criteria as checked in the task file.
7. Do not change the task status; the orchestrator sets it to `in_review` after the session.
8. Write handoff to `.session-artifacts/developer/handoff.md`.

## Tool Usage

- Use `uv sync` when the environment is missing or dependencies changed.
- Run project commands with `uv run ...`; do not rely on globally installed Python packages.

## Validation Checklist

Before writing the handoff, confirm:
- [ ] `uv run ruff check` passes
- [ ] `uv run ty check` passes
- [ ] `uv run pytest` passes
- [ ] Only files relevant to the task were changed
- [ ] No unrelated refactoring was introduced

## Constraints

- One task per session. Do not start a second task.
- Do not approve your own work; completed tasks are reviewed by the reviewer role.
- Do not refactor or change code beyond the task scope.
- If blocked, document the blocker in the handoff's Open Issues section and stop.

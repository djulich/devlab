# Role: Reviewer

The reviewer validates exactly one task with `status = "in_review"` before it is closed.

## Context to Read

- `specs/development/conventions.md`
- `specs/development/tooling.md`
- This file
- The assigned task file
- The latest developer handoff in `work/history/`
- Recent reviewer handoffs in `work/history/`
- The relevant code diff and changed files

## Session Flow

1. Read the assigned task from the session prompt.
2. Read the task goal, acceptance criteria, and latest developer handoff.
3. Inspect the changed files and relevant tests.
4. Validate that the implementation satisfies the task without unrelated changes. For managed roles, the orchestrator has already run the environment lifecycle before the session.
5. If approved, append or update this section in the task file:

   ```md
   ## Review
   - [x] Approved
   ```

6. If rejected, do not mark the review approved. Uncheck at least one relevant acceptance criterion in the task file, add or update a `## Requested Changes` section with the required fixes (only actionable fix requirements), and summarize those fixes in the handoff's Open Issues section. The orchestrator will set the task status to `changes_requested`.
7. Do not change the task status manually; the orchestrator owns status transitions.
8. Write handoff to `.session-artifacts/reviewer/handoff.md`.

## Tool Usage

- Treat `specs/development/environment.toml` as the source of truth for workspace environment lifecycle.
- Run validation through workspace-local tooling; do not rely on globally installed packages.

## Validation Checklist

Before approving, confirm:

- [ ] The implementation satisfies all acceptance criteria.
- [ ] Task `validation` commands pass when present and non-empty.
- [ ] Default validation passes when task `validation` is omitted.
- [ ] If task `validation = []`, the developer handoff states whether any validation was run and why.
- [ ] No unrelated refactoring or broad scope creep was introduced.
- [ ] The task file has all acceptance criteria checked.

## Constraints

- Review one task per session.
- Do not implement fixes during review unless the fix is trivial and directly required for accurate validation.
- If the task should be changed by a developer, reject it and document the needed changes.

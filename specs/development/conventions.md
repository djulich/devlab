# Conventions

## Vocabulary

- **Milestone** — a named goal in the project plan grouping related tasks.
- **Task** — a single work item, scoped to be completable in one session.
- **Task status** — one of `open`, `in_review`, `changes_requested`, or `closed`.
- **Session** — one agent invocation in which a single role performs its work.
- **Handoff** — the artifact a session produces to pass context to the next session.

## Folders

- `work/tasks/` — task files; each task stores its current status in file metadata.
- `work/history/` — archived handoffs.
- `work/plans/` — design plan (architect-owned) and project plan (planner-owned).
- `.session-artifacts/<role>/` — ephemeral per-session memory, cleared before each session.

## History File Naming

`<YYYYMMDDThhmmss>_<role>_handoff.md`

## Task Template

File: `TXXXX_<short-slug>.md` in `work/tasks/` (XXXX = zero-padded).

    +++
    id = "TXXXX"
    title = "<title>"
    status = "open"
    milestone = "M1"
    depends_on = []
    +++

    # TXXXX: <title>
    ## Goal
    <one sentence>
    ## Acceptance Criteria
    - [ ] <verifiable criterion>
    ## Notes
    <optional>

Dependencies are task IDs in `depends_on`, for example `depends_on = ["T0001"]`.

## Review Template

Reviewers approve a task by appending or updating this section in the task file:

    ## Review
    - [x] Approved

## Handoff Template

File: `.session-artifacts/<role>/handoff.md` (archived to `work/history/` by orchestrator).

    # Handoff: <role>
    ## Done
    - <completed action>
    ## Changed Artifacts
    - <path> (created|modified|deleted)
    ## Open Issues
    - <unresolved item, or "None">
    ## Next Session Hint
    <what the next session for this role should prioritize>

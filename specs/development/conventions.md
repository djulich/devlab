# Conventions

## Vocabulary

- **Milestone** — a named goal in the project plan grouping related tasks.
- **Task** — a single backlog work item, scoped to be completable in one session.
- **Session** — one agent invocation in which a single role performs its work.
- **Handoff** — the artifact a session produces to pass context to the next session.

## Folders

- `work/backlog/` — open task files (one per task), removed on completion.
- `work/history/` — archived handoffs and closed-task records.
- `work/plans/` — design plan (architect-owned) and project plan (planner-owned).
- `.session-artifacts/<role>/` — ephemeral per-session memory, cleared before each session.

## History File Naming

`<YYYYMMDDThhmmss>_<role>_<type>.md` where type is `handoff` or `closed-task`.

## Task Template

File: `TXXX_<short-slug>.md` in `work/backlog/` (XXX = zero-padded).

    # TXXX: <title>
    ## Goal
    <one sentence>
    ## Acceptance Criteria
    - [ ] <verifiable criterion>
    ## Notes
    <optional>

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

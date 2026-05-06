# Conventions

## Vocabulary

- **Milestone** — a named goal in the project plan grouping related tasks.
- **Task** — a single work item, scoped to be completable in one session.
- **Task status** — one of `open`, `in_review`, `changes_requested`, or `closed`.
- **Session** — one agent invocation in which a single role performs its work.
- **Handoff** — the artifact a session produces to pass context to the next session.

## Core Artifacts

- **System specification** — `specs/system/`
- **Design plan** — `work/plans/design-plan.md`
- **Project plan** — `work/plans/project-plan.md`
- **Task files** — `work/tasks/TXXXX_<short-slug>.md`
- **Finding files** — `work/findings/FXXXX_<short-slug>.md`
- **Session handoff** (ephemeral per-session memory) — `.session-artifacts/<role>/handoff.md`
- **Archived handoffs** — `work/history/`

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
    validation = []
    +++

    # TXXXX: <title>
    ## Goal
    <one sentence>
    ## Acceptance Criteria
    - [ ] <verifiable criterion>
    ## Notes
    <optional>

Dependencies are task IDs in `depends_on`, for example `depends_on = ["T0001"]`.

Task-specific validation commands may be listed in `validation`. Commands are run from the workspace root. If `validation` is omitted, use the workspace defaults from `specs/development/tooling.md`. If `validation = []`, no validation commands are required; state in the handoff whether any validation was run and why.

## Finding Template

File: `FXXXX_<short-slug>.md` in `work/findings/` (XXXX = zero-padded).

    +++
    id = "FXXXX"
    title = "<title>"
    status = "open"
    source = "integrator"
    milestone = "M1"
    handoff = "<archived-handoff-file>"
    +++

    # <title>
    ## Finding
    <what is wrong or missing>
    ## Requested Planning
    <what kind of follow-up task planning is needed>

Findings are created by the orchestrator from role handoffs.

Planners convert open findings into task files and list addressed finding IDs in their handoff.

### Finding Status

- `open` — needs planner attention
- `planned` — planner created follow-up task(s)
- `resolved` — the issue was validated as resolved

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
    ## Addressed Findings
    - <finding ID, or "None">
    ## Next Session Hint
    <what the next session for this role should prioritize>

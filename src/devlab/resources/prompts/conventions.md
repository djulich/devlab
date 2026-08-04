# Conventions

## Vocabulary

- **Milestone** — a named goal in the project plan grouping related tasks.
- **Task** — a single work item, scoped to be completable in one session.
- **Task status** — one of `open`, `in_review`, `changes_requested`, or `closed`.
- **Session** — one agent invocation in which a single role performs its work.
- **Handoff** — the artifact a session produces to pass context to the next session.
- **CONTEXT.md** — target-owned project language glossary for domain terms, relationships, and flagged ambiguities.
- **ADR** — Architecture Decision Record; a target-owned note in `docs/adr/` explaining an important architectural decision and why it was made.

## Core Artifacts

- **System specification** — `.devlab/specs/system/`
- **Deployment specification** — `.devlab/specs/deployment/`
- **Design plan** — `.devlab/plans/design-plan.md`
- **Project plan** — `.devlab/plans/project-plan.md`
- **Task files** — `.devlab/tasks/TXXXX_<short-slug>.md`
- **Finding files** — `.devlab/findings/FXXXX_<short-slug>.md`
- **Tooling policy** — `.devlab/config/tooling.md`
- **Task profiles** — `.devlab/config/profiles/*.toml`
- **Session handoff** (per-session memory) — `.devlab/session-artifacts/<role>/handoff.md`
- **Archived handoffs** — `.devlab/history/`
- **Environment lifecycle logs** — `.devlab/logs/environment/`
- **Project context** — `CONTEXT.md` or `CONTEXT-MAP.md` with linked context files, if present
- **Architecture Decision Records (ADRs)** — `docs/adr/NNNN-slug.md`, if present

## History File Naming

`<YYYYMMDDThhmmss>_<role>_handoff.md`, with an added numeric suffix after the timestamp if multiple handoffs are archived in the same second.

## Task Template

File: `TXXXX_<short-slug>.md` in `.devlab/tasks/` (XXXX = zero-padded).

    +++
    id = "TXXXX"
    title = "<title>"
    status = "open"
    milestone = "M1"
    profile = "default"
    domain = "general"
    depends_on = []
    addresses_findings = []
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

Follow-up tasks for findings list finding IDs in `addresses_findings`, for example `addresses_findings = ["F0001"]`.

Each task has one primary domain with `domain = "<domain>"`; if omitted, `domain = "general"` is used. Use `domain = "deployment"` for tasks whose primary acceptance criteria concern packaging, deployment artifacts, runtime environment commands, smoke tests, teardown, or deployment documentation.

Each task may specify one profile with `profile = "<profile-id>"`; if omitted, `profile = "default"` is used. Profiles live in `.devlab/config/profiles/` and define tooling, default validation, and executable lifecycle commands for task types. If a task needs combined tooling/environment behavior, create a dedicated profile for that task type. Existing profiles may be extended or fixed in backward-compatible ways; breaking behavior changes should use a new profile so already-planned tasks keep their expected execution contract.

Task-specific validation commands may be listed in `validation`. Commands are run from the workspace root after the orchestrator-managed environment lifecycle has established the development environment. If `validation` is omitted, use the default validation from the resolved task profile. If `validation = []`, no mechanical validation commands are required; report only relevant manual checks or deliberately skipped checks that DevLab cannot infer.

## Finding Template

File: `FXXXX_<short-slug>.md` in `.devlab/findings/` (XXXX = zero-padded).

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

Planners convert open findings into task files. Each follow-up task must list the finding in `addresses_findings`, and the planner handoff must list the complete follow-up task set for each addressed finding.

### Finding Status

- `open` — needs planner attention
- `planned` — planner created follow-up task(s)
- `resolved` — the issue was validated as resolved

## Review Template

Reviewers approve a task by appending or updating this section in the task file:

    ## Review
    - [x] Approved

## Handoff Submission

DevLab initializes `.devlab/session-artifacts/<role>/handoff-candidate.toml`
before the session. Fill that candidate, then run:

    "$DEVLAB_PYTHON" -m devlab.cli session handoff submit

The session is complete only after the command reports `Accepted`. If it reports
validation errors, correct all listed fields and submit again. Do not directly
edit `result.toml` or `handoff.md`; DevLab publishes those canonical artifacts
after accepting the candidate.

The common candidate fields are:

    schema_version = 1
    outcome = "completed"
    commit_message = "Concise one-line summary"
    done = ["Completed action"]
    changed_artifacts = ["path/to/file"]
    open_issues = []
    addressed_findings = []
    next_session_hint = "What the next session should prioritize."

Use `outcome = "needs_clarification"` only with one `[clarification]` table, and
use `outcome = "failed"` only with at least one actionable `open_issues` entry.
Planner candidates additionally contain `planning_complete = true` or `false`.

For planner `addressed_findings`, use `"FXXXX: TXXXX[, TXXXX]"` entries to
assert the complete follow-up task set for each addressed finding. Use an empty
array when no findings were addressed.

If continuing would require inventing operator intent, set
`outcome = "needs_clarification"` and add:

    [clarification]
    title = "Specific decision title"
    scope = "planning"
    blocks = "planning"
    answer_shape = "choice"
    recommended_option = "A"
    details = """
    ### Context
    <why repository state is insufficient>

    ### Question
    <specific operator decision needed>

    ### Options
    - A: <recommended option and rationale>
    - B: <alternative>
    """

Allowed `answer_shape` values are `choice`, `text`, and `file-edit`. Use
`### Expected Answer` for text answers and `### Expected File Edits` for
file-edit answers. Ask only one specific, bounded clarification.

Do not include the task ID or role prefix in `commit_message`; the orchestrator
adds that prefix when creating the commit.

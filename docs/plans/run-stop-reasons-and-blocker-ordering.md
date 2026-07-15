# Run Stop Reasons and Blocker-First Selection

Status: implemented.

## Goal

Make every orchestrator stop machine-readable and ensure durable clarification
blockers are reported before ordinary role selection can misclassify the run as
complete or ineligible.

This plan implements priorities 1 and 2 from
`architectural-improvements.md`. It deliberately keeps CLI exit codes compatible
and does not redesign clarification scope, resume storage, or role selection.

## Outcome

`RunResult` now carries an explicit `RunStopReason`; evaluation diagnostics
serialize it as `stop_reason`; and `completed` is limited to terminal workflow or
command boundaries. The orchestrator checks pending durable clarification
blockers before ordinary role selection, while answered clarification resume
routes continue to receive task/milestone identity validation. CLI exit codes
remain unchanged.

## Current Problem

`RunResult.completed` currently combines several different meanings. A true
terminal workflow, a completed planning command, a reached session limit, a
dependency-blocked backlog, and an operator clarification stop can all return
`completed = true` with exit code zero. Callers must infer the actual outcome
from session counts, workspace state, or log messages.

The loop also selects an ordinary role before checking pending clarification
blockers. When selection returns no role, the loop exits before the blocker check
and can describe a clarification-blocked workflow as complete or unable to
proceed.

## Decisions

### Add one authoritative stop reason

Define a provider-independent `RunStopReason(StrEnum)` in `orchestrator.py`:

```python
class RunStopReason(StrEnum):
    WORKFLOW_COMPLETE = "workflow_complete"
    COMMAND_COMPLETE = "command_complete"
    SESSION_LIMIT = "session_limit"
    CLARIFICATION_BLOCKED = "clarification_blocked"
    NO_ELIGIBLE_ROLE = "no_eligible_role"
    ERROR = "error"
```

`COMMAND_COMPLETE` distinguishes a successfully bounded command from completion
of the whole DevLab workflow. Examples include `devlab plan` stopping before an
implementation role and `--mark-specs-planned` completing without a session.

Do not add `USER_QUIT` until an operator-quit path exists in the current CLI.
Adding unused enum states would imply a supported transition that has no
producer. If interactive continuation returns later, it can add that reason in
the same explicit way.

Add `stop_reason` to `RunResult` and make it required at every construction
site. Do not infer it in `RunResult.__post_init__` from `completed`, errors, or
exit codes; that would preserve the ambiguity in a different place.

Retain `completed` during this compatibility slice, but define it narrowly as:

```text
completed = stop_reason in {WORKFLOW_COMPLETE, COMMAND_COMPLETE}
```

`SESSION_LIMIT`, `CLARIFICATION_BLOCKED`, `NO_ELIGIBLE_ROLE`, and `ERROR` all
set `completed = false`. A later compatibility cleanup may replace the stored
boolean with a derived property after downstream users have migrated.

CLI exit-code behavior remains unchanged:

- successful and bounded non-error stops continue to exit zero;
- existing error paths retain their current nonzero code;
- `RunStopReason.ERROR` describes all nonzero/error-bearing outcomes without
  replacing the more detailed `SessionError.phase` diagnostics.

### Classify successful stops at their owning branch

Each return or loop break must choose its reason where the decision is made:

| Condition | Stop reason | `completed` | Exit code |
|---|---|---:|---:|
| Entire reconciled workflow has no remaining work | `WORKFLOW_COMPLETE` | true | 0 |
| Plan boundary reached or specs explicitly marked planned | `COMMAND_COMPLETE` | true | 0 |
| `max_sessions` reached while further work may remain | `SESSION_LIMIT` | false | 0 |
| Pending blocking clarification | `CLARIFICATION_BLOCKED` | false | 0 |
| Tasks remain but none is eligible, such as dependency blockage | `NO_ELIGIBLE_ROLE` | false | 0 |
| Validation, provider, configuration, state, Git, or artifact failure | `ERROR` | false | existing |

Avoid one unconditional success return after the loop. Track or return the
specific reason at the branch that stops execution. In particular, reaching the
`while sessions_run < max_sessions` boundary must not be called completion.

### Inspect blockers before ordinary role selection

Use this order at the start of each loop iteration:

1. Refresh the workspace snapshot when the current mode requires it.
2. Inspect pending clarifications that block the requested command family.
3. If an active resume pointer exists, validate that its clarification and
   command state permit resume processing.
4. Select the ordinary role and its task or milestone route.
5. Validate the selected route against the active resume pointer.
6. Continue with spec guards, planning boundaries, and session invocation.

The existing conservative top-level blocking behavior remains unchanged. This
slice only changes ordering; it does not introduce task- or milestone-scoped
blocker routing.

`blocks = "none"` records must not stop selection. Reuse
`WorkspaceSnapshot.blocking_clarifications()` rather than parsing clarification
files or duplicating blocking semantics in `orchestrator.py`.

Wrong-command resume guidance remains an earlier command-entry guard. An
answered clarification with a resume pointer must proceed to route validation,
not be treated as a pending blocker. Missing, stale, or invalid resume targets
remain errors with phase `clarification_resume` and `RunStopReason.ERROR`.

## Implementation Slices

### Slice 1: Introduce and propagate stop reasons

In `src/devlab/orchestrator.py`:

- add `RunStopReason` and the required `RunResult.stop_reason` field;
- classify every `RunResult` construction explicitly;
- replace ambiguous loop `break` handling with branch-owned results or a local
  stop reason that cannot remain unset;
- distinguish clean terminal completion from dependency-blocked no-role state;
- classify planning-only boundaries separately from whole-workflow completion;
- update the `RunResult` docstring to describe the compatibility role of
  `completed` and `exit_code`.

Prefer a small private result factory only if it makes invariants explicit, for
example separate `_success_result(...)` and `_error_result(...)` helpers. Do not
move workflow stop policy out of `orchestrator.py`.

In `src/devlab/clarification_ops.py`, use `stop_reason` where resume behavior
currently relies on the combination of exit code and session count. Preserve
the existing human-facing repair messages.

In `tests/evaluations/harness.py`:

- add serialized `stop_reason` to `EvaluationDiagnostics`;
- populate it from `RunResult.stop_reason.value`;
- keep `completed` for historical result compatibility;
- update evaluation fixtures and assertions to require the expected reason
  where it materially distinguishes success, limits, and blockers.

### Slice 2: Move blocker detection before role selection

In `src/devlab/orchestrator.py`:

- evaluate `_blocking_clarification_error()` before `assess_state()` or forced
  ordinary role selection;
- return `CLARIFICATION_BLOCKED`, zero exit code, `completed = false`, and retain
  the actionable clarification diagnostic;
- keep active-resume validation split into state checks possible before
  selection and route checks that require the selected role/task/milestone;
- ensure forced architect/planner routes cannot bypass a blocker unless the
  documented `plan --revise` command exception applies;
- preserve the non-mutating nature of blocker and resume validation.

If splitting `_resume_validation_error()` improves ordering, keep both helpers
private to `orchestrator.py`: one for clarification/resume record validity and
one for selected-route identity. Do not add a new module for these tightly
coupled workflow decisions.

### Slice 3: Operator and developer documentation

Update:

- `docs/plans/architectural-improvements.md` to mark priorities 1 and 2
  implemented and link this plan;
- `docs/plans/README.md` to move this plan from active to implemented when the
  code lands;
- `README.md` or `docs/operator-guide.md` only where operator-visible stop
  wording or library semantics need explanation;
- `docs/evaluations.md` for the new diagnostics field.

Do not add durable target-workspace state or workflow events merely to record a
run's process-local stop reason. The reason belongs to the returned result and
evaluation output; repository state remains the source for workflow facts.

## Tests

Add focused orchestrator tests for:

- terminal workflow completion returns `WORKFLOW_COMPLETE`;
- a normal planning boundary returns `COMMAND_COMPLETE`;
- `--mark-specs-planned` returns `COMMAND_COMPLETE`;
- reaching `max_sessions` with remaining work returns `SESSION_LIMIT`;
- a pending command-family blocker returns `CLARIFICATION_BLOCKED` even when
  `assess_state()` would return no role;
- a non-blocking clarification does not prevent role selection;
- dependency-blocked tasks return `NO_ELIGIBLE_ROLE`;
- every existing error family returns `ERROR` while preserving its exit code and
  `SessionError.phase`;
- an answered clarification with a valid resume pointer selects and resumes the
  stored route;
- stale, invalid, and wrong-command resume pointers retain repair-oriented
  diagnostics and return `ERROR`;
- `plan --revise` retains its documented ability to supersede the ordinary
  wrong-command guard without silently bypassing a relevant pending blocker.

Add evaluation coverage proving JSON diagnostics contain stable string reasons.
Update CLI tests to confirm exit codes remain compatible for completion,
session-limit, clarification-blocked, and error outcomes.

## Acceptance Criteria

- Every `run_loop()` return path supplies an explicit `RunStopReason`.
- No caller needs to parse logs or inspect session counts to distinguish the
  supported stop classes.
- `completed = true` means the requested workflow or command actually reached
  its intended terminal boundary.
- A pending blocking clarification is reported before no-role or completion
  classification for its command family.
- `blocks = "none"` does not affect role selection.
- Resume validation remains precise and non-mutating.
- CLI exit codes remain backward compatible.
- Evaluation JSON exposes `stop_reason` while retaining `completed`.
- Full development validation passes:

```bash
make check
```

# Architectural Improvements

Status: active backlog. Implement only when a concrete workflow change or usage
signal justifies the relevant slice; this is not authorization for a broad
refactor.

## Purpose

Collect cross-cutting architectural weaknesses that do not belong to one feature
plan. Keep each item tied to an observable failure mode and preserve DevLab's
module boundaries: orchestration owns workflow policy, providers own invocation,
trackers own file formats, and `Workspace` handles own mutations.

## Priorities

### 1. Distinguish workflow completion from bounded and blocked stops

Implementation plan: `run-stop-reasons-and-blocker-ordering.md`.

Current `RunResult` semantics can report `completed = true` with exit code zero
when a durable clarification blocks progress. Similar ambiguity can arise when a
session limit is reached normally. Automation cannot reliably distinguish:

- the requested workflow reaching its terminal state;
- a bounded run stopping after its session budget;
- a workflow waiting for operator clarification;
- a run with no currently eligible role;
- an operator-requested quit.

Introduce a structured stop reason, preferably an enum such as:

```python
class RunStopReason(StrEnum):
    WORKFLOW_COMPLETE = "workflow_complete"
    SESSION_LIMIT = "session_limit"
    CLARIFICATION_BLOCKED = "clarification_blocked"
    NO_ELIGIBLE_ROLE = "no_eligible_role"
    USER_QUIT = "user_quit"
    ERROR = "error"
```

Keep CLI exit-code behavior backward compatible unless a separate CLI policy is
explicitly adopted. Update evaluation diagnostics and library callers to consume
the structured reason instead of inferring meaning from `completed`, session
count, or log strings.

Acceptance:

- every `run_loop()` return path has an explicit stop reason;
- clarification stops are not described as completed workflows;
- JSON/evaluation diagnostics expose the reason;
- focused tests cover every reason and compatibility of CLI exit codes.

Priority: high.

### 2. Check durable workflow blockers before ordinary role selection

Implementation plan: `run-stop-reasons-and-blocker-ordering.md`.

The workflow loop currently selects a role before reporting pending clarification
blockers. If no role is eligible, the run can report that work is complete or
cannot proceed without surfacing the durable blocker.

Move command-family blocker inspection ahead of ordinary role selection. Resume
route validation may still need role/task/milestone selection, so keep these as
separate stages:

1. inspect global and command-family durable blockers;
2. validate an active resume route when present;
3. select the ordinary next role only when unblocked.

Acceptance:

- a pending blocking clarification is always the primary stop reason for its
  command family;
- `blocks = "none"` does not prevent role selection;
- stale or invalid resume pointers retain repair-oriented diagnostics;
- no reporting or validation path mutates workflow state.

Priority: high.

### 3. Make tracker mutations atomic and interruption-safe

Status: implemented for authoritative task, milestone, finding, clarification,
workflow-state, generation-manifest, and handoff/result writes through the shared
`_files.atomic_write_text()` helper. Logs and other disposable artifacts retain
ordinary writes.

The shared helper writes a temporary file in the destination directory, flushes
and fsyncs it, preserves existing permissions, and atomically replaces the target.
Trackers retain ownership of their formats and complete-file mutation policy.

Do not add general locking prematurely. First make single-writer interruption
safe. Add an optimistic concurrency guard only if simultaneous DevLab processes
become supported, for example by comparing a content digest or revision read
before mutation.

Acceptance:

- interruption cannot expose a partially formatted tracker/workflow file;
- a failed replacement preserves the previous durable record;
- tests simulate replacement failure without corrupting the original;
- the helper does not move domain mutation policy out of trackers or workspace
  handles.

Remaining concurrency protection is covered separately below; atomic replacement
does not make simultaneous read-modify-write operations conflict-safe.

### 4. Define concurrent-process behavior explicitly

Clarification ID allocation scans existing files and chooses the next number.
Workflow resume state also assumes one active writer. Two DevLab processes can
allocate the same ID or overwrite state derived from stale reads.

Before adding locking, decide and document one supported policy:

- reject concurrent mutating DevLab processes with a workspace lock; or
- support optimistic concurrency with record revisions and retryable conflicts.

A simple workspace lock is likely the better first policy because DevLab already
models a bounded, sequential role workflow. The lock must not block read-only
commands such as `status`, `doctor`, prompt context reporting, or diagnostics.

Acceptance:

- mutating commands have deterministic behavior when another mutation is active;
- stale lock recovery is documented and conservative;
- read-only commands remain non-mutating and available;
- tests cover lock contention and stale-lock handling.

Priority: medium; implement before multi-agent concurrent sessions.

### 5. Replace string-coupled validation errors with typed failures

Some callers specialize diagnostics by matching exception message text, such as
recognizing an answered clarification with an empty `## Answer` section. Message
wording changes can silently break control flow or repair guidance.

Introduce small typed tracker/validation exceptions or structured result reason
codes. Keep human-readable messages at adapter boundaries rather than using them
as internal discriminators.

Acceptance:

- no workflow decision depends on matching an exception string;
- malformed, missing, conflicting, and invalid-state cases have stable reason
  codes;
- CLI and doctor retain concise repair-oriented messages;
- trackers remain the owners of file-format validation.

Priority: medium.

The handoff-specific portion now has a concrete implementation sequence in
`resilient-session-handoffs.md`. It uses typed failures for an orchestrator-owned
submission and acceptance protocol rather than parsing new agent-authored
Markdown control artifacts. Retain this item for validation failures in other
trackers and workflow paths.

### 6. Strengthen resolver edit isolation without scanning the whole workspace

Unattended clarification resolution now snapshots file digests, enforces expected
file-edit paths, and restores forbidden workflow-state files. Remaining limits:

- whole-workspace traversal can be expensive in large repositories;
- pre-existing symlink targets are intentionally not followed and therefore are
  not fully monitored;
- unexpected non-workflow edits stop the run but remain for operator inspection;
- file changes and answer application are not one transaction.

Prefer a Git-aware changed-path baseline when the target is a clean Git workspace,
with the current digest approach as a non-Git fallback. If stronger rollback is
needed, isolate the resolver in a temporary worktree and apply only approved paths
after its output validates. Do not implement ad hoc broad rollback that could
discard user changes.

Acceptance:

- large repositories avoid unnecessary full-content hashing where Git can provide
  an authoritative baseline;
- approved file edits and the clarification answer are applied as one controlled
  integration step;
- unexpected edits cannot be committed automatically;
- rollback never removes changes that predated the resolver session.

Priority: medium; raise if live evaluations show performance or containment
failures.

### 7. Bound agent-to-orchestrator artifact sizes

Handoffs, clarification bodies, titles, resolver answers, and retained prompts can
currently consume unbounded text apart from the clarification title limit. A
malformed agent response can create oversized durable records and subsequent
prompt bloat.

Define generous explicit limits for structured artifacts and individual fields.
Reject oversized output with a repair-oriented error before mutating durable
workflow state. Keep product files outside these limits; this applies only to
DevLab control artifacts.

Acceptance:

- handoff and resolver artifact limits are documented and enforced;
- errors identify the field or artifact and its allowed size;
- prompt assembly cannot repeatedly amplify an oversized clarification answer;
- tests cover boundary and over-limit cases.

Priority: medium-low.

### 8. Revisit `run_loop()` cohesion only alongside a substantive change

`run_loop()` still owns role selection, environment lifecycle, invocation,
handoff processing, version control, clarification dispatch, and stop semantics.
The code remains understandable because policy is colocated, so line count alone
does not justify extraction.

When implementing stop reasons, blocker ordering, or resolver isolation, consider
extracting only one cohesive internal domain:

- session execution and environment lifecycle;
- post-session artifact validation;
- version-control integration after validated state transitions.

Keep role selection and workflow transition policy visible in `orchestrator.py`.
Reject extractions that increase cross-module navigation or require importing
orchestrator-owned types into several support modules.

Priority: opportunistic.

## Suggested implementation order

1. Add structured run stop reasons without changing CLI exit codes.
2. Move clarification blocker inspection ahead of ordinary role selection.
3. Add atomic file replacement and migrate the highest-risk workflow and tracker
   mutations.
4. Replace string-matched validation errors with typed reasons while touching
   those mutation paths.
5. Decide concurrent mutation policy before any multi-agent execution work.
6. Improve resolver isolation only when Git/non-Git evaluation evidence warrants
   the additional machinery.
7. Add artifact size limits based on observed provider output sizes.

## Non-goals

- Do not split `orchestrator.py` merely to reduce line count.
- Do not add concurrent agent sessions as part of atomic-write work.
- Do not hide durable state in process memory, locks, or conversational context.
- Do not make reporting or validation commands mutate state.
- Do not introduce a database for file-backed workflow records.
- Do not use broad rollback commands that can discard operator-authored changes.

## Validation

Each implemented slice should include focused state-transition or failure-injection
tests, followed by:

```bash
uv --cache-dir /tmp/uv-cache run ruff check src tests
uv --cache-dir /tmp/uv-cache run ty check
uv --cache-dir /tmp/uv-cache run pytest
```

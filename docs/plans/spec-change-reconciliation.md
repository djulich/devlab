# Spec Change Reconciliation

## Problem

`devlab plan` currently behaves like an optional planning preflight: it creates missing design/project planning state and becomes a no-op once implementation tasks exist. `devlab run` then continues the workflow from durable state. That makes `run` easy to treat as the command that will figure everything out, even when the target system or deployment specification has changed after planning.

The desired mental model is sharper:

- `devlab plan` reconciles operator-authored specifications with DevLab workflow state.
- `devlab run` implements the already-reconciled workflow state.

If `.devlab/specs/system/` or `.devlab/specs/deployment/` changes after planning, DevLab must not blindly keep executing stale tasks. The operator should run `devlab plan` again so architecture and planning sessions can preserve still-valid work, revise or supersede stale work, and add newly required work.

## Decision

Add durable spec baseline state to `.devlab/workflow.toml` and make `devlab plan` responsible for reconciling changes against that baseline.

Proposed state:

```toml
version = 1

[planning]
complete = false

[specs]
last_planned_tree = "<git tree/content fingerprint for .devlab/specs>"
last_planned_spec_commit = "<latest commit touching .devlab/specs/system or .devlab/specs/deployment>"
last_planned_at = "2026-06-15T12:34:56Z"
```

Semantics:

- Missing `[specs]` means DevLab has never recorded a planning baseline for this target workspace. The next `devlab plan` is a first planning run.
- `last_planned_tree` is the content baseline used for deterministic changed/not-changed checks.
- `last_planned_spec_commit` supports the operator-facing explanation that specs changed through Git history since the last planning baseline.
- Dirty staged or unstaged spec paths are detected, but they block reconciliation until the operator commits them.
- Reporting commands may read and report this state, but must not repair or update it.

## Command Behavior

### `devlab plan`

`devlab plan` becomes the reconciliation command.

On first planning run:

1. Detect that no spec baseline exists.
2. Run the existing missing planning sessions: architect, then planner as needed.
3. After successful planning, record the current spec baseline in `.devlab/workflow.toml`.
4. Commit the session changes through the existing automatic version-control path.

On later planning runs:

1. Check spec status before the generic clean-worktree requirement.
2. Detect changed specs from either:
   - committed changes touching `.devlab/specs/system/` or `.devlab/specs/deployment/` since `last_planned_spec_commit`, or
   - a current spec tree fingerprint that differs from `last_planned_tree`.
3. Detect staged or unstaged changes under `.devlab/specs/system/` or `.devlab/specs/deployment/` and stop with a clear message asking the operator to commit spec changes before running `devlab plan`.
4. If no committed spec changes exist and no `--revise` flag is passed, keep the current no-op behavior.
5. If committed spec changes exist, force a planning revision path equivalent to `devlab plan --revise`.
6. After successful architect/planner revision, update the spec baseline.

Dirty working tree handling stays strict:

- Dirty paths anywhere remain a hard stop before agent sessions.
- Dirty spec paths get a more specific error than generic clean-worktree failure: commit the spec changes, then run `devlab plan`.
- This keeps operator-authored specification commits separate from DevLab-authored reconciliation commits and preserves the existing clean-worktree invariant.

### `devlab run`

`devlab run` should be described and validated as implementation continuation, not reconciliation.

Before selecting implementation roles, it should check whether specs differ from the recorded planning baseline. If they do, it should stop with a clear error:

```text
Specifications changed since the last devlab plan baseline.
Run devlab plan to reconcile .devlab/specs with workflow state before running implementation.
```

This keeps `run` from silently turning into a planning command while preserving bounded role sessions and the user review point.

### `devlab plan --revise`

`--revise` remains the explicit "review and possibly update existing plans" command. It should also refresh the spec baseline after a successful revision, even if the detected spec content did not change.

`--revise` still runs both architect and planner. DevLab should not try to infer that the architect can be skipped for deployment-spec-only changes: the deployment spec may alter architecture, operability, boundaries, packaging, validation strategy, or profile needs. The bounded and reviewable rule is simple: any spec reconciliation re-runs architecture review of the design plan first, then planning.

## Git Detection Details

Add a small spec-baseline helper, likely in a new focused module such as `spec_reconciliation.py` or in `workflow_state.py` if the code stays compact.

Inputs:

- root path
- spec paths:
  - `.devlab/specs/system`
  - `.devlab/specs/deployment`

Checks:

- `git status --porcelain -- .devlab/specs/system .devlab/specs/deployment` for staged/unstaged spec changes that should block reconciliation until committed.
- `git log --format=%H -1 -- .devlab/specs/system .devlab/specs/deployment` for the latest committed spec change.
- A stable spec content fingerprint for the current spec tree.

The fingerprint should represent committed spec content. Use Git primitives where practical, and do not parse spec Markdown outside the spec domain. Dirty or untracked spec files do not become part of the baseline until the operator commits them.

Result object:

```python
SpecReconciliationStatus(
    baseline_exists: bool,
    changed: bool,
    dirty_spec_paths: tuple[str, ...],
    latest_spec_commit: str,
    current_tree: str,
    baseline_tree: str,
)
```

This keeps orchestration decisions explicit and gives CLI/status/doctor code a reusable diagnostic surface.

## Workflow Integration

`run_loop` should not grow broad Git policy inline. Add a preflight step near the existing automatic-version-control setup:

- For `planning_only=True`:
  - load workflow state,
  - compute spec reconciliation status,
  - decide whether this is first planning, no-op planning, explicit revision, or detected reconciliation,
  - reject any dirty worktree before agent sessions, with a spec-specific message when dirty spec paths are present.
- For `planning_only=False`:
  - compute status,
  - reject changed specs with a `SessionError` whose message tells the user to run `devlab plan`.

The actual role forcing can reuse existing `revise_plan` behavior by deriving an internal `reconcile_plan` flag. Public API callers can still pass `revise_plan`; CLI `devlab plan` can rely on automatic detection.

After successful planning/revision, update `[specs]` in workflow state through an explicit mutation helper and ensure the update is committed by automatic version control.

## Agent Prompt Changes

Planning revision prompts should distinguish ordinary explicit revision from spec reconciliation:

- Architect: compare changed system/deployment specs against the existing design plan, completed work, integrated milestones, and architecture-review findings.
- Planner: update project plan/tasks so stale tasks are revised or closed with rationale, and new requirements become durable tasks.

Do not ask developer/reviewer/integrator roles to infer spec reconciliation policy. They should consume reconciled workflow state or report contradictions through existing blockers/findings.

## Task and Milestone Treatment

Initial implementation can avoid adding a new task status if the planner can represent decisions with existing mechanisms:

- Closed tasks remain historical completed work. Reconciliation should not reopen them automatically.
- Open or in-review tasks that still apply may be edited by the planner to match the revised plan.
- Open or in-review tasks that no longer apply should be closed with an explicit reconciliation rationale in the task body or review history, not assigned a new status.
- Newly required work gets new task ids.
- Milestones remain durable coordination units, but reconciliation may change their future scope.

Partially implemented milestones need special handling:

- Keep closed tasks in the milestone as completed evidence.
- Reconcile every non-closed task in that milestone against the revised design plan.
- If the milestone goal still exists, the planner may keep the milestone and replace only the obsolete remaining tasks.
- If the milestone goal changed materially, the planner should mark the old milestone as no longer the future integration target by closing its remaining obsolete tasks with rationale, then create a new milestone for the revised goal.
- The integrator should only integrate a milestone after its current task set is closed, so replacing the remaining task set is enough to keep integration bounded without adding a `superseded` status.

This deliberately avoids a mass dismissal rule for all non-closed tasks. Blanket closure would be easy to reason about, but it would lose useful partially planned work and make partially implemented milestones noisy. The first implementation should instruct architect/planner sessions to preserve applicable tasks and close only tasks that conflict with or are made irrelevant by the revised specs.

A dedicated `superseded` task status remains a follow-up option, but it is out of scope for the first implementation.

## Documentation Updates

Update:

- `README.md`: present `devlab plan` as spec/workflow reconciliation and `devlab run` as implementation continuation.
- `docs/design.md`: replace the current "idempotent planning preflight" language with the new command model.
- `docs/todo.md`: mark item 9 as planned once this design is accepted.
- `docs/plans/README.md`: list this plan as active until implemented.

## Test Plan

Focused tests:

- First `devlab plan` on initialized workspace records a spec baseline.
- Subsequent `devlab plan` with unchanged specs remains a no-op.
- Subsequent `devlab plan` with dirty staged spec changes stops and asks the operator to commit them.
- Subsequent `devlab plan` with dirty unstaged spec changes stops and asks the operator to commit them.
- Dirty non-spec changes still stop planning before agent sessions.
- Committed spec changes after the baseline force architect/planner revision.
- `devlab run` with changed specs stops and instructs the user to run `devlab plan`.
- `devlab plan --revise` refreshes the baseline even when no spec change is detected.
- `devlab status` or `doctor` can report stale spec baseline without mutating state, if we expose this diagnostically.

## Open Questions

1. Should the spec baseline store only the latest spec commit and content fingerprint, or should it also store a short list of changed spec files for better prompts and status output?
2. Should reconciliation produce a separate durable summary artifact, or are architect/planner handoffs plus edited plans/tasks sufficient?

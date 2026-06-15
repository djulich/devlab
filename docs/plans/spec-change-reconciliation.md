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
- Dirty staged or unstaged spec paths also count as changed, even before they have a commit.
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
   - staged or unstaged changes under `.devlab/specs/system/` or `.devlab/specs/deployment/`, or
   - committed changes touching those folders since `last_planned_spec_commit`, or
   - a current spec tree fingerprint that differs from `last_planned_tree`.
3. If no spec changes exist and no `--revise` flag is passed, keep the current no-op behavior.
4. If spec changes exist, force a planning revision path equivalent to `devlab plan --revise`.
5. After successful architect/planner revision, update the spec baseline.

Dirty working tree handling should be narrow:

- Dirty paths outside the two spec folders remain a hard stop before agent sessions.
- Dirty paths inside the spec folders are allowed for `devlab plan` reconciliation because they are the input being reconciled.
- If spec paths are dirty, the final automatic commit may include both operator spec edits and DevLab planning revisions. The command output should say that clearly. If we want stricter authorship separation later, `devlab plan` can require users to commit spec edits first, but that would weaken the requested staged/unstaged detection flow.

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

## Git Detection Details

Add a small spec-baseline helper, likely in a new focused module such as `spec_reconciliation.py` or in `workflow_state.py` if the code stays compact.

Inputs:

- root path
- spec paths:
  - `.devlab/specs/system`
  - `.devlab/specs/deployment`

Checks:

- `git status --porcelain -- .devlab/specs/system .devlab/specs/deployment` for staged/unstaged spec changes.
- `git log --format=%H -1 -- .devlab/specs/system .devlab/specs/deployment` for the latest committed spec change.
- A stable spec content fingerprint for the current spec tree.

The fingerprint should include tracked and relevant untracked spec files so dirty first-time spec edits are visible. Use Git primitives where practical, but do not parse spec Markdown outside the spec domain. If untracked files complicate pure Git tree hashing, compute a deterministic hash over relative path, mode/classification, and bytes for files under the spec folders while using Git only to decide tracked/dirty/history state.

Result object:

```python
SpecReconciliationStatus(
    baseline_exists: bool,
    changed: bool,
    dirty_spec_paths: tuple[str, ...],
    dirty_non_spec_paths: tuple[str, ...],
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
  - allow dirty spec-only worktree when reconciliation is needed,
  - reject dirty non-spec paths.
- For `planning_only=False`:
  - compute status,
  - reject changed specs with a `SessionError` whose message tells the user to run `devlab plan`.

The actual role forcing can reuse existing `revise_plan` behavior by deriving an internal `reconcile_plan` flag. Public API callers can still pass `revise_plan`; CLI `devlab plan` can rely on automatic detection.

After successful planning/revision, update `[specs]` in workflow state through an explicit mutation helper and ensure the update is committed by automatic version control.

## Agent Prompt Changes

Planning revision prompts should distinguish ordinary explicit revision from spec reconciliation:

- Architect: compare changed system/deployment specs against the existing design plan, completed work, integrated milestones, and architecture-review findings.
- Planner: update project plan/tasks so stale tasks are revised, superseded, or closed with rationale, and new requirements become durable tasks.

Do not ask developer/reviewer/integrator roles to infer spec reconciliation policy. They should consume reconciled workflow state or report contradictions through existing blockers/findings.

## Task and Milestone Treatment

Initial implementation can avoid adding a new task status if the planner can represent decisions with existing mechanisms:

- keep valid open tasks unchanged,
- edit planned/open tasks that still apply but need updated acceptance criteria,
- close tasks that are already satisfied by completed work,
- create new tasks for new scope,
- for obsolete tasks, either close with a clear rationale in the task body or leave blocked with a rationale if closure would be misleading.

A dedicated `superseded` task status remains a follow-up option. It should be added only if live use shows closed-with-rationale is ambiguous in status reports or history.

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
- Subsequent `devlab plan` with dirty staged spec changes forces architect/planner revision.
- Subsequent `devlab plan` with dirty unstaged spec changes forces architect/planner revision.
- Dirty non-spec changes still stop planning before agent sessions.
- Committed spec changes after the baseline force architect/planner revision.
- `devlab run` with changed specs stops and instructs the user to run `devlab plan`.
- `devlab plan --revise` refreshes the baseline even when no spec change is detected.
- `devlab status` or `doctor` can report stale spec baseline without mutating state, if we expose this diagnostically.

## Open Questions

1. Should dirty spec changes be allowed and committed together with planning revisions, or should `devlab plan` detect them but require the operator to commit them before reconciliation?
2. Should deployment-spec-only changes always force both architect and planner, or may they force planner only when the design plan is unaffected?
3. Do we want a first-class `superseded` task status in the first implementation, or should the planner use existing task statuses plus rationale until ambiguity appears in real runs?
4. Should we add a public alias such as `devlab implement` for `devlab run`, or only change the documentation and runtime guardrails?

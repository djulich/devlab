# Spec Change Reconciliation

## Problem

`devlab plan` currently behaves like an optional planning preflight: it creates missing design/project planning state and becomes a no-op once implementation tasks exist. `devlab run` then continues the workflow from durable state. That makes `run` easy to treat as the command that will figure everything out, even when the target system or deployment specification has changed after planning.

The desired mental model is sharper:

- `devlab plan` reconciles operator-authored specifications with DevLab workflow state.
- `devlab run` implements the already-reconciled workflow state.

If `.devlab/specs/system/` or `.devlab/specs/deployment/` changes after planning, DevLab must not blindly keep executing stale tasks. The operator should run `devlab plan` again so architecture and planning sessions can preserve completed work, carry still-valid unfinished work forward into the new planning generation, revise stale work, and add newly required work.

## Decision

Add durable spec baseline state to `.devlab/workflow.toml` and make `devlab plan` responsible for reconciling changes against that baseline. This plan depends on moving `.devlab/workflow.toml` ownership to the orchestrator first: planner agents should report desired planning completion in their handoff, and the orchestrator should update `[planning].complete` programmatically.

Prerequisite plan: [orchestrator-owned-workflow-state.md](orchestrator-owned-workflow-state.md).

Proposed state:

```toml
version = 1

[planning]
complete = false
generation = 1

[specs]
last_planned_tree = "<git tree/content fingerprint for .devlab/specs/system and .devlab/specs/deployment>"
last_planned_spec_commit = "<latest commit touching .devlab/specs/system or .devlab/specs/deployment>"
last_planned_at = "2026-06-15T12:34:56Z"
```

Semantics:

- `.devlab/workflow.toml` is the semantically correct home for this state because it is durable workflow-control state.
- The orchestrator should own all writes to `.devlab/workflow.toml`. Agents may read summarized workflow state and report requested state changes through structured handoff fields, but they should not edit this TOML file directly.
- `[specs]` is still required because it is the durable planning baseline. `planning.generation` says which workflow generation is actionable, but it does not identify which committed specification content that generation reconciled.
- Missing `[specs]` means DevLab has never recorded a planning baseline for this target workspace. The next `devlab plan` is a first planning run.
- `last_planned_tree` is the source of truth for deterministic changed/not-changed checks.
- `last_planned_spec_commit` supports operator-facing explanations and diagnostics, but it is not the sole correctness check. A later commit that leaves the spec content identical to `last_planned_tree` does not need a new planning generation.
- Dirty staged or unstaged spec paths are detected, but they block reconciliation until the operator commits them.
- `planning.generation` is the current actionable plan generation.
- Tasks may carry `planning_generation = N`. A task is actionable only when its generation matches `workflow.toml`'s current planning generation and its status is active.
- Milestones may carry `planning_generation = N`. A milestone participates in current orchestration only when its generation matches the current planning generation. Older integrated, architecture-reviewed, or complete milestones remain historical evidence of delivered work, not current workflow targets.
- Missing task or milestone generation metadata should be treated as generation 1 for backward compatibility.
- Reporting commands may read and report this state, but must not repair or update it.

## Command Behavior

### `devlab plan`

`devlab plan` becomes the reconciliation command.

On first planning run:

1. Detect that no spec baseline exists.
2. Run the existing missing planning sessions: architect, then planner as needed.
3. Ensure created tasks and milestones belong to the current planning generation.
4. After successful planning, record the current spec baseline in `.devlab/workflow.toml`.
5. Commit the session changes through the existing automatic version-control path.

On later planning runs:

1. Check spec status before the generic clean-worktree requirement.
2. Detect changed specs by comparing the current committed spec content fingerprint with `last_planned_tree`. The latest spec commit can be reported to explain the Git history, but generation advancement is tied to a content-baseline difference.
3. Detect staged or unstaged changes under `.devlab/specs/system/` or `.devlab/specs/deployment/` and stop with a clear message asking the operator to commit spec changes before running `devlab plan`.
4. If no committed spec content changes exist and no `--revise` flag is passed, keep the current no-op behavior.
5. If committed spec content changes exist, infer reconciliation automatically and run architect/planner with `next_generation = current_generation + 1`; `--revise` is not required.
6. During reconciliation, prior-generation active tasks and unfinished milestones remain in the repository unchanged but become stale/non-actionable once the new generation is committed.
7. After successful architect/planner revision, update the spec baseline and advance `planning.generation` to `next_generation`.

Dirty working tree handling stays strict:

- Dirty paths anywhere remain a hard stop before agent sessions.
- Dirty spec paths get a more specific error than generic clean-worktree failure: commit the spec changes, then run `devlab plan`.
- This keeps operator-authored specification commits separate from DevLab-authored reconciliation commits and preserves the existing clean-worktree invariant.

### `devlab run`

`devlab run` should be described and validated as implementation continuation, not reconciliation.

Before selecting any non-planning workflow role, it should check whether specs differ from the recorded planning baseline. If they do, it should stop with a clear error:

```text
Specifications changed since the last devlab plan baseline.
Run devlab plan to reconcile .devlab/specs with workflow state before continuing.
```

This guard applies to developer, reviewer, integrator, and architecture-review continuation sessions. Only `devlab plan` may proceed from a changed-spec state, because it is the command that reconciles specs with workflow state. This keeps `run` from silently turning into a planning command while preserving bounded role sessions and the user review point.

### `devlab plan --revise`

`--revise` remains the explicit "review and possibly update existing plans" command. It should also refresh the spec baseline after a successful revision, even if the detected spec content did not change.

`--revise` still runs both architect and planner. DevLab should not try to infer that the architect can be skipped for deployment-spec-only changes: the deployment spec may alter architecture, operability, boundaries, packaging, validation strategy, or profile needs. The bounded and reviewable rule is simple: any spec reconciliation re-runs architecture review of the design plan first, then planning.

`--revise` does not by itself advance planning generation. Generation advancement is tied to reconciling committed spec content changes against an existing baseline:

- First `devlab plan --revise`: treat as initial planning, keep generation 1, and record the first spec baseline after success.
- `devlab plan --revise` with committed spec content changes: reconcile because the specs changed, advance exactly once from `N` to `N + 1`.
- `devlab plan --revise` with no committed spec content changes: run architect/planner against the current generation and refresh the baseline after success, but keep `planning.generation = N`.

This keeps the invariant simple: planning generation changes only when the committed specification content changes.

## Git Detection Details

Add a small spec-baseline helper, likely in a new focused module such as `spec_reconciliation.py` or in `workflow_state.py` if the code stays compact.

Inputs:

- root path
- spec paths:
  - `.devlab/specs/system`
  - `.devlab/specs/deployment`

Checks:

- `git status --porcelain -- .devlab/specs/system .devlab/specs/deployment` for staged/unstaged spec changes that should block reconciliation until committed.
- `git log --format=%H -1 -- .devlab/specs/system .devlab/specs/deployment` for the latest committed spec change, used for diagnostics and operator-facing messages.
- A stable spec content fingerprint for the current spec tree.

The fingerprint should represent committed spec content. Use Git primitives where practical, and do not parse spec Markdown outside the spec domain. Dirty or untracked spec files do not become part of the baseline until the operator commits them.

Result object:

```python
SpecReconciliationStatus(
    baseline_exists: bool,
    changed: bool,  # current_tree != baseline_tree
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
  - reject changed specs before role assessment or agent invocation with a `SessionError` whose message tells the user to run `devlab plan`.

The actual role forcing can reuse existing planning-revision behavior by deriving an internal `reconcile_plan` flag and a `next_generation` value when committed spec content changed. Public API callers can still pass `revise_plan`; CLI `devlab plan` should rely on automatic detection for normal reconciliation.

After successful planning/revision, update `.devlab/workflow.toml` through an explicit mutation helper and ensure the update is committed by automatic version control. Update `[planning].generation` only for committed spec content reconciliation, not for ordinary `--revise` runs without spec changes.

The orchestrator owns generation advancement. Agents should not edit `planning.generation`. A conservative flow is:

1. Detect committed spec content change.
2. Compute `next_generation = current_generation + 1`.
3. Pass `next_generation` and reconciliation context to architect/planner prompts.
4. Validate that new tasks and milestones are assigned to `next_generation`.
5. After the planner handoff succeeds, write `planning.generation = next_generation` and the new spec baseline.

If reconciliation fails midway, durable workflow state remains on the previous generation and `devlab run` continues to block because the spec baseline is still stale.

## Agent Prompt Changes

Planning revision prompts should distinguish ordinary explicit revision from spec reconciliation:

- Architect: compare changed system/deployment specs against the existing design plan, completed work, integrated milestones, and architecture-review findings.
- Planner: create current-generation milestones and tasks for all work still required by the revised plan. Previous-generation unfinished milestones and active tasks are stale planning artifacts; they should not be edited in place unless the planner intentionally carries their content forward into current-generation milestone/task structure.

Do not ask developer/reviewer/integrator roles to infer spec reconciliation policy. They should consume reconciled workflow state or report contradictions through existing blockers/findings.

## Task and Milestone Treatment

Spec reconciliation advances the planning generation. It does not close, delete, archive, or re-status non-closed tasks or unfinished milestones from older generations.

Core rules:

- A task's `status` is interpreted within the planning generation that created it.
- A task is actionable only when `task.planning_generation == workflow.planning.generation`.
- Older-generation open, in-review, or changes-requested tasks are stale planning artifacts, not current workflow work.
- Closed tasks from older generations remain historical completed work.
- A milestone's lifecycle status is interpreted within the planning generation that created it.
- A milestone is actionable only when `milestone.planning_generation == workflow.planning.generation`.
- Older-generation milestones that were not fully integrated and architecture-reviewed are stale planning artifacts, not current integration targets.
- Integrated or architecture-reviewed older-generation milestones remain historical delivered work.
- The planner creates new current-generation milestones and tasks for all work still required by the revised design/project plan.
- If content from an old task or milestone still applies, the planner should create current-generation structure that carries that work forward instead of mutating old-generation artifacts in place.

This reflects the truth of the workflow: old tasks and milestones may still be open relative to the plan generation that produced them, but that plan generation itself is no longer current.

Partially implemented milestones:

- Completed older-generation tasks remain evidence of work already delivered.
- The older-generation milestone remains as historical partial planning state if it was not integrated before reconciliation.
- Non-closed older-generation tasks in that milestone no longer count as remaining current scope.
- The revised plan defines current-generation milestone scope with current-generation milestones and tasks.
- If the old milestone goal still applies, the planner creates a new current-generation milestone that carries forward the relevant remaining work.
- If the old milestone goal changed materially, the planner creates a new current-generation milestone for the revised goal.

Milestone completion/integration logic must be generation-aware. A milestone is ready for integration only when it belongs to the current generation and its current-generation task set is complete. Older-generation stale tasks and unfinished milestones should be reported, but they must not block current workflow progress and must not be counted as implemented work.

This deliberately avoids a mass dismissal rule for all non-closed tasks and unfinished milestones. It keeps the audit trail honest, avoids new lifecycle statuses, and avoids reason fields such as `closure_kind`, while still allowing code to present "really open" current work clearly.

## Documentation Updates

Update:

- `README.md`: present `devlab plan` as spec/workflow reconciliation and `devlab run` as implementation continuation.
- `docs/design.md`: replace the current "idempotent planning preflight" language with the new command model.
- `docs/todo.md`: mark item 9 as planned once this design is accepted.
- `docs/plans/README.md`: list this plan as active until implemented.

## Test Plan

Focused tests:

- First `devlab plan` on initialized workspace records a spec baseline.
- First `devlab plan` records or defaults to planning generation 1.
- Subsequent `devlab plan` with unchanged specs remains a no-op.
- Subsequent `devlab plan` with dirty staged spec changes stops and asks the operator to commit them.
- Subsequent `devlab plan` with dirty unstaged spec changes stops and asks the operator to commit them.
- Dirty non-spec changes still stop planning before agent sessions.
- Committed spec content changes after the baseline automatically force architect/planner reconciliation without requiring `--revise`.
- Successful spec reconciliation advances planning generation.
- First `devlab plan --revise` does not advance beyond generation 1.
- `devlab plan --revise` with committed spec content changes advances exactly once.
- `devlab plan --revise` without committed spec content changes does not advance planning generation.
- `devlab plan --revise` with a later spec commit whose content matches the stored baseline does not advance planning generation.
- Old-generation active tasks are not selected for development or review.
- Old-generation active tasks are reported as stale planning artifacts.
- Old-generation unfinished milestones are not selected for integration.
- Old-generation unfinished milestones are reported as stale planning artifacts.
- Milestone completion considers current-generation milestones and tasks, not stale older-generation artifacts.
- `devlab run` with changed specs stops before any non-planning role assessment or agent invocation and instructs the user to run `devlab plan`.
- `devlab plan --revise` refreshes the baseline even when no spec change is detected.
- `devlab status` or `doctor` can report stale spec baseline without mutating state, if we expose this diagnostically.

## Open Questions

1. Should the spec baseline store only the latest spec commit and content fingerprint, or should it also store a short list of changed spec files for better prompts and status output?
2. Should reconciliation produce a separate durable summary artifact, or are architect/planner handoffs plus edited plans/tasks sufficient?

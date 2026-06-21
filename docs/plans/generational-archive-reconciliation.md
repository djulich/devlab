# Generational Archive Reconciliation

Status: **implemented**. DevLab now archives the active workflow bundle for
fresh-generation planning, derives the active generation from archive directories,
removes active task/milestone `planning_generation` front matter, supports
`devlab plan --replace-plan` and `devlab plan --adopt-existing`, and blocks
`devlab run` until committed spec changes are reconciled. Remaining ideas at the
end of this document are follow-up hardening options, not active implementation
instructions.

## Problem

The current spec-change reconciliation design keeps all task and milestone files in
the active workspace and uses `planning_generation` metadata to decide which files
are actionable. That works mechanically, but it makes the active DevLab state harder
to reason about:

- active task and milestone directories contain stale historical work;
- task and milestone IDs are globally increasing even after a plan replacement;
- milestones can mix historical and current task membership;
- handoffs and history can reference task IDs that no longer describe current work;
- reconciliation needs special rules for when old tasks or milestones may be reused.

Starting DevLab on an existing project has a similar shape. DevLab must create a
current planning graph from repository reality and current specs. Spec reconciliation
is the stronger case because prior DevLab planning can be used as context, but the
desired output is still a coherent current plan.

## Decision

Replace in-place generation filtering with a first-class generation archive model.

The active DevLab directories describe only the current planning generation:

```text
.devlab/
  tasks/
  milestones/
  findings/
  history/
  session-artifacts/
  logs/agents/
  plans/
  workflow.toml
```

When DevLab performs fresh-generation planning, it archives the active workflow
bundle as an immutable generation and starts the active planning graph anew:

```text
.devlab/
  generations/
    0001/
      tasks/
      milestones/
      findings/
      history/
      session-artifacts/
      logs/agents/
      plans/
      workflow.toml
      generation.toml
```

Task and milestone IDs are generation-local. After reconciliation, the active
generation may start again at `T0001` and `M1`. Archived history remains
traceable because task, milestone, handoff, log, and workflow files are archived
together as one coherent generation set.

## Workflow State

Do not store active generation numbers in `.devlab/workflow.toml`.

With archive-scoped generations, selectors do not need `planning.generation`.
The active generation can be derived from the filesystem:

- no archived generations: active generation is 1;
- highest archive `NNNN`: active generation is `NNNN + 1`;
- previous generation, if any, is the highest archived generation.

Keep `.devlab/workflow.toml` focused on active workflow control:

```toml
version = 1

[planning]
complete = false

[specs]
last_planned_spec_commit = "<latest committed spec revision planned by DevLab>"
```

Each archived generation has its own manifest:

```toml
version = 1
generation = 1
archived_at = "2026-06-21T12:34:56Z"
reason = "spec_reconciliation"
spec_baseline = "<baseline commit, if known>"
```

## Command Semantics

### `devlab plan`

`devlab plan` auto-detects the normal fresh-planning cases:

- **First planning run**: create generation 1. If DevLab detects repository source,
  tests, packaging, deployment files, or tooling, it should use existing-project
  prompt context; otherwise it may use greenfield prompt context.
- **Committed spec change after a recorded baseline**: archive the active generation
  and create a fresh active generation from current specs, current repository state,
  and summarized previous-generation context.
- **No changed specs and active planning exists**: keep the current no-op behavior
  unless `--revise` or `--replace-plan` is supplied.

`devlab run` never auto-reconciles specs. If committed specs differ from the recorded
baseline, it stops and instructs the operator to run `devlab plan`.

### `devlab plan --adopt-existing`

Explicitly treat the repository as an already-started project on the first planning
run. This affects prompt mode: architect and planner must inspect existing code,
tests, tooling, packaging, and deployment state before planning new work.

Validation:

- allowed only when no active DevLab plan exists;
- rejected when an active DevLab plan exists;
- rejected when combined with `--replace-plan`.

This option is for cases where automatic greenfield-vs-existing detection may be
wrong or too weak.

### `devlab plan --replace-plan`

Force fresh-generation planning when DevLab did not auto-detect a spec reconciliation
requirement.

Validation:

- allowed only when an active DevLab plan exists;
- rejected when no active DevLab plan exists;
- rejected when combined with `--adopt-existing`.

This option means: archive the active DevLab generation and create a fresh current
plan because the operator considers the current plan stale or unsuitable.

### `devlab plan --mark-specs-planned`

Future escape hatch for typo-only, formatting-only, or otherwise plan-neutral spec
commits. It should update the recorded spec baseline without archiving, invoking
agents, or changing the active plan. This is intentionally separate from incremental
reconciliation.

Do not implement incremental reconciliation until real usage proves fresh-generation
planning too noisy.

## Active Plan Detection

Define one helper for CLI validation:

```python
has_active_plan(root) -> bool
```

It should return true if active DevLab planning or execution artifacts exist, for
example:

- non-empty `.devlab/plans/design-plan.md`;
- non-empty `.devlab/plans/project-plan.md`;
- `.devlab/tasks/*.md`;
- `.devlab/milestones/*.toml`;
- `.devlab/history/*`.

Archived generations alone do not mean there is an active plan. If archived
generations exist but active planning files are missing after a failed replacement,
DevLab should report a recovery/repair state rather than silently treating the
workspace as a normal first-planning run.

## Archive Operation

Fresh-generation planning must require a clean worktree before archiving.

Archive these active paths together when they exist:

- `.devlab/tasks/`
- `.devlab/milestones/`
- `.devlab/findings/`
- `.devlab/history/`
- `.devlab/session-artifacts/`
- `.devlab/logs/agents/`
- `.devlab/plans/`
- `.devlab/workflow.toml`

Do not archive these target-owned configuration or requirement inputs:

- `.devlab/specs/`
- `.devlab/config/`
- `.devlab/adr/` if present
- other non-DevLab repository files

After archiving, recreate the active directory skeleton needed for new sessions.
The architect and planner should see current repository files and summarized archive
context, but archived files are read-only history and must not be mutated.

## Prompt Context

Fresh-generation planning should include prior DevLab state only as context:

- previous design and project plan summaries;
- completed work and integrated milestones;
- unresolved findings or known failed integration/review outcomes;
- stale active tasks from the archived generation, if any.

The planner output is not a patch over archived tasks. It creates a complete active
project plan and current task files for remaining/current work.

For existing-project adoption, use the same planning machinery without archive
context. The prompt emphasis is repository inspection rather than prior DevLab state.

## File Format Changes

Remove `planning_generation` from active task and milestone file formats once the
archive model replaces in-place filtering. Generation is represented by directory
scope, not front matter.

Consequences:

- active selectors read all active task and milestone files;
- milestone generation stamping disappears;
- planner task generation stamping disappears;
- P1/P2-style generation metadata bugs are structurally avoided.

## Implementation Plan

1. Add `generations.py` with archive path helpers, generation-number derivation,
   manifest formatting/parsing, active-plan detection, and archive operations.
2. Add tests for archiving a complete active workflow bundle and deriving active
   generation from archives.
3. Add CLI/orchestrator options and validation for `--adopt-existing` and
   `--replace-plan`.
4. Wire spec-change `devlab plan` to archive the active generation automatically
   before architect/planner reconciliation.
5. Update prompt builders to support greenfield, adopt-existing, and
   previous-generation-context planning modes.
6. Convert workspace selectors to active-directory semantics and remove
   `planning_generation` filtering.
7. Remove task and milestone `planning_generation` parsing/writing once selectors
   no longer depend on it.
8. Update status/history diagnostics to report the active derived generation and
   archived generations.
9. Update docs and evaluations for existing-project adoption and spec reconciliation.

## Implemented Coverage

- First `devlab plan` with no active plan creates generation 1 without archiving.
- `devlab plan --adopt-existing` is allowed only with no active plan.
- `devlab plan --adopt-existing` is rejected when an active plan exists.
- `devlab plan --replace-plan` is rejected when no active plan exists.
- `devlab plan --replace-plan` archives an active generation and starts a fresh one.
- `devlab plan --adopt-existing --replace-plan` is rejected.
- Committed spec changes after a baseline cause plain `devlab plan` to archive and
  reconcile automatically.
- `devlab run` with stale committed specs stops before implementation roles.
- Archived tasks, milestones, findings, history, logs, and plans remain together in
  the same generation directory.
- Active task IDs can restart at `T0001` without conflicting with archived `T0001`.
- Active selectors ignore archived tasks and milestones.
- Planner sessions cannot mutate archived generation files.
- Existing-project adoption prompt context includes repository inspection guidance.
- Spec reconciliation and replacement prompts tell agents that the prior active
  planning graph was archived and that the new plan must be complete.

## Follow-Up Options

- What exact recovery command should handle a failure after archive creation but
  before a new active plan is completed?
- How much previous-generation detail should prompts include before context-size
  reduction becomes necessary?
- Should fresh-generation planning prompts include summarized previous-generation
  context, beyond telling agents that the prior graph was archived?
- Should generation archive manifests store the commit that performed the archive
  after automatic version control commits the session?

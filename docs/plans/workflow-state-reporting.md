# Workflow State Reporting

## Problem

Operators need a quick answer to "what state is this DevLab target project in?"
without manually inspecting `.devlab/` files, project artifacts, Git history, or
archived handoffs.

Existing commands cover adjacent needs:

- `devlab status` reports the next workflow role and current generation.
- `devlab status --verbose` adds provider, prompt, milestone, and finding state.
- `devlab diagnostics --verbose` reports historical sessions, task cycles,
  profiles, findings, generations, and artifact hygiene.
- `devlab history --json` exposes archived session history.

None of these is a lifecycle summary. They do not directly answer whether the
target started as greenfield or adopted existing work, whether design/planning
has happened, how many revisions happened, or how often spec reconciliation
replaced the active planning generation.

## Decision

Add a read-only `devlab workflow-state` command for lifecycle reporting.

The command should combine:

1. current durable workflow state;
2. current workspace artifacts;
3. generation archives;
4. archived session history;
5. a new orchestrator-owned lifecycle event log for future precision.

Use inference for target workspaces created before the lifecycle event log
exists. Inferred fields must be labeled as inferred or unknown when exact
provenance is not available.

Do not overload `devlab status`. `status` remains "what happens next?" while
`workflow-state` becomes "what lifecycle/provenance state is this target in?"

## Command

```bash
devlab workflow-state [--root PATH] [--json]
```

Text output should be compact and operator-facing:

```text
Workflow state:
Project mode: adopted existing project
Lifecycle phase: implementation
Next role: developer
Planning: complete
Design plan: present
Project plan: present
Active generation: 2
Archived generations: 1

Spec reconciliation:
Baseline commit: abc1234
Specs changed since baseline: no
Dirty spec paths: none
Reconciliations: 1
Plan replacements: 0

Planning history:
Architect sessions: 2
Planner sessions: 3
Greenfield planning runs: 0
Adoption planning runs: 1
Plan revisions: 1
Reconciliations: 1

Current work:
Tasks: 7 total, 3 closed, 4 active
Milestones: 2 total
Findings: 1 open, 2 resolved
```

The JSON output should expose the same information as a stable object for tools
and tests.

## Lifecycle Event Log

Add an append-only JSON Lines file:

```text
.devlab/workflow-events.jsonl
```

The orchestrator owns this file. Role agents must not edit it directly. The file
is historical audit/provenance state, not workflow-control state. Continue to use
`.devlab/workflow.toml` for current control state such as planning completeness
and spec baselines.

Initial event types:

```json
{"version":1,"type":"init","at":"2026-06-22T12:00:00+00:00"}
{"version":1,"type":"plan_started","at":"...","mode":"greenfield","generation":1}
{"version":1,"type":"plan_started","at":"...","mode":"adopt_existing","generation":1}
{"version":1,"type":"plan_started","at":"...","mode":"revise","generation":1}
{"version":1,"type":"generation_archived","at":"...","mode":"spec_reconciliation","generation":1,"spec_baseline":"abc123"}
{"version":1,"type":"generation_archived","at":"...","mode":"replace_plan","generation":1,"spec_baseline":"abc123"}
{"version":1,"type":"plan_completed","at":"...","mode":"spec_reconciliation","generation":2,"planning_complete":true}
```

Keep event payloads deliberately small. Do not store prompt text, handoff prose,
or large summaries. Those remain in existing handoff/log artifacts.

## Project Mode

Report one of:

- `greenfield`
- `adopted existing project`
- `unknown`

With lifecycle events:

- first successful planning mode `adopt_existing` means `adopted existing project`;
- first successful planning mode `greenfield` means `greenfield`.

Without lifecycle events:

- if archived events are absent, report `unknown`;
- do not infer greenfield from lack of evidence, because older workspaces may
  have used `--adopt-existing` before event logging existed.

## Lifecycle Phase

Compute phase from current durable state:

- `uninitialized`: `.devlab/manifest.toml` or `.devlab/` is absent.
- `awaiting design`: no active non-empty design plan and next role is architect.
- `awaiting planning`: design exists, but no active project plan/tasks or next
  role is planner.
- `implementation`: open or reviewable tasks exist.
- `integration`: milestone state indicates integration or architecture review is
  pending.
- `complete`: no next role and all known tasks/milestones/findings are complete.
- `blocked or inconsistent`: reporting encounters invalid state or no role can
  proceed while incomplete work remains.

Reuse `WorkspaceSnapshot.assess_state()` for next-role selection. Do not mutate
or repair state while reporting.

## Revisions And Reconciliations

Use lifecycle events when available:

- plan revisions: count `plan_started` events with `mode = "revise"`;
- greenfield/adoption planning runs: count `plan_started` events by mode;
- spec reconciliations: count `generation_archived` events with
  `mode = "spec_reconciliation"`;
- plan replacements: count `generation_archived` events with
  `mode = "replace_plan"`.

Fallback inference for older workspaces:

- spec reconciliations: count generation manifests whose `reason` is
  `spec_reconciliation`;
- plan replacements: count generation manifests whose `reason` is
  `replace_plan`;
- architect/planner session counts: derive from `.devlab/history`;
- design/plan revisions: report `unknown` unless lifecycle events identify the
  command mode. Extra architect/planner sessions alone are not precise enough,
  because they may be initial incremental planning, adoption, revision,
  reconciliation, or architecture review.

## Implementation Notes

Add a small module, likely `workflow_events.py`, that owns:

- event dataclasses or typed dictionaries;
- append helper;
- tolerant reader that skips malformed future/unknown event types only if they
  are not needed for current reporting;
- count/projection helpers used by `workflow_state_report.py`.

Add a reporting module, likely `workflow_state_report.py`, that owns:

- a `WorkflowStateReport` dataclass;
- `build_workflow_state_report(root)`;
- `format_workflow_state_report(report)`;
- `to_json`/`as_dict` behavior matching the diagnostics style.

Do not put this logic in `cli.py`; keep `cli.py` to argument parsing and command
dispatch.

Hook event writing into:

- `init_workspace`: append `init` after a successful initialization;
- `run_loop` planning-only path: append `plan_started` with mode
  `greenfield`, `adopt_existing`, `revise`, `replace_plan`, or
  `spec_reconciliation`;
- generation archiving path: append `generation_archived`;
- successful planning completion: append `plan_completed` after the final
  planner/architect planning run updates durable workflow state.

If a command fails before completing, keep either no completion event or an
explicit failed event only if it proves useful later. The first implementation
should avoid noisy failed-event semantics.

## Documentation Updates

Update:

- `README.md` command list;
- `docs/operator-guide.md` inspection section;
- `docs/design.md` durable workflow-state discussion;
- `docs/release-policy.md` compatibility surfaces if the event log becomes a
  stable file format.

## Test Plan

Focused tests:

- CLI help includes `workflow-state`.
- Initialized workspace reports awaiting design, active generation 1, no
  archived generations, unknown project mode, and planning incomplete.
- JSON output contains stable keys for project mode, lifecycle phase, planning,
  specs, generations, history counts, and current work counts.
- A workspace with design/project plans, tasks, milestones, and findings reports
  the expected current work summary.
- Lifecycle events classify greenfield and adopted projects without relying on
  prose or handoff parsing.
- `--revise`, `--replace-plan`, and spec reconciliation modes increment the
  correct counters.
- Older workspaces without events infer reconciliation/replacement counts from
  generation manifests and report revision counts as unknown.
- Reporting commands do not mutate `.devlab/` state.
- Malformed workflow state surfaces a clear reporting error rather than silently
  producing misleading lifecycle output.

## Open Questions

- Should the command name remain `workflow-state`, or should `state` be added as
  an alias after the report stabilizes?
  -> ANSWER: Keep `workflow-state` for the first implementation.
- Should failed plan/run attempts be represented in the event log, or should this
  command focus only on successful lifecycle transitions?
  -> ANSWER: I would prefer to have the failed attempts in the event log as well, if their addition doesn't cause too much "noise" or add too much code complexity.
- Should lifecycle events be archived with active generations during spec
  reconciliation, or stay cross-generation at `.devlab/workflow-events.jsonl`?
  Recommendation: keep them cross-generation, because they describe the target
  workflow timeline rather than the active planning graph.
  -> ANSWER: Keep them cross-generation

# Orchestrator-Owned Workflow State

## Problem

`.devlab/workflow.toml` is durable workflow-control state, but ownership is currently mixed:

- the orchestrator reads and validates `.devlab/workflow.toml`;
- planner agents are instructed to edit `[planning].complete` directly;
- future workflow-control fields, such as planning generation and spec baselines, would also semantically fit in `.devlab/workflow.toml`.

This mixed ownership is brittle. If DevLab adds strict orchestrator-owned fields to the same TOML file, planner agents would need to preserve unrelated structured state while editing one boolean. That makes a central workflow state file harder to extend safely.

## Decision

Make `.devlab/workflow.toml` orchestrator-owned. Agents may receive summarized workflow state in prompts and may report requested state changes through structured handoff fields, but they must not edit `.devlab/workflow.toml` directly.

The first ownership change is `[planning].complete`:

- The planner decides whether planning is complete.
- The planner reports that decision in its handoff.
- The orchestrator parses and validates the planner handoff.
- The orchestrator writes `[planning].complete` to `.devlab/workflow.toml`.

This keeps the existing operator-visible incremental planning behavior while making workflow state mutation programmatic and easier to extend.

## Handoff Contract

Add a planner handoff section:

```md
## Planning State
planning_complete = true
```

Rules:

- Planner handoffs must include `## Planning State`.
- The section must contain exactly one TOML-style boolean assignment: `planning_complete = true` or `planning_complete = false`.
- Non-planner handoffs should not include this section.
- `planning_complete = false` means future planner sessions are still needed.
- `planning_complete = true` means all required in-scope specification work is represented by durable tasks/milestones or explicitly out of scope.

The section should appear after the existing required handoff sections. It should not interrupt the current required section order.

## Workflow Behavior

Planner sessions:

1. Orchestrator invokes the planner with the current planning completion state summarized in the prompt.
2. Planner creates or updates plans/tasks as usual.
3. Planner writes `## Planning State` in the handoff.
4. Orchestrator parses the handoff.
5. Orchestrator updates `.devlab/workflow.toml` with the reported `planning_complete` value.
6. Orchestrator continues existing post-handoff processing and automatic version-control commit behavior.

Validation:

- A planner handoff missing `## Planning State` is invalid.
- A planner handoff with malformed planning state is invalid.
- A non-planner handoff with `## Planning State` is invalid unless we intentionally decide to tolerate and ignore it.
- The exhausted-backlog guard should check the orchestrator-updated workflow state after planner handoff processing.

The old safety rule remains: when the planner is invoked because the backlog is exhausted and `[planning].complete` was false, the planner must either create durable work or report `planning_complete = true`.

## File Ownership

`.devlab/workflow.toml` remains the single durable workflow-control state file.

Owned by the orchestrator:

- `version`
- `[planning].complete`
- future `[planning].generation`
- future spec baseline fields such as `[specs].last_planned_tree`

Owned by agents:

- task files
- milestone/project planning content
- role handoffs
- requested workflow-state changes expressed in handoff fields

Agents should not edit `.devlab/workflow.toml` directly.

## Implementation Notes

- Extend `handoffs.py` to recognize optional `## Planning State` after the required handoff sections.
- Add a strict parser for planner planning state. Use TOML parsing or an equivalent strict one-line parser; reject extra fields and non-boolean values.
- Extend `Handoff` with a planner planning-state accessor.
- Update planner prompt instructions:
  - remove instructions to edit `.devlab/workflow.toml`;
  - require `## Planning State`;
  - explain when to report `planning_complete = true` or `false`.
- Update prompt assembly so planner context still shows the current planning completion value, but describes it as orchestrator-owned state.
- Update orchestrator planner handoff processing to write `[planning].complete` programmatically.
- Add a workflow-state mutation helper rather than ad hoc text edits.
- Preserve existing TOML compatibility and error messages for invalid workflow state.
- Keep reporting/diagnostic paths read-only.

## Documentation Updates

Update:

- `docs/design.md`: describe `.devlab/workflow.toml` as orchestrator-owned workflow-control state.
- `docs/plans/incremental-milestone-planning.md`: add a note that the original implementation let planners edit the file directly, but ownership is being moved to the orchestrator.
- `src/devlab/resources/prompts/role-planner.md`: remove direct workflow TOML editing instructions.
- `src/devlab/resources/prompts/conventions.md`: document the planner-only `## Planning State` handoff section.

## Test Plan

Focused tests:

- Planner handoff with `planning_complete = true` updates `.devlab/workflow.toml` to `complete = true`.
- Planner handoff with `planning_complete = false` updates or preserves `complete = false`.
- Planner handoff missing `## Planning State` is rejected.
- Planner handoff with malformed planning state is rejected.
- Planner handoff with extra planning-state fields is rejected.
- Non-planner handoff with `## Planning State` is rejected or explicitly ignored, depending on the implementation decision.
- Exhausted-backlog planner invocation still passes when the planner creates durable work and reports `planning_complete = false`.
- Exhausted-backlog planner invocation still passes when the planner creates no durable work but reports `planning_complete = true`.
- Exhausted-backlog planner invocation still fails when the planner creates no durable work and reports `planning_complete = false`.
- Prompt logs for planner sessions no longer instruct agents to edit `.devlab/workflow.toml` directly.
- `devlab doctor` continues to validate malformed `.devlab/workflow.toml`.

## Follow-On Work

Spec change reconciliation depends on this plan. Once `.devlab/workflow.toml` is orchestrator-owned, the reconciliation plan can safely add `[planning].generation` and `[specs]` fields to the same file without requiring agents to preserve strict TOML state manually.

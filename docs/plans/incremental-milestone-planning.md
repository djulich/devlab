# Incremental Milestone Planning

## Problem

A planner may intentionally plan only the next milestone and leave later work as prose. Before this change, once that milestone completed, DevLab saw no open tasks and stopped, even when the project plan still contained future milestone candidates.

## Decision

Add explicit durable workflow state in `.devlab/workflow.toml`:

```toml
version = 1

[planning]
complete = false
```

Semantics:

- `planning.complete = false`: backlog exhaustion routes back to the planner.
- `planning.complete = true`: backlog exhaustion means the workflow may stop.

The flag is intentionally minimal. We do not add a `next_focus` field yet; the follow-up planner can inspect specs, plans, closed tasks/milestones, history, and repository state to decide what to plan next.

## Scope Implemented

- `devlab init` creates `.devlab/workflow.toml` with planning incomplete.
- `WorkspaceSnapshot.assess_state()` routes to planner when all known work is closed but planning is incomplete.
- Planner prompts include the current planning completion state and instructions for reporting the desired state in the planner handoff.
- Planner role instructions permit incremental milestone planning and require `planning_complete = true|false` in the handoff's `## Planning State` section.
- The orchestrator owns `.devlab/workflow.toml`, parses the planner handoff, and updates `planning.complete` programmatically.
- `devlab doctor` validates workflow state when present in initialized workspaces.
- The orchestrator rejects a follow-up planner session invoked on exhausted backlog if the planner neither creates new durable work nor reports `planning_complete = true`.

## Future Extension

The same `.devlab/workflow.toml` file can host future phase-completion state for multi-session architecture planning, for example an `[architecture] complete = false` section, but architecture semantics are intentionally not implemented in this slice.

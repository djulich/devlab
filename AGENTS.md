# AGENTS.md

For agents changing DevLab itself. Packaged prompts in `src/devlab/resources/prompts/` are for DevLab-spawned worker agents.

## Goal

DevLab is a reusable CLI/package that turns repository-stored specs, plans, and tasks into reviewed software changes via bounded role-based agent sessions.

## Design constraints

- Orchestrator decides what to do; providers decide how to invoke agents; trackers decide how to store state.
- Keep packaged role prompts minimal; enforce workflow rules in code/tests where practical.
- Keep durable workflow state in repository files, not conversational memory or hidden runtime state.
- DevLab operates on a target workspace; dogfooding must not assume the target is this repo.
- Preserve bounded sessions: one role per session, one task per developer/reviewer session.
- Keep task storage behind `task_tracker.py`; do not parse task files elsewhere.
- Use workspace boundaries: `WorkspaceSnapshot` for cached reads; `Workspace`/handles for mutations.
- Reporting/validation paths (`status`, `doctor`, prompt assembly, prompt context) must not mutate state.
- Keep provider-specific invocation in `agents.py`, not orchestration.

## Durable knowledge

- `CONTEXT.md`: DevLab terminology.
- `docs/adr/`: durable architectural decisions that are hard to reverse, surprising without context, and trade-off based.
- `AGENTS.md`: operational instructions for coding agents.
- `docs/design.md`: human-oriented overview; do not make it the only source for agent-critical terms, constraints, or decisions.

## Module boundaries

- `workspace.py`: shared constants/utilities, `Workspace`, mutation handles, `WorkspaceSnapshot` queries.
- `orchestrator.py`: workflow loop, session lifecycle, handoff processing, error recovery.
- `prompts.py`: system/session prompt assembly from read-only state.
- `task_tracker.py`, `milestones.py`, `findings.py`, `profiles.py`: file-backed domain state.
- `agents.py`: provider-specific agent invocation.
- `prompt_context.py`: prompt size measurement/reporting, not prompt construction.

## Coding standards

- Preserve separation of concerns; put behavior in the owning module/abstraction.
- Prefer domain names: task, milestone, finding, profile, handoff, provider, workspace.
- Add concise docstrings only when they clarify purpose, contracts, invariants, or tradeoffs.
- Add focused tests for behavior changes, especially state transitions, file formats, CLI output, and validation errors.

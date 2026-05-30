# AGENTS.md

For agents changing DevLab itself. Packaged prompts in `src/devlab/resources/prompts/` are for DevLab-spawned worker agents.

## Goal

DevLab is a reusable CLI/package that turns repository-stored specs, plans, and tasks into reviewed software changes via bounded role-based agent sessions.

DevLab is developed and maintained by AI agents. Code and project structure must be optimized for agent comprehension: minimize the files an agent must read to understand a domain, keep module boundaries obvious, and prefer one well-organized file over several cross-referencing files when the coupling is tight.

## Design constraints

- Orchestrator decides what to do; providers decide how to invoke agents; trackers decide how to store state.
- Keep packaged role prompts minimal; enforce workflow rules in code/tests where practical.
- Keep durable workflow state in repository files, not conversational memory or hidden runtime state.
- DevLab operates on a target workspace; dogfooding must not assume the target is this repo.
- Preserve bounded sessions: one role per session, one task per developer/reviewer session.
- Keep task storage behind `task_tracker.py`; do not parse task files elsewhere.
- Use workspace boundaries: `WorkspaceSnapshot` for cached reads; `Workspace`/handles for mutations.
- Reporting/validation paths (`status`, `doctor`, prompt assembly, prompt context) must not mutate state.
- DevLab may invoke deployment tools via target-owned verification commands, but must not install missing host tools; report them as unverified user/CI prerequisites.
- Keep provider-specific invocation in `agents.py`, not orchestration.

## Durable knowledge

- `CONTEXT.md`: DevLab terminology.
- `docs/adr/`: durable architectural decisions that are hard to reverse, surprising without context, and trade-off based.
- `AGENTS.md`: operational instructions for coding agents.
- `docs/design.md`: human-oriented overview; do not make it the only source for agent-critical terms, constraints, or decisions.

## Module boundaries

Workflow core:
- `orchestrator.py`: workflow loop, session lifecycle, handoff processing, error recovery.
- `workspace.py`: mutation boundary (`Workspace`/handles) and cached read-only view (`WorkspaceSnapshot`).
- `handoffs.py`: handoff parsing and validation.
- `agents.py`: provider-specific invocation, not orchestration logic.
- `agent_config.py`: `agents.toml` loading and role/provider resolution.

Domain state (file-backed trackers):
- `task_tracker.py`, `milestones.py`, `findings.py`, `profiles.py`: one tracker per domain.
- `environment.py`: profile lifecycle command execution, not profile loading.

Prompts and knowledge:
- `prompts.py`: system/session prompt assembly from read-only state.
- `prompt_context.py`: prompt size reporting, not prompt construction.
- `knowledge.py`: target-workspace context and ADR discovery.

Git:
- `git.py`: low-level subprocess wrapper and read-only helpers.
- `version_control.py`: mutation-oriented operations; uses `git.py`.

Diagnostics:
- `workflow_diagnostics.py`: quality metrics facade.
- `workflow_history.py`: session/task-cycle derivation from handoff files.
- `history.py`: session history reporting from metadata files.
- `artifact_hygiene.py`: git-based artifact classification.
- `doctor.py`: workspace validation checks.
- `status.py`, `session_logging.py`, `cli.py`, `init.py`, `_logging.py`, `_toml.py`.

## Coding standards

- Preserve separation of concerns; put behavior in the owning module/abstraction.
- Prefer domain names: task, milestone, finding, profile, handoff, provider, workspace.
- Add concise docstrings only when they clarify purpose, contracts, invariants, or tradeoffs.
- Add focused tests for behavior changes, especially state transitions, file formats, CLI output, and validation errors.
- Only split a module when the extracted piece is a self-contained domain with minimal coupling back. If the extracted code needs types or functions from multiple other modules, it increases the import graph agents must navigate — keep it together instead.

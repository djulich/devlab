# AGENTS.md

## Scope

These instructions apply only to agents changing DevLab itself. They are not
instructions for DevLab-spawned role sessions in target workspaces. Those
sessions use the packaged prompts in `src/devlab/resources/prompts/` together
with target-workspace context.

## Goal

DevLab is a reusable CLI/package that turns repository-stored specs, plans, and tasks into reviewed software changes via bounded role-based agent sessions.

DevLab is developed and maintained by AI agents. Code and project structure must be optimized for agent comprehension: minimize the files an agent must read to understand a domain, keep module boundaries obvious, and prefer one well-organized file over several cross-referencing files when the coupling is tight.

## Design constraints

- Orchestrator decides what to do; providers decide how to invoke agents; trackers decide how to store state.
- Keep packaged role prompts minimal; enforce workflow rules in code/tests where practical.
- Keep durable workflow state in repository files, not conversational memory or hidden runtime state.
- DevLab operates on a target workspace; do not assume the target is this repo or reintroduce checked-in root `.devlab/` workflow state for DevLab itself.
- Preserve bounded sessions: one role per session, one task per developer/reviewer session.
- Keep task storage behind `task_tracker.py`; do not parse task files elsewhere.
- Use workspace boundaries: `WorkspaceSnapshot` for cached reads; `Workspace` domain handles (`workspace.tasks()`, `workspace.findings()`, `workspace.milestones()`) for mutations. Direct tracker access is lower-level infrastructure for tracker modules/tests and read-only diagnostics when no snapshot helper exists.
- Reporting/validation paths (`status`, `doctor`, prompt assembly, prompt context) must not mutate state.
- DevLab may invoke deployment tools via target-owned verification commands, but must not install missing host tools; report them as unverified user/CI prerequisites.
- Keep provider-specific invocation in `agents.py`, not orchestration.
- Preserve the possibility of separating a domain-neutral workflow kernel from domain-specific workflow packages. For each new workflow capability, explicitly distinguish reusable workflow mechanics—such as bounded session requests, durable state, validated handoffs, provenance, interruption, and resume—from software-development policy—such as eligible requesting roles, planning effects, task transitions, artifact meaning, and required follow-up.
- Keep DevLab's current software-workflow contracts explicit and enforced. Do not introduce speculative generic abstractions, generic names for software-specific concepts, or configuration that moves correctness-critical policy back into prompts. Extract a kernel interface only when its semantics are genuinely domain-neutral and supported by a concrete second workflow.

## Durable knowledge

- `CONTEXT.md`: DevLab terminology.
- `docs/vision.md`: fundamental motivation, suitable target projects, and the prospective kernel/domain-package direction.
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
- `roles.py`: provider-independent workflow role definitions and prompt/environment needs.

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
- `_files.py`: low-level atomic text replacement for authoritative workflow files.

## Coding standards

- Preserve separation of concerns; put behavior in the owning module/abstraction.
- Prefer precise names from the owning domain. Within DevLab's software workflow, prefer task, milestone, finding, profile, handoff, provider, and workspace. Use domain-neutral names only for contracts whose semantics are genuinely independent of software development.
- Add concise docstrings only when they clarify purpose, contracts, invariants, or tradeoffs.
- Add focused tests for behavior changes, especially state transitions, file formats, CLI output, and validation errors.
- Run the complete development validation (`make check`, including Ruff, ty, and pytest) for code changes.
- Only split a module when the extracted piece is a self-contained domain with minimal coupling back. If the extracted code needs types or functions from multiple other modules, it increases the import graph agents must navigate — keep it together instead.

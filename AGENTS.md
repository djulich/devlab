# AGENTS.md

## Project Goal

This project is DevLab, a reusable CLI/package that orchestrates role-based agent sessions to turn repository-stored specifications, plans, and tasks into reviewed software changes.

## Scope of This File

This file is for agents changing DevLab itself. Packaged prompt resources in `src/devlab/resources/prompts/` are used for worker agents spawned by DevLab.

## DevLab Development Principles

The orchestrator decides *what* to do; providers decide *how* to invoke agents; trackers decide *how* to store state. When changing DevLab itself, preserve these design constraints:

- Keep packaged agent prompt files in `src/devlab/resources/prompts/` minimal. Do not add explanatory detail there unless the invoked role needs it to act correctly.
- Prefer implementing workflow rules in code over adding prompt instructions. The orchestrator/task tracker should enforce selection, status transitions, and validation where practical.
- Keep durable workflow state in repository files, not conversational memory or hidden runtime state.
- Treat DevLab as a reusable tool that operates on a target workspace; dogfooding in this repo must not add assumptions that the target is DevLab repo.
- Preserve bounded sessions: one role per session, and one task per developer/reviewer session.
- Keep task storage behind the task-tracker abstraction; do not spread file-backed task assumptions through unrelated code.
- Use the workspace access boundary for cross-tracker reads and mutations: `WorkspaceSnapshot` owns cached read-only state queries, while `Workspace` exposes first-class mutation handles such as `WorkspaceTask`, `WorkspaceMilestone`, and `WorkspaceFinding`.
- Keep reporting and validation commands non-mutating. `status`, `doctor`, prompt assembly, and prompt context reporting should read from snapshots rather than syncing or repairing workflow state.
- Keep concrete agent invocation behind the agent-provider abstraction; do not bake one agent CLI into orchestration logic.

## Durable Project Knowledge

Durable knowledge needed by future coding agents should not live only in `docs/devlab-design.md`. Treat that file as a human-oriented design overview that may duplicate or summarize authoritative agent-relevant sources.

When changing DevLab itself:

- Put terminology and domain-language clarifications in `CONTEXT.md` when that file exists.
- Put durable architectural decisions and rationale in `docs/adr/` when the decision is hard to reverse, surprising without context, and the result of a real trade-off.
- Put operational instructions for coding agents in this `AGENTS.md` file.
- Put executable workflow rules in code and tests, not prose-only documentation.
- Keep `docs/devlab-design.md` useful for humans, but do not make it the only place where agent-critical terminology, constraints, or decisions are recorded.

### Key module boundaries

- `workspace.py` owns shared workspace infrastructure: path constants, role definitions, file utilities, explicit workspace sync via `Workspace`, first-class mutation handles, and cached read-only cross-tracker queries via `WorkspaceSnapshot`.
- `orchestrator.py` owns the workflow loop (session lifecycle, handoff processing, error recovery). It may call explicit workspace mutations, but should use fresh snapshots for workflow decisions after mutations.
- `prompts.py` owns prompt assembly — system prompts and per-role session prompts built from read-only workspace snapshots.
- `task_tracker.py` owns task file parsing and status transitions. Other modules should use the `FileTaskTracker` API, not parse task files directly.
- `agents.py` owns agent invocation. Provider-specific logic (CLI flags, stdin protocols) belongs here, not in the orchestrator.
- `milestones.py`, `findings.py`, `profiles.py` each own their respective file-backed state. The orchestrator coordinates between them but should not duplicate their parsing or mutation logic.
- `prompt_context.py` owns prompt size measurement and threshold reporting; it should not implement prompt construction rules itself.

## Coding Standards

- Add concise docstrings for public modules, classes, and non-trivial functions. Docstrings should clarify purpose, contracts, invariants, or design tradeoffs — not restate what the code does.
- Preserve separation of concerns: put behavior in the module or abstraction that owns it, and avoid duplicating or leaking file formats, workflow rules, provider details, or environment assumptions across unrelated code.
- Prefer clear domain names over generic names. Use names that expose workflow concepts such as task, milestone, finding, profile, handoff, provider, and workspace.
- Add or update focused tests for behavior changes, especially state transitions, file formats, CLI output, and validation errors.

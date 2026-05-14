# AGENTS.md

## Project Goal

This project is DevLab, a reusable CLI/package that orchestrates role-based agent sessions to turn repository-stored specifications, plans, and tasks into reviewed software changes.

## Scope of This File

This file is for agents changing DevLab itself. Packaged prompt resources in `src/devlab/resources/prompts/` are used for worker agents spawned by DevLab.

## DevLab Development Principles

When changing DevLab itself, preserve these design constraints:

- Keep packaged agent prompt files in `src/devlab/resources/prompts/` minimal. Do not add explanatory detail there unless the invoked role needs it to act correctly.
- Prefer implementing workflow rules in code over adding prompt instructions. The orchestrator/task tracker should enforce selection, status transitions, and validation where practical.
- Keep durable workflow state in repository files, not conversational memory or hidden runtime state.
- Treat DevLab as a reusable tool that operates on a target workspace; dogfooding in this repo must not add assumptions that the target is DevLab repo.
- Preserve bounded sessions: one role per session, and one task per developer/reviewer session.
- Keep task storage behind the task-tracker abstraction; do not spread file-backed task assumptions through unrelated code.
- Keep concrete agent invocation behind the agent-provider abstraction; do not bake one agent CLI into orchestration logic.

## Coding Standards

- Prefer readable, explicit code over explanatory comments. Add concise docstrings/comments for public modules, classes, and non-trivial functions when they clarify purpose, responsibility, contracts, invariants, or design tradeoffs.
- Comments should explain why the code is shaped a certain way, not restate what nearby code does.
- Avoid comment noise for obvious variables, simple helpers, or implementation details that are clear from names and structure.
- Preserve separation of concerns: put behavior in the module or abstraction that owns it, and avoid duplicating or leaking file formats, workflow rules, provider details, or environment assumptions across unrelated code.
- Prefer clear domain names over generic names. Use names that expose workflow concepts such as task, milestone, finding, profile, handoff, provider, and workspace.
- Add or update focused tests for behavior changes, especially state transitions, file formats, CLI output, and validation errors.

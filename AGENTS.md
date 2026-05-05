# AGENTS.md

## Project Goal

This project is a harness that orchestrates role-based agent sessions to turn repository-stored plans and tasks into reviewed software changes.

## Scope of This File

This file is for agents changing the harness itself. `specs/development/*.md` is for worker agents spawned by the harness.

## Harness Development Principles

When changing the harness itself, preserve these design constraints:

- Keep agent input files in `specs/development/` minimal. Do not add explanatory detail there unless the invoked role needs it to act correctly.
- Prefer implementing workflow rules in code over adding prompt instructions. The orchestrator/task tracker should enforce selection, status transitions, and validation where practical.
- Keep durable workflow state in repository files, not conversational memory or hidden runtime state.
- Treat the harness as a reusable tool that operates on a target workspace; dogfooding in this repo must not add assumptions that the target is the harness repo.
- Preserve bounded sessions: one role per session, and one task per developer/reviewer session.
- Keep task storage behind the task-tracker abstraction; do not spread file-backed task assumptions through unrelated code.

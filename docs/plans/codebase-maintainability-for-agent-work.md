# Codebase Maintainability for Agent Work

## Goal

Close todo item 9 by reducing the amount of unrelated code an agent must load when working on orchestration, doctor checks, prompt assembly, or scripted evaluations.

## Outcome

Implemented. Doctor checks were split by validation domain behind the `doctor.py` facade, and reusable scripted-evaluation black-box checks moved to `tests/evaluations/checks.py`. Orchestrator and prompt assembly extraction were explicitly deferred because those modules remain cohesive and splitting them now would hide workflow/prompt policy rather than reduce agent context.

## Non-goals

- Do not split modules only to reduce line count.
- Do not move workflow policy out of `orchestrator.py`.
- Do not create abstractions that require agents to jump across more files to understand one behavior.

## Slice 1: Orchestrator internal seams

Keep `run_loop(...)` and workflow policy in `orchestrator.py`, but extract tightly scoped helpers only where they are self-contained:

- Move session metadata construction/log writing only if it can live behind one small module with no workflow decisions.
- Keep handoff outcome processing in `orchestrator.py` unless a pure validation/formatting helper emerges.
- Keep Git commit/tag policy visible near session processing; extract only low-level formatting helpers if they grow.

Acceptance:

- `orchestrator.py` remains the single place to understand role transitions and handoff side effects.
- Any extracted module has a narrow name and imports from at most the owning support modules it needs.
- Existing orchestrator tests continue to describe behavior without major rewrites.

## Slice 2: Doctor validation domains

Split `doctor.py` only along stable validation domains that can be understood independently:

- agent configuration validation
- prompt context validation
- workflow state validation for tasks/milestones/findings
- deployment spec diagnostics
- project knowledge diagnostics

Acceptance:

- `doctor.py` remains the public facade with `check_workspace(...)` and report formatting.
- Domain check modules are read-only and non-mutating.
- Tests remain grouped by observable doctor behavior, with new focused tests only if extraction exposes regressions.

## Slice 3: Scripted evaluation scenario families

Split `tests/evaluations/scripted_agents.py` by scenario family if it continues to grow:

- calculator/basic workflow
- HTTP API/static frontend
- deployment/compose
- stateful web API

Acceptance:

- Test imports stay simple through a small compatibility barrel or direct family imports.
- Shared black-box checks stay in `tests/evaluations/checks.py`; generated product helpers stay in `generated_products.py`.
- Scenario-specific agents/checks live together when that helps agents understand one evaluation without unrelated scenarios.

## Slice 4: Prompt assembly boundaries

Keep role/domain prompt assembly in `prompts.py` until a cohesive extraction is obvious. If needed, extract only formatting helpers that do not decide workflow:

- profile formatting
- spec section formatting
- domain overlay discovery/selection helpers

Acceptance:

- Workflow decisions remain outside prompt construction.
- Role prompt builders remain easy to find from `build_session_prompt(...)`.
- Prompt tests continue to assert behavior through public prompt builders.

## Close criteria

Todo item 9 can be removed when:

- Either the above slices are implemented, or each is explicitly deferred as not meaningful yet.
- `AGENTS.md` captures any resulting module-boundary guidance.
- `docs/todo.md` no longer contains open-ended maintainability bullets that are just standing coding standards.
- `uv run ruff check`, `uv run ty check`, and `uv run pytest -q` pass.

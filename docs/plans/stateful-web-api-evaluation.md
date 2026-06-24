# Stateful Web API Workflow Evaluation Plan

Status: scripted evaluation implemented as `stateful-web-api-happy-path`; opt-in live-agent evaluation implemented as `live-stateful-web-api-happy-path`; Claude and Codex live baselines are recorded in `docs/plans/stateful-web-api-live-baseline-2026-06-24.md`; additional provider baseline collection remains follow-up work.

## Goal

Add a workflow evaluation that is materially more complex than the CLI calculator and tiny echo HTTP API while remaining deterministic, fast, and dependency-light. The evaluation should prove that DevLab can drive a target project with multiple source files, project-owned commands, HTTP behavior, stateful request flows, tests/docs, Git hygiene, and normal session commit/tag behavior.

## Scenario

Add a scripted evaluation named `stateful-web-api-happy-path`.

Target system spec:

> Build a small Python JSON HTTP API for todo items. It must expose `/health`, create todos, list todos, delete todos by id, keep data in memory, and provide project-owned run/test commands.

Required behavior:

- `GET /health` returns JSON `{"status": "ok"}`.
- `POST /todos` with JSON `{"title": "..."}` creates an item and returns a top-level JSON object with integer `id` and `title` fields.
- `GET /todos` returns all current items as `{"todos": [...]}`.
- `DELETE /todos/{id}` deletes an item and returns exactly `{"deleted": <id>}`.
- Invalid JSON, missing title, empty title, or blank title returns a 4xx client error.
- Unknown routes return 404.
- State is in-memory only; persistence is not required.

Required project artifacts:

- application source under a small source tree, e.g. `src/todo_api/` or equivalent
- tests or a smoke-test script committed as product artifacts
- `Makefile` or scripts exposing project-owned commands, at minimum:
  - `make run` or documented equivalent run command
  - `make test` or documented equivalent validation command
- README or usage documentation
- `.gitignore` covering Python caches and local runtime artifacts

## Evaluation Harness Changes

1. Add a new scripted agent class, e.g. `StatefulWebApiScriptedAgent`, in `tests/evaluations/scripted_agents.py`.
2. Add helper writers for:
   - design plan
   - project plan
   - task file(s)
   - source files
   - test/smoke files
   - Makefile/docs/gitignore
3. Add a black-box check function that:
   - starts the server on a free localhost port
   - waits for `/health`
   - performs create/list/delete requests with `http.client`
   - verifies JSON response shape and state transitions
   - verifies invalid request behavior
   - terminates the server and captures stdout/stderr on failure
4. Add file/content checks for project-owned commands and docs.
5. Add `test_scripted_stateful_web_api_evaluation` to `tests/evaluations/test_scripted_workflow_evaluations.py`.
6. Reuse existing diagnostics assertions for:
   - completion
   - expected role sequence
   - prompt/log metrics
   - task/milestone closure
   - session commits
   - milestone tag
   - Git-based artifact hygiene

## Expected Workflow Shape

Initial deterministic version should use one implementation task unless this hides important behavior.

Expected roles:

```text
architect -> planner -> developer -> reviewer -> integrator -> architect
```

Expected sessions: `6`.

Task expectations:

- One task may be enough if it includes source, tests/smoke, docs, Makefile, and ignore rules.
- If the scripted/live versions show oversize behavior, split into two tasks later: implementation and validation/docs.

## Boundaries

- Do not introduce third-party web framework dependencies in the first version. Use Python standard library HTTP support so the evaluation is stable in isolated CI and temp repos.
- Do not run target-owned `pytest` from the harness yet; use black-box checks directly in the evaluation harness.
- Do not add frontend dependencies in this task.
- Do not require container or deployment tools here; deployment-specific evaluations are tracked under the deployment TODO.

## Follow-up Live Evaluation

The opt-in live-agent version is enabled with `DEVLAB_LIVE_EVALS=1 DEVLAB_LIVE_STATEFUL_WEB_API=1`. Its checks remain black-box and provider-independent, with quality diagnostics initially warning rather than failing on hygiene issues unless correctness breaks. Passing Claude and Codex baselines were collected on 2026-06-24; remaining work is to collect additional baseline outcomes across local provider environments if available.

## Appendix: Qualitative Provider Assessment

The Claude and Codex live baselines both passed the deterministic scenario checks,
but the generated target projects differed in project shape and validation
strength.

For this small stateful API scenario, the Codex target is qualitatively stronger
overall. It delivered the product in one compact implementation task, kept the
API implementation cohesive, documented explicit behavior choices, and made the
target-owned `make test` command run the full validation set: `ruff check`,
`ruff format --check`, whole-repo `ty check`, and `pytest`. Its tests cover API
behavior, invalid inputs, delete behavior, unknown routes, and the actual module
startup path. The injected store/handler design also avoids awkward global state
in tests.

The Claude target is also correct and clean, but it is more workflow-shaped than
product-shaped for this scope: it created a separate profile task, scaffold task,
implementation task, separate store module, separate store tests, and a generated
profile that type-checks only `src/`. That structure could be useful if the API
grew, and the separate `store.py` improves extensibility, but it adds ceremony
for a tiny standard-library API. A whole-repo `uv run ty check` also reports a
test fixture annotation issue in the Claude target, even though the configured
profile validation passes.

Summary assessment:

- Correctness: tie; both pass the black-box evaluation.
- Target validation quality: Codex is stronger.
- Implementation simplicity for this scope: Codex is stronger.
- Extensibility: Claude has a slight advantage from the separated store module.
- Workflow efficiency: Codex is stronger.
- Overall target quality for this scenario: Codex is stronger.

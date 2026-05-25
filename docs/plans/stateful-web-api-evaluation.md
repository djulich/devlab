# Stateful Web API Workflow Evaluation Plan

Status: scripted evaluation implemented as `stateful-web-api-happy-path`; opt-in live-agent evaluation implemented as `live-stateful-web-api-happy-path`; provider baseline collection remains follow-up work.

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

The opt-in live-agent version is enabled with `DEVLAB_LIVE_EVALS=1 DEVLAB_LIVE_STATEFUL_WEB_API=1`. Its checks remain black-box and provider-independent, with quality diagnostics initially warning rather than failing on hygiene issues unless correctness breaks. Remaining work is to collect baseline outcomes across local provider environments.

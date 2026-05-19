# Remaining DevLab Workflow Evaluations Plan

Status: implemented except for collecting baseline live-agent outcomes and refining diagnostics from real failures. The harness was refactored, a tiny stdlib HTTP/API scripted scenario was added, skipped-by-default live evaluations were added, and diagnostics can be exported with `DEVLAB_EVAL_RESULTS_DIR`.

## Readiness assessment

We are ready to address the remaining TODO #3 work.

No blocking reason is apparent:

- Deterministic scripted evaluations already exist and run in the default suite.
- Agent invocation observability is implemented, so live-agent failures have stdout/stderr/config logs.
- DevLab logging is implemented, so optional live runs can emit useful run logs.
- Evaluations already use temporary target repositories, preserving the dogfood workspace boundary.
- Existing scenarios already record diagnostics and use black-box checks, giving a foundation for reuse.

Main risks are manageable rather than blocking:

- Live-agent evaluations are provider-dependent and token-consuming, so they must remain opt-in.
- HTTP/API process checks can be flaky if overbuilt, so start with Python standard-library server behavior, strict timeouts, and reliable teardown.
- Current evaluation helpers live in one test file; refactor them before adding live/API scenarios to avoid duplication.

## Goal

Finish the current TODO #3 open work by adding:

1. reusable evaluation harness modules,
2. a tiny HTTP/API or smoke-app deterministic scenario,
3. skipped-by-default live-agent evaluations that reuse the scenario/check shape,
4. outcome export support for tracking evaluation runs over time.

## Non-goals

- Do not make live-agent evaluations part of default `uv run pytest`.
- Do not require network access beyond local loopback.
- Do not introduce non-stdlib target dependencies for the first API scenario.
- Do not persist full prompts in diagnostics.
- Do not add a user-facing `devlab eval` CLI yet.
- Do not commit routine live-evaluation result artifacts to the repository.

## Phase 1: Refactor current evaluation helpers

Move shared code out of `tests/evaluations/test_scripted_workflow_evaluations.py` into test-support modules:

```text
tests/evaluations/
  harness.py          # scenario dataclasses, diagnostics, runner, check helpers
  scripted_agents.py  # CalculatorScriptedAgent and future scripted agents
  test_scripted_workflow_evaluations.py
```

Keep these as test modules/support code, not production APIs.

Refactor without changing behavior:

- `CheckResult`
- `BlackBoxCheck`
- `EvaluationScenario`
- `EvaluationDiagnostics`
- `_run_scripted_evaluation(...)`
- command/file check helpers
- workspace initialization helper
- generic handoff helper

Add or preserve tests that prove diagnostics include:

- scenario id
- provider mode
- sessions and role sequence
- findings created/resolved
- review rejections
- duration
- prompt-size estimate
- checks
- artifact paths

## Phase 2: Add tiny HTTP/API deterministic scenario

Add a fourth scripted evaluation that produces a minimal stdlib Python HTTP app.

Recommended target artifact:

```text
app.py
```

Expected behavior:

- `GET /health` returns HTTP 200 with body `ok`
- `GET /echo?value=hello` returns HTTP 200 with body `hello`

Implementation constraints:

- Use only Python standard library, e.g. `http.server` and `urllib.parse`.
- Bind to an ephemeral loopback port in the black-box check.
- Start the server with a subprocess command such as:

```bash
python app.py --port <port>
```

Black-box check behavior:

- allocate a free local port
- start subprocess with stdout/stderr capture
- poll `/health` with a short deadline
- check `/echo?value=hello`
- terminate process in `finally`
- include stdout/stderr snippets in failure messages

Workflow path can initially be happy-path only:

- architect
- planner
- developer
- reviewer
- integrator
- architect

Keep corrective HTTP scenarios deferred unless the first API scenario exposes new workflow issues.

## Phase 3: Add opt-in live-agent evaluations

Add:

```text
tests/evaluations/test_live_workflow_evaluations.py
```

Skip unless:

```text
DEVLAB_LIVE_EVALS=1
```

Initial live scenario:

- CLI calculator happy path first, because its black-box checks are simple and stable.
- Add HTTP/API live scenario only after the scripted API scenario is stable.

Configuration approach:

- Create a temporary target repo with `init_workspace(root)`.
- Write the scenario system spec and no-command default profile.
- Use one of these opt-in config paths:
  - `DEVLAB_LIVE_AGENTS_TOML=/path/to/agents.toml` copies a caller-provided agent config into the target repo.
  - If not set, use the initialized target's default starter config and allow `DEVLAB_LIVE_PROVIDER`, `DEVLAB_LIVE_MODEL`, and `DEVLAB_LIVE_EFFORT` to pass through to `run_loop(...)`.
- Cap sessions tightly, e.g. `DEVLAB_LIVE_MAX_SESSIONS` defaulting to the scenario max.

Live test behavior:

- call `run_loop(root, auto=True, max_sessions=..., provider=..., model=..., effort=...)`
- run the same black-box checks after completion
- always write diagnostics JSON with `provider_mode = "live"`
- include target root, `.devlab/logs/agents/`, and diagnostics path in assertion messages
- do not assert exact role sequence initially; assert completion and black-box checks first, then tighten once stable

Expected invocation:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_AGENTS_TOML=/path/to/agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py -s
```

## Phase 4: Add outcome export for tracking over time

Support optional copying of diagnostics to a persistent local directory:

```text
DEVLAB_EVAL_RESULTS_DIR=/path/to/eval-results
```

When set, copy each diagnostics JSON file to:

```text
<results-dir>/<timestamp>_<scenario-id>_<provider-mode>.json
```

Keep this helper in the test harness. Do not commit generated results by default.

Diagnostics should include enough fields to compare runs over time:

- timestamp
- git commit if cheaply available (`git rev-parse --short HEAD`, best-effort)
- scenario id
- provider mode
- provider/model/effort for live runs when known
- sessions run
- completed/exit code
- role sequence when known
- findings created/resolved
- review rejections
- duration
- max prompt chars or approximate tokens
- checks and messages
- key artifact paths
- agent log directory path

## Phase 5: Documentation and TODO update

Update `docs/evaluations.md` with:

- deterministic scenario list including HTTP/API
- live-agent evaluation environment variables
- result export instructions
- guidance that live results are local diagnostics, not default CI

Update `docs/todo.md` item #3 after implementation:

- mark live eval harness and API/smoke scenario complete
- leave only follow-up about collecting live results and refining diagnostics if needed

Consider updating the original plan file with a status note rather than duplicating details there.

## Test strategy

Default validation:

```bash
uv run ruff check
uv run ty check
uv run pytest
uv run devlab doctor
```

Focused deterministic validation:

```bash
uv run pytest tests/evaluations -q
```

Optional live validation:

```bash
DEVLAB_LIVE_EVALS=1 uv run pytest tests/evaluations/test_live_workflow_evaluations.py -s
```

If `DEVLAB_EVAL_RESULTS_DIR` is implemented:

```bash
DEVLAB_EVAL_RESULTS_DIR=/tmp/devlab-eval-results uv run pytest tests/evaluations -q
```

## Acceptance criteria

- Default tests remain deterministic, fast, and token-free.
- Existing scripted calculator scenarios still pass after refactor.
- New stdlib HTTP/API scripted scenario passes black-box HTTP checks.
- Live evaluation module is skipped by default and runs only with `DEVLAB_LIVE_EVALS=1`.
- Live diagnostics include target root and agent log paths.
- Optional result export writes diagnostics outside the temp repo when requested.
- Documentation explains how to run deterministic and live evaluations.

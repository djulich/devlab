# DevLab Live Evaluation Quality Metrics Plan

Status: implemented and refined with live stateful web API, deployable web API, and static frontend baselines. Diagnostics now include live role sequence, task metrics, artifact hygiene warnings, agent/prompt log metrics, quality summary, live session progress lines, stronger calculator black-box checks, and stricter scenario contracts. Target-owned test-suite execution remains deferred.

## Goal

Strengthen workflow evaluations so a passing live eval means more than "the final command happened to work". The first live calculator eval proved end-to-end workflow viability, but the grading is too shallow for produced-system quality.

This plan adds lightweight, deterministic quality metrics and stronger black-box checks while deferring target-owned test-suite execution. Subsequent stateful web API live runs showed that the main source of false-negative churn was underspecified API contracts, not missing repository metrics.

## Non-goals

- Do not run `pytest` or other target-owned test commands yet. Target projects may require their own environment lifecycle, dependency install, or profile-specific setup.
- Do not judge code style subjectively with LLMs.
- Do not require a specific package layout for live agents unless the scenario spec explicitly requires it.
- Do not fail evaluations only because extra artifacts exist; initially record/flag hygiene signals separately from hard correctness checks.
- Do not inspect or persist full prompt text in exported diagnostics.

## Current baseline from first live eval

Observed first successful live run:

- completed in 10 sessions
- produced passing `calculator.py add/subtract` behavior
- created multiple tasks and rework cycles
- generated a Python package, tests, `.venv`, `.pytest_cache`, `.ruff_cache`, and other artifacts
- retained split prompt logs successfully

Takeaway: workflow viability is proven for a small scenario; produced-system quality needs stronger metrics.

## Findings from live baselines

### Stateful web API

The first stateful web API live runs completed the DevLab workflow but failed black-box correctness checks. The failures were useful quality signals and led to these refinements:

- **Scenario specs must state exact response shapes.** Agents produced plausible alternatives such as `{"todo": {"id": 1, "title": "write eval"}}`, but the evaluator needed a top-level `{"id": 1, "title": "write eval"}` object to drive follow-up requests. Live specs and the companion plan now require top-level `id` and `title` fields.
- **Destructive-operation contracts should be exact when the product spec says so.** `DELETE /todos/{id}` briefly returned semantically rich variants such as `{"deleted": true, "id": 1}`. The scenario now requires exactly `{"deleted": <id>}`.
- **Negative cases need explicit edge-case wording.** A live run accepted `{"title": ""}` and created an empty todo. The scenario now requires 4xx responses for invalid JSON, missing title, empty title, and blank title.
- **Live failures should expose enough context without manual log spelunking.** Failure messages now include the target root, diagnostics path, agent log path, and diagnostics JSON. Live evaluation sessions also print start/finish role progress lines for long-running tests.
- **Correctness remains the hard gate.** The failed runs had closed tasks and reasonable hygiene diagnostics, but the product was wrong. This confirms that black-box scenario checks are the primary pass/fail signal; task closure, session count, and hygiene remain supporting diagnostics.

Implication: each new live scenario should first define its externally observable contract in exact request/response terms, including negative cases. The evaluator should fail with a contract-specific message before falling back to broad diagnostic summaries.

### Deployable web API

The first passing deployable web API live run completed successfully but exposed workflow-quality signals that were not captured well enough by the diagnostics:

- **Reviewer missed an API contract mismatch that integrator later found.** The initial API task was approved even though `POST /todos` and `DELETE /todos/{id}` returned/documented the wrong success shapes. Integrator created a finding, planner created a corrective task, and the workflow recovered. This is a success for the milestone-boundary review, but a concern for reviewer effectiveness.
- **Reviewer did catch a deployment runtime defect.** During the deployment task review, the reviewer built and smoke-tested the local container and found that the service bound to container-local `127.0.0.1`, making host port publishing unusable. The developer fixed this with configurable host binding and container environment defaults. This is a positive signal for deployment-domain review behavior.
- **Live `review_rejections` was undercounted.** Scripted evaluations can count rejections from the scripted agent, but live evaluations need to derive rejection counts from archived reviewer handoffs with non-empty Open Issues. Otherwise diagnostics can show `review_rejections = 0` even when reviewers requested changes.
- **Passing after substantial rework should be visible.** The deployable baseline passed after 16 sessions, one integrator finding, and multiple review/development cycles. Correctness remains the hard gate, but high session counts and rework cycles should be recorded as quality warnings or at least surfaced prominently.

Recommended actions from this run:

1. Strengthen reviewer instructions to compare implementation, tests, and documentation against exact externally observable system/deployment contracts before approval.
2. Derive live review rejection counts from archived reviewer handoffs rather than leaving them at zero.
3. Add or refine diagnostics for rework intensity, such as session-count warnings, reviewer rejection count, integrator finding count, and per-task review cycles.
4. Keep integrator architecture/spec sync as a required safety net; the run showed it catches drift that may escape task review.

### Static frontend

The static frontend live baselines produced good final applications and highlighted where quality metrics need to distinguish workflow overhead from rework:

- **Artifact and behavior checks were more reliable than exact documentation phrases.** One run provided `static/index.html`, `static/app.js`, `static/styles.css`, direct todo API usage, error handling, and README instructions for opening the served static frontend. The only initial failure was that README did not contain the exact phrase "no frontend build step".
- **Negative evidence is better for "no build step" constraints.** For this scenario, absence of `package.json`, frontend lockfiles, and Vite config better captures the no-React/no-build-step requirement than requiring a specific README sentence.
- **Static frontend evaluation should stay browser-light initially.** The current checker inspects static artifacts and route usage rather than introducing browser automation. That keeps the scenario deterministic and focused on workflow behavior.
- **Multiple developer/reviewer pairs are not always rework.** A later passing run used 8 sessions with two planned tasks: one to add a reusable `python-app` profile and one to implement the API/frontend. There were two reviewer sessions but no rejections or findings. Rework metrics should distinguish planned multi-task execution from repeated work on the same task.
- **Target-owned profile creation is useful but adds workflow overhead.** The generated `python-app` profile made reviewer/integrator validation concrete (`uv run ruff format --check .`, `ruff check`, `ty check`, `pytest`), but it consumed an extra task/session pair. Diagnostics should make this overhead visible without treating it as failure.
- **Ignored local environments can dominate target size.** The passing run created an ignored `.venv`/cache footprint of roughly tens of megabytes. Git-based hygiene correctly excluded it from product files, but quality reporting should continue surfacing ignored-file counts/bytes and may eventually warn on unexpectedly large ignored artifacts.
- **Reviewer/integrator behavior was healthy in the passing run.** The reviewer checked implementation against the design/system spec and profile validation; the integrator ran profile validation plus a live server smoke covering API and static asset serving. This is a useful positive baseline for the narrowed reviewer role.

Recommended actions from these runs:

1. Prefer exact checks for externally consumed contracts and artifact paths, but avoid exact prose requirements unless the prose itself is the contract.
2. Enforce no-build-step frontend constraints by detecting build artifacts rather than requiring agents to document a magic phrase.
3. Revisit browser automation only after static artifact baselines are stable and profile/tooling setup can model browser dependencies explicitly.
4. Refine rework metrics to count repeated developer/reviewer cycles per task, not just total role alternations.
5. Track target-created profiles and ignored artifact size as supporting diagnostics, not hard failures.

## Metrics to add

### 1. Live role sequence

Current live diagnostics leave `roles = []` because no scripted agent records invocations.

Derive role sequence from archived handoff filenames:

```text
.devlab/history/<timestamp>_<role>_handoff.md
```

Record:

```json
"roles": ["architect", "planner", "developer", ...]
```

This enables detecting excessive rework and comparing live runs to scripted baselines.

### 2. Task and rework metrics

Record task counts by status and task ids/titles:

```json
"tasks": {
  "total": 3,
  "by_status": {"closed": 3},
  "items": [
    {"id": "T0001", "title": "...", "status": "closed", "milestone": "M1"}
  ]
}
```

Useful derived signals:

- all tasks closed
- number of tasks created for a small scenario
- developer/reviewer churn inferred from role sequence
- live reviewer rejection count, derived from archived reviewer handoffs whose Open Issues are not `None`
- integrator finding count and resolved finding count
- high session count or repeated developer/reviewer cycles as a rework-intensity warning

### 3. Artifact hygiene metrics

Record repo artifact summary without failing by default:

```json
"artifact_hygiene": {
  "file_count": 123,
  "total_bytes": 456789,
  "flagged_paths": [".venv", ".pytest_cache", ".ruff_cache"],
  "source_files": ["calculator.py", "src/calculator_cli/__init__.py"],
  "test_files": ["tests/test_calculator_cli.py"]
}
```

Flag, but do not initially fail on:

- `.venv/`
- `.pytest_cache/`
- `.ruff_cache/`
- `__pycache__/`
- build/dist/egg-info artifacts

Rationale: these may indicate agents are doing environment setup inside the target repo, but making them hard failures immediately could obscure the first baseline runs.

### 4. Stronger calculator black-box checks

Expand hard checks beyond two happy-path commands:

- `python calculator.py add 2 3` -> `5`
- `python calculator.py subtract 7 4` -> `3`
- `python calculator.py add -2 5` -> `3`
- `python calculator.py subtract 2 5` -> `-3`
- output is exact, with no explanatory prose

Add one negative/usage check if stable across implementations:

- missing args exits nonzero

Avoid requiring a specific invalid-operation message because implementations may rely on `argparse`, custom parser text, or package entry points.

### 5. Prompt/log metrics

When prompt retention is enabled, record:

```json
"prompt_logs": {
  "system_count": 10,
  "session_count": 10,
  "max_system_prompt_bytes": 12345,
  "max_session_prompt_bytes": 23456
}
```

Also record agent log counts:

```json
"agent_logs": {
  "stdout_count": 10,
  "stderr_count": 10,
  "config_count": 10
}
```

Do not export prompt contents.

### 6. Live session progress output

Long live evaluations can run for several minutes with no pytest output. Print one progress line when each session starts and one when it finishes:

```text
[12:34:56] live eval session 3 start: developer
[12:36:10] live eval session 3 finish: developer
```

This is operator feedback only; it is not part of the persisted quality schema. Use `pytest -s` when pytest output capture would otherwise hide the progress lines until the test ends.

### 7. Scenario-specific contract checks

For stateful/live API scenarios, hard correctness checks should verify exact externally observable contracts rather than broad semantic equivalence:

- response status codes for happy path and negative path requests
- top-level response fields needed by clients/evaluators
- exact response bodies where the scenario specifies them
- final state after mutating operations
- project-owned documentation/command artifacts by file presence/content, without executing target-owned test suites

Failure messages should name the violated contract and include the observed status/body.

### 8. Quality gate summary

Add a simple computed summary:

```json
"quality": {
  "correctness_passed": true,
  "all_tasks_closed": true,
  "has_flagged_artifacts": true,
  "session_count": 10,
  "warnings": ["flagged artifact directory: .venv"]
}
```

Only correctness should be a hard test failure initially. Hygiene warnings are diagnostics until enough live baselines exist.

## Implementation phases

### Phase 1: Diagnostics schema expansion

Update `tests/evaluations/harness.py`:

- derive live role sequence from `.devlab/history`
- derive live reviewer rejection count from archived reviewer handoffs
- collect task metrics using `FileTaskTracker`
- collect artifact hygiene summary
- collect agent/prompt log counts and max sizes
- compute quality summary/warnings

Keep existing fields for compatibility with previous diagnostics.

### Phase 2: Stronger calculator checks

Update `tests/evaluations/test_live_workflow_evaluations.py` and scripted calculator scenarios to use expanded command checks:

- add negative-number add/subtract checks
- add missing-args nonzero check helper

Apply these checks to both deterministic and live calculator scenarios so scripted and live grading stay aligned.

### Phase 3: Documentation

Update `docs/evaluations.md`:

- explain correctness vs hygiene diagnostics
- document that target test-suite execution is deferred
- describe flagged artifact directories
- describe prompt/log metrics when retention is enabled

Update `docs/todo.md` TODO #3 open work to mention collecting baselines with new quality metrics.

### Phase 4: Stateful API contract hardening

Update the stateful web API live and scripted scenarios so they agree on an explicit contract:

- `POST /todos` returns a top-level JSON object with integer `id` and `title`.
- `GET /todos` returns `{"todos": [...]}`.
- `DELETE /todos/{id}` returns exactly `{"deleted": <id>}`.
- invalid JSON, missing title, empty title, and blank title return a 4xx client error.
- black-box check failures report the observed status and JSON payload.

### Phase 5: Static frontend quality baseline

Add a static frontend scenario that reuses the stateful API black-box contract and adds browser-facing artifact checks without introducing Node, React, Vite, or browser automation:

- exact static artifact paths: `static/index.html`, `static/app.js`, `static/styles.css`
- vanilla HTML/CSS/JS; no frontend build step
- UI affordances for listing, adding, and deleting todos plus validation error display
- JavaScript calls to the exact todo API routes
- README instructions for running the API and using the static frontend
- absence of frontend package-manager/build artifacts such as `package.json` or Vite config
- an opt-in live gate (`DEVLAB_LIVE_STATIC_FRONTEND=1`) and independent session cap

The first static frontend baseline should inspect static artifacts, API route usage, README usage instructions, and absence of frontend build artifacts rather than requiring a browser automation stack or exact documentation phrase. Browser-level checks remain a later profile/tooling question.

### Phase 6: Deployable web API quality baseline

Add a deployable web API scenario that reuses the stateful API black-box contract and adds deployment-specific artifacts without requiring production deployment:

- explicit deployment spec in the temporary target workspace, so architect/planner prompts receive deployment overlays intentionally
- a `deployment`-domain task in the scripted baseline, so developer/reviewer/integrator domain overlays are exercised
- checks for `Containerfile`, exact Makefile targets named `image` and `deployment-check`, and README deployment instructions that reference both commands
- an opt-in live gate (`DEVLAB_LIVE_DEPLOYMENT=1`) and independent session cap

The first deployment baseline should inspect artifacts and project-owned verification commands rather than requiring Podman/Docker availability. Runtime execution of container builds remains a later, tool-availability-gated check. The initial live baselines showed why command names must be explicit: agents may produce valid alternatives such as `image-build` and `deploy-verify`, but the evaluation needs stable project-owned command names to grade without interpretation. Cosmetic documentation wording should be less brittle; for example, a README heading like `Local container deployment` should satisfy a deployment-section check even if it does not use title case.

## Acceptance criteria

- Default tests remain fast and deterministic.
- Scripted calculator evaluations pass with expanded checks.
- Live diagnostics include non-empty role sequence after a live run.
- Live diagnostics count reviewer rejections from archived reviewer handoffs with non-empty Open Issues.
- Live tests print session start/finish progress lines when run with visible pytest output.
- Diagnostics include task metrics, artifact hygiene, prompt/log counts, and quality summary.
- `.venv`/cache directories are flagged as warnings, not hard failures.
- No target-owned `pytest` or validation command is run by the evaluation harness.
- Stateful web API live/scripted checks enforce exact response shapes and explicit negative cases.
- Static frontend scripted/live scenarios check vanilla static UI artifacts, direct todo API route usage, error display, and README instructions without requiring browser automation.
- Deployable web API scripted/live scenarios check local container artifacts and deployment verification instructions without deploying to production.

## Validation

```bash
uv run ruff check
uv run ty check
uv run pytest
uv run devlab doctor
```

Optional live rerun:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_AGENTS_TOML=live-eval/agents.toml \
DEVLAB_LIVE_MAX_SESSIONS=30 \
DEVLAB_LIVE_RETAIN_PROMPTS=1 \
DEVLAB_EVAL_RESULTS_DIR=/tmp/devlab-eval-results \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py -s
```

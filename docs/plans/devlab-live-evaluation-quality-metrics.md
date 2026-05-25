# DevLab Live Evaluation Quality Metrics Plan

Status: implemented and refined with live stateful web API baselines. Diagnostics now include live role sequence, task metrics, artifact hygiene warnings, agent/prompt log metrics, quality summary, live session progress lines, stronger calculator black-box checks, and a stricter stateful API contract. Target-owned test-suite execution remains deferred.

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

## Findings from stateful web API live baselines

The first stateful web API live runs completed the DevLab workflow but failed black-box correctness checks. The failures were useful quality signals and led to these refinements:

- **Scenario specs must state exact response shapes.** Agents produced plausible alternatives such as `{"todo": {"id": 1, "title": "write eval"}}`, but the evaluator needed a top-level `{"id": 1, "title": "write eval"}` object to drive follow-up requests. Live specs and the companion plan now require top-level `id` and `title` fields.
- **Destructive-operation contracts should be exact when the product spec says so.** `DELETE /todos/{id}` briefly returned semantically rich variants such as `{"deleted": true, "id": 1}`. The scenario now requires exactly `{"deleted": <id>}`.
- **Negative cases need explicit edge-case wording.** A live run accepted `{"title": ""}` and created an empty todo. The scenario now requires 4xx responses for invalid JSON, missing title, empty title, and blank title.
- **Live failures should expose enough context without manual log spelunking.** Failure messages now include the target root, diagnostics path, agent log path, and diagnostics JSON. Live evaluation sessions also print start/finish role progress lines for long-running tests.
- **Correctness remains the hard gate.** The failed runs had closed tasks and reasonable hygiene diagnostics, but the product was wrong. This confirms that black-box scenario checks are the primary pass/fail signal; task closure, session count, and hygiene remain supporting diagnostics.

Implication: each new live scenario should first define its externally observable contract in exact request/response terms, including negative cases. The evaluator should fail with a contract-specific message before falling back to broad diagnostic summaries.

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

### 2. Task metrics

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

## Acceptance criteria

- Default tests remain fast and deterministic.
- Scripted calculator evaluations pass with expanded checks.
- Live diagnostics include non-empty role sequence after a live run.
- Live tests print session start/finish progress lines when run with visible pytest output.
- Diagnostics include task metrics, artifact hygiene, prompt/log counts, and quality summary.
- `.venv`/cache directories are flagged as warnings, not hard failures.
- No target-owned `pytest` or validation command is run by the evaluation harness.
- Stateful web API live/scripted checks enforce exact response shapes and explicit negative cases.

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

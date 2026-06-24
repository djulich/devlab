# Stateful Web API Live Evaluation Baseline — 2026-06-24

Scenario: `live-stateful-web-api-happy-path`

Command shape:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_STATEFUL_WEB_API=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_stateful_web_api_happy_path_evaluation -s
```

Claude target workspace inspected after the run:

```text
/tmp/pytest-of-djulich/pytest-53/test_live_stateful_web_api_hap0
```

Codex target workspace inspected after the run:

```text
/tmp/pytest-of-djulich/pytest-54/test_live_stateful_web_api_hap0
```

Evaluation diagnostics artifacts:

```text
.devlab/evaluations/live-stateful-web-api-happy-path.json
```

Persistent diagnostics copy: none recorded outside the pytest temp target.

## Outcome

The live evaluation passed with two providers on 2026-06-24. Follow-up
inspection of both generated target workspaces and DevLab artifacts confirmed
the recorded evaluation results.

Both workflows produced a standard-library Python todo JSON API, project-owned
run and test commands, README endpoint documentation, and Python cache ignores.
The black-box stateful API checks passed at the end of each pytest run.

Both evaluation diagnostics JSON files recorded all five checks as passing:

- stateful todo API behavior
- project run command
- project test command
- usage docs
- Python cache `.gitignore`

## Claude Workflow Metrics

- Completed: `true`
- Pytest result: `1 passed`
- Pytest duration: `1210.30s` (`0:20:10`)
- Evaluation diagnostics duration: `1208.93s`
- Sessions run: `10`
- Provider: `default`
- Provider version: `2.1.187 (Claude Code)`
- Roles:
  - `architect`
  - `planner`
  - `developer`
  - `reviewer`
  - `developer`
  - `reviewer`
  - `developer`
  - `reviewer`
  - `integrator`
  - `architect`
- Review rejections: `0` observed in session log
- Integrator findings: `0` observed in session log
- Same-task rework: none observed in session log
- Unattributed developer/reviewer sessions: `0`
- Tasks closed: `3 / 3`
- Quality warnings: none
- Product artifacts: `14` files, `32151` bytes
- Ignored artifacts: `679` files, `65444785` bytes, primarily `.venv/`
- Flagged artifact paths: none
- Agent logs: `10` stdout, `10` stderr, `10` config, `10` metadata
- Retained prompt logs: none
- Milestone tag created: `devlab/milestone/M1`

## Claude Session Breakdown

- Session 1: architect, initial architecture, `158.7s`
- Session 2: planner, planned M1 with profile, scaffold, and implementation tasks, `158.1s`
- Session 3: developer, `T0001` python-api profile, `75.4s`
- Session 4: reviewer, approved `T0001`, `76.3s`
- Session 5: developer, `T0002` project scaffold, `107.2s`
- Session 6: reviewer, approved `T0002`, `105.3s`
- Session 7: developer, `T0003` todo API implementation and tests, `186.4s`
- Session 8: reviewer, approved `T0003`, `105.6s`
- Session 9: integrator, validated M1 integration, `112.6s`
- Session 10: architect, architecture review, `122.8s`

## Codex Workflow Metrics

- Completed: `true`
- Pytest result: `1 passed`
- Pytest duration: `592.52s` (`0:09:52`)
- Evaluation diagnostics duration: `591.23s`
- Sessions run: `6`
- Provider: `codex`
- Model: `gpt-5-codex`
- Provider version: `codex-cli 0.142.0`
- Roles:
  - `architect`
  - `planner`
  - `developer`
  - `reviewer`
  - `integrator`
  - `architect`
- Review rejections: `0`
- Integrator findings: `0`
- Same-task rework: none
- Unattributed developer/reviewer sessions: `0`
- Tasks closed: `1 / 1`
- Quality warnings: none
- Product artifacts: `10` files, `30766` bytes
- Ignored artifacts: `673` files, `65430876` bytes, primarily `.venv/`
- Flagged artifact paths: none
- Agent logs: `6` stdout, `6` stderr, `6` config, `6` metadata
- Retained prompt logs: none
- Milestone tag created: `devlab/milestone/M1`

## Codex Session Breakdown

- Session 1: architect, initial architecture, `76.5s`
- Session 2: planner, planned M1 with one end-to-end implementation task, `72.8s`
- Session 3: developer, `T0001` todo API scaffold and implementation, `196.2s`
- Session 4: reviewer, approved `T0001`, `76.8s`
- Session 5: integrator, validated M1 integration, `95.4s`
- Session 6: architect, architecture review, `73.2s`

## Provider Comparison

- Both providers passed the scenario and all black-box checks.
- Codex completed the workflow in `6` sessions versus Claude's `10`.
- Codex used one end-to-end implementation task; Claude split the work into
  profile, scaffold, and implementation tasks.
- Codex completed in about `592s`, roughly half of Claude's `1210s` run time.
- Both runs had `0` review rejections, `0` integrator findings, no same-task
  rework, and no quality warnings.
- Codex produced fewer product files (`10` vs `14`) by keeping the todo store in
  `src/todo_api/server.py` and using one `tests/test_server.py` file. Claude
  split store and server code/tests into separate files.
- Codex's target-owned `make test` was stricter: it runs `ruff check .`,
  `ruff format --check .`, whole-repo `ty check`, and `pytest`. Claude's
  generated profile type-checked only `src/`, and its Makefile test target ran
  only `uv run pytest`.
- Codex DevLab logs were much larger (`720203` bytes under `.devlab/logs/`) than
  Claude's (`18138` bytes), despite fewer sessions. This is likely provider
  stdout/stderr verbosity rather than product complexity.

## Observations

Positive evidence:

- The Claude target contains `src/todo_api/server.py`, `src/todo_api/store.py`,
  `tests/test_server.py`, `tests/test_store.py`, `Makefile`, `README.md`,
  `pyproject.toml`, `uv.lock`, and `.gitignore`.
- The Codex target contains `src/todo_api/server.py`, `tests/test_server.py`,
  `Makefile`, `README.md`, `pyproject.toml`, `uv.lock`, and `.gitignore`.
- Both API implementations use only the Python standard library at runtime.
- Independent Claude target validation after the run confirmed:
  - `uv run ruff check src/ tests/` passed.
  - `uv run ruff format --check src/ tests/` passed.
  - `uv run ty check src/` passed.
  - `make test` passed with `23` tests after rerunning outside the restricted socket sandbox.
- Normal developer/reviewer task attribution was sufficient in both runs.
- The Claude planner split the scenario into a useful profile/scaffold/implementation
  sequence; the Codex planner chose a compact single-task implementation.
- Reviewer and integrator sessions approved without rework loops in both runs.
- The final architecture review found no design or spec drift in both runs.
- No workflow or checker changes were indicated by this baseline.
- The Codex target independently passed its stricter `make test` command:
  `ruff check`, `ruff format --check`, whole-repo `ty check`, and `17` pytest
  tests.

Caveat:

- `uv run ty check` over the whole target repo reports one annotation issue in
  `tests/test_server.py`: the pytest fixture `base_url` is annotated as `str`
  even though it is a generator fixture. This does not contradict the profile
  validation because the generated profile intentionally runs `ty check src/`,
  but it is useful target-quality evidence if test type-checking becomes part of
  future profile expectations.
- The requested `/tmp/pytest-of-dirk/` directory was not present in this
  environment; the Codex run was found under `/tmp/pytest-of-djulich/pytest-54/`.

Follow-up evidence to collect later:

- Additional provider/model environments for the same scenario, if available.
- Comparison with static frontend and deployment live baselines when calibrating
  high-session and workflow-overhead warnings.

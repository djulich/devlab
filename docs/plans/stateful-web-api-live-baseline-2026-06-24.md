# Stateful Web API Live Evaluation Baseline — 2026-06-24

Scenario: `live-stateful-web-api-happy-path`

Command shape:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_STATEFUL_WEB_API=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_stateful_web_api_happy_path_evaluation -s
```

Target workspace inspected after the run:

```text
/tmp/pytest-of-djulich/pytest-53/test_live_stateful_web_api_hap0
```

Evaluation diagnostics artifact:

```text
.devlab/evaluations/live-stateful-web-api-happy-path.json
```

Persistent diagnostics copy: none recorded outside the pytest temp target.

## Outcome

The live evaluation passed. A follow-up inspection of the generated target
workspace and DevLab artifacts confirmed the recorded evaluation result.

The workflow produced a standard-library Python todo JSON API, project-owned run
and test commands, README endpoint documentation, and Python cache ignores. The
black-box stateful API checks passed at the end of the pytest run.

The evaluation diagnostics JSON recorded all five checks as passing:

- stateful todo API behavior
- project run command
- project test command
- usage docs
- Python cache `.gitignore`

## Workflow metrics

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

## Session breakdown

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

## Observations

Positive evidence:

- The generated product contains `src/todo_api/server.py`, `src/todo_api/store.py`,
  `tests/test_server.py`, `tests/test_store.py`, `Makefile`, `README.md`,
  `pyproject.toml`, `uv.lock`, and `.gitignore`.
- The API implementation uses only the Python standard library at runtime.
- Independent target validation after the run confirmed:
  - `uv run ruff check src/ tests/` passed.
  - `uv run ruff format --check src/ tests/` passed.
  - `uv run ty check src/` passed.
  - `make test` passed with `23` tests after rerunning outside the restricted socket sandbox.
- Normal developer/reviewer task attribution was sufficient for all three tasks.
- The planner split the scenario into a useful profile/scaffold/implementation sequence.
- Reviewer and integrator sessions approved without rework loops.
- The final architecture review found no design or spec drift.
- No workflow or checker changes were indicated by this baseline.

Caveat:

- `uv run ty check` over the whole target repo reports one annotation issue in
  `tests/test_server.py`: the pytest fixture `base_url` is annotated as `str`
  even though it is a generator fixture. This does not contradict the profile
  validation because the generated profile intentionally runs `ty check src/`,
  but it is useful target-quality evidence if test type-checking becomes part of
  future profile expectations.

Follow-up evidence to collect later:

- Additional provider/model environments for the same scenario.
- Comparison with static frontend and deployment live baselines when calibrating
  high-session and workflow-overhead warnings.

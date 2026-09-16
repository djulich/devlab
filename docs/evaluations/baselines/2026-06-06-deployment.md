# Deployment Live Evaluation Baseline — 2026-06-06

Scenario: `live-deployable-web-api-happy-path`

Command shape:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_DEPLOYMENT=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/agents.toml \
DEVLAB_EVAL_RESULTS_DIR=.local/live-eval/results \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_deployable_web_api_happy_path_evaluation -s
```

Persistent diagnostics copy:

```text
.local/live-eval/results/20260606T210014Z_live-deployable-web-api-happy-path_live.json
```

## Outcome

The DevLab workflow completed successfully but the evaluation initially failed one black-box check because the check required `POST /todos` to return HTTP `201` even though the scenario specification only required a top-level JSON object with integer `id` and `title` fields.

The generated API returned `200` with the required body:

```text
{'id': 1, 'title': 'write eval'}
```

Decision: accept any successful `2xx` create status in `stateful_todo_api_check`. The evaluation contract should not be stricter than the scenario specification.

After updating the check, rerunning the black-box checks against the generated target passed all checks.

## Workflow metrics

- Completed: `true`
- Exit code: `0`
- Sessions run: `10`
- Duration: about `756s`
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
- Review rejections: `0`
- Integrator findings: `0`
- Same-task rework: none
- Unattributed developer/reviewer sessions: `0`
- Tasks closed: `3 / 3`
- Git worktree clean: `true`
- Milestone tag created: `devlab/milestone/M1`

## Deployment observations

Positive evidence:

- Planner created a deployment-domain task: `T0003` with `domain = "deployment"`.
- Planner created a deployment profile and assigned it to the deployment task.
- Generated artifacts satisfied the structural deployment contract:
  - `Containerfile`
  - Make target `image`
  - Make target `deployment-check`
  - deployment documentation referencing both commands
- Normal workflow task attribution was sufficient; no fallback prose parsing was needed.
- No prompt or workflow changes were indicated by this baseline.

Follow-up evidence to collect later:

- Runs with optional deployment tools enabled, to observe missing-tool and project-owned command behavior.
- Additional provider/model environments.
- Compose live deployment scenario if/when promoted from scripted-only coverage.

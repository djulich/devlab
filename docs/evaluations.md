# DevLab Workflow Evaluations

DevLab has deterministic workflow evaluations under `tests/evaluations/`.

They differ from lower-level orchestrator tests: evaluations create temporary target repositories, run the normal DevLab workflow, then grade the generated target system with black-box checks.

## Deterministic scripted evaluations

Run with the normal test suite:

```bash
uv run pytest tests/evaluations
```

Current scenarios cover:

- CLI calculator happy path
- reviewer rejection and developer rework
- integration finding with corrective task and finding resolution
- tiny standard-library HTTP API happy path

The scripted provider writes realistic role artifacts without using LLM tokens. Each scenario records diagnostics in the temporary target repository:

```text
.devlab/evaluations/<scenario-id>.json
```

Diagnostics include sessions used, role sequence, findings, review rejections, runtime, prompt-size estimate, checked artifacts, target root, agent log directory, and black-box check results.

To copy diagnostics to a persistent local directory, set:

```bash
DEVLAB_EVAL_RESULTS_DIR=/tmp/devlab-eval-results uv run pytest tests/evaluations
```

## Live-agent evaluations

Live-agent evaluations are opt-in and skipped by default because they are slower, token-consuming, and provider-dependent.

Run the current live calculator evaluation with:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_AGENTS_TOML=/path/to/agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py -s
```

Useful environment variables:

- `DEVLAB_LIVE_EVALS=1`: enable live evaluations.
- `DEVLAB_LIVE_AGENTS_TOML`: copy this agent config into the temporary target repo.
- `DEVLAB_LIVE_PROVIDER`: optional provider override passed to `run_loop`.
- `DEVLAB_LIVE_MODEL`: optional model override passed to `run_loop`.
- `DEVLAB_LIVE_EFFORT`: optional effort override passed to `run_loop`.
- `DEVLAB_LIVE_MAX_SESSIONS`: optional session cap for live runs.
- `DEVLAB_EVAL_RESULTS_DIR`: optional directory for persistent diagnostics copies.
- `DEVLAB_LIVE_RETAIN_PROMPTS=1`: retain split system/session prompt logs under `.devlab/logs/agents/` for live-run debugging.

Live evaluation failures report the temporary target root, diagnostics JSON path, and `.devlab/logs/agents/` path.

# DevLab Workflow Evaluations

DevLab has deterministic workflow evaluations under `tests/evaluations/`.

They differ from lower-level orchestrator tests: evaluations create temporary target repositories, run the normal DevLab workflow, then grade the generated target system with black-box checks. Workflow evaluations require Git on `PATH`; evaluation targets are initialized with `devlab init` as Git repositories, DevLab commits after every valid session, and artifact hygiene uses Git's ignore rules rather than reimplementing `.gitignore` parsing.

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
- stateful JSON web API happy path
- deployable web API happy path with local container artifacts

The scripted provider writes realistic role artifacts without using LLM tokens. Each scenario records diagnostics in the temporary target repository:

```text
.devlab/evaluations/<scenario-id>.json
```

Diagnostics include sessions used, role sequence, task status summaries, findings, review rejections, runtime, prompt-size estimate, checked artifacts, artifact hygiene, target root, agent log directory, prompt/log counts, and black-box check results. Artifact hygiene separates Git-relevant product files, Git-ignored files, and DevLab workflow files under `.devlab/` so generated-system metrics are not dominated by orchestration state or local tooling output.

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

For DevLab development, keep environment-specific live-agent configs outside version control. The recommended repo-local convention is:

```text
.local/live-eval/<environment>.agents.toml
```

For example:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py -s
```

These files are local operator config: they may encode installed CLIs, account-specific providers, models, auth assumptions, or machine-specific timeouts. Commit sanitized examples separately if a shared starting point is useful.

The stateful JSON web API live evaluation is an additional opt-in scenario. It is skipped unless explicitly enabled:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_STATEFUL_WEB_API=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py -s
```

The deployable web API live evaluation extends the stateful API scenario with project-owned local container deployment artifacts. It checks for the API behavior plus `Containerfile`, Makefile image/verification targets, and README deployment instructions. It is skipped unless explicitly enabled:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_DEPLOYMENT=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_deployable_web_api_happy_path_evaluation -s
```

Useful environment variables:

- `DEVLAB_LIVE_EVALS=1`: enable live evaluations.
- `DEVLAB_LIVE_AGENTS_TOML`: copy this agent config into the temporary target repo.
- `DEVLAB_LIVE_PROVIDER`: optional provider override passed to `run_loop`.
- `DEVLAB_LIVE_MODEL`: optional model override passed to `run_loop`.
- `DEVLAB_LIVE_EFFORT`: optional effort override passed to `run_loop`.
- `DEVLAB_LIVE_MAX_SESSIONS`: optional session cap for the live calculator run.
- `DEVLAB_LIVE_STATEFUL_WEB_API=1`: enable the additional stateful JSON web API live evaluation.
- `DEVLAB_LIVE_STATEFUL_MAX_SESSIONS`: optional session cap for the stateful JSON web API live run; defaults to `18`.
- `DEVLAB_LIVE_DEPLOYMENT=1`: enable the deployable web API live evaluation.
- `DEVLAB_LIVE_DEPLOYMENT_MAX_SESSIONS`: optional session cap for the deployable web API live run; defaults to `22`.
- `DEVLAB_EVAL_RESULTS_DIR`: optional directory for persistent diagnostics copies.
- `DEVLAB_LIVE_RETAIN_PROMPTS=1`: retain split system/session prompt logs under `.devlab/logs/agents/` for live-run debugging.

Live evaluations print a progress line when each agent session starts and when it finishes, for example `live eval session 3 start: developer`. Use `pytest -s` if your pytest invocation captures output and you want to watch those lines as they happen.

Live evaluation failures report the temporary target root, diagnostics JSON path, and `.devlab/logs/agents/` path.

Evaluation correctness checks are hard failures. Artifact hygiene uses `git ls-files --cached --others --exclude-standard` for product files and `git ls-files --others --ignored --exclude-standard` for ignored files, excluding `.devlab/` from both classes. DevLab does not guess which paths are ephemeral; target/tooling conventions decide through `.gitignore`. Target-owned test-suite execution is intentionally deferred because target projects may require their own environment setup.

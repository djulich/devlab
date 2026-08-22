# DevLab Workflow Evaluations

DevLab has deterministic workflow evaluations under `tests/evaluations/`.

They differ from lower-level orchestrator tests: evaluations create temporary target repositories, run the normal DevLab workflow, then grade the generated target system with black-box checks. Workflow evaluations require Git on `PATH`; evaluation targets are initialized with `devlab init` as Git repositories, DevLab commits after every valid session, and artifact hygiene uses Git's ignore rules rather than reimplementing `.gitignore` parsing.

## Independent grading boundary

Evaluation checks are independent graders, not inputs to DevLab's regular
self-correction loop. They run after the evaluated workflow stops and must not
create findings or corrective tasks, reopen milestones, resume the workflow, or
invoke additional role sessions. A failed check leaves the evaluated run failed.

This boundary does not disable normal workflow correction. Task acceptance
criteria, target-owned validation commands, reviewer outcomes, and integrator or
architecture-review findings remain visible to the workflow and may cause
bounded rework before completion. Evaluation checks may independently repeat or
strengthen that verification afterward, but their results are recorded only as
grading evidence. See
[ADR 0011](adr/0011-keep-workflow-evaluation-grading-outside-the-workflow.md).

Independence includes runtime resolution, not only workflow policy. Evaluator
executables and libraries must resolve from evaluator-owned absolute locations;
the target's working directory, `PATH`, `PYTHONPATH`, `NODE_PATH`, classpath, or
similar search mechanisms must not silently replace grader dependencies. A
read-only target mount provides mutation isolation but not dependency-resolution
isolation. Checks that copy a target into disposable storage must preserve both
boundaries explicitly.

Specification-specific demonstration graders are repository-only packages under
[`demos/`](../demos/). Generic DevLab workflow-evaluation infrastructure remains
in this test suite.

Black-box check diagnostics use four statuses:

- `passed` — product behavior was exercised and satisfied the check;
- `failed` — product behavior was exercised and violated the check;
- `unverified` — the check did not run because an external prerequisite was
  unavailable or deliberately disabled; and
- `grader_error` — evaluator setup, execution, or cleanup failed before the
  product claim could be decided.

The retained Boolean `passed` field remains for compatibility and for deciding
whether an evaluation test itself succeeds. Quality correctness is indeterminate
when grading is incomplete and no actual product check failed; grader errors are
not recorded as product failures. Diagnostic handling should wrap dependency
loading, fixture setup, tool/browser launch, product actions, and cleanup rather
than only the central assertion steps.

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
- static frontend todo app happy path with vanilla HTML/CSS/JS
- deployable web API happy path with local container artifacts
- Compose deployment happy path with local deploy/teardown commands
- Rust Cargo CLI happy path
- Go module CLI happy path
- C and C++ CMake-presets CLI happy paths
- mixed Rust/Go components with task-specific profiles and a root integration command

The normal scripted suite uses structural checks as hard gates. Deployment scenarios may also include optional tool-backed checks, such as running a target-owned `make deployment-check`, `make compose-check`, or `docker compose config`, but these are skipped unless explicitly enabled:

```bash
DEVLAB_EVAL_DEPLOYMENT_TOOLS=1 uv run pytest tests/evaluations
```

When enabled, missing host tools such as `make` are reported as skipped/unverified rather than installed. Target-owned commands that do run must pass, or the evaluation fails.

Compiled-language structural scenarios always exercise the complete scripted
workflow and check their generated projects without depending on host
toolchains. Separate toolchain-verification tests run Cargo, Go, compiler,
CMake, CTest, and mixed-workspace commands. Each verification test has a fixed
scope: it runs all of its commands when its complete prerequisite set is on
`PATH`, or pytest explicitly skips the whole test and reports the missing tools.
Use `pytest -rs` to display individual skip reasons.

The scripted provider writes realistic role artifacts without using LLM tokens. Each scenario records diagnostics in the temporary target repository:

```text
.devlab/evaluations/<scenario-id>.json
```

Diagnostics include sessions used, the structured run `stop_reason`, role sequence, per-session task attribution, per-task developer/reviewer cycle counts, task rework summaries, integrator rework summaries, task status summaries, profile summaries, findings, review rejections, runtime, prompt-size estimate, checked artifacts, Git commit/tag metrics, artifact hygiene, target root, agent log directory, prompt/log counts, quality warnings, and black-box check results. The retained `completed` field is true only for terminal workflow or command boundaries; `stop_reason` distinguishes workflow completion, command completion, session limits, clarification blockers, ineligible work, and errors. Workflow-history diagnostics are shared with `devlab diagnostics`; evaluation-specific diagnostics add scenario identity, runtime, checked artifacts, and black-box check results. Task cycle metrics use the task identity in DevLab-published structured session results, with changed-task-artifact inference only for legacy history. Conflicting sources remain unattributed and visible rather than being guessed. Integrator rework metrics count durable findings whose `source` is `integrator`, which reflects milestone-level rejection/follow-up work without parsing integrator prose. Profile diagnostics list target profiles, validation-command counts, managed roles, and tasks using each profile. Artifact hygiene separates Git-relevant product files, Git-ignored files, and DevLab workflow files under `.devlab/`. Ignored totals are further divided into conventional dependency environments/tool caches and other ignored artifacts; only the latter trigger large-footprint warnings, while verbose output retains contributors for both categories.

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

The compiled-language live evaluations exercise real agent planning, dedicated
task profiles, implementation, review, integration, and architecture review in
non-Python targets. Rust requires an operator-installed stable Rust toolchain;
Go requires Go and gofmt; C and C++ require CMake, CTest, Make, and the respective
compiler. The scenarios grade formatting or configure/build/test commands plus
CLI behavior. Each test skips before invoking agents if any required host tool
is absent; DevLab does not install or bootstrap the toolchains. Every scenario
requires the product task to use its dedicated profile and requires milestone
verification to contain the expected passing profile-sourced commands. The
four-language baseline is recorded in
`docs/plans/compiled-language-live-baseline-2026-08-20.md`.

Run all four scenarios with:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_RUST=1 \
DEVLAB_LIVE_GO=1 \
DEVLAB_LIVE_C=1 \
DEVLAB_LIVE_CPP=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest \
  tests/evaluations/test_live_workflow_evaluations.py::test_live_rust_cli_happy_path_evaluation \
  tests/evaluations/test_live_workflow_evaluations.py::test_live_go_cli_happy_path_evaluation \
  tests/evaluations/test_live_workflow_evaluations.py::test_live_c_cmake_cli_happy_path_evaluation \
  tests/evaluations/test_live_workflow_evaluations.py::test_live_cpp_cmake_cli_happy_path_evaluation \
  -s
```

The static frontend live evaluation extends the stateful API scenario with a browser-facing vanilla HTML/CSS/JS UI. It requires exact static artifact paths (`static/index.html`, `static/app.js`, `static/styles.css`), direct calls to the todo API routes, an error display, README usage instructions, and absence of frontend build artifacts such as `package.json` or Vite config. It is skipped unless explicitly enabled:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_STATIC_FRONTEND=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_static_frontend_todo_app_happy_path_evaluation -s
```

The React/Vite frontend live evaluation extends the stateful API scenario with a framework-based browser UI. It verifies the API behavior, structurally checks `package.json`, Vite scripts, React/Vite dependencies including `@vitejs/plugin-react`, `index.html`, React entrypoint/component files under `src/`, todo API calls, error handling, and README instructions for `npm run dev` and `npm run build`, builds the generated frontend inside a disposable Podman Node container, then runs an API, Vite dev server, and real browser flow inside a disposable Playwright-capable Podman container. The connectivity contract uses one deterministic strategy: browser code calls same-origin routes, while Vite reads the API target from `API_BASE_URL` and proxies `/health` and `/todos`. The grader chooses a non-default API port to expose hard-coded targets. The generated project must also own a `make browser-test` Podman check that installs dependencies, builds the frontend, and runs the browser flow; its `todo-app` profile must run backend tests and that browser check. The independent grader still runs its own separate browser flow. The browser flow opens the app, checks empty-submit validation, adds a todo, verifies it appears, deletes it, and fails with captured container/browser diagnostics if the UI cannot reach the API or emits runtime errors. The target repository is mounted read-only, copied to container-local `/tmp/work`, and `npm ci` or `npm install` plus `npm run build` run there so target dependencies are not installed into the host checkout or temporary target repo. The browser container installs its pinned Playwright Node client into a separate evaluator-owned temporary prefix; the image supplies the matching browser binaries and system libraries but not that Node package.

There is no separate browser/API integration flag. Setting `DEVLAB_LIVE_REACT_VITE_FRONTEND=1` enables the full React/Vite check set, including the direct API contract check, the Podman-isolated frontend build check, and the Podman/Playwright browser/API integration check. The host running this live evaluation must have `podman` available and be able to pull or use the required Node and Playwright container images. It is skipped unless explicitly enabled:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_REACT_VITE_FRONTEND=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_react_vite_todo_app_happy_path_evaluation -s
```

The deployable web API live evaluation extends the stateful API scenario with project-owned local container deployment artifacts. It checks for the API behavior plus `Containerfile`, exact Makefile targets named `image` and `deployment-check`, and deployment instructions that reference both commands. API create responses may use any successful `2xx` status unless the scenario spec says otherwise. The deployment-section check is case-insensitive and may be satisfied by `README.md` or `docs/**/*.md`. It is skipped unless explicitly enabled:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_DEPLOYMENT=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_deployable_web_api_happy_path_evaluation -s
```

The spec reconciliation live evaluation runs a small project to completion, commits a system-spec change, verifies that normal `devlab implement` is blocked until reconciliation, runs `devlab plan`, verifies that generation 1 was archived and generation 2 has active tasks, then finishes the replacement project. This structural test reports the target root and agent log directory on failure rather than writing the standard evaluation diagnostics JSON. It is skipped unless explicitly enabled:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_SPEC_RECONCILIATION=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_spec_reconciliation_archives_and_replans -s
```

The adopt-existing live evaluation starts from a tiny pre-existing calculator repo,
runs `devlab plan --adopt-existing`, checks that the design plan records
current-state evidence, then runs implementation and verifies both the existing
`add` behavior and the newly requested `subtract` behavior. The target repo owns
its validation environment through `pyproject.toml`, `uv.lock`, `.gitignore`, and
the validation command `uv run pytest`; the evaluation rejects planned task
validation that uses bare `pytest`, because that can accidentally resolve to the
DevLab harness environment. It is skipped unless explicitly enabled:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_ADOPT_EXISTING=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_adopt_existing_current_state_baseline_and_feature_work -s
```

Useful environment variables:

- `DEVLAB_EVAL_DEPLOYMENT_TOOLS=1`: enable optional tool-backed deployment checks, such as target-owned Make targets. Missing host tools are skipped/unverified, not installed.
- `DEVLAB_LIVE_EVALS=1`: enable live evaluations.
- `DEVLAB_LIVE_AGENTS_TOML`: copy this agent config into the temporary target repo.
- `DEVLAB_LIVE_PROVIDER`: optional provider override passed to `run_loop`.
- `DEVLAB_LIVE_MODEL`: optional model override passed to `run_loop`.
- `DEVLAB_LIVE_EFFORT`: optional effort override passed to `run_loop`.
- `DEVLAB_LIVE_MAX_SESSIONS`: optional session cap for the live calculator run.
- `DEVLAB_LIVE_STATEFUL_WEB_API=1`: enable the additional stateful JSON web API live evaluation.
- `DEVLAB_LIVE_STATEFUL_MAX_SESSIONS`: optional session cap for the stateful JSON web API live run; defaults to `18`.
- `DEVLAB_LIVE_RUST=1`: enable the Rust CLI live evaluation.
- `DEVLAB_LIVE_RUST_MAX_SESSIONS`: optional session cap for the Rust live run; defaults to `12`.
- `DEVLAB_LIVE_GO=1`: enable the Go CLI live evaluation.
- `DEVLAB_LIVE_GO_MAX_SESSIONS`: optional session cap for the Go live run; defaults to `12`.
- `DEVLAB_LIVE_C=1`: enable the C/CMake CLI live evaluation.
- `DEVLAB_LIVE_C_MAX_SESSIONS`: optional session cap for the C live run; defaults to `12`.
- `DEVLAB_LIVE_CPP=1`: enable the C++/CMake CLI live evaluation.
- `DEVLAB_LIVE_CPP_MAX_SESSIONS`: optional session cap for the C++ live run; defaults to `12`.
- `DEVLAB_LIVE_STATIC_FRONTEND=1`: enable the static frontend todo app live evaluation.
- `DEVLAB_LIVE_STATIC_FRONTEND_MAX_SESSIONS`: optional session cap for the static frontend live run; defaults to `20`.
- `DEVLAB_LIVE_REACT_VITE_FRONTEND=1`: enable the React/Vite frontend todo app live evaluation.
- `DEVLAB_LIVE_REACT_VITE_FRONTEND_MAX_SESSIONS`: optional session cap for the React/Vite frontend live run; defaults to `24`.
- `DEVLAB_LIVE_DEPLOYMENT=1`: enable the deployable web API live evaluation.
- `DEVLAB_LIVE_DEPLOYMENT_MAX_SESSIONS`: optional session cap for the deployable web API live run; defaults to `22`.
- `DEVLAB_LIVE_SPEC_RECONCILIATION=1`: enable the spec reconciliation live evaluation.
- `DEVLAB_LIVE_SPEC_RECONCILIATION_INITIAL_MAX`: optional session cap for the initial live run before the spec change; defaults to `10`.
- `DEVLAB_LIVE_SPEC_RECONCILIATION_FINAL_MAX`: optional session cap for the final live run after reconciliation; defaults to `10`.
- `DEVLAB_LIVE_ADOPT_EXISTING=1`: enable the adopt-existing live evaluation.
- `DEVLAB_LIVE_ADOPT_EXISTING_MAX_SESSIONS`: optional session cap for the implementation run after adopt-existing planning; defaults to `8`.
- `DEVLAB_EVAL_RESULTS_DIR`: optional directory for persistent diagnostics copies.
- `DEVLAB_LIVE_RETAIN_PROMPTS=1`: retain split base/session prompt logs under `.devlab/logs/agents/` for live-run debugging.

Live evaluations configure the DevLab logger at INFO level so normal workflow session logs are visible, including contextual start/finish lines such as `Starting session 3: developer task=T0001 ...` and `Finished session 3: developer task=T0001 status=in_review next=reviewer`. Use `pytest -s` if your pytest invocation captures output and you want to watch those lines as they happen.

Live evaluation failures report the temporary target root, diagnostics JSON path, and `.devlab/logs/agents/` path. Deployment baseline notes are kept under `docs/plans/`, starting with `docs/plans/deployment-live-baseline-2026-06-06.md`.

Evaluation correctness checks are hard failures. Live evaluations also structurally assert automatic version-control behavior: the target workspace must be a Git repository, finish with a clean worktree, create at least one commit per completed role session after evaluation setup, and include expected milestone tags such as `devlab/milestone/M1`. Diagnostics record baseline and final commit counts, session commit count, target HEAD commit, milestone tags, missing expected tags, and peeled tag target commits. Quality warnings are diagnostic only and currently cover flagged artifact paths, same-task developer/reviewer rework, integrator findings, high sessions per closed task, attribution failures, and unusually large non-conventional ignored artifact footprints. Artifact hygiene uses `git ls-files --cached --others --exclude-standard` for product files and `git ls-files --others --ignored --exclude-standard` for ignored files, excluding `.devlab/` from both classes. Conventional directories such as `.venv`, `node_modules`, Python tool caches, `.tox`, and `.nox` remain measured but do not trigger size warnings by themselves. Verbose diagnostics include top product, conventional ignored, other ignored, and `.devlab/` contributors. Target-owned test-suite execution is intentionally deferred because target projects may require their own environment setup.

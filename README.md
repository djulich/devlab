# DevLab

DevLab is a reusable CLI and Python package for running an auditable, file-backed, role-based agentic software development workflow inside a target repository.

DevLab provides the orchestrator and packaged worker prompts. The target repository stores product-specific specs, plans, tasks, milestones, findings, handoffs, configuration, and logs under `.devlab/`.

## Maturity

DevLab is an early, tested orchestrator prototype.

Current confidence:

- deterministic unit/integration tests cover the core workflow mechanics;
- scripted workflow evaluations exercise temporary target repositories;
- opt-in live-agent evaluations exist for representative workflows, with baseline
  collection still ongoing;
- existing-project adoption, spec reconciliation, prompt-size monitoring, and
  agent invocation diagnostics are implemented.

Current limits:

- broad live-agent baseline results are not collected yet;
- target-owned test-suite execution and deployment verification are deferred;
- sandboxing and approval policy are not implemented.

Use DevLab on disposable or version-controlled workspaces until you have reviewed the generated changes and trust your local configuration.

## Trust and safety warning

DevLab executes target-owned configuration.

In particular:

- `.devlab/config/agents.toml` defines the agent CLI commands DevLab runs;
- `.devlab/config/profiles/*.toml` may define setup/teardown/environment lifecycle commands;
- agent permission and approval behavior is provider-specific and controlled through `.devlab/config/agents.toml`.

DevLab does **not** sandbox these commands. Only run DevLab in repositories and configurations you trust. Review `.devlab/config/agents.toml` and profile files before running `devlab run`, especially in cloned or agent-modified workspaces.

## Prerequisites

To install and run DevLab, you need:

- Python 3.12 or newer.
- [`uv`](https://docs.astral.sh/uv/) for installing and running the DevLab tool.
- Git on `PATH`; DevLab initializes target repositories when needed and commits workflow changes after valid sessions.
- At least one configured agent CLI/provider, such as a local coding-agent command, declared in the target project's `.devlab/config/agents.toml` before running `devlab plan` or `devlab run`.

Target projects may define their own validation, build, environment lifecycle, or deployment commands. DevLab may invoke those target-owned commands when configured, but it does not install missing project tools for you.

## Installation from a source checkout

DevLab is not published to PyPI yet. Install it as a `uv` tool from a local checkout or a Git URL.

For DevLab development, install the checkout in editable mode so code changes are reflected immediately:

```bash
cd /path/to/devlab-checkout
uv tool install --editable .
# or: make install-editable
```

For a normal (non-development) installation from a checkout, install a regular tool copy:

```bash
uv tool install /path/to/devlab-checkout
# or, from inside the checkout: make install
```

If the repository is available over Git, install directly from a branch, tag, or commit:

```bash
uv tool install "git+https://example.com/org/devlab.git@main"
```

After installation, the `devlab` command can be run from inside any target project repository.

## Quickstart inside a target project

```bash
mkdir -p /path/to/target-project
cd /path/to/target-project
devlab init
```

`devlab init` initializes Git when needed and creates an initial commit containing all non-ignored files. In existing directories, add secrets, local configuration, caches, and generated artifacts to `.gitignore` before running it.

Edit the target project's system spec. The starter file is:

```text
.devlab/specs/system/README.md
```

For larger projects, split the system or deployment specification across additional Markdown files under `.devlab/specs/system/` or `.devlab/specs/deployment/`; DevLab reads all `*.md` files in those directories.

Configure the target project's agent command. The configured executable must be installed and available on `PATH` before running agent sessions:

```text
.devlab/config/agents.toml
```

Commit your user-authored setup changes before planning. `devlab plan` and `devlab run` require a clean Git working tree so agent-authored changes can be isolated and committed safely:

```bash
git add .devlab/specs .devlab/config
git commit -m "Configure DevLab project"
```

Inspect the workspace:

```bash
devlab doctor
devlab status --verbose
devlab agent-smoke-test
devlab diagnostics
```

Optionally generate design and project plans before implementation, then re-run diagnostics against the planned workflow state:

```bash
devlab plan
devlab doctor
```

`devlab plan` reconciles committed system/deployment specs with durable workflow state. It creates missing design and project planning state, records the committed spec revision it planned against, and stops before implementation. Later, if committed files under `.devlab/specs/system/` or `.devlab/specs/deployment/` change, run `devlab plan` again so architect and planner sessions can carry still-valid work into the current planning generation. Use `devlab plan --revise` when you explicitly want architect and planner sessions to review and update existing plans even without a spec change.

Run the workflow. `devlab run` implements already-reconciled workflow state. It requires a Git repository with a clean working tree, stops if committed specs changed since the last `devlab plan` baseline, and commits all non-ignored changes after every valid session. Re-running it continues where the last `devlab plan` or `devlab run` stopped:

```bash
devlab run --max-sessions 20
```

For prompt-debugging only, retain full base/session prompts alongside agent logs:

```bash
devlab run --retain-prompts
```

Prompt logs and agent output can contain target-project details. Treat `.devlab/logs/agents/` as sensitive.

## CLI commands

- `devlab init [--root PATH] [--force]` — create starter `.devlab/` files.
- `devlab plan [--root PATH] [--revise] [--max-sessions N] [...]` — reconcile committed system/deployment specs with workflow state, run needed architect/planner sessions, and stop before implementation.
- `devlab run [--root PATH] [--max-sessions N] [...]` — run implementation/review/integration continuation from the current reconciled durable state.
- `devlab status [--root PATH] [--verbose]` — report workflow state without mutating it.
- `devlab agent-smoke-test [--root PATH] [--config PATH] [--role ROLE] [...]` — start configured providers with a tiny prompt to verify commands, templated arguments, and prompt transport.
- `devlab diagnostics [--root PATH] [--verbose] [--json]` — report workflow-history diagnostics and quality warnings without mutating state.
- `devlab doctor [--root PATH]` — validate workspace configuration without mutating it.
- `devlab clean-failed-session [--root PATH]` — remove untracked agent/environment logs and artifacts from failed sessions while leaving target source changes untouched.

Useful `run` and `plan` options include `--provider`, `--model`, `--effort`, `--quiet`, `--verbose`, `--log-file`, and `--retain-prompts`.

## Target workspace layout

A DevLab target repository contains workflow state under `.devlab/`:

```text
.devlab/
├── workflow.toml        # workflow control state, including planning completeness
├── config/              # agents, profiles, tooling policy
├── specs/               # system and deployment specs
├── plans/               # design and project plans
├── tasks/               # task files with status metadata
├── milestones/          # milestone workflow state
├── findings/            # corrective integration/architecture findings
├── history/             # archived handoffs
├── logs/                # agent and environment logs
└── session-artifacts/   # current session output before archiving
```

DevLab also discovers optional target-owned project knowledge in `CONTEXT.md`, `CONTEXT-MAP.md`, and `docs/adr/*.md`.

## Agent configuration

Agent invocation is configured per target workspace in `.devlab/config/agents.toml`.

Prefer stdin prompt transport when supported to avoid command-line length limits and prompt text in process listings. See [`docs/agent-configuration.md`](docs/agent-configuration.md) for examples.

## Evaluations

Run deterministic workflow evaluations:

```bash
uv run pytest tests/evaluations
```

Live-agent evaluations are opt-in and token/provider dependent:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/pi-codex.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py -s
```

Keep environment-specific live-agent configs under `.local/live-eval/` and out of version control. See [`docs/evaluations.md`](docs/evaluations.md).

## Development validation

```bash
make check
```

Equivalent direct commands:

```bash
uv run ruff check
uv run ty check
uv run pytest -q
```

## More documentation

- [`docs/design.md`](docs/design.md) — architecture and workflow overview.
- [`docs/operator-guide.md`](docs/operator-guide.md) — operating DevLab in a target workspace.
- [`docs/agent-configuration.md`](docs/agent-configuration.md) — target-owned agent command configuration.
- [`docs/evaluations.md`](docs/evaluations.md) — scripted and live workflow evaluations.
- [`docs/todo.md`](docs/todo.md) — current roadmap and known gaps.

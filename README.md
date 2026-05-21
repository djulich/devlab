# DevLab

DevLab is a reusable CLI and Python package for running an auditable, file-backed, role-based agentic software development workflow inside a target repository.

DevLab provides the orchestrator and packaged worker prompts. The target repository stores product-specific specs, plans, tasks, milestones, findings, handoffs, configuration, and logs under `.devlab/`.

## Maturity

DevLab is an early, tested orchestrator prototype.

Current confidence:

- deterministic unit/integration tests cover the core workflow mechanics;
- scripted workflow evaluations exercise temporary target repositories;
- an opt-in live-agent evaluation path exists and has been used for a small calculator scenario.

Current limits:

- broad live-agent baseline results are not collected yet;
- existing-project adoption is still planned work;
- target-owned test-suite execution and deployment verification are deferred;
- sandboxing and approval policy are not implemented.

Use DevLab on disposable or version-controlled workspaces until you have reviewed the generated changes and trust your local configuration.

## Trust and safety warning

DevLab executes target-owned configuration.

In particular:

- `.devlab/config/agents.toml` defines the agent CLI commands DevLab runs;
- `.devlab/config/profiles/*.toml` may define setup/teardown/environment lifecycle commands;
- `devlab run --dangerously-skip-permissions` may pass reduced-permission-check flags to configured agents.

DevLab does **not** sandbox these commands. Only run DevLab in repositories and configurations you trust. Review `.devlab/config/agents.toml` and profile files before running `devlab run`, especially in cloned or agent-modified workspaces.

## Quickstart from this repository

```bash
uv sync
mkdir -p /path/to/target-project
uv run devlab init --root /path/to/target-project
```

`devlab init` initializes Git when needed and creates an initial commit containing all non-ignored files. In existing directories, add secrets, local configuration, caches, and generated artifacts to `.gitignore` before running it.

Edit the target project's system spec:

```text
/path/to/target-project/.devlab/specs/system/README.md
```

Configure the target project's agent command:

```text
/path/to/target-project/.devlab/config/agents.toml
```

Inspect the workspace:

```bash
uv run devlab doctor --root /path/to/target-project
uv run devlab status --root /path/to/target-project --verbose
```

Run the workflow. `devlab run` requires a Git repository with a clean working tree and commits all non-ignored changes after every valid session:

```bash
uv run devlab run --root /path/to/target-project --auto --max-sessions 20
```

For prompt-debugging only, retain full system/session prompts alongside agent logs:

```bash
uv run devlab run --root /path/to/target-project --auto --retain-prompts
```

Prompt logs and agent output can contain target-project details. Treat `.devlab/logs/agents/` as sensitive.

## CLI commands

- `devlab init [--root PATH] [--force]` — create starter `.devlab/` files.
- `devlab run [--root PATH] [--auto] [--max-sessions N] [...]` — run the workflow loop.
- `devlab status [--root PATH] [--verbose]` — report workflow state without mutating it.
- `devlab doctor [--root PATH]` — validate workspace configuration without mutating it.

Useful `run` options include `--provider`, `--model`, `--effort`, `--quiet`, `--verbose`, `--log-file`, and `--retain-prompts`.

## Target workspace layout

A DevLab target repository contains workflow state under `.devlab/`:

```text
.devlab/
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
uv run ruff check
uv run ty check
uv run pytest
uv run devlab doctor
```

## More documentation

- [`docs/design.md`](docs/design.md) — architecture and workflow overview.
- [`docs/agent-configuration.md`](docs/agent-configuration.md) — target-owned agent command configuration.
- [`docs/evaluations.md`](docs/evaluations.md) — scripted and live workflow evaluations.
- [`docs/todo.md`](docs/todo.md) — current roadmap and known gaps.

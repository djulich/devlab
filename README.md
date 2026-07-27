# DevLab

DevLab is a reusable CLI and Python package for running an auditable, file-backed, role-based agentic software development workflow inside a target repository. DevLab itself requires Python, but target projects may use Python, Rust, Go, C, C++, or mixed toolchains.

DevLab provides the orchestrator and packaged worker prompts. The target repository stores product-specific specs, plans, tasks, milestones, findings, handoffs, configuration, and logs under `.devlab/`.

## Maturity

DevLab is pre-1.0 software with a tested end-to-end workflow and evolving live-agent baselines.

Current confidence:

- deterministic unit/integration tests cover the core workflow mechanics;
- scripted workflow evaluations exercise temporary target repositories;
- opt-in live-agent evaluations exist for representative workflows, with baseline
  collection still ongoing;
- existing-project adoption, spec reconciliation, prompt-size monitoring, and
  agent invocation diagnostics are implemented;
- role sessions use same-session structured handoff submission with trusted
  session identity, aggregate validation feedback, and DevLab-owned publication;
- durable operator clarifications support explicit answer/resume flows and an
  opt-in bounded unattended resolver.

Current limits:

- broad live-agent baseline results are not collected yet;
- orchestrator-enforced execution and recording of task validation commands is
  deferred; worker roles currently run target-owned validation from task/profile
  instructions;
- sandboxing and approval policy are not implemented.

Use DevLab on disposable or version-controlled workspaces until you have reviewed the generated changes and trust your local configuration.

## Trust and safety warning

DevLab executes target-owned configuration.

In particular:

- `.devlab/config/agents.toml` defines the agent CLI commands DevLab runs;
- `.devlab/config/profiles/*.toml` may define setup/teardown/environment lifecycle commands;
- agent permission and approval behavior is provider-specific and controlled through `.devlab/config/agents.toml`.

DevLab does **not** sandbox these commands. Only run DevLab in repositories and configurations you trust. Review `.devlab/config/agents.toml` and profile files before running `devlab implement`, especially in cloned or agent-modified workspaces.

Before starting configured processes, DevLab fingerprints the effective provider
and profile lifecycle configuration. Operators can approve that fingerprint in
user-local state with `devlab trust executable-config`, require an independently
approved digest in CI, or explicitly accept the current snapshot for one
externally contained invocation. DevLab treats provider permission and sandbox
options as opaque operator-owned policy. Trusting configured process entry points
does not certify the commands or their transitive behavior as safe.

## Prerequisites

To install and run DevLab, you need:

- Python 3.12 or newer.
- [`uv`](https://docs.astral.sh/uv/) for installing and running the DevLab tool.
- Git on `PATH`; DevLab initializes target repositories when needed and commits workflow changes after valid sessions.
- At least one configured agent CLI/provider, such as a local coding-agent command, declared in the target project's `.devlab/config/agents.toml` before running `devlab plan` or `devlab implement`.

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
uv tool install "git+https://github.com/mucisland/devlab.git@main"
```

After installation, the `devlab` command can be run from inside any target project repository.

DevLab is licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).
Pre-1.0 compatibility and release expectations are documented in
[`docs/release-policy.md`](docs/release-policy.md).

## Quickstart inside a target project

```bash
mkdir -p /path/to/target-project
cd /path/to/target-project
devlab init
```

Initialization is language-neutral by default. To start a greenfield project
with conventional tooling guidance, select an explicit starter:

```bash
devlab init --template python  # or rust, go, c, cpp
```

Templates only generate initial tooling policy and profile files. They do not
enable a hidden language mode, and DevLab does not install their host tools.

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

Commit your user-authored setup changes before planning. `devlab plan` and `devlab implement` require a clean Git working tree so agent-authored changes can be isolated and committed safely:

```bash
git add .devlab/specs .devlab/config
git commit -m "Configure DevLab project"
```

Inspect the workspace:

```bash
devlab doctor
devlab status --verbose
devlab workflow-state
devlab trust executable-config --show
devlab trust executable-config
devlab agent-smoke-test
devlab diagnostics
```

Optionally generate design and project plans before implementation, then re-run diagnostics against the planned workflow state:

```bash
devlab plan
devlab doctor
```

`devlab plan` reconciles committed system/deployment specs with durable workflow state. It creates missing design and project planning state, records the committed spec revision it planned against, and stops before implementation. Later, if committed files under `.devlab/specs/system/` or `.devlab/specs/deployment/` change, run `devlab plan` again so architect and planner sessions can carry still-valid work into the current planning generation. Use `devlab plan --revise` when you explicitly want architect and planner sessions to review and update existing plans even without a spec change. Use `devlab plan --mark-specs-planned` only for operator-confirmed typo-only, format-only, or otherwise plan-neutral spec commits; it updates the recorded spec baseline without running architect or planner sessions and warns that it bypasses the reconciliation guardrail.

Implement the planned workflow. `devlab implement` carries out already-reconciled workflow state. It requires a Git repository with a clean working tree, stops if committed specs changed since the last `devlab plan` baseline, and commits all non-ignored changes after every valid session. Re-running it continues where the last `devlab plan` or `devlab implement` stopped:

```bash
devlab implement --max-sessions 20
```

For prompt-debugging only, retain full base/session prompts alongside agent logs:

```bash
devlab implement --retain-prompts
```

Prompt logs and agent output can contain target-project details. Treat `.devlab/logs/agents/` as sensitive.

## CLI commands

- `devlab init [--root PATH] [--force]` — create starter `.devlab/` files.
- `devlab plan [--root PATH] [--revise] [--adopt-existing] [--replace-plan] [--mark-specs-planned] [--max-sessions N] [...]` — reconcile committed system/deployment specs with workflow state, run needed architect/planner sessions, and stop before implementation.
- `devlab implement [--root PATH] [--max-sessions N] [...]` — run implementation/review/integration continuation from the current reconciled durable state.
- `devlab clarify [--root PATH] list|show|answer|supersede ...` — inspect and answer durable operator clarifications.
- `devlab resume [--root PATH] [--max-sessions N]` — resume the workflow blocked by an answered clarification.
- `devlab status [--root PATH] [--verbose]` — report workflow state without mutating it.
- `devlab workflow-state [--root PATH] [--digest] [--json]` — report lifecycle/provenance state, planning generations, spec reconciliation, and current work counts without mutating state. Use `--digest` for a compact operator summary; add `--json` to serialize the selected view.
- `devlab agent-smoke-test [--root PATH] [--config PATH] [--role ROLE] [...]` — start configured providers with a tiny prompt to verify commands, templated arguments, and prompt transport.
- `devlab trust executable-config [--root PATH] [--config PATH] [--show|--revoke]` — inspect, approve, or revoke workspace-scoped executable-configuration trust stored in user-local DevLab state.
- `devlab diagnostics [--root PATH] [--verbose] [--json]` — report workflow-history diagnostics and quality warnings without mutating state.
- `devlab doctor [--root PATH]` — validate workspace configuration without mutating it.
- `devlab clean-failed-session [--root PATH]` — remove untracked agent/environment logs and artifacts from failed sessions while leaving target source changes untouched.

Useful `implement` and `plan` options include `--provider`, `--model`, `--effort`,
`--quiet`, `--verbose`, `--log-file`, and `--retain-prompts`. Both commands also
support `--clarification-mode=operator|agent`; `--unattended` selects bounded
agent clarification resolution. They also support
`--handoff-correction` (one isolated correction attempt when a role exits without
an accepted result).

## Target workspace layout

A DevLab target repository contains workflow state under `.devlab/`:

```text
.devlab/
├── workflow.toml        # workflow control state, including planning completeness and resume
├── workflow-events.jsonl # append-only lifecycle/provenance events
├── config/              # agents, profiles, tooling policy
├── specs/               # system and deployment specs
├── plans/               # design and project plans
├── tasks/               # task files with status metadata
├── milestones/          # milestone workflow state
├── findings/            # corrective integration/architecture findings
├── clarifications/      # operator clarification requests and answers
├── history/             # archived handoffs
├── logs/                # agent and environment logs
└── session-artifacts/   # trusted envelope, candidate, result, and rendered handoff
```

## Session results and handoffs

Before invoking a role, DevLab initializes a trusted `session.toml` envelope and
a role-aware `handoff-candidate.toml` under
`.devlab/session-artifacts/<role>/`. The role fills the candidate and submits it
inside the same session with:

```bash
"$DEVLAB_PYTHON" -m devlab.cli session handoff submit
```

DevLab validates the structured candidate and its workflow meaning before
publishing authoritative `result.toml` and the human-readable `handoff.md`.
Rejected attempts are recorded and report aggregate diagnostics to the role.
Accepted results, rendered handoffs, and submission-attempt evidence are archived
together. Directly authored Markdown remains readable in old history but is not
accepted as the control result for a new role session.

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

Some live evaluations require additional host tooling. In particular, the
React/Vite frontend live evaluation requires Podman and access to the Node and
Playwright container images used by the evaluation harness. These are
development/live-evaluation prerequisites, not DevLab runtime package
dependencies.

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
- [`docs/release-policy.md`](docs/release-policy.md) — versioning, compatibility, and release expectations.
- [`docs/todo.md`](docs/todo.md) — current roadmap and known gaps.

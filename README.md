# DevLab

DevLab is a reusable CLI and Python package for running an auditable, file-backed, role-based agentic software development workflow inside a target repository. DevLab itself requires Python, but target projects may use Python, Rust, Go, C, C++, or mixed toolchains.

DevLab exists because substantial projects cannot be created reliably in a
single agent session. It decomposes software development into bounded sessions
whose intent, decisions, progress, and feedback survive as durable project
state. See the [project vision](docs/vision.md) for the motivation, suitable
target projects, and a possible future separation between a reusable workflow
kernel and domain-specific workflow packages.

DevLab provides the orchestrator and packaged worker prompts. The target repository stores product-specific specs, plans, tasks, milestones, findings, handoffs, configuration, and logs under `.devlab/`.

Four commands cover the normal operator loop:

- `devlab status`: Where am I?
- `devlab doctor`: Is the workspace healthy?
- `devlab diagnostics`: How is the workflow performing?
- `devlab continue`: Advance it.

## Maturity

DevLab is pre-1.0 software with a tested end-to-end workflow and evolving live-agent baselines.

Current confidence:

- deterministic unit/integration tests cover the core workflow mechanics;
- scripted workflow evaluations exercise temporary target repositories;
- opt-in live-agent evaluations exist for representative workflows, with baseline
  collection still ongoing;
- existing-project adoption, spec reconciliation, prompt-size monitoring, and
  agent invocation diagnostics are implemented;
- provider sessions support an opt-in output-inactivity limit and an independent
  optional maximum duration, with structured timeout reporting and bounded local
  process-tree cleanup;
- role sessions use same-session structured handoff submission with trusted
  session identity, aggregate validation feedback, and DevLab-owned publication;
- durable operator clarifications support explicit answer/resume flows and an
  opt-in bounded unattended resolver.
- durable research sessions store cited evidence and resume the exact requesting route.

Current limits:

- broad live-agent baseline results are not collected yet;
- configured task and milestone validation is executed and recorded by the
  orchestrator, while missing host tools remain explicit unverified prerequisites;
- DevLab does not supply its own operating-system sandbox or approval layer;
  those controls belong to the configured provider and execution environment.

Use DevLab on disposable or version-controlled workspaces until you have reviewed the generated changes and trust your local configuration.

## Trust and safety warning

DevLab executes target-owned configuration.

In particular:

- `.devlab/config/agents.toml` defines the agent CLI commands DevLab runs;
- `.devlab/config/profiles/*.toml` may define validation, lifecycle,
  prerequisite checks, and preparation commands;
- `.devlab/config/test-services.toml` may define workspace-owned service
  lifecycle commands;
- agent permission and approval behavior is provider-specific and controlled through `.devlab/config/agents.toml`.

DevLab does **not** sandbox these commands. Only run DevLab in repositories and configurations you trust. Review `.devlab/config/agents.toml` and profile files before running `devlab continue`, especially in cloned or agent-modified workspaces.

Before starting configured processes, DevLab fingerprints the effective provider
invocation, profile validation/lifecycle/prerequisite configuration, and managed
test services. Operators can approve that fingerprint in user-local state with
`devlab trust executable-config`, require an independently approved digest in CI,
or explicitly accept the current snapshot for one externally contained
invocation. DevLab treats provider permission and sandbox options as opaque
operator-owned policy. Trusting configured process entry points does not certify
the commands or their transitive behavior as safe.

If a reviewed task changes executable configuration, DevLab stops cleanly before
preparing a session outside that task cycle. The running command never adopts the
changed snapshot; inspect and authorize its new digest, then start a fresh command.

## Prerequisites

To install and run DevLab, you need:

- Python 3.12 or newer.
- [`uv`](https://docs.astral.sh/uv/) for the supported installation and
  development workflow.
- Git on `PATH`; DevLab initializes target repositories when needed and commits workflow changes after valid sessions.
- At least one configured agent CLI/provider, such as a local coding-agent
  command, declared in the target project's `.devlab/config/agents.toml` before
  running `devlab continue`, `devlab plan`, or `devlab implement`.

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
uv tool install "git+https://github.com/djulich/devlab.git@main"
```

After installation, the `devlab` command can be run from inside any target project repository.
Confirm the installed release with:

```bash
devlab --version
```

DevLab is licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).
Pre-1.0 evolution and release expectations are documented in
[`docs/release-policy.md`](docs/release-policy.md).
See [`CONTRIBUTING.md`](CONTRIBUTING.md) to contribute and
[`SECURITY.md`](SECURITY.md) to report vulnerabilities privately.

New to DevLab? Follow [Your First DevLab Workflow](docs/tutorial.md) for a
step-by-step installation, configuration, and small example project.
For a resettable live presentation, use the
[reproducible first-workflow demo](demos/first-workflow/).

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

For larger projects, split the system specification across additional Markdown
files under `.devlab/specs/system/`; DevLab reads all `*.md` files in that
directory. The scaffolded `.devlab/specs/deployment/README.md` is an optional,
inactive deployment-requirements overlay and a checklist for packaging,
runtime, verification, configuration, and production boundaries. Remove its
placeholder marker when deployment is in scope; that activates
deployment-specific planning guidance and diagnostics.

Configure the target project's agent command. The configured executable must be installed and available on `PATH` before running agent sessions:

```text
.devlab/config/agents.toml
```

Commit your user-authored setup changes before continuing. Workflow execution requires a clean Git working tree so agent-authored changes can be isolated and committed safely:

```bash
git add .devlab/specs .devlab/config
git commit -m "Configure DevLab project"
```

Before the first provider session, inspect and authorize the executable
configuration, then smoke-test the provider:

```bash
devlab trust executable-config
devlab agent-smoke-test
```

The trust command displays the effective configuration and fingerprint before
asking for approval. Authorization changes operator-local trust, and the smoke
test starts the configured provider.

Run the workflow through its single normal operator entry point:

```bash
devlab continue
```

`devlab continue` derives the next valid action from durable state. It runs
planning, implementation, review, integration, clarification resume, or a
validation retry as needed. After a bounded stop, resolve any explicitly
reported external condition and run the same command again. On an interrupted
dirty worktree it can offer an exact, operator-confirmed discard back to the
committed boundary; ignored files and external effects are never claimed to be
restored. See the [operator guide](docs/operator-guide.md) for recovery and
phase-restricted automation commands.

Use `status`, `doctor`, and `diagnostics` for read-only inspection at any
checkpoint.

Bounded commands finish with a summary explaining why they stopped and what to
do next. DevLab commits accepted session results so later invocations resume
from repository state rather than conversation memory.

## Core commands

- `devlab init [--root PATH] [--force] [--template neutral|python|rust|go|c|cpp] [--git-user-name NAME --git-user-email EMAIL]` — create starter `.devlab/` files.
- `devlab continue` — perform the next valid lifecycle action; this is the
  normal operator entry point.
- `devlab plan` and `devlab implement` — phase-restricted interfaces for
  explicit planning modes, expert use, and automation.
- `devlab clarify [--root PATH] list|show|answer|supersede ...` — inspect and answer durable operator clarifications.
- `devlab resume [--root PATH] [--max-sessions N]` — resume the workflow blocked by an answered clarification.
- `devlab status`, `devlab diagnostics`, `devlab history`, and `devlab doctor` —
  inspect workflow state without mutating it. `status` also provides JSON,
  digest, and next-command views.
- `devlab agent-smoke-test` — verify configured provider invocation with a tiny
  prompt.
- `devlab trust executable-config` — inspect or manage workspace-scoped
  executable-configuration trust.
- `devlab prerequisite ...` and `devlab test-service ...` — inspect runtime
  requirements, manage attestations, and explicitly clean up owned services.
- `devlab clean-failed-session [--root PATH]` — remove untracked agent/environment logs and artifacts from failed sessions while leaving target source changes untouched.

Run `devlab COMMAND --help` for the authoritative option list.

Research has no standalone command. Architect, planner, and developer may
return `needs_research`; run `devlab continue` to invoke one bounded researcher
and then resume the requester. Results
are strict staged JSON and canonical `.devlab/research/` records with evidence,
sources, confidence, unresolved questions, and provenance. Configure an
optional `[roles.researcher]`; otherwise it inherits the requesting role's
provider. Invalid output or provider failure remains retryable. Research is
supporting evidence, while operator choices and authority use clarification.

Profile prerequisites and managed test services provide declared readiness
checks, bounded runtime preparation, durable service ownership, and explicit
cleanup. Their configuration and safety boundaries are documented in
[Runtime Prerequisites and Managed Test Services](docs/runtime-prerequisites.md).

## More documentation

- [`docs/README.md`](docs/README.md) — documentation map and ownership.
- [`docs/design.md`](docs/design.md) — architecture and workflow overview.
- [`docs/operator-guide.md`](docs/operator-guide.md) — operating DevLab in a target workspace.
- [`docs/how-to/`](docs/how-to/README.md) — step-by-step procedures for common DevLab use cases.
- [`docs/agent-configuration.md`](docs/agent-configuration.md) — target-owned agent command configuration.
- [`docs/runtime-prerequisites.md`](docs/runtime-prerequisites.md) — prerequisite
  checks/preparation and workspace-owned test services.
- [`docs/evaluations/`](docs/evaluations/README.md) — scripted and live workflow evaluations.
- [`demos/`](demos/README.md) — repository-only demonstrations and external graders.
- [`docs/release-policy.md`](docs/release-policy.md) — versioning, compatibility, and release expectations.
- [`docs/roadmap.md`](docs/roadmap.md) — strategic outcomes and 1.0 release gates.

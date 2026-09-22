# DevLab

DevLab is a command-line tool that turns written software requirements into
reviewed changes through a sequence of bounded agent sessions. It coordinates
planning, implementation, review, and integration, keeping the work and its
history in your project's Git repository.

DevLab is intended for projects whose scope spans many agent sessions and needs
consistent decisions, explicit review, and a way to recover after interruptions.
It works with new and existing repositories. DevLab itself runs on Python;
target projects can use Python, Rust, Go, C, C++, or mixed toolchains.

[First-workflow tutorial](https://github.com/djulich/devlab/blob/main/docs/tutorial.md)
· [Documentation](https://github.com/djulich/devlab/blob/main/docs/README.md)
· [Project vision](https://github.com/djulich/devlab/blob/main/docs/vision.md)

## How it works

You supply the requirements, configure the coding agents and project tools, and
review the results. DevLab manages the workflow:

1. **Plan:** an architect develops the design; a planner breaks the work into
   tasks and milestones.
2. **Implement and review:** a developer works on one task. DevLab runs its
   configured validation, then a separate reviewer session checks the work.
   Requested changes return to a developer.
3. **Integrate:** an integrator checks completed milestones. Architecture review
   records remaining gaps for corrective work.

Each agent session has one role. Specifications, plans, tasks, findings,
and handoffs live under `.devlab/` in the target repository, alongside the
software being built. DevLab commits accepted session results and uses the
recorded progress to choose the next action. Sessions can request research or
stop for a decision from you when needed.

You can inspect the files and Git history between runs and continue from the
recorded state after a stop. Progress does not depend on retaining a conversation
with an agent.

You choose the coding-agent CLI and can configure different providers or models
for different roles. DevLab supplies the workflow and role prompts; the target
project supplies its tooling and validation commands.

## Project status

DevLab is **pre-1.0**. Its CLI, configuration, and workspace formats remain
provisional until the 1.0 compatibility freeze. It is distributed as a Python
package to provide the CLI; its Python modules are not a supported library API.
See the [release policy](https://github.com/djulich/devlab/blob/main/docs/release-policy.md)
for compatibility expectations.

Automated tests and scripted workflow evaluations cover the core workflow.
Live-agent evaluation coverage is still developing; see the
[evaluation evidence](https://github.com/djulich/devlab/blob/main/docs/evaluations/README.md).
Start with a disposable project and review the generated changes before relying
on them.

## Install

You need:

- Python 3.12 or newer and [`uv`](https://docs.astral.sh/uv/).
- Git on `PATH`, with a name and email configured for commits.
- An installed coding-agent CLI with access to its provider to run the workflow.
- The build and test tools required by your target project. DevLab does not
  install missing host tools.

DevLab is not yet distributed through production PyPI. Install the current
development version from Git:

```bash
uv tool install "git+https://github.com/djulich/devlab.git@main"
devlab --version
```

To pin an installation, replace `main` with an immutable tag or commit. You can
also install a local checkout with `uv tool install /path/to/devlab-checkout`.
TestPyPI uploads are release-pipeline rehearsals; Git and local checkouts are the
supported installation paths. For an editable development installation, see
[Contributing](https://github.com/djulich/devlab/blob/main/CONTRIBUTING.md).

## Run your first workflow

The [first-workflow tutorial](https://github.com/djulich/devlab/blob/main/docs/tutorial.md)
provides a complete specification, agent configuration, and commands for building
a small Python CLI. The outline below shows the same setup process for a new
project. For an existing repository, follow
[Adopt an existing project](https://github.com/djulich/devlab/blob/main/docs/how-to/adopt-existing-project.md).

### 1. Initialize a target workspace

Create a directory for the software you want to build, then initialize DevLab
inside it:

```bash
mkdir my-project
cd my-project
devlab init
```

Initialization is language-neutral. For a new project with conventional tooling
preferences, use `devlab init --template python` instead; starters also exist
for Rust, Go, C, and C++. Templates provide initial tooling configuration, not
the application itself.

`devlab init` initializes Git when needed and commits non-ignored files. Before
using it in a populated directory, make sure `.gitignore` excludes secrets,
local configuration, caches, and generated artifacts.

### 2. Describe the work and configure the tools

Edit these files in the target workspace:

- `.devlab/specs/system/README.md`: the required behavior and acceptance criteria.
- `.devlab/config/agents.toml`: how DevLab starts your installed coding agent.
- `.devlab/config/tooling.md` and `.devlab/config/profiles/`: the project's
  tooling policy, validation commands, and any environment setup.

The tutorial supplies a working example. For other providers or role overrides,
see [Agent configuration](https://github.com/djulich/devlab/blob/main/docs/agent-configuration.md).

**Review executable configuration before running it.** DevLab executes agent,
validation, and environment commands from the target repository. It does not
sandbox these commands; permissions and isolation come from your agent provider
and execution environment. Only authorize configuration you trust.

Commit your setup changes. DevLab requires a clean working tree before starting
agent sessions:

```bash
git add .devlab/specs .devlab/config
git commit -m "Configure DevLab project"
```

### 3. Check the setup and start a bounded run

```bash
devlab doctor
devlab trust executable-config
devlab agent-smoke-test
devlab continue --max-sessions 2
```

`doctor` checks configuration and workflow state without changing them. The
trust command shows the executable configuration and asks for approval; the
smoke test invokes the provider to check that it works. Resolve any reported
setup problems before continuing.

The continuation command runs at most two role sessions. A complete workflow
usually needs several such runs. Both the smoke test and workflow sessions
consume usage from your configured provider; a session limit does not cap
provider billing.

## Inspect and continue

After a run, read its summary and inspect the generated files and Git commits.
These four commands cover routine operation:

| Question | Command | Purpose |
| --- | --- | --- |
| Where am I? | `devlab status` | Show progress, blockers, and the next action. |
| Is the workspace healthy? | `devlab doctor` | Validate configuration and workflow state. |
| How is the workflow performing? | `devlab diagnostics` | Inspect workflow history and quality indicators. |
| What happens next? | `devlab continue --max-sessions 2` | Run the next sessions from recorded state. |

The first three commands are read-only. `continue` selects planning,
implementation, review, integration, or recovery as needed. Reaching the session
limit is a checkpoint, not completion. Resolve any reported blockers or requests
for your decision, then run the same continuation command again.

See the [operator guide](https://github.com/djulich/devlab/blob/main/docs/operator-guide.md)
for clarification, recovery, unattended operation, and advanced commands. Use
`devlab --help` and `devlab COMMAND --help` for the full command reference.

## Documentation and examples

- [Documentation index](https://github.com/djulich/devlab/blob/main/docs/README.md):
  guides, architecture, evaluations, and project direction.
- [How-to guides](https://github.com/djulich/devlab/blob/main/docs/how-to/README.md):
  adopt an existing project, fix a bug, revise a specification, or recover an
  interrupted workflow.
- [Runtime prerequisites and managed test services](https://github.com/djulich/devlab/blob/main/docs/runtime-prerequisites.md):
  configure validation environments and workspace-owned services.
- [First-workflow demo](https://github.com/djulich/devlab/tree/main/demos/first-workflow/):
  a resettable presentation of the tutorial with independent result checks.

## Contributing and license

See [Contributing](https://github.com/djulich/devlab/blob/main/CONTRIBUTING.md)
for development setup and contribution guidelines. Report bugs through
[GitHub issues](https://github.com/djulich/devlab/issues) and security
vulnerabilities privately through the
[security policy](https://github.com/djulich/devlab/blob/main/SECURITY.md).

DevLab is licensed under the
[Apache License 2.0](https://github.com/djulich/devlab/blob/main/LICENSE).

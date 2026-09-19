# DevLab Tutorial: Your First Workflow

This tutorial takes you from an empty directory to a small, tested Python
command-line application created through DevLab's planning, development, and
review workflow. You do not need to know DevLab before you begin.

You will create a command named `hello-devlab`. By the end, this command will
print a greeting:

```console
$ uv run hello-devlab Ada
Hello, Ada!
```

The tutorial uses the Codex CLI as the worker agent. DevLab can use other agent
CLIs too, but using one concrete provider keeps the first run simple. See
[Agent Configuration](agent-configuration.md) after the tutorial if you want to
use another provider.

## What you will do

You will:

1. install `uv`, Codex, and DevLab;
2. initialize an empty project;
3. write a short system specification;
4. configure and test the worker agent;
5. let DevLab plan, implement, and review the project; and
6. run the finished application and its tests.

DevLab starts several bounded agent sessions to complete a workflow. Even this
small example normally needs separate architecture, planning, development, and
review sessions. The exact number and duration depend on the agent's decisions,
and every session consumes usage from your configured provider. The commands
below limit each DevLab run to at most two sessions so that you get regular
checkpoints. Plan for seven to twelve provider calls and allow up to 80 minutes
for a first run; a simple successful run may finish sooner. Review can add more
development sessions. DevLab does not estimate or cap provider billing; your
Codex sign-in method and account determine whether those calls use an included
allowance or billed API usage.

Use a disposable directory for this tutorial. DevLab executes commands from the
project's checked-in configuration, and worker agents can edit the project.

## Install the prerequisites

This tutorial uses a macOS or Linux shell. On Windows, follow it inside WSL.
You need Git and `curl` on `PATH` and an OpenAI account that can use Codex.

Check Git first:

```bash
git --version
```

If the command is not found, install Git with your operating system's package
manager before continuing. Git also needs your name and email so that DevLab can
create commits. Check them with:

```bash
git config --global user.name
git config --global user.email
```

If either command prints nothing, configure your own identity:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### Install uv and Python

[`uv`](https://docs.astral.sh/uv/getting-started/installation/) installs DevLab
in an isolated environment and can install the required Python version:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

The installer tells you if you need to restart your shell or update `PATH`.
Then run:

```bash
uv --version
uv python install 3.12
```

### Install and sign in to Codex

Install Codex using the command from the
[official Codex CLI guide](https://developers.openai.com/codex/cli/):

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Start Codex:

```bash
codex
```

On the first run, choose **Sign in with ChatGPT** or another available sign-in
method. When Codex is ready for a prompt, exit it with `Ctrl-C`. Confirm that
the command remains available:

```bash
codex --version
```

### Install DevLab

DevLab is not yet published to PyPI. Install it from its Git repository:

```bash
uv tool install --python 3.12 "git+https://github.com/djulich/devlab.git@main"
```

Confirm the installation:

```bash
devlab --version
```

If your shell cannot find `devlab`, run `uv tool update-shell`, restart the
shell, and try again.

## Create the project

Create and enter a new directory:

```bash
mkdir hello-devlab
cd hello-devlab
```

Initialize DevLab with its Python starter:

```bash
devlab init --template python
```

DevLab creates a Git repository, adds its files under `.devlab/`, and makes an
initial commit. The Python starter tells future agents to use `uv`, pytest,
Ruff, and ty. It does not create the application yet.

Look at the new files:

```bash
find .devlab -maxdepth 3 -type f | sort
git log --oneline --max-count=1
```

The two files you will edit are:

- `.devlab/specs/system/README.md`, which says what to build; and
- `.devlab/config/agents.toml`, which says how to start the worker agent.

## Write the system specification

Replace `.devlab/specs/system/README.md` with this specification. You can use
your editor, or copy and run the complete command below:

```bash
cat > .devlab/specs/system/README.md <<'EOF'
# Hello DevLab System Specification

## Goal

Create a small Python command-line application named `hello-devlab` that greets
one person. This is a learning project, so keep the implementation simple.

## Behavior

- Running `uv run hello-devlab Ada` prints exactly `Hello, Ada!`.
- The command accepts one required name argument.
- When the name is missing, the command exits unsuccessfully and shows usage
  information.

## Quality requirements

- Use a `src/` package layout.
- Add focused pytest tests for successful and missing-name behavior.
- Keep the project compatible with Python 3.12 or newer.
- Document installation and first usage in the project `README.md`.

## Acceptance criteria

- `uv run hello-devlab Ada` prints `Hello, Ada!` followed by a newline.
- `uv run pytest` passes.
- `uv run ruff check` passes.
- `uv run ty check` passes.
EOF
```

This file is an operator-owned input. DevLab's architect and planner will use it
to decide what work is needed, but they will not replace it.

## Configure the worker agent

Replace `.devlab/config/agents.toml` with this configuration:

```bash
cat > .devlab/config/agents.toml <<'EOF'
[defaults]
provider = "codex"
max_session_duration_seconds = 900

[providers.codex]
command = "codex"
args = [
    "--sandbox", "workspace-write",
    "--ask-for-approval", "never",
    "exec", "-",
]
stdin_template = "{system_prompt}\n\n---\n\n{session_prompt}"
EOF
```

This starts Codex non-interactively, lets it write only within the project
workspace, and uses your normal Codex model and reasoning defaults. DevLab does
not add a sandbox of its own. The `never` approval setting is necessary because
there is no person inside a non-interactive worker session to answer a Codex
approval prompt.

Review and commit your inputs:

```bash
git diff
git add .devlab/specs/system/README.md .devlab/config/agents.toml
git commit -m "Configure the first DevLab workflow"
git status --short
```

The last command should print nothing. DevLab requires a clean working tree so
that it can keep your inputs separate from agent-authored commits.

## Check the setup

Ask DevLab to inspect the project without changing it:

```bash
devlab doctor
devlab status --verbose
```

`devlab doctor` should finish without blocking problems. In the status output,
each workflow role should resolve to the `codex` provider.

DevLab requires you to review and approve executable configuration before it
runs it. The trust command displays the effective configuration and exact
fingerprint before asking for approval:

```bash
devlab trust executable-config
```

The configuration should refer to the `codex` command you just wrote. Approving
the prompt records trust for that snapshot in your user-local DevLab state.

Now run one tiny provider session to check authentication, prompt transport, and
the configured command:

```bash
devlab agent-smoke-test
```

This smoke test contacts the provider and consumes a small amount of provider
usage. If it fails, do not start the workflow yet. Check `codex` directly,
correct `.devlab/config/agents.toml`, commit the correction, and approve the new
configuration fingerprint.

## Run the workflow

Start DevLab's normal continuation command:

```bash
devlab continue --max-sessions 2
```

DevLab examines the durable project state and chooses the next valid work. On a
new project, the first sessions normally create architecture and project plans.
The `--max-sessions 2` option stops the command after at most two agent sessions;
it does not declare the whole workflow finished.

Read the summary at the end. Then inspect what changed:

```bash
devlab status
devlab diagnostics
git log --oneline --max-count=5
```

DevLab commits valid session results, so `git status --short` should normally be
empty. Plans and tasks are ordinary files under `.devlab/`; you can read them at
any checkpoint.

Continue with the same bounded command:

```bash
devlab continue --max-sessions 2
```

The process ending at this checkpoint demonstrates interruption and
continuation: DevLab is no longer running, but its plans, tasks, events,
handoffs, and resume position remain in files and Git. Starting the same command
continues from that durable state rather than relying on conversational memory.

Later sessions implement and review the planned tasks. A reviewer may request
changes, which adds another development and review cycle. Keep reading each
summary and running the same command until DevLab reports that the workflow is
complete. You can ask for the safe next command at any time:

```bash
devlab status --next-command
```

If DevLab stops for an untrusted configuration, a clarification, a failed
validation, or another condition, follow the specific commands in its summary
instead of guessing. The [interruption guide](how-to/resume-interrupted-workflow.md)
explains the less common recovery paths.

## Try the finished application

Once DevLab reports completion, inspect the repository and run the acceptance
checks from your specification:

```bash
git status --short
git log --oneline --max-count=12
uv run hello-devlab Ada
uv run pytest
uv run ruff check
uv run ty check
```

The greeting should be:

```text
Hello, Ada!
```

The validation commands should pass, and `git status --short` should print
nothing. You have now taken one project through specification, planning,
implementation, review, and verification while keeping the workflow record in
Git.

## Where to go next

- Read the [Operator Guide](operator-guide.md) to understand the files and
  lifecycle in more detail.
- Use the [reproducible first-workflow demo](../demos/first-workflow/) when you
  want versioned preparation and marker-protected reset commands for a live
  presentation or repeated rehearsal.
- Read [Agent Configuration](agent-configuration.md) to select models, set
  reasoning effort, use another provider, or use a separate reviewer.
- Follow [Adopt an Existing Project](how-to/adopt-existing-project.md) when you
  are ready to use DevLab in a repository that already contains software.
- Keep using `devlab continue` as the normal entry point. Use `devlab status`
  and `devlab doctor` whenever you want a read-only view of the current state.

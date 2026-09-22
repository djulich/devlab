# First Workflow Demonstration

This is the reproducible companion to the
[first-workflow tutorial](../../docs/tutorial.md). It prepares the same small
`hello-devlab` target from versioned inputs, making it suitable for a live demo
or a clean rehearsal.

The demonstration uses Codex as the worker provider. It requires DevLab, Git,
`uv`, Python 3.12, and an authenticated `codex` command on `PATH`. Agent calls
consume provider usage. Plan for seven to twelve provider calls and allow up to
80 minutes for a first run; a simple successful run may finish sooner.

## Prepare a Disposable Target

Run preparation from the DevLab repository root. Choose an absolute target path
that does not exist. The preparation script initializes
the Python starter, installs this demo's specification and agent configuration,
and commits those operator-owned inputs:

```bash
./demos/first-workflow/prepare.sh /tmp/devlab-first-workflow
cd /tmp/devlab-first-workflow
```

Review the inputs and authorize their executable configuration:

```bash
devlab doctor
devlab status --verbose
devlab trust executable-config
devlab agent-smoke-test
```

The trust command displays the effective configuration and fingerprint before
asking for approval.

## Run Bounded Checkpoints

Run at most two role sessions at a time:

```bash
devlab continue --max-sessions 2
devlab status
devlab status --next-command
devlab diagnostics
```

Stopping after the first command demonstrates a clean checkpoint between
sessions: the process has ended, while plans, tasks, events, and handoffs remain
in the repository. This does not simulate a crash with uncommitted changes. Inspect them and the Git history, then run the same
four commands again. Continue until DevLab reports that the workflow is
complete, without exceeding 12 total provider calls or 80 elapsed minutes.

Verify the reviewed result:

```bash
git status --short
uv run hello-devlab Ada
uv run pytest
uv run ruff check
uv run ty check
devlab diagnostics --verbose
```

The greeting must be `Hello, Ada!`, all validation commands must pass, and the
worktree must be clean.

## Reset

Leave the target directory, then run the marker-protected reset script. It
refuses to remove a directory that was not created by `prepare.sh`:

```bash
cd /path/to/devlab-checkout
./demos/first-workflow/reset.sh /tmp/devlab-first-workflow
```

Run `prepare.sh` again to reproduce the initial state. Never use the reset
script on a target containing work you want to keep.

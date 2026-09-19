# Adopt an Existing Project

Use this procedure for the first DevLab planning run in a repository that
already contains source code. Existing-project adoption tells the architect and
planner to inspect and preserve the project's current structure, development
stack, and validation approach.

## 1. Prepare the repository

Make sure secrets, local configuration, caches, build output, and other
generated artifacts are covered by `.gitignore`. Commit or otherwise resolve
all existing work so the repository has a clean Git working tree.

If the directory is not already a Git repository, `devlab init` initializes it
and creates a baseline commit containing all non-ignored files.

## 2. Initialize DevLab

Use neutral initialization for an established project so the generated starter
policy does not imply a language or build system:

```bash
devlab init --template neutral
```

Initialization does not overwrite existing files unless `--force` is supplied.
Do not use `--force` as an upgrade mechanism for an established DevLab
workspace.

## 3. Describe the intended work

Edit the Markdown files under:

```text
.devlab/specs/system/
.devlab/specs/deployment/
```

Record the required behavior and relevant constraints, not an assumed
implementation. DevLab treats these files as operator-owned planning input;
`devlab plan --adopt-existing` reads them but does not own or replace them.

## 4. Configure agents and validation

Configure an installed provider in `.devlab/config/agents.toml`. Review
`.devlab/config/tooling.md` and the profiles under
`.devlab/config/profiles/`. Validation should invoke commands, scripts, and
tools owned or documented by the target project. DevLab reports missing host
tools rather than installing them.

Commit the operator-authored setup:

```bash
git add .devlab .gitignore
git commit -m "Configure DevLab for existing project"
```

## 5. Validate and authorize the workspace

```bash
devlab doctor
devlab status --verbose
devlab trust executable-config
devlab agent-smoke-test
```

Executable configuration includes agent configuration, executable profile
fields, and managed-test-service definitions. The trust command displays it and
its fingerprint before asking for approval.

## 6. Create the adoption plan

```bash
devlab plan --adopt-existing
```

This mode is for the first planning run, before an active DevLab plan exists.
The architect records a current-state baseline and gaps from the specifications;
the planner creates tasks around the repository's existing validation path.

Inspect the resulting `.devlab/plans/`, `.devlab/tasks/`, and
`.devlab/milestones/` files, then check the workspace:

```bash
devlab doctor
devlab status --verbose
```

## 7. Continue the workflow

```bash
devlab continue --max-sessions 20
```

The session limit is a bound, not a completion target. If the summary reports
`session limit reached`, inspect its next-command advice and run another bounded
continuation command when appropriate.

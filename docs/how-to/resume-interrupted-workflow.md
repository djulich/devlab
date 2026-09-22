# Resume an Interrupted Workflow

DevLab keeps workflow state in the target repository, so bounded, failed, or
clarification-blocked runs can be inspected and continued without relying on
conversation history.

## 1. Inspect why the workflow stopped

Start with the previous command's final summary. Then run read-only diagnostics:

```bash
devlab status --verbose
devlab status --next-command
devlab doctor
```

Use the reported stop reason and next command rather than guessing which role
should run. Fix provider availability, an unclean worktree, invalid state, or
other reported prerequisites before continuing.

`devlab doctor` is the authoritative global health check and returns nonzero for
every finding. Workflow commands reuse those same domain-owned findings and stop
only when a finding blocks the requested planning or session operation. They
still print known non-blocking findings; proceeding does not make the global
doctor result healthy.

## 2. Continue an ordinary bounded run

If a run stopped only because its session bound was reached, continue with:

```bash
devlab continue --max-sessions 20
```

A session-limit stop is successful but does not mean the workflow is complete.

If executable configuration changed, inspect and authorize the current snapshot
before continuing:

```bash
devlab trust executable-config
```

The command displays the effective configuration and fingerprint before asking
for approval.

## 3. Recover an interrupted session with uncommitted changes

First stop any still-running provider process and inspect the affected work:

```bash
git status --short
git diff
git diff --cached
```

Read any untracked files named by `git status` as well; they do not appear in
`git diff`. Preserve work you want to keep before agreeing to discard it.

Run `devlab continue` to see the supported recovery action. For ordinary
uncommitted state, it can propose discarding the described tracked, staged,
and non-ignored untracked changes back to the observed committed boundary.
Inspect the exact HEAD and affected paths before confirming. If you decline,
follow the preservation guidance it prints, including the scoped stash command
when applicable. Do not substitute a broader reset or clean command.

Git conflicts, an in-progress Git operation, or nested repository dirt require
the explicit remediation DevLab reports. A discard does not undo ignored files,
containers, databases, or other external effects. Check those separately before
restarting the session.

`devlab clean-failed-session` removes only eligible untracked session diagnostics.
It does not roll back tracked workflow or product changes and is not a general
recovery command.

## 4. Answer an operator clarification

List and inspect the pending clarification:

```bash
devlab clarify list
devlab clarify show CL0001
```

Record operator intent using the answer shape requested by the clarification:

```bash
devlab clarify answer CL0001 --choice A
```

or:

```bash
devlab clarify answer CL0001 --text "Use a 24-hour idle timeout."
```

For a file-edit clarification, edit only the requested paths, commit the
required durable change when instructed, and provide a concise text answer that
describes it.

Resume from the validated pointer stored in `.devlab/workflow.toml`:

```bash
devlab resume
```

To answer and resume in one operation, add `--resume` to `devlab clarify
answer`. If a clarification is genuinely obsolete, use `devlab clarify
supersede` with a reason instead of inventing an answer.

## 5. Inspect the continued run

After continuation, check the final summary and repository state:

```bash
devlab doctor
devlab status --verbose
git status --short
```

Reporting commands do not repair or mutate workflow state. If diagnostics still
report invalid state, resolve that problem before starting another agent
session.

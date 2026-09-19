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

## 3. Answer an operator clarification

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

## 4. Inspect the continued run

After continuation, check the final summary and repository state:

```bash
devlab doctor
devlab status --verbose
git status --short
```

Reporting commands do not repair or mutate workflow state. If diagnostics still
report invalid state, resolve that problem before starting another agent
session.

# Resume an Interrupted Workflow

DevLab keeps workflow state in the target repository, so bounded, failed, or
clarification-blocked runs can be inspected and continued without relying on
conversation history.

For supported failure scenarios, command boundaries, and the exact cleanup
scope, see [Recovery in the operator guide](../operator-guide.md#recovery).

## 1. Inspect why the workflow stopped

Start with the previous command's final summary. Then run read-only diagnostics:

```bash
devlab status --verbose
devlab status --next-command
devlab doctor
```

Use the reported stop reason and next command rather than guessing which role
should run. For uncommitted changes, run `devlab continue` for diagnosis and
recovery choices. Resolve provider availability, invalid state, or other reported
prerequisites before starting further sessions.

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

`devlab continue` reports related session evidence, provider timeout/failure
details, handoff candidate/result presence, and all preservation/restart choices
before asking whether to discard changes. A short “What happened” summary
connects the recorded stop to session completion before the detailed evidence.
It states uncertainty when records are incomplete or cannot explain current edits.
Declining leaves files unchanged and
prints only that confirmation. In unattended mode, the same guidance is shown
and continuation stops unless explicit discard authorization was supplied.
`devlab doctor` retains a concise dirty-worktree finding and points to `continue`
for diagnosis and recovery options. Doctor remains read-only; continuation can
start workflow work when the worktree is clean or after authorized recovery.
Candidate claims are not accepted results, and session evidence does not prove
that every current edit came from the session. Missing or malformed evidence is
reported as unknown rather than guessed.

New role sessions record their starting HEAD, last lifecycle phase, accepted
handoff reference, and uncommitted stop reason in session metadata. Recovery diagnosis uses
Git history to identify a commit containing the metadata; that is evidence of
preservation, not reviewer approval. Provider success alone does not establish
successful handoff processing or commit. Older sessions may lack lifecycle
details; a start record without completion may represent an active or interrupted
session. Auxiliary researcher/resolver/doctor sessions retain their existing
provider metadata and do not yet record these main workflow lifecycle phases.

First stop any still-running provider process and inspect the affected work:

```bash
git status --short
git diff
git diff --cached
```

Read any untracked files named by `git status` as well; they do not appear in
`git diff`. Preserve work you want to keep before agreeing to discard it.
Stashing with untracked files preserves partial work but restarts the workflow
from the committed boundary. To retain the implementation in place, review and
finish it, validate it, and commit selectively without manufacturing a completed
handoff or reviewer approval.

Run `devlab continue` to see the supported recovery action. For ordinary
uncommitted state, it can propose discarding the described tracked, staged,
and non-ignored untracked changes back to the observed committed boundary.
Inspect the diagnosis, recovery alternatives, exact HEAD, and affected paths
before confirming. All guidance, including the applicable stash command, is
shown before the prompt; declining reveals no additional choices. The offered stash preserves tracked and non-ignored untracked
work across the repository. Do not substitute a broader reset or clean command.

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

# ADR 0012: Use one workflow continuation entry point

## Status

Accepted

## Context

DevLab exposes planning, implementation, clarification resume, diagnostics,
doctor, cleanup, and prerequisite commands. After an abnormal stop, an operator
must otherwise diagnose both the failure and which command represents the next
valid lifecycle transition. This duplicates lifecycle policy in operator
knowledge and makes interrupted bookkeeping especially difficult to recover
without losing evidence.

Reporting commands must remain non-mutating, and DevLab must not infer whether
arbitrary product changes are correct. Some failures are nevertheless
recognizable incomplete DevLab-owned transactions whose intended completion is
provable from durable accepted-session envelopes and archived evidence.

## Decision

`devlab continue` is the normal operator entry point. It derives the next valid
action from durable workflow state and delegates to existing bounded planning,
implementation, clarification-resume, research, and validation mechanics.
After a bounded stop, operator guidance returns to `devlab continue`.

Recovery is an internal continuation action, not a separate general-purpose
fix command. DevLab does not reconstruct arbitrary interrupted transactions or
classify operations as repeatable. When plain uncommitted state prevents
continuation, it may instead offer to discard tracked, staged, and non-ignored
untracked changes back to the observed committed boundary. The proposal is
bound to the exact HEAD, affected paths, Git status classifications, clean
preview, and session identity, and requires operator confirmation. File contents
are not hashed because approval concerns the affected Git scope, not a particular
version of already-dirty content. Git conflicts, in-progress Git operations, and
nested repository dirt are refused. After reset and clean, DevLab verifies that
the worktree is actually clean before recording the interruption or continuing.

If the operator declines or DevLab refuses, it emits structured, condition-specific
guidance: inspection commands, a non-destructive stash alternative when
applicable, exact manual remediation, warnings, and `devlab continue` as the
retry command. DevLab restores only Git-controlled repository state. Ignored
files and external effects are neither reverted nor claimed to be repeatable;
the operator decides whether restarting the bounded session is appropriate.

`devlab status`, `devlab doctor`, and `devlab diagnostics` remain read-only.
`devlab plan`, `devlab implement`, and targeted resume commands remain
available as phase-restricted expert and automation interfaces.

## Consequences

Operators normally learn one continuation command rather than classifying the
current lifecycle phase. The same read-only next-action resolver drives reports
and execution, reducing contradictory advice. At most one bounded session of
uncommitted progress is intentionally sacrificed instead of introducing a
general transaction journal. External side effects remain an explicit operator
consideration, and unsupported Git states are never hidden behind speculative
repair.

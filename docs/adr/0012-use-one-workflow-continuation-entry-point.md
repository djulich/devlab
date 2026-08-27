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
fix command. A recovery recipe must:

- recognize one exact state from durable evidence;
- enumerate every path it may mutate;
- refuse staged, mixed, ambiguous, or stale state;
- be idempotent and evidence-preserving;
- require explicit operator approval when it creates an intervention commit;
- never determine whether product work is correct.

`devlab status`, `devlab workflow-state`, `devlab doctor`, and `devlab
diagnostics` remain read-only. `devlab plan`, `devlab implement`, and targeted
resume commands remain available as phase-restricted expert and automation
interfaces.

## Consequences

Operators normally learn one continuation command rather than classifying the
current lifecycle phase. The same read-only next-action resolver drives reports
and execution, reducing contradictory advice. Known interrupted transactions
can be completed safely, while unknown incidents still require a manual decision
and are never hidden behind speculative repair.

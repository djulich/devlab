# ADR 0016: Own Configured Validation and Gate Review

## Status

Accepted. Amends the validation policy used by ADR 0015.

## Context

Developer prompts required the full configured suite before handoff, then the
orchestrator immediately repeated it. Slow lifecycle checks consumed much of a
bounded agent session. Meanwhile, profile-default failures were only warnings,
so review could begin despite failed configured checks.

## Decision

The orchestrator owns the full configured mechanical suite after a completed
developer or integrator handoff. Those agents run focused checks needed for
implementation, diagnosis, or integration risks and report only actual results.
Reviewer validation remains independent. This removes the prompt requirement to
duplicate the full suite; it does not prohibit checks needed to develop safely.

All configured task-command failures use the existing bounded correction and
doctor recovery policy, regardless of whether commands came from task metadata
or profile defaults. Review cannot proceed on a failed profile check. Historical
failed validation for tasks awaiting review is retried before reviewer selection.
Missing prerequisites and infrastructure failures remain separate outcomes.

Do not reuse agent claims as authoritative validation evidence or add a cache
keyed only by source changes: lifecycle checks also depend on external state.
Fresh review and milestone checks retain their separate purposes.

## Consequences

Targets must scope validation to checks that can pass for the current task. A
repository-wide suite that depends on later tasks needs an appropriate task
override, rather than an implicit warning exception. Existing pending review
work may return to development when its historical failure persists.

Durable outcomes and bounded recovery are reusable workflow mechanics. Choosing
which software roles run checks, returning tasks to development, and gating
review and milestone integration remain explicit software-workflow policy.
No generic kernel interface or new configuration is introduced.

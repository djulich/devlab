# ADR 0015: Route Bounded Doctor Recovery

## Status

Accepted.

## Context

A developer session can fail to advance its task without telling the operator
why. A repeated explicit task validation failure has the same symptom.
Stopping safely preserves evidence, but asking an operator to inspect raw logs
is an expensive default. Repeating the developer session without new evidence
can waste sessions or loop indefinitely.

## Decision

After the first unexplained non-advancing developer session, or after repeated
explicit task validation failure, DevLab commits the evidence and records one
durable doctor recovery route for that task. The doctor is a bounded
auxiliary role. It reads task and session evidence, may use its own configured
provider, and writes only a strict staged diagnosis with existing file evidence
and one of three proposed actions: retry the developer with specific guidance,
send a focused revision to the planner, or stop for the operator.

The orchestrator validates the diagnosis and owns all transitions. A supported
action continues automatically within the remaining session budget or on the
next `devlab continue`. A doctor-routed planner may revise only the assigned
task and workflow bookkeeping. The resulting developer attempt is bounded; a
further failure stops without invoking another doctor. Clarification and research
interruptions preserve the diagnosis and remaining recovery route across resume;
they do not reset the recovery allowance. Successful completion follows existing
validation policy, including soft profile-default warnings. Recovery belongs to
its planning generation: specification reconciliation takes precedence, and
generation replacement archives and clears the old recovery with its task.

The doctor is prohibited from editing product or workflow files, running
arbitrary repairs, installing host tools, or deciding unresolved product intent.
DevLab checks and restores workspace file contents, types, symlink targets, and
permissions after invocation. This detects workspace contract violations; it is
not a process sandbox and cannot undo external effects. Provider permissions
remain responsible for process containment. Existing authorized prerequisite
preparation and managed-test-service ensure commands remain the only automatic
environment preparation paths.

If the diagnosis is inconclusive, invalid, or the bounded repair fails, DevLab
records the result and reports focused guidance. The operator can resolve the
cause and use `devlab continue --retry-stopped-task` explicitly. Read-only
reporting surfaces the pending or blocked recovery route.

## Consequences

- The expected benefit is a specific diagnosis and continuation with less
  operator log inspection. Representative live-provider evaluations are needed
  to establish diagnosis quality and the additional session cost.
- Doctor and planner sessions consume the same session budget as other roles.
- A planner revision and subsequent developer session can span separate
  invocations without losing their route.
- A doctor's recommendation is evidence, not authority; code validates actions
  and enforces one task, bounded retries, and workspace boundaries.
- Role invocation, staged results, provenance, and resume pointers are reusable
  workflow mechanics. Which failures trigger a doctor, whether a task may be
  revised, and which software role follows are DevLab software-workflow policy.

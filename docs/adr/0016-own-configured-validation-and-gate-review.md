# ADR 0016: Own Configured Validation and Gate Review

## Status

Accepted.

## Context

Developer prompts previously required the full configured suite before handoff,
then the orchestrator immediately repeated it. Slow lifecycle checks consumed
much of a bounded agent session. Meanwhile, profile-default failures were only
warnings, so review could begin despite failed configured checks.

Independent review is essential, but repeating the same expensive suite after an
orchestrator-observed pass does not necessarily add independent scrutiny.
Reviewers should spend that time checking acceptance criteria, test adequacy and
uncovered failure modes. A recorded HEAD alone cannot justify evidence reuse:
validation runs against a working tree that may contain uncommitted changes.

## Decision

### Validation ownership and failure gates

The orchestrator owns the full configured mechanical suite after a completed
developer or integrator handoff. Those agents run focused checks needed for
implementation, diagnosis, or integration risks and report only actual results.
They need not repeat the full suite solely to submit a handoff or claim its
pending results.

All configured task-command failures use the bounded correction and doctor
recovery policy in [ADR 0015](0015-route-bounded-doctor-recovery.md), regardless
of whether commands came from task metadata or profile defaults. Review cannot
proceed on a failed profile check. Historical failed validation for tasks awaiting
review is retried before reviewer selection. Missing prerequisites and
infrastructure failures remain separate outcomes.

### Independent review and evidence reuse

The orchestrator may supply a reviewer with the latest complete passing task
validation record when its commands, resolved profile/validation contract,
versionable workspace content and inherited/managed command environment match.
Records identify actual file content and modes before and after execution;
changed inputs during validation disable reuse. Normal bookkeeping and commits
of identical tested content do not invalidate evidence. Old, malformed, failed,
partial or mismatched records cannot enable reuse. Missing logs and unsupported
inputs (including symlinks and submodules) also disable reuse conservatively.

Reviewers inspect the supplied evidence and independently review behavior and
test adequacy. They run focused checks for uncovered risks, rather than repeat
the configured suite solely for approval. Without supplied matching evidence,
they execute configured checks independently. Handoffs distinguish reused
observations from checks the reviewer actually ran. Agent claims are not
accepted as authoritative validation evidence.

This is reuse of a recorded observation, not certification of the current
external environment. Ignored dependencies, installed tools, external services
and physical devices are not identified by the workspace digest. Reviewers must
rerun affected checks when those conditions or environment setup can invalidate
the observation. Matching environment variables and the DevLab interpreter do
not establish external service freshness. No source-only validation cache or
partial-suite resume is introduced.

Before accepting approval that used supplied evidence, the orchestrator checks
its applicability again. A change to identified inputs requires a fresh full
configured run before closure. Failure returns the task to development; missing
tools or infrastructure errors leave it awaiting review and stop progression.
Rejected reviews do not incur an extra suite merely to record the rejection.
Milestone validation and failed-validation retries retain their separate fresh
runs; retries start the suite from the beginning.

### Observational progress reporting

Validation announces each command before execution and its outcome afterward.
While waiting, validation and provider sessions share a configurable reporting
interval (60 seconds by default, zero to disable). Heartbeats distinguish
observed output from silence, without treating output as proof of progress or
resetting execution/inactivity deadlines. Both streams are drained while waiting;
reporting requires no additional threads. The interval is an operator logging
option, not executable workspace configuration or software-workflow policy.

## Consequences

Targets must scope validation to checks that can pass for the current task. A
repository-wide suite that depends on later tasks needs an appropriate task
override, rather than an implicit warning exception. Existing pending review
work may return to development when its historical failure persists.

Evidence matching is intentionally conservative and can cause a redundant run
when an unrelated versionable file or environment variable changes. It does not
attempt dependency analysis or certify arbitrary shell-command inputs. Future
optimization must preserve these distinctions rather than broaden cache claims.

Durable outcomes, validation provenance, progress reporting and bounded recovery
are reusable mechanics. Choosing which software roles run checks, when reviewers
can reuse evidence, and how results gate task closure and milestone integration
remain explicit software-workflow policy. No generic kernel interface or new
workflow-policy configuration is introduced.

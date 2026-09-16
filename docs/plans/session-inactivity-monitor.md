# Session Inactivity Monitor and Maximum Duration

Status: implemented and development-complete (2026-09-16). No further
development slice is planned. A controlled live-provider smoke run and output-gap
observation remain as an operational follow-up before any inactivity default is
considered; they are not required to complete this implementation.

## Problem and evidence

DevLab previously applied only an absolute timeout to an agent CLI invocation.
That bounded elapsed time but did not distinguish a silent provider from an
active agent that had exhausted its budget.

During Generation 2 of system-evolution-01, developer invocation
`20260913T000729_019_developer` on T0006 reached its 1,200-second limit.
The timestamped Codex record showed edits immediately before a final deployment
check began, about six seconds before termination. An earlier successful check
took approximately 126 seconds. This supports budget exhaustion rather than an
approval wait; it does not establish that the final check would have succeeded.
Keep that attempt's result and recovery evidence intact. Do not change the
completed comparison's recorded timeout policy or preserved evidence.

## Decision

DevLab now enforces two independent limits with narrowly defined semantics:

| Limit | Purpose | Reset condition |
|---|---|---|
| Inactivity timeout | Detect absence of observable provider output | New bytes on either stdout or stderr |
| Maximum session duration | Bound elapsed invocation time | Never resets |

The first implementation measures silence, not semantic progress. A noisy retry
loop can evade the inactivity limit; a healthy silent build can exceed it.
Retain an optional absolute limit as the resource-control backstop and explain
these limitations in configuration and stop messages.

Observe process streams directly. Do not tail log files, parse human-readable
provider output, or depend on Codex's private session storage. Structured
provider events may improve diagnostics later, but are not required for this
feature.

## Scope and ownership

- `agent_config.py`: load and validate limits through existing role/provider
  resolution. Preserve the current configuration hierarchy.
- `agents.py`: invoke and monitor the provider process, enforce deadlines,
  preserve output, terminate and reap local processes, and return structured
  outcomes. Keep tightly coupled process-monitoring code here.
- `orchestrator.py`: select authorized invocation policy and handle returned
  outcomes through existing failure/recovery paths. No provider-event parsing.
- `session_logging.py`: record resolved limits, duration, inactivity at stop,
  and the specific timeout reason.
- Reporting adapters: distinguish silence from total-budget exhaustion without
  changing state or reproducing potentially sensitive raw output.
- `environment.py`: retain separate command timeouts for DevLab-owned setup,
  teardown, and post-session validation. Streaming those commands is separate
  work, not a prerequisite for this monitor.

Deadlines, stream observation, process ownership, and outcome provenance are
reusable workflow mechanics. Task transitions, validation policy, handoff
acceptance, and interruption recovery remain software-workflow policy. No new
generic kernel abstraction is needed for this implementation.

## Configuration and compatibility

Configuration names (illustrative durations, not selected defaults):

```toml
inactivity_timeout_seconds = 600
max_session_duration_seconds = 1800
```

- Inactivity monitoring is opt-in. Existing workspaces preserve their defaults,
  including the existing meaning of an omitted timeout.
- The string `"none"` explicitly disables an inherited limit. Negative values,
  zero, booleans, and other non-integer values are rejected.
- Effective values are logged and the new fields participate in executable-
  configuration fingerprinting and trust.
- The maximum can be disabled where operator policy permits, with the documented
  consequence that an output-producing loop can then run indefinitely.
- No inactivity default was selected from the motivating failed run. Typical
  output gaps, especially during silent builds and tests, must be observed before
  proposing a default change.

## Monitoring algorithm

1. Start the invocation with monotonic start and last-output timestamps. Silence
   before the first byte counts toward inactivity.
2. Drain stdout and stderr concurrently into their existing separate log files.
   Read chunks, not lines, so partial lines and output without newlines count.
3. Update the last-output timestamp on receipt of nonempty bytes from either
   stream. Do not count polling, elapsed timers, or monitor diagnostics as child
   activity. Preserve bytes without requiring valid text decoding.
4. Check both deadlines at a bounded interval without busy polling. Use
   monotonic time for enforcement and wall-clock time only for human records.
5. On expiry, terminate the owned invocation, allow a bounded grace period, then
   force termination if necessary. Drain remaining output and reap processes.
6. Return a structured result with timeout kind, effective limits, elapsed time,
   and time since last output.

Maintain stdin prompt delivery without deadlocking against full output pipes.
Handle stream EOF independently: one closed stream must not stop draining the
other. Do not wait indefinitely for EOF from a descendant that retained a pipe.
Process exit and deadline races need deterministic handling: prefer an already
observed exit; otherwise report the earlier deadline, with a documented tie rule.

Use process groups or the supported platform equivalent for bounded local-child
cleanup. Never signal unrelated process groups. Document platform limitations,
including detached descendants. Container and remote side effects are not
rolled back by process termination and remain subject to existing recovery.
Ensure output-capture failures also clean up the invocation and report an error.

## Outcomes and minimal agent awareness

Example stop messages:

```text
Session stopped: provider output inactive for 600 seconds.
Elapsed session time: 1,043 seconds.
```

```text
Session stopped: maximum duration of 1,800 seconds reached.
Last provider output: 2 seconds ago.
```

Keep timeout outcomes machine-distinguishable even if both retain exit code 124.
Audit existing callers of `failure_kind="timeout"` before choosing a compatible
timeout subtype or new failure kinds. Older metadata must remain readable.
Persist the resolved limits and stop metrics; no per-byte event journal is
required. Configured limits belong in durable invocation artifacts, while live
monotonic timers are ephemeral execution state.

When a maximum is configured, expose the absolute deadline in trusted session
context and give concise guidance that validation and handoff must fit within
it. The agent must not control the deadline. Wall-clock presentation is advisory;
monotonic enforcement remains authoritative.

Do not automatically restart, extend a limit, accept partial work, or advance a
task after timeout. Preserve existing interruption and handoff contracts.

## Deferred alternatives

- Parsing meaningful progress, approval waits, retry loops, or tool events:
  useful later for diagnostics but provider-specific and insufficient to prove
  progress. Byte observation is the portable first step.
- Planner-assigned task budgets or complexity classes: unnecessary for initial
  silence detection; would add allocation policy and accounting requirements.
- Validation/handoff reserves and historical duration prediction: revisit only
  if explicit total budgets continue causing avoidable incomplete sessions.
- A `devlab session budget` command: optional follow-up if deadline context is
  insufficient in practice.
- Validated incomplete checkpoints: separate workflow-contract change; do not
  accept timeout residue implicitly.
- Task-wide or whole-run cumulative budgets: distinct from an invocation limit;
  the maximum here does not bound accumulated retries or multiple sessions.

Related plans: [invocation observability](agent-invocation-observability-and-error-handling.md)
and [resilient handoffs](resilient-session-handoffs.md). Implemented portions of
those plans remain historical context, not instructions to replace current code.

## Implementation record

The implementation audit, configuration model, concurrent stream monitor,
bounded process cleanup, structured outcomes, durable metadata, reporting,
trusted deadline context, documentation, and automated validation are complete.
The completed source validation was 808 passed and 12 skipped; the demo grader
validation was 40 passed.

One non-development follow-up remains: perform a controlled provider smoke run
outside scored targets and record representative output gaps. This is evidence
collection for any future default-policy proposal, not an unfinished development
slice. Do not infer or introduce a default inactivity timeout without that
evidence and a separate decision.

## Acceptance and tests

- A silent child reaches inactivity before a longer maximum.
- Periodic stdout or stderr, including partial lines and non-text bytes, resets
  inactivity; a continuously noisy child still reaches its maximum.
- A process producing no first output is bounded; one stream's EOF does not
  disable monitoring of the other.
- Concurrent high-volume output and stdin prompt delivery do not deadlock or
  accumulate unbounded memory; captured output is preserved.
- Normal exit, nonzero exit, missing executable, capture failure, interruption,
  and deadline races return the correct result and clean up owned processes.
- Timeout terminates a local child tree, including a child ignoring graceful
  termination, without hanging on inherited pipes or affecting unrelated work.
- Legacy timeout configuration retains behavior; conflicting names and invalid
  values are rejected; new policy affects the authorization fingerprint.
- Metadata and operator output distinguish both timeouts and read older records.
- No timeout path accepts an incomplete handoff or changes existing task/recovery
  semantics. No test touches evaluator volumes or launches paid agent sessions.
- Run `make check` (Ruff, ty, full pytest) for implementation changes. Use
  deterministic clock tests for deadline decisions and bounded subprocess tests
  for pipe/termination behavior rather than fragile timing-only assertions.
